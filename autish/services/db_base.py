"""Base classes and utilities for SQLite database management.

Provides reusable patterns for database initialization, CRUD operations,
and common queries to reduce code duplication across autish services.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


class SQLiteDB:
    """Base class for SQLite database managers.

    Provides common initialization, connection management, and helper methods
    for derived classes (BashAliasDB, etc.).

    Usage:
        class MyDB(SQLiteDB):
            DB_NAME = "myapp.db"
            SCHEMA = '''CREATE TABLE IF NOT EXISTS mytable (...)'''

            def _init_db(self) -> None:
                super()._init_db()
                # Add custom initialization if needed
    """

    DB_NAME: str = "autish.db"  # Override in subclass
    SCHEMA: str = ""  # Override in subclass with SQL schema

    def __init__(self, db_path: Path | None = None) -> None:
        """Initialize database connection.

        Args:
            db_path: Path to SQLite database. If None, uses ~/.config/autish/{DB_NAME}
        """
        if db_path is None:
            config_dir = Path.home() / ".config" / "autish"
            config_dir.mkdir(parents=True, exist_ok=True)
            db_path = config_dir / self.DB_NAME

        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema if it doesn't exist.

        Executes SCHEMA if defined in subclass.
        Override in subclass to add custom initialization.
        """
        if self.SCHEMA:
            with sqlite3.connect(self.db_path) as conn:
                conn.executescript(self.SCHEMA)

    def _execute_one(
        self, query: str, params: tuple[Any, ...] | None = None
    ) -> Any:
        """Execute query and return single value.

        Args:
            query: SQL query to execute.
            params: Query parameters.

        Returns:
            First column of first row, or None if no rows.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(query, params or ())
            row = cursor.fetchone()
            return row[0] if row else None

    def _execute_all(
        self, query: str, params: tuple[Any, ...] | None = None
    ) -> list[tuple[Any, ...]]:
        """Execute query and return all rows.

        Args:
            query: SQL query to execute.
            params: Query parameters.

        Returns:
            List of result tuples.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(query, params or ())
            return cursor.fetchall()

    def _execute_row(
        self, query: str, params: tuple[Any, ...] | None = None
    ) -> dict[str, Any] | None:
        """Execute query and return first row as dict.

        Args:
            query: SQL query to execute.
            params: Query parameters.

        Returns:
            Dictionary mapping column names to values, or None.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query, params or ())
            row = cursor.fetchone()
            return dict(row) if row else None

    def _execute_rows(
        self, query: str, params: tuple[Any, ...] | None = None
    ) -> list[dict[str, Any]]:
        """Execute query and return all rows as dicts.

        Args:
            query: SQL query to execute.
            params: Query parameters.

        Returns:
            List of dictionaries.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query, params or ())
            return [dict(row) for row in cursor.fetchall()]

    def _execute_write(self, query: str, params: tuple[Any, ...] | None = None) -> int:
        """Execute write query (INSERT/UPDATE/DELETE) and return affected rows.

        Args:
            query: SQL query to execute.
            params: Query parameters.

        Returns:
            Number of rows affected.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(query, params or ())
            conn.commit()
            return cursor.rowcount

    def _execute_many(
        self, query: str, params: list[tuple[Any, ...]]
    ) -> int:
        """Execute write query multiple times with different parameters.

        Args:
            query: SQL query to execute.
            params: List of parameter tuples.

        Returns:
            Number of rows affected.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.executemany(query, params)
            conn.commit()
            return cursor.rowcount

    def _table_exists(self, table_name: str) -> bool:
        """Check if table exists in database.

        Args:
            table_name: Name of table to check.

        Returns:
            True if table exists, False otherwise.
        """
        query = (
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name = ?"
        )
        return self._execute_one(query, (table_name,)) is not None

    def _column_exists(self, table_name: str, column_name: str) -> bool:
        """Check if column exists in table.

        Args:
            table_name: Name of table.
            column_name: Name of column.

        Returns:
            True if column exists, False otherwise.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(f"PRAGMA table_info({table_name})")
            return any(row[1] == column_name for row in cursor.fetchall())
