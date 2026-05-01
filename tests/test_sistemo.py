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

    class MockVM:
        def __init__(self):
            self.total = 16 * 1024**3
            self.available = 8 * 1024**3
            self.percent = 50.0
            self.used = 8 * 1024**3
            self.free = 8 * 1024**3

    class MockDisk:
        def __init__(self):
            self.total = 500 * 1024**3
            self.used = 200 * 1024**3
            self.free = 300 * 1024**3
            self.percent = 40.0

    monkeypatch.setattr(psutil, "virtual_memory", lambda: MockVM())
    monkeypatch.setattr(psutil, "cpu_percent", lambda *a, **kw: 25.0)
    monkeypatch.setattr(psutil, "disk_usage", lambda p: MockDisk())

    result = runner.invoke(app, ["sistemo", "info"])
    assert result.exit_code == 0
    assert "OS" in result.output
    assert "CPU" in result.output
    assert "RAM" in result.output


def test_info_shows_battery_when_available(monkeypatch):
    """Test sistemo info shows battery info when battery present."""

    class MockVM:
        def __init__(self):
            self.total = 16 * 1024**3
            self.available = 8 * 1024**3
            self.percent = 50.0
            self.used = 8 * 1024**3
            self.free = 8 * 1024**3

    class MockDisk:
        def __init__(self):
            self.total = 500 * 1024**3
            self.used = 200 * 1024**3
            self.free = 300 * 1024**3
            self.percent = 40.0

    class FakeBattery:
        percent = 85
        power_plugged = False

    monkeypatch.setattr(psutil, "virtual_memory", lambda: MockVM())
    monkeypatch.setattr(psutil, "cpu_percent", lambda *a, **kw: 25.0)
    monkeypatch.setattr(psutil, "disk_usage", lambda p: MockDisk())
    monkeypatch.setattr(psutil, "sensors_battery", lambda: FakeBattery())

    result = runner.invoke(app, ["sistemo", "info"])
    assert result.exit_code == 0
    assert "Battery" in result.output


def test_info_hides_battery_when_not_available(monkeypatch):
    """Test sistemo info hides battery when no battery present."""

    class MockVM:
        def __init__(self):
            self.total = 16 * 1024**3
            self.available = 8 * 1024**3
            self.percent = 50.0
            self.used = 8 * 1024**3
            self.free = 8 * 1024**3

    class MockDisk:
        def __init__(self):
            self.total = 500 * 1024**3
            self.used = 200 * 1024**3
            self.free = 300 * 1024**3
            self.percent = 40.0

    monkeypatch.setattr(psutil, "virtual_memory", lambda: MockVM())
    monkeypatch.setattr(psutil, "cpu_percent", lambda *a, **kw: 25.0)
    monkeypatch.setattr(psutil, "disk_usage", lambda p: MockDisk())
    monkeypatch.setattr(psutil, "sensors_battery", lambda: None)

    result = runner.invoke(app, ["sistemo", "info"])
    assert result.exit_code == 0
    # When no battery, shows n/a
    assert "Battery  : n/a" in result.output


def test_info_shows_network_info(monkeypatch):
    """Test sistemo info shows network interfaces."""

    class MockVM:
        def __init__(self):
            self.total = 16 * 1024**3
            self.available = 8 * 1024**3
            self.percent = 50.0
            self.used = 8 * 1024**3
            self.free = 8 * 1024**3

    class MockDisk:
        def __init__(self):
            self.total = 500 * 1024**3
            self.used = 200 * 1024**3
            self.free = 300 * 1024**3
            self.percent = 40.0

    class MockSaddr:
        def __init__(self, family, address):
            self.family = family
            self.address = address

    monkeypatch.setattr(psutil, "virtual_memory", lambda: MockVM())
    monkeypatch.setattr(psutil, "cpu_percent", lambda *a, **kw: 25.0)
    monkeypatch.setattr(psutil, "disk_usage", lambda p: MockDisk())
    monkeypatch.setattr(psutil, "net_if_addrs", lambda: {
        "eth0": [MockSaddr(psutil.AF_INET, "192.168.1.100")],
        "lo": [MockSaddr(psutil.AF_INET, "127.0.0.1")],
    })

    result = runner.invoke(app, ["sistemo", "info"])
    assert result.exit_code == 0
    assert "Network" in result.output or "192.168" in result.output


def test_bash_alias_list_empty(monkeypatch, tmp_path):
    """Test sistemo bash alias ls when no aliases exist."""
    import autish.commands.sistemo as sistemo_mod

    # Mock the database path
    db_path = tmp_path / "bash_aliases.db"
    monkeypatch.setattr(sistemo_mod, "_get_bash_alias_db_path", lambda: db_path)

    result = runner.invoke(app, ["sistemo", "bash-alias", "ls"])
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
    result = runner.invoke(app, ["sistemo", "bash-alias", "ls"])
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
    uid = db.add_alias("to_remove", "echo 'test'", "test command")

    # Remove alias by UID
    result = runner.invoke(
        app,
        ["sistemo", "bash-alias", "forigi", "--justa", str(uid)],
    )
    assert result.exit_code == 0

    # Verify removed
    result = runner.invoke(app, ["sistemo", "bash-alias", "ls"])
    assert "to_remove" not in result.output


def test_bash_alias_forigi_cancelled(monkeypatch, tmp_path):
    """Test cancelled alias removal."""
    import autish.commands.sistemo as sistemo_mod
    from autish.services.bash_alias import BashAliasDB

    db_path = tmp_path / "bash_aliases.db"
    monkeypatch.setattr(sistemo_mod, "_get_bash_alias_db_path", lambda: db_path)

    db = BashAliasDB(db_path)
    uid = db.add_alias("test_alias", "echo 'test'", "test")

    # Cancel removal - without --justa so it prompts
    result = runner.invoke(
        app,
        ["sistemo", "bash-alias", "forigi", str(uid)],
        input="N\n",  # Cancel
    )
    assert result.exit_code == 0

    # Verify not removed
    result = runner.invoke(app, ["sistemo", "bash-alias", "ls"])
    assert "test_alias" in result.output
