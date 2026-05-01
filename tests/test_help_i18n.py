from __future__ import annotations

from typer.testing import CliRunner

import autish.i18n as i18n_mod
from autish.main import app

runner = CliRunner()


def test_autish_help_is_localized_in_esperanto(monkeypatch):
    monkeypatch.setenv("LANG", "eo_FR.UTF-8")
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Cross-platform CLI for essential tasks" not in result.output
    assert "Transplatforma CLI por esencaj taskoj" in result.output
    assert "Show this message and exit." not in result.output
    assert "Montri ĉi tiun mesaĝon kaj eliri." in result.output
    assert "Install completion for the current shell." not in result.output
    assert "Instali kompletigon por la aktuala ŝelo." in result.output


def test_ui_lang_prefers_profile_lingvoj_order(monkeypatch):
    monkeypatch.setenv("LANG", "eo_FR.UTF-8")
    # Patch autish.profile.load_profile which is what i18n.py imports
    import autish.profile as profile_mod
    monkeypatch.setattr(
        profile_mod,
        "load_profile",
        lambda quiet=False: {"lingvoj": ["fr", "en"]},
    )
    assert i18n_mod.ui_lang() == "fr"


def test_ui_lang_falls_back_to_system_when_profile_lingvoj_missing(monkeypatch):
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    import autish.profile as profile_mod
    monkeypatch.setattr(profile_mod, "load_profile", lambda quiet=False: {})
    assert i18n_mod.ui_lang() == "en"


def test_ui_lang_accepts_profile_lingvo_csv(monkeypatch):
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    import autish.profile as profile_mod
    monkeypatch.setattr(
        profile_mod,
        "load_profile",
        lambda quiet=False: {"lingvoj": "fr,en"},
    )
    assert i18n_mod.ui_lang() == "fr"
