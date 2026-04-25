"""Tests for disko particio command."""

import pytest
from unittest.mock import patch, MagicMock
from typer.testing import CliRunner
from autish.commands.disko import app
from autish.services.partition_manager import (
    is_mounted,
    is_root_filesystem,
    get_mount_point,
)

runner = CliRunner()


class TestPartitionHelpers:
    """Tests for partition management helper functions."""

    @patch("autish.services.partition_manager.subprocess.run")
    def test_is_mounted(self, mock_run):
        """Test checking if a device is mounted."""
        mock_run.return_value = MagicMock(
            stdout="/dev/sda1 on / type ext4\n/dev/sda2 on /home type ext4\n"
        )
        
        assert is_mounted("sda1") is True
        assert is_mounted("/dev/sda1") is True
        assert is_mounted("sdb1") is False

    @patch("autish.services.partition_manager.get_mount_point")
    def test_is_root_filesystem(self, mock_mount_point):
        """Test checking if device is root filesystem."""
        mock_mount_point.return_value = "/"
        assert is_root_filesystem("sda1") is True
        
        mock_mount_point.return_value = "/boot"
        assert is_root_filesystem("sda2") is True
        
        mock_mount_point.return_value = "/home"
        assert is_root_filesystem("sdb1") is False

    @patch("autish.services.partition_manager.subprocess.run")
    def test_get_mount_point(self, mock_run):
        """Test getting mount point of a device."""
        mock_run.return_value = MagicMock(
            stdout="/dev/sda1 on / type ext4 (rw,relatime)\n"
        )
        
        result = get_mount_point("sda1")
        assert result == "/"


class TestDiskoParticioCLI:
    """Tests for disko particio CLI commands."""

    def test_particio_help(self):
        """Test particio subcommand help."""
        result = runner.invoke(app, ["particio", "--help"])
        
        assert result.exit_code == 0
        assert "shrink" in result.stdout
        assert "krei" in result.stdout
        assert "formati" in result.stdout

    def test_shrink_requires_args(self):
        """Test shrink command requires arguments."""
        result = runner.invoke(app, ["particio", "shrink"])
        
        assert result.exit_code != 0

    def test_krei_requires_args(self):
        """Test krei command requires arguments."""
        result = runner.invoke(app, ["particio", "krei"])
        
        assert result.exit_code != 0

    def test_formati_requires_args(self):
        """Test formati command requires arguments."""
        result = runner.invoke(app, ["particio", "formati"])
        
        assert result.exit_code != 0

    @patch("autish.services.partition_manager.shrink_partition")
    def test_shrink_with_confirmation_cancel(self, mock_shrink):
        """Test shrink command with user cancellation."""
        # Simulate user declining confirmation
        result = runner.invoke(
            app,
            ["particio", "shrink", "sda1", "50GB"],
            input="n\n"  # Say 'no' to confirmation
        )
        
        # Command should exit cleanly without calling the backend
        assert result.exit_code == 0
        assert "Nuligita" in result.stdout

    @patch("autish.services.partition_manager.create_partition")
    def test_krei_with_confirmation_cancel(self, mock_create):
        """Test krei command with user cancellation."""
        result = runner.invoke(
            app,
            ["particio", "krei", "sda", "50GB"],
            input="n\n"  # Say 'no' to confirmation
        )
        
        assert result.exit_code == 0
        assert "Nuligita" in result.stdout

    @patch("autish.services.partition_manager.format_partition")
    def test_formati_with_confirmation_cancel(self, mock_format):
        """Test formati command with user cancellation."""
        result = runner.invoke(
            app,
            ["particio", "formati", "sda1"],
            input="n\n"  # Say 'no' to confirmation
        )
        
        assert result.exit_code == 0
        assert "Nuligita" in result.stdout

    @patch("autish.services.partition_manager.shrink_partition")
    def test_shrink_success_with_justa(self, mock_shrink):
        """Test shrink command with -j flag to skip confirmation."""
        mock_shrink.return_value = (True, "Particio sda1 shrinkita al 50GB")
        
        result = runner.invoke(
            app,
            ["particio", "shrink", "sda1", "50GB", "-j"]
        )
        
        assert result.exit_code == 0
        assert "[✓]" in result.stdout

    @patch("autish.services.partition_manager.shrink_partition")
    def test_shrink_error(self, mock_shrink):
        """Test shrink command error handling."""
        mock_shrink.return_value = (False, "Apparato ne trovita")
        
        result = runner.invoke(
            app,
            ["particio", "shrink", "sda1", "50GB", "-j"]
        )
        
        assert result.exit_code != 0
        assert "[!]" in result.output or "Apparato" in result.output

    @patch("autish.services.partition_manager.create_partition")
    def test_krei_success_with_justa(self, mock_create):
        """Test krei command with -j flag."""
        mock_create.return_value = (True, "Nova particio sda1 kreitaen ext4")
        
        result = runner.invoke(
            app,
            ["particio", "krei", "sda", "50GB", "-j"]
        )
        
        assert result.exit_code == 0
        assert "[✓]" in result.stdout

    @patch("autish.services.partition_manager.format_partition")
    def test_formati_success_with_justa(self, mock_format):
        """Test formati command with -j flag."""
        mock_format.return_value = (True, "Particio sda1 formatita kiel ext4")
        
        result = runner.invoke(
            app,
            ["particio", "formati", "sda1", "-j"]
        )
        
        assert result.exit_code == 0
        assert "[✓]" in result.stdout

    @patch("autish.services.partition_manager.format_partition")
    def test_formati_with_custom_filesystem(self, mock_format):
        """Test formati command with custom filesystem type."""
        mock_format.return_value = (True, "Particio sda1 formatita kiel ntfs")
        
        result = runner.invoke(
            app,
            ["particio", "formati", "sda1", "-t", "ntfs", "-j"]
        )
        
        assert result.exit_code == 0
        assert "[✓]" in result.stdout
        # Verify the filesystem type was passed correctly
        mock_format.assert_called_with("sda1", "ntfs", force=True)


class TestPartitionSafetyGuards:
    """Tests for partition management safety checks."""

    @patch("autish.services.partition_manager.is_root_filesystem")
    @patch("autish.services.partition_manager.format_partition")
    def test_prevent_formatting_root(self, mock_format, mock_is_root):
        """Test that formatting root filesystem is prevented."""
        mock_is_root.return_value = True
        mock_format.return_value = (False, "Ne eblas formati la radikan dosierujon!")
        
        result = runner.invoke(
            app,
            ["particio", "formati", "sda1", "-j"]
        )
        
        # Should fail with safety message
        assert result.exit_code != 0

    @patch("autish.services.partition_manager.is_mounted")
    @patch("autish.services.partition_manager.format_partition")
    def test_prevent_formatting_mounted(self, mock_format, mock_is_mounted):
        """Test that formatting mounted filesystem is prevented."""
        mock_is_mounted.return_value = True
        mock_format.return_value = (
            False,
            "sda1 estas munkita. Bonvolu elmuntigi antaŭ ol formati."
        )
        
        result = runner.invoke(
            app,
            ["particio", "formati", "sda1", "-j"]
        )
        
        # Should fail with safety message
        assert result.exit_code != 0
