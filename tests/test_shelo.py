"""Tests for autish.commands.shelo."""

from __future__ import annotations

import shutil
import sys
from unittest.mock import patch

from typer.testing import CliRunner

from autish.main import app

runner = CliRunner()


def test_shelo_help_shows_usage(monkeypatch):
    """Test shelo --help shows the help message."""
    result = runner.invoke(app, ["shelo", "--help"])
    assert result.exit_code == 0
    assert "interagan" in result.output or "interactive" in result.output.lower()


def test_autish_cmd_finds_executable(monkeypatch):
    """Test _autish_cmd returns correct command."""
    import autish.commands.shelo as shelo_mod

    # Test when 'autish' is in PATH
    with patch.object(shutil, "which", return_value="/usr/bin/autish"):
        cmd = shelo_mod._autish_cmd()
        assert cmd == ["/usr/bin/autish"]

    # Test when not found - falls back to python -m
    with patch.object(shutil, "which", return_value=None):
        with patch.object(sys, "executable", "/usr/bin/python3"):
            cmd = shelo_mod._autish_cmd()
            assert cmd == ["/usr/bin/python3", "-m", "autish"]


def test_history_file_path(monkeypatch):
    """Test that history file path is correctly configured."""
    import autish.commands.shelo as shelo_mod

    # The path should be set to ~/.local/share/autish/shelo_history
    assert "shelo_history" in str(shelo_mod._HISTORY_FILE)
    assert ".local" in str(shelo_mod._HISTORY_FILE)


def test_exit_words_includes_esperanto(monkeypatch):
    """Test that exit words include Esperanto 'eliru'."""
    import autish.commands.shelo as shelo_mod

    assert "eliru" in shelo_mod._EXIT_WORDS
    assert "exit" in shelo_mod._EXIT_WORDS
    assert "quit" in shelo_mod._EXIT_WORDS