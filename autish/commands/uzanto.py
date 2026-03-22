"""uzanto — user profile management for autish.

Usage:
    uzanto profilo vidi           — view all or specific profile fields
    uzanto profilo modifi         — modify profile fields
    uzanto profilo eksporti       — export encrypted profile
    uzanto profilo importi <file> — import profile
    uzanto pasvorto               — set (or clear) user master password
"""

from __future__ import annotations

import re
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

# ──────────────────────────────────────────────────────────────────────────────
# Typer apps
# ──────────────────────────────────────────────────────────────────────────────

app = typer.Typer(
    name="uzanto",
    help="Uzanto — user profile and master-password management.",
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help", "--helpo"]},
)

profilo_app = typer.Typer(
    name="profilo",
    help="Manage user profile (profilo).",
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help", "--helpo"]},
)
app.add_typer(profilo_app, name="profilo")

console = Console()

# ──────────────────────────────────────────────────────────────────────────────
# Paths & constants
# ──────────────────────────────────────────────────────────────────────────────

_DATA_DIR: Path = Path.home() / ".local" / "share" / "autish"
_PROFILE_FILE: Path = _DATA_DIR / "uzanto_profilo.toml"
_PROFILE_ENC_FILE: Path = _DATA_DIR / "uzanto_profilo.enc"

_KEYRING_SERVICE: str = "autish-uzanto"
_KEYRING_KEY: str = "master"

# Standard profile field names (TOML keys)
_STANDARD_FIELDS: tuple[str, ...] = (
    "nomo",
    "familia_nomo",
    "naskig_dato",
    "lingvoj",
    "organizo",
)

# ──────────────────────────────────────────────────────────────────────────────
# TOML helpers
# ──────────────────────────────────────────────────────────────────────────────


def _toml_loads(text: str) -> dict:
    try:
        import tomllib  # type: ignore[import-untyped]  # noqa: PLC0415
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef,import-untyped]  # noqa: PLC0415
    return tomllib.loads(text)


def _toml_dumps(data: dict) -> str:
    import tomli_w  # noqa: PLC0415

    return tomli_w.dumps(data)


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


def _set_master_password(password: str) -> None:
    import keyring  # noqa: PLC0415

    keyring.set_password(_KEYRING_SERVICE, _KEYRING_KEY, password)


def _delete_master_password() -> None:
    try:
        import keyring  # noqa: PLC0415

        keyring.delete_password(_KEYRING_SERVICE, _KEYRING_KEY)
    except Exception:
        pass


# ──────────────────────────────────────────────────────────────────────────────
# Profile storage helpers
# ──────────────────────────────────────────────────────────────────────────────


def _load_profile() -> dict:
    """Load the user profile.  Returns {} if not found."""
    from autish.commands._crypto import decrypt, is_encrypted  # noqa: PLC0415

    # Try encrypted file first
    if _PROFILE_ENC_FILE.exists():
        master = _get_master_password()
        if not master:
            typer.echo(
                "[!] Profilo estas cifrita, sed neniu majstra pasvorto estas agordita.",
                err=True,
            )
            raise typer.Exit(1)
        raw = _PROFILE_ENC_FILE.read_bytes()
        if is_encrypted(raw):
            try:
                raw = decrypt(raw, master)
            except ValueError as exc:
                typer.echo(f"[!] Ne povis malcifri profilon: {exc}", err=True)
                raise typer.Exit(1) from exc
        return _toml_loads(raw.decode("utf-8"))

    # Plain file
    if _PROFILE_FILE.exists():
        return _toml_loads(_PROFILE_FILE.read_text(encoding="utf-8"))

    return {}


def _save_profile(data: dict) -> None:
    """Persist the user profile (encrypted if master password set)."""
    from autish.commands._crypto import encrypt  # noqa: PLC0415

    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    toml_text = _toml_dumps(data)
    master = _get_master_password()

    if master:
        # Encrypt and remove plain file
        blob = encrypt(toml_text.encode("utf-8"), master)
        _PROFILE_ENC_FILE.write_bytes(blob)
        if _PROFILE_FILE.exists():
            _PROFILE_FILE.unlink()
    else:
        # Plain file — remove encrypted file if exists
        _PROFILE_FILE.write_text(toml_text, encoding="utf-8")
        if _PROFILE_ENC_FILE.exists():
            _PROFILE_ENC_FILE.unlink()


def _re_encrypt_profile(old_password: str | None, new_password: str | None) -> None:
    """Re-encrypt (or decrypt) the profile when the master password changes."""
    from autish.commands._crypto import decrypt, encrypt, is_encrypted  # noqa: PLC0415

    _DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Load existing profile bytes
    if _PROFILE_ENC_FILE.exists() and old_password:
        raw = _PROFILE_ENC_FILE.read_bytes()
        if is_encrypted(raw):
            raw = decrypt(raw, old_password)
        toml_text = raw.decode("utf-8")
    elif _PROFILE_FILE.exists():
        toml_text = _PROFILE_FILE.read_text(encoding="utf-8")
    else:
        return  # Nothing to re-encrypt

    if new_password:
        blob = encrypt(toml_text.encode("utf-8"), new_password)
        _PROFILE_ENC_FILE.write_bytes(blob)
        if _PROFILE_FILE.exists():
            _PROFILE_FILE.unlink()
    else:
        _PROFILE_FILE.write_text(toml_text, encoding="utf-8")
        if _PROFILE_ENC_FILE.exists():
            _PROFILE_ENC_FILE.unlink()


# ──────────────────────────────────────────────────────────────────────────────
# profilo subcommands
# ──────────────────────────────────────────────────────────────────────────────


@profilo_app.command("vidi")
def profilo_vidi(
    nomo: bool = typer.Option(False, "-N", "--nomo", help="Show given name."),
    familia_nomo: bool = typer.Option(
        False, "-F", "--familia-nomo", help="Show family name."
    ),
    naskig_dato: bool = typer.Option(
        False, "-d", "--naskig-dato", help="Show date of birth."
    ),
    lingvoj: bool = typer.Option(False, "-L", "--lingvoj", help="Show languages."),
    organizo: bool = typer.Option(False, "-o", "--organizo", help="Show organisation."),
    kampo: str | None = typer.Option(
        None, "-k", "--kampo", help="Show a specific custom field by KEY."
    ),
) -> None:
    """View the user profile (or specific fields)."""
    profile = _load_profile()

    flags = {
        "nomo": nomo,
        "familia_nomo": familia_nomo,
        "naskig_dato": naskig_dato,
        "lingvoj": lingvoj,
        "organizo": organizo,
    }
    selected = [k for k, v in flags.items() if v]

    if kampo:
        custom = profile.get("kampoj", {})
        val = custom.get(kampo)
        if val is None:
            typer.echo(f"[!] Kampo ne trovita: {kampo}", err=True)
            raise typer.Exit(1)
        typer.echo(f"{kampo}: {val}")
        return

    if not selected:
        # Show everything
        if not profile:
            typer.echo("Neniu profilo trovita.")
            return
        table = Table(title="Uzanta Profilo")
        table.add_column("Kampo", style="cyan")
        table.add_column("Valoro")
        for key in _STANDARD_FIELDS:
            val = profile.get(key)
            if val is not None:
                display = ", ".join(val) if isinstance(val, list) else str(val)
                table.add_row(key.replace("_", "-"), display)
        custom = profile.get("kampoj", {})
        for k, v in custom.items():
            table.add_row(f"[kampoj] {k}", str(v))
        console.print(table)
        return

    # Show only selected fields
    for key in selected:
        val = profile.get(key)
        if isinstance(val, list):
            display = ", ".join(val)
        else:
            display = str(val) if val is not None else "—"
        typer.echo(f"{key.replace('_', '-')}: {display}")


@profilo_app.command("modifi")
def profilo_modifi(
    nomo: str | None = typer.Option(None, "-N", "--nomo", help="Set given name(s)."),
    familia_nomo: str | None = typer.Option(
        None, "-F", "--familia-nomo", help="Set family name."
    ),
    naskig_dato: str | None = typer.Option(
        None, "-d", "--naskig-dato", help="Set date of birth (YYYY-MM-DD)."
    ),
    lingvoj: str | None = typer.Option(
        None,
        "-L",
        "--lingvoj",
        help="Set languages (comma-separated 2-letter codes, e.g. 'en,fr').",
    ),
    organizo: str | None = typer.Option(
        None, "-o", "--organizo", help="Set organisation."
    ),
    kampo: list[str] | None = typer.Option(
        None,
        "-k",
        "--kampo",
        help="Set a custom field as KEY:VALUE (repeatable).",
    ),
) -> None:
    """Modify user profile fields."""
    profile = _load_profile()

    if nomo is not None:
        profile["nomo"] = nomo
    if familia_nomo is not None:
        profile["familia_nomo"] = familia_nomo
    if naskig_dato is not None:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", naskig_dato):
            typer.echo(
                "[!] naskig-dato devas esti en formato YYYY-MM-DD.", err=True
            )
            raise typer.Exit(1)
        profile["naskig_dato"] = naskig_dato
    if lingvoj is not None:
        codes = [c.strip() for c in lingvoj.split(",") if c.strip()]
        profile["lingvoj"] = codes
    if organizo is not None:
        profile["organizo"] = organizo

    if kampo:
        if "kampoj" not in profile:
            profile["kampoj"] = {}
        for entry in kampo:
            if ":" not in entry:
                typer.echo(
                    f"[!] Kampo-formato malgusta (atendita KEY:VALUE): {entry}",
                    err=True,
                )
                raise typer.Exit(1)
            key, _, value = entry.partition(":")
            profile["kampoj"][key.strip()] = value.strip()

    _save_profile(profile)
    typer.echo("[v] Profilo gisdatigita.")


@profilo_app.command("eksporti")
def profilo_eksporti(
    dosiero: str = typer.Argument(..., help="Output file path (e.g. profilo.enc)."),
    pasvorto: str | None = typer.Option(
        None,
        "-p",
        "--pasvorto",
        help="Encryption password (asked interactively if omitted).",
    ),
) -> None:
    """Export the user profile as an encrypted file."""
    from autish.commands._crypto import (  # noqa: PLC0415
        encrypt,
        validate_strong_password,
    )

    profile = _load_profile()
    if not profile:
        typer.echo("[!] Neniu profilo trovita.", err=True)
        raise typer.Exit(1)

    if not pasvorto:
        pasvorto = typer.prompt("Pasvorto", hide_input=True, confirmation_prompt=True)

    err = validate_strong_password(pasvorto)
    if err:
        typer.echo(f"[!] {err}", err=True)
        raise typer.Exit(1)

    toml_text = _toml_dumps(profile)
    blob = encrypt(toml_text.encode("utf-8"), pasvorto)
    out_path = Path(dosiero)
    out_path.write_bytes(blob)
    typer.echo(f"[v] Profilo eksportita al {out_path} (cifrita).")


@profilo_app.command("importi")
def profilo_importi(
    dosiero: str = typer.Argument(..., help="Input encrypted profile file."),
    pasvorto: str | None = typer.Option(
        None,
        "-p",
        "--pasvorto",
        help="Decryption password (asked interactively if omitted).",
    ),
    anstatauigi: bool = typer.Option(
        False,
        "-A",
        "--anstatauigi",
        help="Overwrite existing profile without prompting.",
    ),
) -> None:
    """Import a user profile from an encrypted file."""
    from autish.commands._crypto import decrypt, is_encrypted  # noqa: PLC0415

    in_path = Path(dosiero)
    if not in_path.exists():
        typer.echo(f"[!] Dosiero ne trovita: {in_path}", err=True)
        raise typer.Exit(1)

    raw = in_path.read_bytes()

    if is_encrypted(raw):
        if not pasvorto:
            pasvorto = typer.prompt("Pasvorto", hide_input=True)
        try:
            raw = decrypt(raw, pasvorto)
        except ValueError as exc:
            typer.echo(f"[!] Malcifrad-eraro: {exc}", err=True)
            raise typer.Exit(1) from exc

    try:
        imported = _toml_loads(raw.decode("utf-8"))
    except Exception as exc:
        typer.echo(f"[!] Malvalida dosierformato: {exc}", err=True)
        raise typer.Exit(1) from exc

    existing = _load_profile()
    if existing and not anstatauigi:
        typed = typer.prompt(
            "Ekzistanta profilo trovita. Tajpu 'anstatauigi' por konfirmi anstatauxigon"
        ).strip()
        if typed not in ("anstatauigi", "anstata\u016digi"):
            typer.echo("Nuligita.")
            return

    _save_profile(imported)
    typer.echo("[v] Profilo importita.")


# ──────────────────────────────────────────────────────────────────────────────
# pasvorto subcommand
# ──────────────────────────────────────────────────────────────────────────────


@app.command("pasvorto")
def pasvorto_cmd(
    forigi: bool = typer.Option(
        False, "-f", "--forigi", help="Remove the master password."
    ),
) -> None:
    """Set (or remove) the user master password.

    When set, the user profile is stored encrypted at rest.
    This password is required before accessing sensitive profile data.
    Email account passwords remain protected by the system keyring.
    Since sekurkopio backups are already encrypted, sensitive data included
    in those backups is not additionally encrypted.
    """
    from autish.commands._crypto import validate_strong_password  # noqa: PLC0415

    old_master = _get_master_password()

    if forigi:
        if not old_master:
            typer.echo("[!] Neniu majstra pasvorto estas agordita.", err=True)
            raise typer.Exit(1)
        confirm = typer.prompt(
            "Tajpu 'konfirmi' por forigi la majstran pasvorton"
        ).strip()
        if confirm != "konfirmi":
            typer.echo("Nuligita.")
            return
        _re_encrypt_profile(old_master, None)
        _delete_master_password()
        typer.echo("[v] Majstra pasvorto forigita. Profilo estas nun necifrita.")
        return

    if old_master:
        # Verify existing password before changing
        entered_old = typer.prompt("Nuna majstra pasvorto", hide_input=True)
        if entered_old != old_master:
            typer.echo("[!] Malgusta pasvorto.", err=True)
            raise typer.Exit(1)

    new_pw = typer.prompt(
        "Nova majstra pasvorto", hide_input=True, confirmation_prompt=True
    )
    err = validate_strong_password(new_pw)
    if err:
        typer.echo(f"[!] {err}", err=True)
        raise typer.Exit(1)

    _re_encrypt_profile(old_master, new_pw)
    _set_master_password(new_pw)
    typer.echo("[v] Majstra pasvorto agordita. Profilo estas nun cifrita.")
