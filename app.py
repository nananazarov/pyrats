"""
File: app.py
PYRATS — Python Rule Automation Table System
Run: uvicorn app:app --reload
"""

import json
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader

from db import (create_version, get_db, init_db, list_functions, list_versions,
                load_active_schema, load_schema, restore_version_by_id,
                save_schema)
from engine import RuleEngine
from models import ColType, ColumnDef, RuleRow, TableSchema, TriggerModel

# ========================= LIFESPAN EVENTS =========================


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize SQLite database and tables
    init_db()
    funcs = list_functions()

    # Seed demo decision tables if they do not exist yet
    # 1. calc_discount
    if "calc_discount" not in funcs:
        discount_schema = TableSchema(
            inputs=[
                ColumnDef(name="customer_tier", type="string"),
                ColumnDef(name="cart_total", type="number"),
            ],
            outputs=[
                ColumnDef(name="discount", type="number"),
                ColumnDef(name="free_shipping", type="boolean"),
            ],
            rules=[
                RuleRow(
                    id="vip_large",
                    priority=10,
                    conditions=['"vip"', ">= 1000"],
                    results=["0.2", "true"],
                    annotation="VIP + large cart",
                    stop_on_match=True,
                ),
                RuleRow(
                    id="gold_large",
                    priority=20,
                    conditions=['"gold"', ">= 500"],
                    results=["0.15", "true"],
                    annotation="Gold + medium/large cart",
                    stop_on_match=True,
                ),
                RuleRow(
                    id="regular_promo",
                    priority=30,
                    conditions=['"regular", "standard"', ">= 200"],
                    results=["0.05", "false"],
                    annotation="Regular/Standard promo total threshold",
                    stop_on_match=True,
                ),
                RuleRow(
                    id="free_shipping_threshold",
                    priority=40,
                    conditions=["*", ">= 100"],
                    results=["0", "true"],
                    annotation="Free shipping for any cart over 100",
                    stop_on_match=True,
                ),
                RuleRow(
                    id="default",
                    priority=100,
                    conditions=["*", "*"],
                    results=["0", "false"],
                    annotation="Default baseline",
                    stop_on_match=True,
                ),
            ],
        )
        save_schema("calc_discount", discount_schema)
        create_version("calc_discount", discount_schema)

    # 2. risk_score
    if "risk_score" not in funcs:
        risk_schema = TableSchema(
            inputs=[
                ColumnDef(name="age", type="number"),
                ColumnDef(name="income", type="number"),
                ColumnDef(name="employment", type="string"),
            ],
            outputs=[
                ColumnDef(name="risk_level", type="string"),
                ColumnDef(name="score", type="number"),
            ],
            rules=[
                RuleRow(
                    id="low_risk_high_income",
                    priority=10,
                    conditions=["[25..60]", ">= 75000", '"employed"'],
                    results=['"low"', "10"],
                    annotation="Stable employed high-earning adult",
                    stop_on_match=True,
                ),
                RuleRow(
                    id="stable_mid_income",
                    priority=20,
                    conditions=["[25..60]", "[40000..75000)", '"employed"'],
                    results=['"medium"', "35"],
                    annotation="Middle-class employed adult",
                    stop_on_match=True,
                ),
                RuleRow(
                    id="young_employed",
                    priority=30,
                    conditions=["< 25", ">= 30000", '"employed"'],
                    results=['"medium"', "45"],
                    annotation="Young adult starting career",
                    stop_on_match=True,
                ),
                RuleRow(
                    id="unemployed_risk",
                    priority=40,
                    conditions=["*", "*", '"unemployed"'],
                    results=['"high"', "85"],
                    annotation="Unemployed status multiplier",
                    stop_on_match=True,
                ),
                RuleRow(
                    id="retired_low_income",
                    priority=50,
                    conditions=["> 65", "< 20000", "*"],
                    results=['"high"', "70"],
                    annotation="Retired low-income household risk",
                    stop_on_match=True,
                ),
                RuleRow(
                    id="default",
                    priority=100,
                    conditions=["*", "*", "*"],
                    results=['"medium"', "50"],
                    annotation="Default baseline score",
                    stop_on_match=True,
                ),
            ],
        )
        save_schema("risk_score", risk_schema)
        create_version("risk_score", risk_schema)

    # Seed default triggers if triggers table is empty
    db = get_db()
    try:
        row = db.execute("SELECT COUNT(*) as count FROM triggers").fetchone()
        if row and row["count"] == 0:
            db.execute(
                "INSERT INTO triggers (path, function_name, description) VALUES (?, ?, ?)",
                ("discount", "calc_discount", "Discount calculation"),
            )
            db.commit()
    except Exception:
        pass
    finally:
        db.close()

    yield


# ========================= FASTAPI SETUP =========================

app = FastAPI(title="PYRATS", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")

# ========================= JINJA2 =========================

jinja_env = Environment(loader=FileSystemLoader("templates"))
jinja_env.filters["tojson"] = json.dumps
main_template = jinja_env.get_template("index.html")
editor_template = jinja_env.get_template("editor.html")


def _get_editor_html(func_name: str) -> str:
    schema = load_schema(func_name)
    versions = list_versions(func_name)
    active_schema = load_active_schema(func_name)
    has_unsaved_changes = (schema.model_dump() != active_schema.model_dump())
    return editor_template.render(
        func_name=func_name,
        schema=schema,
        versions=versions,
        has_unsaved_changes=has_unsaved_changes,
    )


# ========================= ROUTES =========================


@app.get("/", response_class=HTMLResponse)
async def index(func: Optional[str] = None) -> str:
    funcs = list_functions()
    return main_template.render(functions=funcs, selected_func=func or "")


@app.get("/api/functions")
async def get_functions() -> List[str]:
    """List of registered tables (for UI updates)."""
    return list_functions()


@app.post("/api/table")
async def create_table(request: Request) -> Dict[str, Any]:
    """Create a new empty decision table."""
    form = await request.form()
    name = str(form.get("name", "")).strip()
    if not name:
        raise HTTPException(400, "Name cannot be empty")
    import re as _re

    if not _re.match(r"^[a-zA-Z_][a-zA-Z0-9_\-]*$", name):
        raise HTTPException(
            400,
            "Name must start with a letter/underscore and contain only [a-zA-Z0-9_-]",
        )
    if name in list_functions():
        raise HTTPException(400, f"Table '{name}' already exists")
    empty_schema = TableSchema()
    save_schema(name, empty_schema)
    create_version(name, empty_schema)
    return {"success": True, "name": name}


@app.put("/api/table/{func_name}/rename")
async def rename_table(func_name: str, request: Request) -> Dict[str, Any]:
    """Rename decision table."""
    form = await request.form()
    new_name = str(form.get("new_name", "")).strip()
    import re as _re

    if not new_name:
        raise HTTPException(400, "Name cannot be empty")
    if not _re.match(r"^[a-zA-Z_][a-zA-Z0-9_\-]*$", new_name):
        raise HTTPException(400, "Invalid characters in name")
    if new_name == func_name:
        return {"success": True, "name": new_name}
    if new_name in list_functions():
        raise HTTPException(400, f"Table '{new_name}' already exists")
    # Copy schema under new name, delete old one
    schema = load_schema(func_name)
    save_schema(new_name, schema)
    db = get_db()
    db.execute("DELETE FROM tables WHERE function_name = ?", (func_name,))
    # Update all timestamped versions for this renamed table
    db.execute(
        "UPDATE table_versions SET function_name = ? WHERE function_name = ?",
        (new_name, func_name),
    )
    # Update references in triggers
    db.execute(
        "UPDATE triggers SET function_name = ? WHERE function_name = ?",
        (new_name, func_name),
    )
    db.commit()
    db.close()
    return {"success": True, "name": new_name}


@app.get("/api/table/{func_name}/schema")
async def get_schema_info(func_name: str) -> Dict[str, Any]:
    """Returns JSON-schema (inputs/outputs) for the tester."""
    schema = load_schema(func_name)
    return {
        "inputs": [c.model_dump() for c in schema.inputs],
        "outputs": [c.model_dump() for c in schema.outputs],
    }


@app.get("/api/table/{func_name}", response_class=HTMLResponse)
async def get_table_editor(func_name: str) -> str:
    if func_name not in list_functions():
        raise HTTPException(404, "Function not found")
    return _get_editor_html(func_name)


# ── Input columns ──────────────────────────────────────────────────────────────


@app.post("/api/table/{func_name}/add_input_col", response_class=HTMLResponse)
async def add_input_col(func_name: str) -> str:
    schema = load_schema(func_name)
    schema.inputs.append(
        ColumnDef(name=f"field_{len(schema.inputs) + 1}", type="string")
    )
    for rule in schema.rules:
        rule.conditions.append("")
    save_schema(func_name, schema)
    return _get_editor_html(func_name)


@app.delete("/api/table/{func_name}/input_col/{idx}", response_class=HTMLResponse)
async def delete_input_col(func_name: str, idx: int) -> str:
    schema = load_schema(func_name)
    if idx < 0 or idx >= len(schema.inputs):
        raise HTTPException(400, "Invalid column index")
    schema.inputs.pop(idx)
    for rule in schema.rules:
        if idx < len(rule.conditions):
            rule.conditions.pop(idx)
    save_schema(func_name, schema)
    return _get_editor_html(func_name)


@app.put("/api/table/{func_name}/input_col/{idx}/name", response_class=HTMLResponse)
async def update_input_col_name(func_name: str, idx: int, request: Request) -> str:
    form = await request.form()
    name = form.get("name", "")
    if not isinstance(name, str) or not name.strip():
        raise HTTPException(400, "Name cannot be empty")
    schema = load_schema(func_name)
    if idx < 0 or idx >= len(schema.inputs):
        raise HTTPException(400, "Invalid column index")
    schema.inputs[idx].name = name.strip()
    save_schema(func_name, schema)
    return _get_editor_html(func_name)


@app.put("/api/table/{func_name}/input_col/{idx}/type", response_class=HTMLResponse)
async def update_input_col_type(func_name: str, idx: int, request: Request) -> str:
    form = await request.form()
    col_type = form.get("type", "string")
    if col_type not in ("string", "number", "boolean"):
        raise HTTPException(400, "Invalid type")
    schema = load_schema(func_name)
    if idx < 0 or idx >= len(schema.inputs):
        raise HTTPException(400, "Invalid column index")
    from typing import cast

    schema.inputs[idx].type = cast(ColType, col_type)
    save_schema(func_name, schema)
    return _get_editor_html(func_name)


# ── Output columns ─────────────────────────────────────────────────────────────


@app.post("/api/table/{func_name}/add_output_col", response_class=HTMLResponse)
async def add_output_col(func_name: str) -> str:
    schema = load_schema(func_name)
    schema.outputs.append(
        ColumnDef(name=f"output_{len(schema.outputs) + 1}", type="string")
    )
    for rule in schema.rules:
        rule.results.append("")
    save_schema(func_name, schema)
    return _get_editor_html(func_name)


@app.delete("/api/table/{func_name}/output_col/{idx}", response_class=HTMLResponse)
async def delete_output_col(func_name: str, idx: int) -> str:
    schema = load_schema(func_name)
    if idx < 0 or idx >= len(schema.outputs):
        raise HTTPException(400, "Invalid column index")
    schema.outputs.pop(idx)
    for rule in schema.rules:
        if idx < len(rule.results):
            rule.results.pop(idx)
    save_schema(func_name, schema)
    return _get_editor_html(func_name)


@app.put("/api/table/{func_name}/output_col/{idx}/name", response_class=HTMLResponse)
async def update_output_col_name(func_name: str, idx: int, request: Request) -> str:
    form = await request.form()
    name = form.get("name", "")
    if not isinstance(name, str) or not name.strip():
        raise HTTPException(400, "Name cannot be empty")
    schema = load_schema(func_name)
    if idx < 0 or idx >= len(schema.outputs):
        raise HTTPException(400, "Invalid column index")
    schema.outputs[idx].name = name.strip()
    save_schema(func_name, schema)
    return _get_editor_html(func_name)


@app.put("/api/table/{func_name}/output_col/{idx}/type", response_class=HTMLResponse)
async def update_output_col_type(func_name: str, idx: int, request: Request) -> str:
    form = await request.form()
    col_type = form.get("type", "string")
    if col_type not in ("string", "number", "boolean"):
        raise HTTPException(400, "Invalid type")
    schema = load_schema(func_name)
    if idx < 0 or idx >= len(schema.outputs):
        raise HTTPException(400, "Invalid column index")
    from typing import cast

    schema.outputs[idx].type = cast(ColType, col_type)
    save_schema(func_name, schema)
    return _get_editor_html(func_name)


# ── Rules ──────────────────────────────────────────────────────────────────────


@app.post("/api/table/{func_name}/add_rule", response_class=HTMLResponse)
async def add_rule(func_name: str) -> str:
    schema = load_schema(func_name)
    n = len(schema.rules) + 1
    schema.rules.append(
        RuleRow(
            id=f"rule_{n}",
            priority=n * 10,
            conditions=[""] * len(schema.inputs),
            results=[""] * len(schema.outputs),
        )
    )
    save_schema(func_name, schema)
    return _get_editor_html(func_name)


@app.delete("/api/table/{func_name}/rule/{ri}", response_class=HTMLResponse)
async def delete_rule(func_name: str, ri: int) -> str:
    schema = load_schema(func_name)
    if ri < 0 or ri >= len(schema.rules):
        raise HTTPException(400, "Invalid rule index")
    schema.rules.pop(ri)
    save_schema(func_name, schema)
    return _get_editor_html(func_name)


@app.put("/api/table/{func_name}/rule/{ri}/condition/{ci}", response_class=HTMLResponse)
async def update_condition(func_name: str, ri: int, ci: int, request: Request) -> str:
    form = await request.form()
    expr = form.get("expr", "")
    if not isinstance(expr, str):
        expr = ""
    schema = load_schema(func_name)
    rule = schema.rules[ri]
    while len(rule.conditions) <= ci:
        rule.conditions.append("")
    rule.conditions[ci] = expr
    save_schema(func_name, schema)
    return _get_editor_html(func_name)


@app.put("/api/table/{func_name}/rule/{ri}/result/{ci}", response_class=HTMLResponse)
async def update_result(func_name: str, ri: int, ci: int, request: Request) -> str:
    form = await request.form()
    value = form.get("value", "")
    if not isinstance(value, str):
        value = ""
    schema = load_schema(func_name)
    rule = schema.rules[ri]
    while len(rule.results) <= ci:
        rule.results.append("")
    rule.results[ci] = value
    save_schema(func_name, schema)
    return _get_editor_html(func_name)


@app.put("/api/table/{func_name}/rule/{ri}/priority", response_class=HTMLResponse)
async def update_rule_priority(func_name: str, ri: int, request: Request) -> str:
    form = await request.form()
    try:
        priority = int(str(form.get("priority", "1")))
    except ValueError:
        priority = 1
    schema = load_schema(func_name)
    schema.rules[ri].priority = priority
    save_schema(func_name, schema)
    return _get_editor_html(func_name)


@app.put("/api/table/{func_name}/rule/{ri}/annotation", response_class=HTMLResponse)
async def update_rule_annotation(func_name: str, ri: int, request: Request) -> str:
    form = await request.form()
    annotation = form.get("annotation", "")
    if not isinstance(annotation, str):
        annotation = ""
    schema = load_schema(func_name)
    schema.rules[ri].annotation = annotation
    save_schema(func_name, schema)
    return _get_editor_html(func_name)


@app.put("/api/table/{func_name}/rule/{ri}/stop", response_class=HTMLResponse)
async def update_rule_stop(func_name: str, ri: int, request: Request) -> str:
    form = await request.form()
    schema = load_schema(func_name)
    schema.rules[ri].stop_on_match = form.get("stop_on_match") == "on"
    save_schema(func_name, schema)
    return _get_editor_html(func_name)


# ── Evaluate ───────────────────────────────────────────────────────────────────


@app.post("/evaluate/{func_name}")
async def evaluate(func_name: str, body: Dict[str, Any]) -> Dict[str, Any]:
    if func_name not in list_functions():
        raise HTTPException(404, "Function not found")
    schema = load_active_schema(func_name)
    engine = RuleEngine(schema)
    result = engine.evaluate(body)
    if result is None:
        return {
            "matched": False,
            "result": None,
            "outputs_schema": [c.model_dump() for c in schema.outputs],
        }
    return result


# ========================= TRIGGERS =========================


@app.get("/api/triggers")
async def list_triggers() -> List[Dict[str, Any]]:
    db = get_db()
    rows = db.execute(
        "SELECT path, function_name, description FROM triggers"
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


@app.post("/api/triggers")
async def create_trigger(trigger: TriggerModel) -> Dict[str, Any]:
    if trigger.function_name not in list_functions():
        raise HTTPException(400, f"Function '{trigger.function_name}' not found")
    clean_path = trigger.path.strip("/")
    if not clean_path or "/" in clean_path:
        raise HTTPException(400, "Path must be a single segment")
    db = get_db()
    db.execute(
        "INSERT OR REPLACE INTO triggers (path, function_name, description) VALUES (?, ?, ?)",
        (clean_path, trigger.function_name, trigger.description),
    )
    db.commit()
    db.close()
    return {"success": True, "path": clean_path}


@app.delete("/api/triggers/{path}")
async def delete_trigger(path: str) -> Dict[str, Any]:
    db = get_db()
    db.execute("DELETE FROM triggers WHERE path = ?", (path.strip("/"),))
    db.commit()
    db.close()
    return {"success": True}


# ========================= ROUTER =========================


@app.post("/route/{path}")
async def run_trigger_route(path: str, body: Dict[str, Any]) -> Dict[str, Any]:
    db = get_db()
    row = db.execute(
        "SELECT function_name FROM triggers WHERE path = ?", (path.strip("/"),)
    ).fetchone()
    db.close()
    if row is None:
        raise HTTPException(404, f"Route '{path}' is not registered")

    func_name = row["function_name"]
    schema = load_active_schema(func_name)
    engine = RuleEngine(schema)
    result = engine.evaluate(body)
    if result is None:
        return {
            "route_path": path,
            "function_name": func_name,
            "matched": False,
            "result": None,
        }
    return {"route_path": path, "function_name": func_name, **result}


# ========================= VERSIONS =========================


@app.post("/api/table/{func_name}/save", response_class=HTMLResponse)
async def save_active_version_route(func_name: str) -> str:
    if func_name not in list_functions():
        raise HTTPException(404, "Function not found")
    schema = load_schema(func_name)
    create_version(func_name, schema)
    return _get_editor_html(func_name)


@app.post("/api/table/{func_name}/restore/{version_id}", response_class=HTMLResponse)
async def restore_version_route(func_name: str, version_id: int) -> str:
    if func_name not in list_functions():
        raise HTTPException(404, "Function not found")
    try:
        restore_version_by_id(func_name, version_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _get_editor_html(func_name)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", reload=True)
