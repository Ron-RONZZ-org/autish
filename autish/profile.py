"""User profile loading for autish.

This module provides non-interactive profile loading for i18n purposes.
It deliberately avoids Typer dependencies to prevent circular imports.
"""

from __future__ import annotations

from pathlib import Path

# ──────────────────────────────────────────────────────────────────────────────
# Paths & constants
# ──────────────────────────────────────────────────────────────────────────────

_DATA_DIR: Path = Path.home() / ".local" / "share" / "autish"
_PROFILE_FILE: Path = _DATA_DIR / "uzanto_profilo.toml"
_PROFILE_ENC_FILE: Path = _DATA_DIR / "uzanto_profilo.enc"

_KEYRING_SERVICE: str = "autish-uzanto"
_KEYRING_KEY: str = "master"


# ──────────────────────────────────────────────────────────────────────────────
# TOML helpers
# ──────────────────────────────────────────────────────────────────────────────


def _toml_loads(text: str) -> dict:
    try:
        import tomllib  # type: ignore[import-untyped]  # noqa: PLC0415
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef,import-untyped]  # noqa: PLC0415
    return tomllib.loads(text)


# ──────────────────────────────────────────────────────────────────────────────
# Master-password helpers
# ──────────────────────────────────────────────────────────────────────────────


def _get_master_password() -> str | None:
    """Return the stored master password, or None if not set."""
    try:
        import keyring  # noqa: PLC0415

        return keyring.get_password(_KEYRING_SERVICE, _KEYRING_KEY)
    except Exception:
        return None


# ──────────────────────────────────────────────────────────────────────────────
# Profile loading (for i18n and other non-interactive uses)
# ──────────────────────────────────────────────────────────────────────────────


def load_profile(*, quiet: bool = True) -> dict:
    """Load the user profile. Returns {} if not found.

    This is the non-interactive version used by i18n.
    Use autish.commands.uzanto._load_profile for interactive use with full error handling.

    Args:
        quiet: If True, suppresses errors and returns {} on failure.
               If False, raises exceptions on errors.

    Returns:
        Profile dict or {} if not found/loadable.
    """
    from autish.commands._crypto import decrypt, is_encrypted  # noqa: PLC0415

    # Try encrypted file first
    if _PROFILE_ENC_FILE.exists():
        master = _get_master_password()
        if not master:
            if quiet:
                return {}
            raise ValueError("Profile is encrypted but no master password is set.")
        raw = _PROFILE_ENC_FILE.read_bytes()
        if is_encrypted(raw):
            try:
                raw = decrypt(raw, master)
            except ValueError as exc:
                if quiet:
                    return {}
                raise ValueError(f"Could not decrypt profile: {exc}") from exc
        try:
            return _toml_loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            if quiet:
                return {}
            raise ValueError(f"Profile is invalid: {exc}") from exc

    # Plain file
    if _PROFILE_FILE.exists():
        try:
            return _toml_loads(_PROFILE_FILE.read_text(encoding="utf-8"))
        except ValueError as exc:
            if quiet:
                return {}
            raise ValueError(f"Profile is invalid: {exc}") from exc

    return {}