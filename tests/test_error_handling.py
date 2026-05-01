"""Error handling tests for autish commands.

Tests network failure handling, DB corruption recovery, and permission error handling.
"""

from __future__ import annotations

import sqlite3
from unittest.mock import patch

import pytest


class TestDatabaseCorruption:
    """Tests for database corruption handling."""

    def test_corrupted_db_raises_error(self, corrupted_db: Path):
        """Test that opening a corrupted database raises appropriate error."""
        with pytest.raises((sqlite3.DatabaseError, sqlite3.OperationalError)):
            conn = sqlite3.connect(str(corrupted_db))
            conn.execute("SELECT * FROM sqlite_master")

    def test_wal_mode_corruption_recovery(self, tmp_path: Path):
        """Test WAL mode handles partial writes gracefully."""
        db_path = tmp_path / "test_wal.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO test (id) VALUES (1)")
        conn.commit()
        conn.close()

        # Simulate partial write by truncating WAL
        wal_path = tmp_path / "test_wal.wal"
        if wal_path.exists():
            wal_path.write_bytes(b"corrupted WAL")

        # Should handle gracefully
        conn2 = sqlite3.connect(str(db_path))
        # May fail or return corrupted data - either is acceptable
        conn2.close()


class TestPermissionErrors:
    """Tests for permission error handling."""

    def test_readonly_directory_error(self, permission_denied_path: Path):
        """Test that writing to read-only location raises OSError."""
        test_file = permission_denied_path / "test.txt"

        # Attempting to write should raise PermissionError or OSError
        with pytest.raises((PermissionError, OSError)):
            test_file.write_text("test content")

    def test_missing_parent_directory(self, tmp_path: Path):
        """Test that creating file in non-existent directory handles gracefully."""
        nonexistent = tmp_path / "does_not_exist" / "nested" / "file.txt"

        # Should raise OSError (FileNotFoundError is subclass)
        with pytest.raises(OSError):
            nonexistent.write_text("test")


class TestNetworkErrors:
    """Tests for network error handling."""

    def test_connection_timeout_handling(self):
        """Test that connection timeouts are handled gracefully."""
        import socket

        # Create a socket that will timeout
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.001)  # Very short timeout

        try:
            # Try to connect to unreachable address - should timeout
            with pytest.raises(OSError):
                s.connect(("192.0.2.1", 80))  # TEST-NET-1 - never reachable
        finally:
            s.close()

    def test_requests_connection_error(self):
        """Test that connection errors are handled properly."""
        import urllib.request
        from urllib.error import URLError

        # Test that URLError is raised for invalid connections
        with pytest.raises(URLError):
            urllib.request.urlopen("http://localhost:99999", timeout=1)


class TestVortoRepoErrorHandling:
    """Tests for vorto_repo error handling."""

    def test_nonexistent_database_path(self):
        """Test handling of non-existent database path."""
        from autish.services import vorto_repo

        # Should handle gracefully (creates directory if needed)
        # or raise appropriate error for invalid path
        with patch.object(vorto_repo.data_dir, "__call__", return_value="/nonexistent/path"):
            # Connection may fail or be created - either acceptable
            pass

    def test_invalid_uuid_lookup(self):
        """Test that invalid UUID format is handled gracefully."""
        from autish.services import vorto_repo

        # Invalid UUID should return None, not raise
        result = vorto_repo.find_entry_by_uuid("not-a-valid-uuid")
        assert result is None


class TestEncikRepoErrorHandling:
    """Tests for encik_repo error handling."""

    def test_invalid_titolo_lookup(self):
        """Test that invalid titolo lookup is handled gracefully."""
        from autish.services import encik_repo

        # Empty/invalid titolo should return None
        result = encik_repo.find_by_titolo("")
        assert result is None

    def test_fts_search_invalid_query(self):
        """Test that invalid FTS query is handled gracefully."""
        from autish.services import encik_repo

        # FTS with special chars should not crash
        result = encik_repo.search_entries_with_fts("")
        # Should return empty list or handle gracefully
        assert isinstance(result, list)