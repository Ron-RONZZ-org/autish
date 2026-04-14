"""Tests for autish.commands.bluetooth."""

from __future__ import annotations

import subprocess

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
        args=["bluetoothctl"], returncode=rc, stdout=out, stderr=err
    )


def test_konekti_auto_powers_on_when_disabled(monkeypatch):
    calls: list[tuple[str, ...]] = []

    def _fake_bt(*args: str):
        calls.append(args)
        if args == ("show",):
            if len([c for c in calls if c == ("show",)]) == 1:
                return _cp(out="Powered: no\n")
            return _cp(out="Powered: yes\n")
        if args == ("power", "on"):
            return _cp(out="Changing power on succeeded\n")
        if args[0] == "connect":
            return _cp(out="Connection successful\n")
        return _cp()

    import autish.commands.bluetooth as bt_mod

    monkeypatch.setattr(bt_mod, "_bluetoothctl", _fake_bt)
    result = runner.invoke(app, ["bluhdento", "konekti", "AA:BB:CC:DD:EE:FF"])
    assert result.exit_code == 0, result.output
    assert ("power", "on") in calls
    assert ("connect", "AA:BB:CC:DD:EE:FF") in calls


def test_konekti_fails_if_power_on_fails(monkeypatch):
    def _fake_bt(*args: str):
        if args == ("show",):
            return _cp(out="Powered: no\n")
        if args == ("power", "on"):
            return _cp(rc=1, err="power failed")
        return _cp()

    import autish.commands.bluetooth as bt_mod

    monkeypatch.setattr(bt_mod, "_bluetoothctl", _fake_bt)
    result = runner.invoke(app, ["bluhdento", "konekti", "AA:BB:CC:DD:EE:FF"])
    assert result.exit_code != 0
    assert "power failed" in ((result.stdout or "") + (result.stderr or ""))


def test_konekti_retries_power_on_after_rfkill_unblock(monkeypatch):
    calls: list[tuple[str, ...]] = []

    def _fake_bt(*args: str):
        calls.append(args)
        if args == ("show",):
            if len([c for c in calls if c == ("show",)]) == 1:
                return _cp(out="Powered: no\n")
            return _cp(out="Powered: yes\n")
        if args == ("power", "on"):
            if len([c for c in calls if c == ("power", "on")]) == 1:
                return _cp(rc=1, err="Failed to set power on")
            return _cp(out="Changing power on succeeded\n")
        if args[0] == "connect":
            return _cp(out="Connection successful\n")
        return _cp()

    def _fake_run(cmd: list[str]):
        assert cmd == ["rfkill", "unblock", "bluetooth"]
        return _cp()

    import autish.commands.bluetooth as bt_mod

    monkeypatch.setattr(bt_mod, "_bluetoothctl", _fake_bt)
    monkeypatch.setattr(bt_mod, "_run", _fake_run)
    result = runner.invoke(app, ["bluhdento", "konekti", "AA:BB:CC:DD:EE:FF"])
    assert result.exit_code == 0, result.output
    assert calls.count(("power", "on")) == 2


def test_konekti_retries_on_br_connection_busy_then_succeeds(monkeypatch):
    connect_calls = 0

    def _fake_bt(*args: str):
        nonlocal connect_calls
        if args == ("show",):
            return _cp(out="Powered: yes\n")
        if args[0] == "connect":
            connect_calls += 1
            if connect_calls < 3:
                return _cp(rc=1, err="Failed to connect: br-connection-busy")
            return _cp(out="Connection successful\n")
        return _cp()

    import autish.commands.bluetooth as bt_mod

    monkeypatch.setattr(bt_mod, "_bluetoothctl", _fake_bt)
    monkeypatch.setattr(bt_mod.time, "sleep", lambda _s: None)
    result = runner.invoke(app, ["bluhdento", "konekti", "AA:BB:CC:DD:EE:FF"])
    assert result.exit_code == 0, result.output
    assert connect_calls >= 3
