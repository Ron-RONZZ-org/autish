"""Tests for autish.commands.sistemo."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import psutil
from typer.testing import CliRunner

from autish.main import app

runner = CliRunner()


def _cp(
    *,
    rc: int = 0,
    out: str = "",
    err: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["cmd"], returncode=rc, stdout=out, stderr=err
    )


def test_info_shows_os_info(monkeypatch):
    """Test sistemo info shows OS information."""

    def _fake_psutil_virtual_memory():
        m = psutil._common.svmem()
        return psutil._common.svmem(
            total=16 * 1024**3,  # 16 GiB
            available=8 * 1024**3,
            percent=50.0,
            used=8 * 1024**3,
            free=8 * 1024**3,
        )

    def _fake_psutil_cpu_percent(*args, **kwargs):
        return 25.0

    def _fake_psutil_disk_usage(path):
        return psutil._common.sdiskusage(
            total=500 * 1024**3,
            used=200 * 1024**3,
            free=300 * 1024**3,
            percent=40.0,
        )

    monkeypatch.setattr(psutil, "virtual_memory", _fake_psutil_virtual_memory)
    monkeypatch.setattr(psutil, "cpu_percent", _fake_psutil_cpu_percent)
    monkeypatch.setattr(psutil, "disk_usage", _fake_psutil_disk_usage)

    result = runner.invoke(app, ["sistemo", "info"])
    assert result.exit_code == 0
    assert "OS" in result.output
    assert "CPU" in result.output
    assert "RAM" in result.output


def test_info_shows_battery_when_available(monkeypatch):
    """Test sistemo info shows battery info when battery present."""

    def _fake_psutil_virtual_memory():
        return psutil._common.svmem(
            total=16 * 1024**3,
            available=8 * 1024**3,
            percent=50.0,
            used=8 * 1024**3,
            free=8 * 1024**3,
        )

    def _fake_psutil_cpu_percent(*args, **kwargs):
        return 25.0

    def _fake_psutil_disk_usage(path):
        return psutil._common.sdiskusage(
            total=500 * 1024**3,
            used=200 * 1024**3,
            free=300 * 1024**3,
            percent=40.0,
        )

    class FakeBattery:
        percent = 85
        power_plugged = False

    monkeypatch.setattr(psutil, "virtual_memory", _fake_psutil_virtual_memory)
    monkeypatch.setattr(psutil, "cpu_percent", _fake_psutil_cpu_percent)
    monkeypatch.setattr(psutil, "disk_usage", _fake_psutil_disk_usage)
    monkeypatch.setattr(psutil, "sensors_battery", lambda: FakeBattery())

    result = runner.invoke(app, ["sistemo", "info"])
    assert result.exit_code == 0
    assert "Baterio" in result.output


def test_info_hides_battery_when_not_available(monkeypatch):
    """Test sistemo info hides battery when no battery present."""

    def _fake_psutil_virtual_memory():
        return psutil._common.svmem(
            total=16 * 1024**3,
            available=8 * 1024**3,
            percent=50.0,
            used=8 * 1024**3,
            free=8 * 1024**3,
        )

    def _fake_psutil_cpu_percent(*args, **kwargs):
        return 25.0

    def _fake_psutil_disk_usage(path):
        return psutil._common.sdiskusage(
            total=500 * 1024**3,
            used=200 * 1024**3,
            free=300 * 1024**3,
            percent=40.0,
        )

    def _fake_sensors_battery():
        return None

    monkeypatch.setattr(psutil, "virtual_memory", _fake_psutil_virtual_memory)
    monkeypatch.setattr(psutil, "cpu_percent", _fake_psutil_cpu_percent)
    monkeypatch.setattr(psutil, "disk_usage", _fake_psutil_disk_usage)
    monkeypatch.setattr(psutil, "sensors_battery", _fake_sensors_battery)

    result = runner.invoke(app, ["sistemo", "info"])
    assert result.exit_code == 0
    # Battery info should not appear when no battery
    assert "Baterio" not in result.output


def test_info_shows_network_info(monkeypatch):
    """Test sistemo info shows network interfaces."""

    def _fake_psutil_virtual_memory():
        return psutil._common.svmem(
            total=16 * 1024**3,
            available=8 * 1024**3,
            percent=50.0,
            used=8 * 1024**3,
            free=8 * 1024**3,
        )

    def _fake_psutil_cpu_percent(*args, **kwargs):
        return 25.0

    def _fake_psutil_disk_usage(path):
        return psutil._common.sdiskusage(
            total=500 * 1024**3,
            used=200 * 1024**3,
            free=300 * 1024**3,
            percent=40.0,
        )

    def _fake_net_if_addrs():
        return {
            "eth0": [
                psutil._common.saddr(
                    family=psutil.AF_INET, address="192.168.1.100", netmask=None
                )
            ],
            "lo": [
                psutil._common.saddr(
                    family=psutil.AF_INET, address="127.0.0.1", netmask=None
                )
            ],
        }

    monkeypatch.setattr(psutil, "virtual_memory", _fake_psutil_virtual_memory)
    monkeypatch.setattr(psutil, "cpu_percent", _fake_psutil_cpu_percent)
    monkeypatch.setattr(psutil, "disk_usage", _fake_psutil_disk_usage)
    monkeypatch.setattr(psutil, "net_if_addrs", _fake_net_if_addrs)

    result = runner.invoke(app, ["sistemo", "info"])
    assert result.exit_code == 0
    assert "Reto" in result.output or "192.168" in result.output


def test_bash_alias_list_empty(monkeypatch, tmp_path):
    """Test sistemo bash alias ls when no aliases exist."""
    import autish.commands.sistemo as sistemo_mod

    # Mock the database path
    db_path = tmp_path / "bash_aliases.db"
    monkeypatch.setattr(sistemo_mod, "_get_bash_alias_db_path", lambda: db_path)

    result = runner.invoke(app, ["sistemo", "bash", "alias", "ls"])
    assert result.exit_code == 0


def test_bash_alias_add_and_list(monkeypatch, tmp_path):
    """Test adding and listing bash aliases."""
    import autish.commands.sistemo as sistemo_mod
    from autish.services.bash_alias import BashAliasDB

    db_path = tmp_path / "bash_aliases.db"
    monkeypatch.setattr(sistemo_mod, "_get_bash_alias_db_path", lambda: db_path)

    # Create DB and add alias
    db = BashAliasDB(db_path)
    db.add_alias("test_alias", "echo 'test'", "test command")

    # Test listing
    result = runner.invoke(app, ["sistemo", "bash", "alias", "ls"])
    assert result.exit_code == 0
    assert "test_alias" in result.output


def test_bash_alias_remove(monkeypatch, tmp_path):
    """Test removing a bash alias."""
    import autish.commands.sistemo as sistemo_mod
    from autish.services.bash_alias import BashAliasDB

    db_path = tmp_path / "bash_aliases.db"
    monkeypatch.setattr(sistemo_mod, "_get_bash_alias_db_path", lambda: db_path)

    # Create DB and add alias
    db = BashAliasDB(db_path)
    db.add_alias("to_remove", "echo 'test'", "test command")

    # Remove alias
    result = runner.invoke(
        app,
        ["sistemo", "bash", "alias", "forigi", "to_remove"],
        input="J\n",  # Confirm deletion
    )
    assert result.exit_code == 0

    # Verify removed
    result = runner.invoke(app, ["sistemo", "bash", "alias", "ls"])
    assert "to_remove" not in result.output


def test_bash_alias_forigi_cancelled(monkeypatch, tmp_path):
    """Test cancelled alias removal."""
    import autish.commands.sistemo as sistemo_mod
    from autish.services.bash_alias import BashAliasDB

    db_path = tmp_path / "bash_aliases.db"
    monkeypatch.setattr(sistemo_mod, "_get_bash_alias_db_path", lambda: db_path)

    db = BashAliasDB(db_path)
    db.add_alias("test_alias", "echo 'test'", "test")

    # Cancel removal
    result = runner.invoke(
        app,
        ["sistemo", "bash", "alias", "forigi", "test_alias"],
        input="N\n",  # Cancel
    )
    assert result.exit_code == 0
    assert "Nuligita" in result.output