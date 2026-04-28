"""Utilities for local/offline Markmap support."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

_MARKMAP_DIR = Path.home() / ".local" / "share" / "autish" / "markmap"
_MARKMAP_BIN = _MARKMAP_DIR / "node_modules" / ".bin" / "markmap"
_MARKMAP_PACKAGE = "markmap-cli@0.18.12"


def markmap_cli_path() -> Path:
    """Return the local Markmap CLI path."""
    return _MARKMAP_BIN


def has_markmap_cli() -> bool:
    """Return True when local Markmap CLI is installed."""
    return _MARKMAP_BIN.exists()


def install_markmap_cli(timeout: int = 180) -> tuple[bool, str]:
    """Install Markmap CLI locally for offline rendering support."""
    npm = shutil.which("npm")
    if not npm:
        return False, "npm ne trovita; ne eblas instali markmap-cli."

    _MARKMAP_DIR.mkdir(parents=True, exist_ok=True)
    package_json = _MARKMAP_DIR / "package.json"
    if not package_json.exists():
        package_json.write_text(
            json.dumps(
                {"name": "autish-markmap", "private": True, "version": "0.0.0"},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    try:
        result = subprocess.run(
            [
                npm,
                "install",
                "--no-audit",
                "--no-fund",
                "--prefer-offline",
                _MARKMAP_PACKAGE,
            ],
            cwd=_MARKMAP_DIR,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, "Timeout dum instalado de markmap-cli."

    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip().splitlines()
        tail = err[-1] if err else "nekonata npm-eraro"
        return False, f"markmap-cli instalado malsukcesis: {tail}"

    if not has_markmap_cli():
        return False, "markmap-cli ne troviĝis post instalado."

    return True, f"Markmap instalita: {_MARKMAP_BIN}"
