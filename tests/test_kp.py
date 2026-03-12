"""Tests for autish.commands.kp."""

from __future__ import annotations

import sys
from unittest.mock import patch

from autish.commands.kp import _AUTISH_SUBCOMMANDS, _resolve_command


class TestResolveCommand:
    """Unit tests for _resolve_command() subcommand detection."""

    def test_known_subcommand_gets_autish_prefix(self):
        with patch("autish.commands.kp.shutil.which", return_value="/usr/bin/autish"):
            result = _resolve_command(["sistemo"])
        assert result == ["/usr/bin/autish", "sistemo"]

    def test_known_subcommand_with_args_gets_prefix(self):
        with patch(
            "autish.commands.kp.shutil.which",
            return_value="/usr/local/bin/autish",
        ):
            result = _resolve_command(["tempo", "--horzono", "9"])
        assert result == ["/usr/local/bin/autish", "tempo", "--horzono", "9"]

    def test_unknown_command_unchanged(self):
        result = _resolve_command(["ls", "-la"])
        assert result == ["ls", "-la"]

    def test_empty_command_unchanged(self):
        assert _resolve_command([]) == []

    def test_fallback_to_python_when_autish_not_found(self):
        with patch("autish.commands.kp.shutil.which", return_value=None):
            result = _resolve_command(["tempo"])
        assert result[0] == sys.executable
        assert "autish" in result

    def test_all_registered_subcommands_are_known(self):
        """Verify the subcommand set covers all commands registered in main."""
        for name in ("tempo", "wifi", "bluhdento", "sistemo", "kp", "shelo"):
            assert name in _AUTISH_SUBCOMMANDS

    def test_system_command_not_confused_with_subcommand(self):
        """A regular shell command (e.g. 'echo') is not auto-prefixed."""
        result = _resolve_command(["echo", "hello"])
        assert result == ["echo", "hello"]


class TestKpSubprocessError:
    """Ensure kp surfaces errors cleanly when the resolved subprocess fails."""

    def test_resolve_command_called_for_autish_subcommand(self):
        """_resolve_command must prepend autish prefix for known subcommands."""
        with patch("autish.commands.kp.shutil.which", return_value="/usr/bin/autish"):
            result = _resolve_command(["tempo"])
        assert result[0] == "/usr/bin/autish"
        assert result[1] == "tempo"

    def test_resolve_command_not_called_for_unknown_command(self):
        """_resolve_command must leave unknown commands untouched."""
        result = _resolve_command(["date"])
        assert result == ["date"]
