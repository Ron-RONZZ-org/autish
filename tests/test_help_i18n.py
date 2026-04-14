from __future__ import annotations

from typer.testing import CliRunner

from autish.main import app

runner = CliRunner()


def test_autish_help_is_localized_in_esperanto(monkeypatch):
    monkeypatch.setenv("LANG", "eo_FR.UTF-8")
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Cross-platform CLI for essential tasks" not in result.output
    assert "Transplatforma CLI por esencaj taskoj" in result.output
    assert "Montri ĉi tiun mesaĝon kaj eliri." in result.output
    assert "Install completion for the current shell." not in result.output
    assert "Instali kompletigon por la aktuala ŝelo." in result.output
