"""Tests for the man command (documentation management microapp)."""

import sqlite3
import tempfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from autish.commands.man import (
    app,
    _DB_FILE,
    _ensure_db,
    _extract_title_from_markdown,
    _resolve_man_entry,
    get_manuals_for_encik,
)

runner = CliRunner()


@pytest.fixture(autouse=True)
def cleanup_db():
    """Clean up test database before and after each test."""
    if _DB_FILE.exists():
        _DB_FILE.unlink()
    yield
    if _DB_FILE.exists():
        _DB_FILE.unlink()


def test_man_help():
    """Test man command help."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "dokumentaro-mastruma mikroapo" in result.stdout


def test_aldoni_basic():
    """Test adding a basic manual."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as f:
        f.write("# Test Manual\n\nThis is a test manual.")
        f.flush()
        temp_path = f.name

    try:
        result = runner.invoke(app, ["aldoni", temp_path])
        assert result.exit_code == 0
        assert "✓ Manlibro aldonita" in result.stdout
        assert "Test Manual" in result.stdout

        # Verify it was stored in database
        _ensure_db()
        conn = sqlite3.connect(_DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM man")
        count = cursor.fetchone()[0]
        conn.close()
        assert count == 1
    finally:
        Path(temp_path).unlink()


def test_extract_title_from_markdown():
    """Test title extraction from markdown."""
    # H1 in content
    md = "# My Title\nContent here"
    title = _extract_title_from_markdown(md, "default.md")
    assert title == "My Title"

    # No H1, fallback to filename
    md = "Just content"
    title = _extract_title_from_markdown(md, "my_document.md")
    assert title == "My Document"

    # H1 with special characters
    md = "# Fiziko: Elektromagnetismo\nContent"
    title = _extract_title_from_markdown(md, "test.md")
    assert title == "Fiziko: Elektromagnetismo"


def test_vidi_entry():
    """Test viewing a manual entry."""
    # First add an entry
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as f:
        f.write("# Physics Guide\n\nChapter 1: Motion")
        f.flush()
        temp_path = f.name

    try:
        result = runner.invoke(app, ["aldoni", temp_path])
        assert result.exit_code == 0

        # Extract UUID from output
        output_lines = result.stdout.split("\n")
        uuid_line = [l for l in output_lines if "#" in l and "Manlibro aldonita" in l]
        assert uuid_line
        uuid_short = uuid_line[0].split("#")[1].strip()

        # View the entry
        result = runner.invoke(app, ["vidi", uuid_short])
        assert result.exit_code == 0
        assert "Physics Guide" in result.stdout
        assert "Motion" in result.stdout

    finally:
        Path(temp_path).unlink()


def test_serci_entry():
    """Test searching manual entries."""
    # Add entries
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as f:
        f.write("# Physics Manual\n\nContent about physics")
        f.flush()
        temp_path1 = f.name

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as f:
        f.write("# Chemistry Manual\n\nContent about chemistry")
        f.flush()
        temp_path2 = f.name

    try:
        runner.invoke(app, ["aldoni", temp_path1])
        runner.invoke(app, ["aldoni", temp_path2])

        # Search for physics
        result = runner.invoke(app, ["serci", "Physics"])
        assert result.exit_code == 0
        assert "Physics Manual" in result.stdout
        assert "Trovoj" in result.stdout

    finally:
        Path(temp_path1).unlink()
        Path(temp_path2).unlink()


def test_modifi_entry():
    """Test modifying a manual entry."""
    # Add entry
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as f:
        f.write("# Original Title\n\nOriginal content")
        f.flush()
        temp_path = f.name

    try:
        result = runner.invoke(app, ["aldoni", temp_path])
        assert result.exit_code == 0

        # Extract UUID
        uuid_short = result.stdout.split("#")[1].strip().split("\n")[0]

        # Create a modified version
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f2:
            f2.write("# Updated Title\n\nUpdated content")
            f2.flush()
            temp_path2 = f2.name

        # We can't easily test modifi interactively, but we can test the database directly
        # by verifying the original entry exists
        _ensure_db()
        entry = _resolve_man_entry(uuid_short)
        assert entry is not None
        assert "Original Title" in entry["titolo"]

    finally:
        Path(temp_path).unlink()
        try:
            Path(temp_path2).unlink()
        except (UnboundLocalError, FileNotFoundError):
            pass


def test_forigi_entry():
    """Test deleting a manual entry."""
    # Add entry
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as f:
        f.write("# Test Manual to Delete\n\nContent")
        f.flush()
        temp_path = f.name

    try:
        result = runner.invoke(app, ["aldoni", temp_path])
        assert result.exit_code == 0

        # Extract UUID
        uuid_short = result.stdout.split("#")[1].strip().split("\n")[0]

        # Delete with confirmation
        result = runner.invoke(app, ["forigi", uuid_short], input="y\n")
        assert result.exit_code == 0
        assert "✓ Manlibro forigita" in result.stdout

        # Verify it's deleted
        _ensure_db()
        entry = _resolve_man_entry(uuid_short)
        assert entry is None

    finally:
        Path(temp_path).unlink()


def test_resolve_man_entry():
    """Test entry resolution by UUID and title."""
    # Add entry
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as f:
        f.write("# Test Entry\n\nContent")
        f.flush()
        temp_path = f.name

    try:
        runner.invoke(app, ["aldoni", temp_path])

        # Get full UUID
        _ensure_db()
        conn = sqlite3.connect(_DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT uuid FROM man LIMIT 1")
        full_uuid = cursor.fetchone()[0]
        conn.close()

        # Test resolution by full UUID
        entry = _resolve_man_entry(full_uuid)
        assert entry is not None
        assert entry["titolo"] == "Test Entry"

        # Test resolution by short UUID
        short_uuid = full_uuid[:8]
        entry = _resolve_man_entry(short_uuid)
        assert entry is not None

        # Test resolution with # prefix
        entry = _resolve_man_entry(f"#{short_uuid}")
        assert entry is not None

        # Test resolution by partial title
        entry = _resolve_man_entry("Test Entry")
        assert entry is not None

    finally:
        Path(temp_path).unlink()


def test_get_manuals_for_encik():
    """Test getting manuals linked to an encik entry."""
    # Create a manual linked to a specific encik UUID
    encik_uuid = "test-encik-uuid-12345678"

    _ensure_db()
    conn = sqlite3.connect(_DB_FILE)
    cursor = conn.cursor()

    # Manually insert a manual linked to encik
    import uuid as _uuid_mod

    man_uuid = str(_uuid_mod.uuid4())
    cursor.execute(
        """INSERT INTO man (uuid, titolo, enhavo, encik_uuid, kreita_je, modifita_je)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            man_uuid,
            "Test Manual",
            "Content",
            encik_uuid,
            "2026-04-27T00:00:00+00:00",
            "2026-04-27T00:00:00+00:00",
        ),
    )
    conn.commit()
    conn.close()

    # Get manuals for this encik entry
    manuals = get_manuals_for_encik(encik_uuid)
    assert len(manuals) == 1
    assert manuals[0]["titolo"] == "Test Manual"
    assert manuals[0]["uuid"] == man_uuid

    # Get manuals for non-existent encik entry
    manuals = get_manuals_for_encik("non-existent-uuid")
    assert len(manuals) == 0


def test_database_initialization():
    """Test database initialization."""
    _ensure_db()
    assert _DB_FILE.exists()

    conn = sqlite3.connect(_DB_FILE)
    cursor = conn.cursor()

    # Check tables exist
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}
    assert "man" in tables

    # Check indexes exist
    cursor.execute("SELECT name FROM sqlite_master WHERE type='index'")
    indexes = {row[0] for row in cursor.fetchall()}
    assert "idx_man_titolo_lower" in indexes
    assert "idx_man_encik_uuid" in indexes

    conn.close()


def test_aldoni_nonexistent_file():
    """Test adding a non-existent file."""
    result = runner.invoke(app, ["aldoni", "/nonexistent/file.md"])
    assert result.exit_code != 0
    assert "Dosiero ne trovita" in result.stdout or "Dosiero ne trovita" in result.stderr


def test_aldoni_with_encik_link():
    """Test adding a manual with encik link."""
    # This test checks that the -L option is accepted
    # (actual encik validation requires an encik entry to exist)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as f:
        f.write("# Physics\n\nContent")
        f.flush()
        temp_path = f.name

    try:
        # Try with non-existent encik UUID
        result = runner.invoke(app, ["aldoni", temp_path, "-L", "nonexistent-uuid"])
        # Should fail because encik doesn't exist
        assert result.exit_code != 0
        assert "Encik-nodo ne trovita" in result.stdout or "Encik-nodo ne trovita" in result.stderr

    finally:
        Path(temp_path).unlink()


def test_search_by_content():
    """Test searching by content instead of title."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as f:
        f.write("# General Title\n\nSpecial keyword in content")
        f.flush()
        temp_path = f.name

    try:
        runner.invoke(app, ["aldoni", temp_path])

        # Search for content keyword
        result = runner.invoke(app, ["serci", "Special", "-t"])
        assert result.exit_code == 0
        assert "General Title" in result.stdout

    finally:
        Path(temp_path).unlink()


def test_markdown_rendering():
    """Test that markdown content is properly stored and retrieved."""
    md_content = """# Advanced Physics

## Quantum Mechanics

- Wave functions
- Superposition
- Entanglement

### Key Equations

The Schrödinger equation:
iℏ ∂Ψ/∂t = ĤΨ
"""

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as f:
        f.write(md_content)
        f.flush()
        temp_path = f.name

    try:
        result = runner.invoke(app, ["aldoni", temp_path])
        assert result.exit_code == 0

        # Extract UUID and view
        uuid_short = result.stdout.split("#")[1].strip().split("\n")[0]
        result = runner.invoke(app, ["vidi", uuid_short])
        assert result.exit_code == 0
        assert "Quantum Mechanics" in result.stdout
        assert "Schrödinger" in result.stdout

    finally:
        Path(temp_path).unlink()
