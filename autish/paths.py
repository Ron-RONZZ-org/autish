"""Centralized path handling for autish.

This module provides centralized path functions to avoid hardcoded paths
scattered across the codebase. Commands can import from here instead of
defining their own _DATA_DIR constants.

Usage:
    from autish.paths import data_dir, config_dir, ensure_data_dir

    data_dir()              # -> Path("~/.local/share/autish")
    config_dir()            # -> Path("~/.config/autish")
    ensure_data_dir()       # Creates directory if not exists, returns Path
"""

from __future__ import annotations

from pathlib import Path


def data_dir() -> Path:
    """Return the data directory Path (~/.local/share/autish).

    This is where database files and user data are stored.
    """
    return Path.home() / ".local" / "share" / "autish"


def config_dir() -> Path:
    """Return the config directory Path (~/.config/autish).

    This is where configuration files are stored.
    """
    return Path.home() / ".config" / "autish"


def ensure_data_dir() -> Path:
    """Create and return the data directory.

    Creates ~/.local/share/autish if it doesn't exist.
    """
    d = data_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def ensure_config_dir() -> Path:
    """Create and return the config directory.

    Creates ~/.config/autish if it doesn't exist.
    """
    d = config_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


# Database file paths (common ones)
def vorto_db() -> Path:
    """Return path to vorto database."""
    return data_dir() / "vorto.db"


def encik_db() -> Path:
    """Return path to encik database."""
    return data_dir() / "encik.db"


def doc_db() -> Path:
    """Return path to doc database."""
    return data_dir() / "doc.db"


def retposto_db() -> Path:
    """Return path to retposto database."""
    return data_dir() / "retposto.db"


def tasklibro_db() -> Path:
    """Return path to tasklibro (todo/etikedo/taglibro) database."""
    return data_dir() / "tasklibro.db"


def bash_aliases_db() -> Path:
    """Return path to bash aliases database."""
    return config_dir() / "bash_aliases.db"


def profile_file() -> Path:
    """Return path to user profile file."""
    return data_dir() / "uzanto_profilo.toml"


def profile_enc_file() -> Path:
    """Return path to encrypted user profile file."""
    return data_dir() / "uzanto_profilo.enc"