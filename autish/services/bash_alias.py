"""Bash alias management service.

Manages bash aliases stored in SQLite database and synced to shell config.
Database location: ~/.config/autish/bash_aliases.db
Shell config: ~/.autish_aliases (sourced from ~/.bashrc)
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class BashAlias:
    """Represents a bash alias record."""

    uid: int
    alias: str
    function: str
    notes: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class BashAliasDB:
    """SQLite database manager for bash aliases."""

    def __init__(self, db_path: Path | None = None) -> None:
        """Initialize bash alias database.

        Args:
            db_path: Path to SQLite database. Defaults to
                ~/.config/autish/bash_aliases.db
        """
        if db_path is None:
            config_dir = Path.home() / ".config" / "autish"
            config_dir.mkdir(parents=True, exist_ok=True)
            db_path = config_dir / "bash_aliases.db"

        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema if it doesn't exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS bash_aliases (
                    uid INTEGER PRIMARY KEY NOT NULL,
                    alias TEXT UNIQUE NOT NULL,
                    function TEXT NOT NULL,
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            # Metadata table to track next UID (for non-recycling)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS _metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
                """
            )
            # Initialize next_uid if not present
            cursor = conn.execute(
                "SELECT value FROM _metadata WHERE key = 'next_uid'"
            )
            if cursor.fetchone() is None:
                conn.execute(
                    "INSERT INTO _metadata (key, value) VALUES ('next_uid', '1')"
                )
            conn.commit()

    def _get_next_uid(self) -> int:
        """Get next available UID (never recycled).

        Returns:
            Next sequential UID.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT value FROM _metadata WHERE key = 'next_uid'"
            )
            row = cursor.fetchone()
            next_uid = int(row[0]) if row else 1

            # Increment and store
            conn.execute(
                "UPDATE _metadata SET value = ? WHERE key = 'next_uid'",
                (str(next_uid + 1),),
            )
            conn.commit()

        return next_uid

    @staticmethod
    def _normalize_autish_command(function: str) -> str:
        """Normalize autish subcommands to use 'autish' prefix if needed.

        Detects standalone autish subcommands (vorto, encik, retposto, etc.)
        and converts them to 'autish <subcommand>' format so they work
        outside the poetry virtual environment.

        Args:
            function: Original function/command string.

        Returns:
            Normalized function string with autish prefix if applicable.
        """
        autish_commands = {
            'vorto', 'encik', 'retposto', 'kontakto', 'bluhdento',
            'wifi', 'sistemo', 'tempo', 'kp', 'shelo', 'sekurkopio',
            'uzanto', 'md', 'disko', 'usb', 'filmeto', 'kalendaro',
            'etikedo', 'todo', 'verki'
        }

        # Get first word (command)
        parts = function.strip().split(maxsplit=1)
        if not parts:
            return function

        first_word = parts[0]

        # Check if it's an autish command (and not already prefixed with autish)
        if first_word in autish_commands:
            # Convert to 'autish <command> <rest>'
            return f"autish {function}"

        return function

    def add_alias(self, alias: str, function: str, notes: str | None = None) -> int:
        """Add new bash alias to database.

        Args:
            alias: Bash alias name.
            function: Bash alias function/command.
            notes: Optional markdown notes (supports ec# and vt# links).

        Returns:
            UID of newly added alias.

        Raises:
            sqlite3.IntegrityError: If alias name already exists.
        """
        uid = self._get_next_uid()
        now = datetime.now().isoformat()

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO bash_aliases
                    (uid, alias, function, notes, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (uid, alias, function, notes, now, now),
            )
            conn.commit()

        return uid

    def get_alias(self, uid: int) -> BashAlias | None:
        """Get bash alias by UID.

        Args:
            uid: Bash alias UID.

        Returns:
            BashAlias object or None if not found.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT uid, alias, function, notes, created_at, updated_at "
                "FROM bash_aliases WHERE uid = ?",
                (uid,),
            )
            row = cursor.fetchone()

        if row is None:
            return None

        return BashAlias(
            uid=row[0],
            alias=row[1],
            function=row[2],
            notes=row[3],
            created_at=datetime.fromisoformat(row[4]) if row[4] else None,
            updated_at=datetime.fromisoformat(row[5]) if row[5] else None,
        )

    def list_aliases(
        self, sort_by: str = "created_at", descending: bool = True
    ) -> list[BashAlias]:
        """List all bash aliases.

        Args:
            sort_by: Sort field ('created_at', 'alias'). Defaults to 'created_at'.
            descending: Sort in descending order. Defaults to True (newest first).

        Returns:
            List of BashAlias objects.
        """
        order = "DESC" if descending else "ASC"
        sort_field = "alias" if sort_by == "alias" else "created_at"

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                f"""
                SELECT uid, alias, function, notes, created_at, updated_at
                FROM bash_aliases
                ORDER BY {sort_field} {order}
                """
            )
            rows = cursor.fetchall()

        return [
            BashAlias(
                uid=row[0],
                alias=row[1],
                function=row[2],
                notes=row[3],
                created_at=datetime.fromisoformat(row[4]) if row[4] else None,
                updated_at=datetime.fromisoformat(row[5]) if row[5] else None,
            )
            for row in rows
        ]

    def search_aliases(self, query: str) -> list[BashAlias]:
        """Search aliases by fuzzy match on alias, function, or notes.

        Args:
            query: Search query (case-insensitive substring match).

        Returns:
            List of matching BashAlias objects, sorted by relevance.
        """
        query_lower = query.lower()

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT uid, alias, function, notes, created_at, updated_at
                FROM bash_aliases
                WHERE LOWER(alias) LIKE ?
                   OR LOWER(function) LIKE ?
                   OR LOWER(COALESCE(notes, '')) LIKE ?
                ORDER BY created_at DESC
                """,
                (f"%{query_lower}%", f"%{query_lower}%", f"%{query_lower}%"),
            )
            rows = cursor.fetchall()

        return [
            BashAlias(
                uid=row[0],
                alias=row[1],
                function=row[2],
                notes=row[3],
                created_at=datetime.fromisoformat(row[4]) if row[4] else None,
                updated_at=datetime.fromisoformat(row[5]) if row[5] else None,
            )
            for row in rows
        ]

    def update_alias(
        self,
        uid: int,
        alias: str | None = None,
        function: str | None = None,
        notes: str | None = None,
    ) -> bool:
        """Update existing bash alias.

        Args:
            uid: Bash alias UID.
            alias: New alias name (None to skip).
            function: New function (None to skip).
            notes: New notes (None to skip).

        Returns:
            True if updated, False if not found.

        Raises:
            sqlite3.IntegrityError: If new alias name conflicts with existing.
        """
        current = self.get_alias(uid)
        if current is None:
            return False

        new_alias = alias if alias is not None else current.alias
        new_function = function if function is not None else current.function
        new_notes = notes if notes is not None else current.notes
        now = datetime.now().isoformat()

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE bash_aliases
                SET alias = ?, function = ?, notes = ?, updated_at = ?
                WHERE uid = ?
                """,
                (new_alias, new_function, new_notes, now, uid),
            )
            conn.commit()

        return True

    def delete_alias(self, uid: int) -> bool:
        """Delete bash alias (UID not recycled).

        Args:
            uid: Bash alias UID.

        Returns:
            True if deleted, False if not found.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("DELETE FROM bash_aliases WHERE uid = ?", (uid,))
            conn.commit()
            return cursor.rowcount > 0

    def generate_shell_script(self) -> str:
        """Generate shell script with all aliases for sourcing.

        Returns:
            Bash script content with all aliases defined.
        """
        aliases = self.list_aliases(sort_by="created_at", descending=False)
        lines = [
            "#!/bin/bash",
            "# autish bash aliases — auto-generated, do not edit manually",
        ]
        lines.append("# Source this file in ~/.bashrc with: source ~/.autish_aliases")
        lines.append("")

        for alias_obj in aliases:
            # Normalize autish commands to use 'autish' prefix
            normalized_func = self._normalize_autish_command(alias_obj.function)
            # Escape function for shell safety
            escaped_func = normalized_func.replace("'", "'\\''")
            lines.append(f"alias {alias_obj.alias}='{escaped_func}'")

        lines.append("")
        return "\n".join(lines)

    def sync_shell_config(self) -> Path:
        """Write bash aliases to shell config file and return path.

        Returns:
            Path to generated shell script (~/.autish_aliases).
        """
        script_path = Path.home() / ".autish_aliases"
        content = self.generate_shell_script()
        script_path.write_text(content)
        script_path.chmod(0o644)
        return script_path
