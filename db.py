"""
File: db.py
PYRATS — SQLite Persistence Layer
"""

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
