"""Shared database utilities for autish commands.

Provides standardized connection handling, schema management,
and common query patterns to reduce duplication across commands.

Usage:
    from autish.db import get_connection, ensure_schema, row_to_dict
"""

from __future__ import annotations

import sqlite3
from typing import Any

from autish.paths import data_dir


def get_connection(db_name: str, timeout: float = 5.0) -> sqlite3.Connection:
    """Get a connection to the specified database with standard settings.

    Args:
        db_name: Name of database file (e.g., "vorto.db", "encik.db")
        timeout: Connection timeout in seconds

    Returns:
        SQLite connection with WAL mode and row factory set
    """
    db_path = data_dir() / db_name
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=timeout)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def ensure_schema(conn: sqlite3.Connection, schema_sql: str) -> None:
    """Execute schema SQL if tables don't exist.

    Args:
        conn: SQLite connection
        schema_sql: SQL to execute (CREATE TABLE IF NOT EXISTS, etc.)
    """
    conn.executescript(schema_sql)


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a row to dictionary.

    Args:
        row: SQLite Row object

    Returns:
        Dictionary representation
    """
    return dict(row)


def row_to_dict_with_json(
    row: sqlite3.Row,
    json_columns: list[str],
    defaults: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Convert row to dict, parsing JSON columns.

    Args:
        row: SQLite Row object
        json_columns: Column names that contain JSON
        defaults: Default values for missing columns (e.g., {"field": "[]"})

    Returns:
        Dictionary with parsed JSON fields
    """
    import json as json_mod

    d = dict(row)
    defaults = defaults or {}
    for col in json_columns:
        raw = d.get(col) or defaults.get(col, "null")
        try:
            d[col] = json_mod.loads(raw)
        except json_mod.JSONDecodeError:
            d[col] = json_mod.loads(defaults.get(col, "null"))
    return d


def execute_one(
    conn: sqlite3.Connection,
    query: str,
    params: tuple | None = None,
) -> Any:
    """Execute query and return single value.

    Args:
        conn: SQLite connection
        query: SQL query
        params: Query parameters

    Returns:
        First column of first row, or None
    """
    cursor = conn.execute(query, params or ())
    row = cursor.fetchone()
    return row[0] if row else None


def execute_all(
    conn: sqlite3.Connection,
    query: str,
    params: tuple | None = None,
) -> list[tuple]:
    """Execute query and return all rows.

    Args:
        conn: SQLite connection
        query: SQL query
        params: Query parameters

    Returns:
        List of result tuples
    """
    cursor = conn.execute(query, params or ())
    return cursor.fetchall()


def execute_row(
    conn: sqlite3.Connection,
    query: str,
    params: tuple | None = None,
) -> dict[str, Any] | None:
    """Execute query and return first row as dict.

    Args:
        conn: SQLite connection
        query: SQL query
        params: Query parameters

    Returns:
        Dictionary or None
    """
    conn.row_factory = sqlite3.Row
    cursor = conn.execute(query, params or ())
    row = cursor.fetchone()
    return dict(row) if row else None


def execute_write(
    conn: sqlite3.Connection,
    query: str,
    params: tuple | None = None,
) -> int:
    """Execute write query and return affected row count.

    Args:
        conn: SQLite connection
        query: SQL query (INSERT/UPDATE/DELETE)
        params: Query parameters

    Returns:
        Number of rows affected
    """
    cursor = conn.execute(query, params or ())
    conn.commit()
    return cursor.rowcount


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    """Check if table exists.

    Args:
        conn: SQLite connection
        table_name: Name of table to check

    Returns:
        True if table exists
    """
    query = "SELECT name FROM sqlite_master WHERE type='table' AND name = ?"
    return execute_one(conn, query, (table_name,)) is not None


def column_exists(
    conn: sqlite3.Connection,
    table_name: str,
    column_name: str,
) -> bool:
    """Check if column exists in table.

    Args:
        conn: SQLite connection
        table_name: Name of table
        column_name: Name of column

    Returns:
        True if column exists
    """
    cursor = conn.execute(f"PRAGMA table_info({table_name})")
    return any(row[1] == column_name for row in cursor.fetchall())