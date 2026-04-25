"""XDG-compliant recycle bin management for autish."""

import re
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class TrashItem:
    """Represents an item in the recycle bin."""

    uid: str
    original_path: str
    trash_path: str
    deleted_at: str
    size: int


class RecycleBinDB:
    """Database for tracking trashed items."""

    def __init__(self) -> None:
        """Initialize the recycle bin database."""
        self.trash_dir = self._get_trash_dir()
        self.db_path = self.trash_dir / "autish_trash.db"
        self.trash_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @staticmethod
    def _get_trash_dir() -> Path:
        """Get XDG-compliant trash directory."""
        xdg_data_home = Path.home() / ".local" / "share"
        trash_dir = xdg_data_home / "Trash"
        return trash_dir

    def _init_db(self) -> None:
        """Initialize database tables if they don't exist."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS trash_items (
                uid TEXT PRIMARY KEY,
                original_path TEXT NOT NULL,
                trash_path TEXT NOT NULL,
                deleted_at TEXT NOT NULL,
                size INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()
        conn.close()

    def _get_next_uid(self) -> str:
        """Get the next sequential UID for a trash item."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        # Get all UIDs and find the max numeric one
        cursor.execute("SELECT uid FROM trash_items ORDER BY CAST(uid AS INTEGER) DESC LIMIT 1")
        result = cursor.fetchone()
        conn.close()
        
        if result and result[0]:
            try:
                next_uid = int(result[0]) + 1
            except ValueError:
                next_uid = 1
        else:
            next_uid = 1
        return str(next_uid)

    def add_item(self, original_path: str, trash_path: str, size: int = 0) -> str:
        """Add an item to the trash database.
        
        Args:
            original_path: Original path of the file
            trash_path: Path in trash directory
            size: File size in bytes
            
        Returns:
            UID of the trash item
        """
        uid = self._get_next_uid()
        deleted_at = datetime.now().isoformat()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO trash_items (uid, original_path, trash_path, deleted_at, size)
            VALUES (?, ?, ?, ?, ?)
            """,
            (uid, original_path, trash_path, deleted_at, size)
        )
        conn.commit()
        conn.close()
        return uid

    def get_item(self, uid: str) -> TrashItem | None:
        """Get a trash item by UID."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT uid, original_path, trash_path, deleted_at, size
            FROM trash_items WHERE uid = ?
            """,
            (uid,)
        )
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return TrashItem(*row)
        return None

    def list_items(
        self, sort_by: str = "deleted_at", reverse: bool = False
    ) -> list[TrashItem]:
        """List all trash items.
        
        Args:
            sort_by: Field to sort by (deleted_at, original_path, size)
            reverse: Sort in reverse order
            
        Returns:
            List of TrashItem objects
        """
        valid_sorts = ["deleted_at", "original_path", "size"]
        if sort_by not in valid_sorts:
            sort_by = "deleted_at"
        
        order = "DESC" if reverse else "ASC"
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT uid, original_path, trash_path, deleted_at, size
            FROM trash_items
            ORDER BY {sort_by} {order}
            """
        )
        rows = cursor.fetchall()
        conn.close()
        
        return [TrashItem(*row) for row in rows]

    def search_items(
        self,
        keyword: str,
        use_regex: bool = False,
        field: str = "original_path"
    ) -> list[TrashItem]:
        """Search trash items.
        
        Args:
            keyword: Search term or regex pattern
            use_regex: If True, treat keyword as POSIX regex
            field: Field to search (original_path, trash_path)
            
        Returns:
            List of matching TrashItem objects
        """
        items = self.list_items()
        
        if use_regex:
            try:
                pattern = re.compile(keyword)
            except re.error:
                return []
            
            return [
                item for item in items
                if pattern.search(getattr(item, field))
            ]
        else:
            # Wildcard search: * matches anything
            pattern_str = keyword.replace("*", ".*")
            pattern_str = f"^{pattern_str}$"
            try:
                pattern = re.compile(pattern_str)
            except re.error:
                # Fallback to simple substring match
                return [
                    item for item in items
                    if keyword.lower() in getattr(item, field).lower()
                ]
            
            return [
                item for item in items
                if pattern.search(getattr(item, field))
            ]

    def delete_item(self, uid: str) -> bool:
        """Permanently delete a trash item.
        
        Args:
            uid: UID of the item to delete
            
        Returns:
            True if successful, False if not found
        """
        item = self.get_item(uid)
        if not item:
            return False
        
        # Delete physical file
        trash_path = Path(item.trash_path)
        if trash_path.exists():
            if trash_path.is_dir():
                shutil.rmtree(trash_path)
            else:
                trash_path.unlink()
        
        # Delete from database
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM trash_items WHERE uid = ?", (uid,))
        conn.commit()
        conn.close()
        
        return True

    def restore_item(self, uid: str, target_path: str | None = None) -> bool:
        """Restore a trash item to its original location or a new location.
        
        Args:
            uid: UID of the item to restore
            target_path: Optional new location; if None, uses original_path
            
        Returns:
            True if successful, False if not found or error
        """
        item = self.get_item(uid)
        if not item:
            return False
        
        source = Path(item.trash_path)
        if not source.exists():
            # Delete database entry if file already gone
            self.delete_item(uid)
            return False
        
        dest = Path(target_path or item.original_path)
        
        # Create parent directory if needed
        dest.parent.mkdir(parents=True, exist_ok=True)
        
        # Move file back
        if source.is_dir():
            shutil.copytree(source, dest, dirs_exist_ok=True)
            shutil.rmtree(source)
        else:
            shutil.copy2(source, dest)
            source.unlink()
        
        # Remove from trash database
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM trash_items WHERE uid = ?", (uid,))
        conn.commit()
        conn.close()
        
        return True

    def move_to_trash(self, source_path: str) -> str | None:
        """Move a file to trash.
        
        Args:
            source_path: Path to file to trash
            
        Returns:
            UID of trash item, or None if error
        """
        source = Path(source_path).expanduser().resolve()
        
        if not source.exists():
            return None
        
        # Create trash structure
        files_dir = self.trash_dir / "files"
        files_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate unique name in trash
        uid = self._get_next_uid()
        trash_name = f"{source.name}.{uid}"
        trash_path = files_dir / trash_name
        
        # Avoid collisions
        counter = 1
        while trash_path.exists():
            trash_name = f"{source.name}.{uid}_{counter}"
            trash_path = files_dir / trash_name
            counter += 1
        
        # Move to trash
        try:
            if source.is_dir():
                shutil.move(str(source), str(trash_path))
            else:
                shutil.move(str(source), str(trash_path))
            
            # Get size
            size = self._get_path_size(trash_path)
            
            # Add to database
            return self.add_item(str(source), str(trash_path), size)
        except Exception:
            return None

    @staticmethod
    def _get_path_size(path: Path) -> int:
        """Get total size of a file or directory in bytes."""
        if path.is_file():
            return path.stat().st_size
        
        total = 0
        for item in path.rglob("*"):
            if item.is_file():
                total += item.stat().st_size
        return total
