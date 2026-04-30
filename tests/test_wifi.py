"""Tests for autish.commands.wifi."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

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
        args=["nmcli"], returncode=rc, stdout=out, stderr=err
    )


def test_ls_shows_wifi_list(monkeypatch):
    """Test wifi ls shows available networks."""

    def _fake_run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        if "device" in cmd and "wifi" in cmd and "list" in cmd:
            return _cp(
                out="ACTIVE  SSID            SIGNAL  SECURITY\n"
                "yes     MyNetwork         75      WPA2\n"
                "no      NeighborNet       50      WPA2"
            )
        return _cp()

    import autish.commands.wifi as wifi_mod

    monkeypatch.setattr(wifi_mod, "_run", _fake_run)
    result = runner.invoke(app, ["wifi", "ls"])
    assert result.exit_code == 0
    assert "MyNetwork" in result.output
    assert "NeighborNet" in result.output


def test_ls_konservitaj_shows_saved_profiles(monkeypatch):
    """Test wifi ls --konservitaj shows saved profiles."""

    def _fake_run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        if "connection" in cmd and "show" in cmd:
            return _cp(
                out="NAME                 TYPE      DEVICE\n"
                "HomeWiFi               wifi      wlp0s20u2\n"
                "WorkNet                wifi      --"
            )
        return _cp()

    import autish.commands.wifi as wifi_mod

    monkeypatch.setattr(wifi_mod, "_run", _fake_run)
    result = runner.invoke(app, ["wifi", "ls", "-k"])
    assert result.exit_code == 0
    assert "HomeWiFi" in result.output
    assert "WorkNet" in result.output


def test_konekti_success(monkeypatch):
    """Test wifi konekti connects to a network."""

    def _fake_run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        if "connect" in cmd:
            return _cp(out="Connection successfully activated")
        return _cp()

    import autish.commands.wifi as wifi_mod

    monkeypatch.setattr(wifi_mod, "_run", _fake_run)
    result = runner.invoke(app, ["wifi", "konekti", "MyNetwork"])
    assert result.exit_code == 0
    assert "Connection successfully activated" in result.output


def test_konekti_with_password(monkeypatch):
    """Test wifi konekti with password option."""
    captured_cmd: list[str] = []

    def _fake_run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        captured_cmd.extend(cmd)
        return _cp(out="Connection successfully activated")

    import autish.commands.wifi as wifi_mod

    monkeypatch.setattr(wifi_mod, "_run", _fake_run)
    result = runner.invoke(app, ["wifi", "konekti", "MyNetwork", "-p", "secret123"])
    assert result.exit_code == 0
    assert "password" in captured_cmd
    assert "secret123" in captured_cmd


def test_konekti_fails_on_error(monkeypatch):
    """Test wifi konekti handles connection failure."""

    def _fake_run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        if "connect" in cmd:
            return _cp(rc=10, err="Connection failed: No suitable network")
        return _cp()

    import autish.commands.wifi as wifi_mod

    monkeypatch.setattr(wifi_mod, "_run", _fake_run)
    result = runner.invoke(app, ["wifi", "konekti", "BadNetwork"])
    assert result.exit_code != 0


def test_malkonekti_success(monkeypatch):
    """Test wifi malkonekti disconnects active connection."""
    device_calls: list[str] = []

    def _fake_run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        if "device" in cmd and "status" in cmd:
            return _cp(out="wlan0:wifi:connected:HomeWiFi\nlo:loopback:unmanaged")
        if "device" in cmd and "disconnect" in cmd:
            device_calls.append(cmd[-1])
            return _cp(out="Device disconnected successfully")
        return _cp()

    import autish.commands.wifi as wifi_mod

    monkeypatch.setattr(wifi_mod, "_run", _fake_run)
    result = runner.invoke(app, ["wifi", "malkonekti"])
    assert result.exit_code == 0
    assert "wlan0" in device_calls


def test_malkonekti_no_active_connection(monkeypatch):
    """Test wifi malkonekti when no active connection."""

    def _fake_run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        if "device" in cmd and "status" in cmd:
            return _cp(out="lo:loopback:unmanaged\neth0:ethernet:unmanaged")
        return _cp()

    import autish.commands.wifi as wifi_mod

    monkeypatch.setattr(wifi_mod, "_run", _fake_run)
    result = runner.invoke(app, ["wifi", "malkonekti"])
    assert result.exit_code == 0
    assert "No active Wi-Fi connection found" in result.output


def test_forigi_cancelled(monkeypatch):
    """Test wifi forigi cancelled when user says no."""
    prompt_response = "N"

    def _fake_run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        return _cp()

    import autish.commands.wifi as wifi_mod
    from unittest.mock import patch as mock_patch

    monkeypatch.setattr(wifi_mod, "_run", _fake_run)
    with mock_patch("typer.prompt", return_value=prompt_response):
        result = runner.invoke(app, ["wifi", "forigi", "OldNetwork"])
    assert result.exit_code == 0
    assert "Nuligita" in result.output


def test_restarti_success(monkeypatch):
    """Test wifi restarti restarts network stack."""
    calls: list[list[str]] = []

    def _fake_run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return _cp(out="Done")

    import autish.commands.wifi as wifi_mod

    monkeypatch.setattr(wifi_mod, "_run", _fake_run)
    result = runner.invoke(app, ["wifi", "restarti"])
    assert result.exit_code == 0
    assert len(calls) == 4  # off, off, on, on
    assert "radio" in calls[0][1]
    assert "radio" in calls[3][1]


def test_restarti_fails_on_step_error(monkeypatch):
    """Test wifi restarti stops on first error."""

    def _fake_run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        if "radio" in cmd and "off" in cmd:
            return _cp(rc=1, err="Failed to disable radio")
        return _cp()

    import autish.commands.wifi as wifi_mod

    monkeypatch.setattr(wifi_mod, "_run", _fake_run)
    result = runner.invoke(app, ["wifi", "restarti"])
    assert result.exit_code != 0
    assert "Failed to disable radio" in result.output