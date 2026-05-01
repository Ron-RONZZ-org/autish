"""Repository layer for vorto (vocabulary) database operations.

This module provides data access functions for the vorto command,
extracting SQL operations from the CLI module for better maintainability.

Usage:
    from autish.services.vorto_repo import get_db, migrate_db
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from autish.paths import data_dir

# Database schema
_CREATE_VORTO = """
CREATE TABLE IF NOT EXISTS vorto (
    uuid TEXT PRIMARY KEY,
    teksto TEXT NOT NULL,
    tipo TEXT NOT NULL DEFAULT '[]',
    difinoj TEXT NOT NULL DEFAULT '[]',
    uzoj TEXT NOT NULL DEFAULT '[]',
    tonoj TEXT,
    etikedoj TEXT NOT NULL DEFAULT '{}',
    ligiloj TEXT NOT NULL DEFAULT '[]',
    notoj TEXT,
    kategorio TEXT,
    autoro TEXT,
    verko TEXT,
    kreita_je TEXT NOT NULL,
    modifita_je TEXT NOT NULL
);
"""

_CREATE_VORTO_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_vorto_teksto ON vorto(teksto);
CREATE INDEX IF NOT EXISTS idx_vorto_kategorio ON vorto(kategorio);
CREATE INDEX IF NOT EXISTS idx_vorto_kreita ON vorto(kreita_je);
CREATE INDEX IF NOT EXISTS idx_vorto_modifita ON vorto(modifita_je);
"""

_CREATE_RUBUJO = """
CREATE TABLE IF NOT EXISTS rubujo (
    uuid TEXT PRIMARY KEY,
    teksto TEXT NOT NULL,
    tipo TEXT NOT NULL DEFAULT '[]',
    difinoj TEXT NOT NULL DEFAULT '[]',
    uzoj TEXT NOT NULL DEFAULT '[]',
    tonoj TEXT,
    etikedoj TEXT NOT NULL DEFAULT '{}',
    ligiloj TEXT NOT NULL DEFAULT '[]',
    notoj TEXT,
    kategorio TEXT,
    autoro TEXT,
    verko TEXT,
    kreita_je TEXT NOT NULL,
    forigita_je TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rubujo_teksto ON rubujo(teksto);
CREATE INDEX IF NOT EXISTS idx_rubujo_forigita ON rubujo(forigita_je);
"""

_CREATE_UNDO = """
CREATE TABLE IF NOT EXISTS undo_stack (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operation TEXT NOT NULL,
    data TEXT NOT NULL,
    timestamp TEXT NOT NULL
);
"""


def get_db() -> sqlite3.Connection:
    """Open (and initialize) the SQLite database, returning a connection."""
    db_path = data_dir() / "vorto.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path), timeout=5.0)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA foreign_keys=ON;")
    con.executescript(_CREATE_VORTO + _CREATE_VORTO_INDEXES + _CREATE_RUBUJO + _CREATE_UNDO)
    migrate_db(con)
    return con


def migrate_db(con: sqlite3.Connection) -> None:
    """Run database migrations for vorto tables."""
    for table in ("vorto", "rubujo"):
        cols = {row[1] for row in con.execute(f"PRAGMA table_info({table})").fetchall()}
        if "uzoj" not in cols:
            con.execute(f"ALTER TABLE {table} ADD COLUMN uzoj TEXT NOT NULL DEFAULT '[]'")
        if "autoro" not in cols:
            con.execute(f"ALTER TABLE {table} ADD COLUMN autoro TEXT")
        if "verko" not in cols:
            con.execute(f"ALTER TABLE {table} ADD COLUMN verko TEXT")
    con.commit()


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a vorto table row to a plain dict, parsing JSON columns."""
    d = dict(row)
    for col, default in (
        ("difinoj", "[]"),
        ("uzoj", "[]"),
        ("etikedoj", "{}"),
        ("ligiloj", "[]"),
        ("tipo", "[]"),
    ):
        raw = d.get(col) or default
        try:
            d[col] = json.loads(raw)
        except json.JSONDecodeError:
            d[col] = json.loads(default)
    # Normalize difinoj and uzoj
    if "difinoj" in d and isinstance(d["difinoj"], list):
        normalized = []
        for item in d["difinoj"]:
            if isinstance(item, dict) and "difino" in item:
                normalized.append(item["difino"])
            elif isinstance(item, str):
                normalized.append(item)
        d["difinoj"] = normalized
    if "uzoj" in d and isinstance(d["uzoj"], list):
        normalized = []
        for item in d["uzoj"]:
            if isinstance(item, dict) and "uzo" in item:
                normalized.append(item["uzo"])
            elif isinstance(item, str):
                normalized.append(item)
        d["uzoj"] = normalized
    return d