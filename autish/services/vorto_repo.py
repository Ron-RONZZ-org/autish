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
    # Ensure tipo is always a list (handle legacy single-string values)
    if isinstance(d.get("tipo"), str):
        d["tipo"] = [d["tipo"]] if d["tipo"] else []
    elif not isinstance(d.get("tipo"), list):
        d["tipo"] = []
    return d


def dict_to_params(entry: dict[str, Any]) -> tuple:
    """Return the parameter tuple used for INSERT/UPDATE statements."""
    return (
        entry["uuid"],
        entry["teksto"],
        entry.get("lingvo"),
        entry.get("kategorio"),
        json.dumps(entry.get("tipo") or [], ensure_ascii=False),
        entry.get("temo"),
        entry.get("tono"),
        entry.get("nivelo"),
        json.dumps(entry.get("difinoj") or [], ensure_ascii=False),
        json.dumps(entry.get("uzoj") or [], ensure_ascii=False),
        json.dumps(entry.get("etikedoj") or {}, ensure_ascii=False),
        json.dumps(entry.get("ligiloj") or [], ensure_ascii=False),
        entry.get("autoro"),
        entry.get("verko"),
        entry["kreita_je"],
        entry["modifita_je"],
    )


def load_entries() -> list[dict[str, Any]]:
    """Return all wordbank entries ordered by creation date (oldest first)."""
    with get_db() as con:
        rows = con.execute("SELECT * FROM vorto ORDER BY kreita_je ASC").fetchall()
    return [row_to_dict(r) for r in rows]


def find_entry_by_uuid(uuid: str) -> dict[str, Any] | None:
    """Find a single entry by UUID using SQL (indexed lookup)."""
    with get_db() as con:
        row = con.execute("SELECT * FROM vorto WHERE uuid = ?", (uuid,)).fetchone()
        return row_to_dict(row) if row else None


def find_entry_by_teksto(teksto: str) -> dict[str, Any] | None:
    """Find a single entry by case-insensitive teksto."""
    with get_db() as con:
        row = con.execute(
            "SELECT * FROM vorto WHERE LOWER(teksto) = LOWER(?)", (teksto,)
        ).fetchone()
        return row_to_dict(row) if row else None


def find_entries_by_uuid_prefix(prefix: str) -> list[dict[str, Any]]:
    """Find entries whose UUID starts with prefix."""
    with get_db() as con:
        rows = con.execute(
            "SELECT * FROM vorto WHERE uuid LIKE ?", (f"{prefix}%",)
        ).fetchall()
        return [row_to_dict(r) for r in rows]


def save_entries(entries: list[dict[str, Any]]) -> None:
    """Replace the entire entry table with entries in a single transaction."""
    with get_db() as con:
        con.execute("DELETE FROM vorto")
        con.executemany(
            """
            INSERT INTO vorto
                (uuid, teksto, lingvo, kategorio, tipo, temo, tono,
                 nivelo, difinoj, uzoj, etikedoj, ligiloj,
                 autoro, verko, kreita_je, modifita_je)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [dict_to_params(e) for e in entries],
        )
        con.commit()


def insert_entry(entry: dict[str, Any]) -> None:
    """Insert a single entry into the database."""
    with get_db() as con:
        con.execute(
            """
            INSERT INTO vorto
                (uuid, teksto, lingvo, kategorio, tipo, temo, tono,
                 nivelo, difinoj, uzoj, etikedoj, ligiloj,
                 autoro, verko, kreita_je, modifita_je)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            dict_to_params(entry),
        )
        con.commit()


def update_entry(entry: dict[str, Any]) -> None:
    """Update a single entry in the database."""
    with get_db() as con:
        con.execute(
            """
            UPDATE vorto SET
                teksto = ?, lingvo = ?, kategorio = ?, tipo = ?, temo = ?,
                tono = ?, nivelo = ?, difinoj = ?, uzoj = ?, etikedoj = ?,
                ligiloj = ?, autoro = ?, verko = ?, modifita_je = ?
            WHERE uuid = ?
            """,
            (
                entry["teksto"],
                entry.get("lingvo"),
                entry.get("kategorio"),
                json.dumps(entry.get("tipo") or [], ensure_ascii=False),
                entry.get("temo"),
                entry.get("tono"),
                entry.get("nivelo"),
                json.dumps(entry.get("difinoj") or [], ensure_ascii=False),
                json.dumps(entry.get("uzoj") or [], ensure_ascii=False),
                json.dumps(entry.get("etikedoj") or {}, ensure_ascii=False),
                json.dumps(entry.get("ligiloj") or [], ensure_ascii=False),
                entry.get("autoro"),
                entry.get("verko"),
                entry["modifita_je"],
                entry["uuid"],
            ),
        )
        con.commit()


def delete_entry(uuid: str) -> None:
    """Delete an entry by UUID."""
    with get_db() as con:
        con.execute("DELETE FROM vorto WHERE uuid = ?", (uuid,))
        con.commit()


# Rubujo (trash) functions
def load_rubujo() -> list[dict[str, Any]]:
    """Return all entries in the trash, ordered by deletion date (newest first)."""
    with get_db() as con:
        rows = con.execute(
            "SELECT * FROM rubujo ORDER BY forigita_je DESC"
        ).fetchall()
    return [row_to_dict(r) for r in rows]


def move_to_rubujo(entry: dict[str, Any], forigita_je: str) -> None:
    """Move an entry to the trash."""
    with get_db() as con:
        con.execute(
            """
            INSERT INTO rubujo
                (uuid, teksto, lingvo, kategorio, tipo, temo, tono,
                 nivelo, difinoj, uzoj, etikedoj, ligiloj,
                 autoro, verko, kreita_je, forigita_je)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry["uuid"],
                entry["teksto"],
                entry.get("lingvo"),
                entry.get("kategorio"),
                json.dumps(entry.get("tipo") or [], ensure_ascii=False),
                entry.get("temo"),
                entry.get("tono"),
                entry.get("nivelo"),
                json.dumps(entry.get("difinoj") or [], ensure_ascii=False),
                json.dumps(entry.get("uzoj") or [], ensure_ascii=False),
                json.dumps(entry.get("etikedoj") or {}, ensure_ascii=False),
                json.dumps(entry.get("ligiloj") or [], ensure_ascii=False),
                entry.get("autoro"),
                entry.get("verko"),
                entry["kreita_je"],
                forigita_je,
            ),
        )
        con.commit()


def recover_from_rubujo(uuid: str) -> dict[str, Any] | None:
    """Recover an entry from trash by UUID, returning the entry."""
    with get_db() as con:
        row = con.execute("SELECT * FROM rubujo WHERE uuid = ?", (uuid,)).fetchone()
        if not row:
            return None
        entry = row_to_dict(row)
        # Insert back into vorto
        con.execute(
            """
            INSERT INTO vorto
                (uuid, teksto, lingvo, kategorio, tipo, temo, tono,
                 nivelo, difinoj, uzoj, etikedoj, ligiloj,
                 autoro, verko, kreita_je, modifita_je)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry["uuid"],
                entry["teksto"],
                entry.get("lingvo"),
                entry.get("kategorio"),
                json.dumps(entry.get("tipo") or [], ensure_ascii=False),
                entry.get("temo"),
                entry.get("tono"),
                entry.get("nivelo"),
                json.dumps(entry.get("difinoj") or [], ensure_ascii=False),
                json.dumps(entry.get("uzoj") or [], ensure_ascii=False),
                json.dumps(entry.get("etikedoj") or {}, ensure_ascii=False),
                json.dumps(entry.get("ligiloj") or [], ensure_ascii=False),
                entry.get("autoro"),
                entry.get("verko"),
                entry["kreita_je"],
                entry.get("forigita_je"),  # Use deletion time as modifita_je
            ),
        )
        con.execute("DELETE FROM rubujo WHERE uuid = ?", (uuid,))
        con.commit()
        return entry


def permanent_delete_from_rubujo(uuid: str) -> None:
    """Permanently delete an entry from trash."""
    with get_db() as con:
        con.execute("DELETE FROM rubujo WHERE uuid = ?", (uuid,))
        con.commit()


def clear_old_rubujo(days: int = 30) -> int:
    """Delete entries from trash older than specified days. Returns count deleted."""
    with get_db() as con:
        cursor = con.execute(
            "DELETE FROM rubujo WHERE forigita_je < datetime('now', ?)",
            (f"-{days} days",),
        )
        con.commit()
        return cursor.rowcount


# Undo stack functions
def load_undo_stack() -> list[dict[str, Any]]:
    """Load the undo stack from database."""
    with get_db() as con:
        rows = con.execute(
            "SELECT operation, data, timestamp FROM undo_stack ORDER BY id ASC"
        ).fetchall()
    return [
        {"operation": r[0], "data": json.loads(r[1]), "timestamp": r[2]}
        for r in rows
    ]


def save_undo_stack(stack: list[dict[str, Any]]) -> None:
    """Save the entire undo stack to database."""
    with get_db() as con:
        con.execute("DELETE FROM undo_stack")
        con.executemany(
            "INSERT INTO undo_stack (operation, data, timestamp) VALUES (?, ?, ?)",
            [(op["operation"], json.dumps(op["data"]), op["timestamp"]) for op in stack],
        )
        con.commit()


def push_undo(operation: str, data: dict[str, Any], timestamp: str) -> None:
    """Push a single undo operation onto the stack."""
    with get_db() as con:
        con.execute(
            "INSERT INTO undo_stack (operation, data, timestamp) VALUES (?, ?, ?)",
            (operation, json.dumps(data), timestamp),
        )
        con.commit()