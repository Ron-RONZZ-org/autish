"""Repository layer for encik (encyclopedia) database operations.

This module provides data access functions for the encik command,
extracting SQL operations from the CLI module for better maintainability.

Usage:
    from autish.services.encik_repo import get_db, init_db, load_all
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from autish.paths import data_dir

# Database schema
_CREATE_ENCIK = """
CREATE TABLE IF NOT EXISTS encik (
    uuid        TEXT PRIMARY KEY,
    titolo      TEXT NOT NULL,
    difinio     TEXT NOT NULL DEFAULT '',
    terminologio TEXT NOT NULL DEFAULT '{}',
    difinoj     TEXT NOT NULL DEFAULT '{}',
    enhavo      TEXT NOT NULL DEFAULT '',
    superklaso  TEXT NOT NULL DEFAULT '[]',
    ligilo      TEXT NOT NULL DEFAULT '[]',
    fonto       TEXT NOT NULL DEFAULT '[]',
    citajo      TEXT NOT NULL DEFAULT '[]',
    datumo      TEXT NOT NULL DEFAULT '{}',
    semantika   TEXT NOT NULL DEFAULT '[]',
    kreita_je   TEXT NOT NULL,
    modifita_je TEXT NOT NULL
);
"""

_CREATE_ENCIK_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_encik_titolo_lower ON encik(LOWER(titolo));
CREATE INDEX IF NOT EXISTS idx_encik_uuid_prefix ON encik(substr(uuid, 1, 8));
CREATE INDEX IF NOT EXISTS idx_encik_kreita_je ON encik(kreita_je);
"""

_CREATE_ENCIK_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS encik_fts USING fts5(
    uuid UNINDEXED,
    titolo,
    terminologio,
    difinio,
    difinoj,
    enhavo,
    content=encik,
    content_rowid=rowid
);
"""


def get_db_path() -> Path:
    """Return the path to the encik database."""
    db_path = data_dir() / "encik.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path


def init_db() -> None:
    """Initialize the database with schema if needed."""
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(_CREATE_ENCIK)
        conn.executescript(_CREATE_ENCIK_INDEXES)
        conn.execute(_CREATE_ENCIK_FTS)
        migrate_db(conn)
        conn.commit()
    finally:
        conn.close()


def migrate_db(conn: sqlite3.Connection) -> None:
    """Run database migrations for encik tables."""
    cols = {
        row[1]
        for row in conn.execute("PRAGMA table_info(encik)").fetchall()
        if len(row) > 1
    }
    if "terminologio" not in cols:
        conn.execute(
            "ALTER TABLE encik ADD COLUMN terminologio TEXT NOT NULL DEFAULT '{}'"
        )
    if "difinoj" not in cols:
        conn.execute("ALTER TABLE encik ADD COLUMN difinoj TEXT NOT NULL DEFAULT '{}'")
    if "enhavo" not in cols:
        conn.execute("ALTER TABLE encik ADD COLUMN enhavo TEXT NOT NULL DEFAULT ''")
    if "fonto" not in cols:
        conn.execute("ALTER TABLE encik ADD COLUMN fonto TEXT NOT NULL DEFAULT '[]'")
        if "source" in cols:
            conn.execute(
                "UPDATE encik SET fonto = source WHERE (fonto = '[]' OR fonto = '')"
            )
    if "citajo" not in cols:
        conn.execute("ALTER TABLE encik ADD COLUMN citajo TEXT NOT NULL DEFAULT '[]'")
    if "datumo" not in cols:
        conn.execute("ALTER TABLE encik ADD COLUMN datumo TEXT NOT NULL DEFAULT '{}'")
    if "semantika" not in cols:
        conn.execute(
            "ALTER TABLE encik ADD COLUMN semantika TEXT NOT NULL DEFAULT '[]'"
        )


def get_conn() -> sqlite3.Connection:
    """Get a database connection with row factory set."""
    init_db()
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Convert an encik table row to a plain dict, parsing JSON columns."""
    d = dict(row)
    for field in ("superklaso", "ligilo", "fonto", "citajo", "source"):
        if isinstance(d.get(field), str):
            d[field] = json.loads(d[field])
    for field in ("terminologio", "difinoj", "datumo", "semantika"):
        if isinstance(d.get(field), str):
            d[field] = json.loads(d[field])
    if "fonto" not in d and "source" in d:
        d["fonto"] = d.get("source") or []
    if "terminologio" not in d:
        titolo = str(d.get("titolo") or "").strip()
        d["terminologio"] = {"eo": titolo} if titolo else {}
    if "difinoj" not in d:
        difinio = str(d.get("difinio") or "").strip()
        d["difinoj"] = {"eo": difinio} if difinio else {}
    if "enhavo" not in d:
        d["enhavo"] = ""
    if "citajo" not in d:
        d["citajo"] = []
    if "datumo" not in d:
        d["datumo"] = {}
    return d


def load_all_unsorted() -> list[dict[str, Any]]:
    """Load all entries without sorting."""
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM encik").fetchall()
    return [row_to_dict(r) for r in rows]


def load_all() -> list[dict[str, Any]]:
    """Load all entries sorted by title."""
    entries = load_all_unsorted()
    return sorted(entries, key=lambda e: (e.get("titolo") or "").lower())


def find_by_uuid(uid: str) -> dict[str, Any] | None:
    """Find a single entry by UUID."""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM encik WHERE uuid = ?", (uid,)).fetchone()
        return row_to_dict(row) if row else None


def find_by_uuid_prefix(prefix: str) -> list[dict[str, Any]]:
    """Find entries whose UUID starts with prefix."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM encik WHERE uuid LIKE ?", (f"{prefix}%",)
        ).fetchall()
    return [row_to_dict(r) for r in rows]


def find_by_titolo(titolo: str) -> dict[str, Any] | None:
    """Find a single entry by case-insensitive title."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM encik WHERE LOWER(titolo) = LOWER(?)", (titolo,)
        ).fetchone()
        return row_to_dict(row) if row else None


def search_entries_with_fts(
    query: str,
    limo: int = 100,
) -> list[dict[str, Any]]:
    """Search entries using FTS5 full-text search."""
    with get_conn() as conn:
        # Match in titolo, terminologio, difinio, difinoj, enhavo
        fts_query = " OR ".join([f'"{query}"'] * 5)
        rows = conn.execute(
            """
            SELECT encik.* FROM encik
            JOIN encik_fts ON encik.rowid = encik_fts.rowid
            WHERE encik_fts MATCH ?
            LIMIT ?
            """,
            (fts_query, limo),
        ).fetchall()
    return [row_to_dict(r) for r in rows]


def search_entries(
    query: str,
    limo: int = 100,
) -> list[dict[str, Any]]:
    """Search entries using LIKE (fallback when FTS unavailable)."""
    with get_conn() as conn:
        pattern = f"%{query}%"
        rows = conn.execute(
            """
            SELECT * FROM encik
            WHERE titolo LIKE ? OR difinio LIKE ? OR enhavo LIKE ?
            LIMIT ?
            """,
            (pattern, pattern, pattern, limo),
        ).fetchall()
    return [row_to_dict(r) for r in rows]


def insert_entry(entry: dict[str, Any]) -> None:
    """Insert a new entry into the database."""
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO encik (
                uuid, titolo, difinio, terminologio, difinoj, enhavo,
                superklaso, ligilo, fonto, citajo, datumo, semantika,
                kreita_je, modifita_je
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry["uuid"],
                entry.get("titolo", ""),
                entry.get("difinio", ""),
                json.dumps(entry.get("terminologio", {}), ensure_ascii=False),
                json.dumps(entry.get("difinoj", {}), ensure_ascii=False),
                entry.get("enhavo", ""),
                json.dumps(entry.get("superklaso", []), ensure_ascii=False),
                json.dumps(entry.get("ligilo", []), ensure_ascii=False),
                json.dumps(entry.get("fonto", []), ensure_ascii=False),
                json.dumps(entry.get("citajo", []), ensure_ascii=False),
                json.dumps(entry.get("datumo", {}), ensure_ascii=False),
                json.dumps(entry.get("semantika", []), ensure_ascii=False),
                entry["kreita_je"],
                entry["modifita_je"],
            ),
        )
        conn.commit()
        # Update FTS index
        conn.execute(
            """
            INSERT INTO encik_fts (uuid, titolo, terminologio, difinio, difinoj, enhavo)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                entry["uuid"],
                entry.get("titolo", ""),
                json.dumps(entry.get("terminologio", {}), ensure_ascii=False),
                entry.get("difinio", ""),
                json.dumps(entry.get("difinoj", {}), ensure_ascii=False),
                entry.get("enhavo", ""),
            ),
        )
        conn.commit()


def update_entry(entry: dict[str, Any]) -> None:
    """Update an existing entry."""
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE encik SET
                titolo = ?, difinio = ?, terminologio = ?, difinoj = ?,
                enhavo = ?, superklaso = ?, ligilo = ?, fonto = ?,
                citajo = ?, datumo = ?, semantika = ?, modifita_je = ?
            WHERE uuid = ?
            """,
            (
                entry.get("titolo", ""),
                entry.get("difinio", ""),
                json.dumps(entry.get("terminologio", {}), ensure_ascii=False),
                json.dumps(entry.get("difinoj", {}), ensure_ascii=False),
                entry.get("enhavo", ""),
                json.dumps(entry.get("superklaso", []), ensure_ascii=False),
                json.dumps(entry.get("ligilo", []), ensure_ascii=False),
                json.dumps(entry.get("fonto", []), ensure_ascii=False),
                json.dumps(entry.get("citajo", []), ensure_ascii=False),
                json.dumps(entry.get("datumo", {}), ensure_ascii=False),
                json.dumps(entry.get("semantika", []), ensure_ascii=False),
                entry["modifita_je"],
                entry["uuid"],
            ),
        )
        conn.commit()
        # Update FTS index
        conn.execute("DELETE FROM encik_fts WHERE uuid = ?", (entry["uuid"],))
        conn.execute(
            """
            INSERT INTO encik_fts (uuid, titolo, terminologio, difinio, difinoj, enhavo)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                entry["uuid"],
                entry.get("titolo", ""),
                json.dumps(entry.get("terminologio", {}), ensure_ascii=False),
                entry.get("difinio", ""),
                json.dumps(entry.get("difinoj", {}), ensure_ascii=False),
                entry.get("enhavo", ""),
            ),
        )
        conn.commit()


def delete_entry(uuid: str) -> None:
    """Delete an entry by UUID."""
    with get_conn() as conn:
        conn.execute("DELETE FROM encik WHERE uuid = ?", (uuid,))
        conn.execute("DELETE FROM encik_fts WHERE uuid = ?", (uuid,))
        conn.commit()


def count() -> int:
    """Return the total number of entries."""
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM encik").fetchone()[0]