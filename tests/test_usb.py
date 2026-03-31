"""Tests for autish.commands.usb."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from autish.main import app

runner = CliRunner()


class _CP:
    def __init__(self, code: int, out: str = "", err: str = "") -> None:
        self.returncode = code
        self.stdout = out
        self.stderr = err


def test_usb_ls_basic() -> None:
    lines = (
        "Bus 001 Device 002: ID 8087:0029 Intel Corp.\n"
        "Bus 001 Device 003: ID 046d:c534 Logitech, Inc.\n"
    )
    with patch("autish.commands.usb._run", return_value=_CP(0, out=lines)):
        result = runner.invoke(app, ["usb", "ls"])
    assert result.exit_code == 0
    assert "Bus 001 Device 002" in result.output
    assert "Bus 001 Device 003" in result.output


def test_usb_ls_detail_marks_disconnected() -> None:
    lines = "Bus 001 Device 002: ID 8087:0029 Intel Corp.\n"
    with (
        patch("autish.commands.usb._run", return_value=_CP(0, out=lines)),
        patch("autish.commands.usb._sysfs_device_path", return_value=Path("/tmp/dev")),
        patch("autish.commands.usb._driver_bind_path", return_value=None),
    ):
        result = runner.invoke(app, ["usb", "ls", "-a"])
    assert result.exit_code == 0
    assert "malkonektita" in result.output.lower()


def test_usb_malkonekti_success() -> None:
    unbind = MagicMock()
    with (
        patch(
            "autish.commands.usb._sysfs_device_path", return_value=Path("/tmp/devpath")
        ),
        patch(
            "autish.commands.usb._driver_bind_path",
            return_value=(Path("/tmp/bind"), unbind),
        ),
    ):
        result = runner.invoke(app, ["usb", "malkonekti", "001:002"])
    assert result.exit_code == 0
    unbind.write_text.assert_called_once_with("devpath", encoding="utf-8")


def test_usb_konekti_without_driver_fails() -> None:
    with (
        patch("autish.commands.usb._sysfs_device_path", return_value=Path("/tmp/dev")),
        patch("autish.commands.usb._driver_bind_path", return_value=None),
    ):
        result = runner.invoke(app, ["usb", "konekti", "001:002"])
    assert result.exit_code != 0
    assert "neniu aktiva ŝoforo" in result.output.lower()


def test_usb_malkonekti_not_found() -> None:
    with patch("autish.commands.usb._sysfs_device_path", return_value=None):
        result = runner.invoke(app, ["usb", "malkonekti", "001:072"])
    assert result.exit_code != 0
    assert "ne trovita" in result.output.lower()


def test_sysfs_device_path_matches_bus_and_dev(tmp_path) -> None:
    root = tmp_path / "sys"
    dev = root / "1-7"
    dev.mkdir(parents=True)
    (dev / "busnum").write_text("1\n", encoding="utf-8")
    (dev / "devnum").write_text("72\n", encoding="utf-8")
    from autish.commands.usb import _sysfs_device_path
    found = _sysfs_device_path("001", "072", root=root)
    assert found == dev
