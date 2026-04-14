"""Simple CLI i18n helpers for Click/Typer built-in help strings."""

from __future__ import annotations

import inspect
import os

_EO_MAP: dict[str, str] = {
    "Usage:": "Uzado:",
    "Options": "Opcioj",
    "Commands": "Komandoj",
    "Show this message and exit.": "Montri ĉi tiun mesaĝon kaj eliri.",
    "Install completion for the current shell.": (
        "Instali kompletigon por la aktuala ŝelo."
    ),
    (
        "Show completion for the current shell, to copy it or customize "
        "the installation."
    ): (
        "Montri kompletigon por la aktuala ŝelo, por kopii ĝin aŭ agordi la instaladon."
    ),
}

_FR_MAP: dict[str, str] = {
    "Usage:": "Utilisation :",
    "Options": "Options",
    "Commands": "Commandes",
    "Show this message and exit.": "Afficher ce message et quitter.",
    "Install completion for the current shell.": (
        "Installer la complétion pour le shell actuel."
    ),
    (
        "Show completion for the current shell, to copy it or customize "
        "the installation."
    ): (
        "Afficher la complétion du shell actuel pour la copier ou personnaliser "
        "l'installation."
    ),
}


def ui_lang() -> str:
    raw = os.environ.get("LC_ALL") or os.environ.get("LANG") or ""
    code = raw.split(".")[0].split("_")[0].lower()
    return code or "eo"


def tr(eo: str, en: str, fr: str) -> str:
    lang = ui_lang()
    if lang == "fr":
        return fr
    if lang == "en":
        return en
    return eo


def apply_cli_i18n() -> None:
    """Patch Click/Typer gettext hooks for built-in help labels."""
    lang = ui_lang()
    mapping = _EO_MAP if lang == "eo" else _FR_MAP if lang == "fr" else None
    if not mapping:
        return

    def _translate(msg: str) -> str:
        return mapping.get(msg, msg)

    import click.core  # noqa: PLC0415
    import click.decorators  # noqa: PLC0415
    import typer.completion  # noqa: PLC0415

    click.core._ = _translate  # type: ignore[attr-defined]
    click.decorators._ = _translate  # type: ignore[attr-defined]
    typer.completion._ = _translate  # type: ignore[attr-defined]

    # Typer completion option help strings are stored in placeholder function
    # defaults at import time, so patch them explicitly as well.
    for fn_name in (
        "_install_completion_placeholder_function",
        "_install_completion_no_auto_placeholder_function",
    ):
        fn = getattr(typer.completion, fn_name, None)
        if fn is None:
            continue
        sig = inspect.signature(fn)
        for param in sig.parameters.values():
            default = param.default
            help_text = getattr(default, "help", None)
            if isinstance(help_text, str):
                default.help = _translate(help_text)
