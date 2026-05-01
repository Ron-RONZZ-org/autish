"""Shared pytest configuration and fixtures for autish tests."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def mock_webbrowser_globally():
    """Globally mock webbrowser.open() to prevent browser windows from opening during tests.

    This fixture is automatically used by all tests (autouse=True) and prevents
    actual browser windows from being opened during test runs, which would disrupt
    development workflows. Tests that need custom behavior can still override this
    by using their own patch decorators or monkeypatch.
    """
    with patch("webbrowser.open", return_value=True):
        yield


@pytest.fixture
def temp_db(tmp_path: Path) -> sqlite3.Connection:
    """Create a temporary SQLite database with WAL mode.

    Returns an open connection. Caller is responsible for closing it.
    The database is automatically cleaned up after the test.
    """
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    yield conn
    conn.close()


@pytest.fixture
def mock_profile(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Mock user profile for testing.

    Returns a minimal profile dict that commands can use.
    Tests can modify returned dict to customize profile values.
    """
    profile = {
        "lingvoj": ["eo", "en"],
        "uzanto_nomo": "Test User",
        "retposto": {
            "adreso": "test@example.com",
            "servilo": "imap.example.com",
        },
    }
    # Mock _load_profile to return our test profile
    monkeypatch.setitem(
        __import__("autish.commands.uzanto", fromlist=["_load_profile"]).__dict__,
        "_load_profile",
        lambda: profile,
    )
    return profile


@pytest.fixture
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create an isolated config directory for testing.

    Sets up a temporary config directory and patches environment variables
    to point to it. Returns the config directory path.
    """
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)

    # Also create data dir
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    # Patch environment
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_dir))
    monkeypatch.setenv("XDG_DATA_HOME", str(data_dir))

    return config_dir


# ──────────────────────────────────────────────────────────────────────────────
# Error handling test fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_network_timeout(monkeypatch: pytest.MonkeyPatch):
    """Mock network operations to raise timeout errors."""
    import socket

    original_socket = socket.socket

    def timeout_socket(*args, **kwargs):
        s = original_socket(*args, **kwargs)
        s.settimeout(0.001)  # Very short timeout
        return s

    monkeypatch.setattr(socket, "socket", timeout_socket)
    return monkeypatch


@pytest.fixture
def corrupted_db(tmp_path: Path) -> Path:
    """Create a corrupted SQLite database file for testing recovery."""
    db_path = tmp_path / "corrupted.db"
    # Write invalid/corrupted content
    db_path.write_bytes(b"This is not a valid SQLite database\x00\x00\x00")
    return db_path


@pytest.fixture
def permission_denied_path(tmp_path: Path) -> Path:
    """Create a path with no write permissions."""
    protected_dir = tmp_path / "protected"
    protected_dir.mkdir()
    # Make directory read-only (remove write permission)
    protected_dir.chmod(0o555)
    return protected_dir
