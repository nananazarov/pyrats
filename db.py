"""
File: db.py
PYRATS — SQLite Persistence Layer
"""

import datetime
import json
import sqlite3
from typing import List

from models import TableSchema

DATABASE = "rules.db"


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DATABASE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    db = get_db()
    db.execute("""
        CREATE TABLE IF NOT EXISTS tables (
            function_name TEXT PRIMARY KEY,
            schema_json TEXT NOT NULL DEFAULT '{}'
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS triggers (
            path TEXT PRIMARY KEY,
            function_name TEXT NOT NULL,
            description TEXT
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS table_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            function_name TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            schema_json TEXT NOT NULL
        )
    """)
    db.commit()
    db.close()


def load_schema(function_name: str) -> TableSchema:
    db = get_db()
    row = db.execute(
        "SELECT schema_json FROM tables WHERE function_name = ?", (function_name,)
    ).fetchone()
    db.close()
    if row is None:
        return TableSchema()
    return TableSchema(**json.loads(row["schema_json"]))


def save_schema(function_name: str, schema: TableSchema) -> None:
    db = get_db()
    db.execute(
        "INSERT OR REPLACE INTO tables (function_name, schema_json) VALUES (?, ?)",
        (function_name, json.dumps(schema.model_dump(), ensure_ascii=False)),
    )
    db.commit()
    db.close()


def list_functions() -> List[str]:
    db = get_db()
    rows = db.execute(
        "SELECT function_name FROM tables ORDER BY function_name"
    ).fetchall()
    db.close()
    return [r["function_name"] for r in rows]


# ── Versioning Helper Functions ──────────────────────────────────────────────


def create_version(function_name: str, schema: TableSchema) -> None:
    """Creates a new timestamped version snapshot for the function."""
    db = get_db()
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.execute(
        "INSERT INTO table_versions (function_name, timestamp, schema_json) VALUES (?, ?, ?)",
        (function_name, timestamp, json.dumps(schema.model_dump(), ensure_ascii=False)),
    )
    db.commit()
    db.close()


def load_active_schema(function_name: str) -> TableSchema:
    """Loads the latest saved (active) schema for a function. Fallback to draft."""
    db = get_db()
    row = db.execute(
        "SELECT schema_json FROM table_versions WHERE function_name = ? ORDER BY id DESC LIMIT 1",
        (function_name,),
    ).fetchone()
    db.close()
    if row is None:
        return load_schema(function_name)
    return TableSchema(**json.loads(row["schema_json"]))


def list_versions(function_name: str) -> List[dict]:
    """Retrieves all saved versions for a function with rules/inputs/outputs counts."""
    db = get_db()
    rows = db.execute(
        "SELECT id, timestamp, schema_json FROM table_versions WHERE function_name = ? ORDER BY id DESC",
        (function_name,),
    ).fetchall()
    db.close()

    versions = []
    for r in rows:
        try:
            schema_data = json.loads(r["schema_json"])
            rules_count = len(schema_data.get("rules", []))
            inputs_count = len(schema_data.get("inputs", []))
            outputs_count = len(schema_data.get("outputs", []))
        except Exception:
            rules_count = 0
            inputs_count = 0
            outputs_count = 0

        versions.append(
            {
                "id": r["id"],
                "timestamp": r["timestamp"],
                "rules_count": rules_count,
                "inputs_count": inputs_count,
                "outputs_count": outputs_count,
            }
        )
    return versions


def restore_version_by_id(function_name: str, version_id: int) -> TableSchema:
    """Restores an old version to draft and creates a new active version snapshot."""
    db = get_db()
    row = db.execute(
        "SELECT schema_json FROM table_versions WHERE id = ? AND function_name = ?",
        (version_id, function_name),
    ).fetchone()
    db.close()
    if row is None:
        raise ValueError(f"Version {version_id} not found for function {function_name}")

    schema = TableSchema(**json.loads(row["schema_json"]))
    # Overwrite the current draft schema
    save_schema(function_name, schema)
    # Save a new active version snapshot as a copy
    create_version(function_name, schema)
    return schema
