"""Tests for autish.commands.disko (disk management CLI)."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from autish.main import app

runner = CliRunner()


class TestDiskoLs:
    """Test the disko ls command."""

    def test_ls_runs_without_error(self, mocker):
        """Test that disko ls can execute (may need lsblk available)."""
        # Mock lsblk output
        mock_output = {
            "blockdevices": [
                {
                    "name": "sda",
                    "type": "disk",
                    "mountpoint": None,
                    "size": 1000204886016,
                    "fstype": None,
                    "rm": False,
                    "ro": False,
                    "model": "Test Disk",
                    "fsavail": None,
                    "children": [
                        {
                            "name": "sda1",
                            "type": "part",
                            "mountpoint": "/",
                            "size": 500107608064,
                            "fstype": "ext4",
                            "rm": False,
                            "ro": False,
                            "model": None,
                            "fsavail": 250000000000,
                        }
                    ],
                }
            ]
        }
        
        mock_run = mocker.patch("autish.commands.disko.subprocess.run")
        mock_result = mocker.Mock()
        mock_result.stdout = json.dumps(mock_output)
        mock_result.returncode = 0
        mock_run.return_value = mock_result
        
        result = runner.invoke(app, ["disko", "ls"])
        assert result.exit_code == 0
        assert "disko" in result.output or "subdisko" in result.output

    def test_ls_empty_devices(self, mocker):
        """Test disko ls with no devices."""
        mock_output = {"blockdevices": []}
        
        mock_run = mocker.patch("autish.commands.disko.subprocess.run")
        mock_result = mocker.Mock()
        mock_result.stdout = json.dumps(mock_output)
        mock_result.returncode = 0
        mock_run.return_value = mock_result
        
        result = runner.invoke(app, ["disko", "ls"])
        assert result.exit_code == 0
        assert "Neniu disko trovita" in result.output


class TestDiskoHelp:
    """Test disko help and command structure."""

    def test_disko_help(self):
        """Test that disko --help works."""
        result = runner.invoke(app, ["disko", "--help"])
        assert result.exit_code == 0
        assert "disko" in result.output.lower()

    def test_sano_help(self):
        """Test that disko sano --help works."""
        result = runner.invoke(app, ["disko", "sano", "--help"])
        assert result.exit_code == 0
        assert "SMART" in result.output or "sano" in result.output

    def test_munti_help(self):
        """Test that disko munti --help works."""
        result = runner.invoke(app, ["disko", "munti", "--help"])
        assert result.exit_code == 0
        assert "munti" in result.output or "mount" in result.output.lower()

    def test_malmunti_help(self):
        """Test that disko malmunti --help works."""
        result = runner.invoke(app, ["disko", "malmunti", "--help"])
        assert result.exit_code == 0
        assert "malmunti" in result.output or "unmount" in result.output.lower()
