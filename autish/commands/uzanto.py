"""uzanto — user profile management for autish.

Usage:
    uzanto profilo vidi           — view all or specific profile fields
    uzanto profilo modifi         — modify profile fields
    uzanto profilo eksporti       — export encrypted profile
    uzanto profilo importi <file> — import profile
    uzanto pasvorto               — set (or clear) user master password
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import quote

import typer
from rich.console import Console
from rich.table import Table

# ──────────────────────────────────────────────────────────────────────────────
# Typer apps
# ──────────────────────────────────────────────────────────────────────────────

app = typer.Typer(
    name="uzanto",
    help="Uzanto — administri uzantprofilon kaj ĉefpasvorton.",
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help", "--helpo"]},
)

profilo_app = typer.Typer(
    name="profilo",
    help="Administri uzantprofilon (profilo).",
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
    "naskig_loko",
    "lingvoj",
    "organizo",
    "organiza_identiga_numero",
    "telefonnumeroj",
    "retposhtadresoj",
)


def _ui_lang() -> str:
    raw = os.environ.get("LC_ALL") or os.environ.get("LANG") or ""
    lang = raw.split(".")[0].split("_")[0].lower()
    return lang or "eo"


def _url_action_labels() -> tuple[str, str]:
    labels = {
        "eo": ("Viziti", "Kopii"),
        "en": ("Visit", "Copy"),
        "fr": ("Visiter", "Copier"),
    }
    return labels.get(_ui_lang(), labels["eo"])


def _build_copy_url_action_link(url: str) -> str:
    safe_url = json.dumps(url, ensure_ascii=False)
    doc = (
        "<!doctype html><html><meta charset='utf-8'>"
        "<body style='font-family:sans-serif;padding:1rem'>"
        "<script>"
        f"const _u={safe_url};"
        "navigator.clipboard.writeText(_u)"
        ".then(()=>{document.body.textContent='URL kopiita al tondujo.';})"
        ".catch(()=>{document.body.textContent='Ne povis kopii URL.';});"
        "</script></body></html>"
    )
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".html", delete=False, encoding="utf-8"
    ) as fh:
        fh.write(doc)
        return f"file://{quote(fh.name)}"


def _render_url_actions(text: str) -> str:
    value = str(text or "").strip()
    if not re.match(r"^https?://", value, re.IGNORECASE):
        return value
    visit_label, copy_label = _url_action_labels()
    copy_link = _build_copy_url_action_link(value)
    return (
        f"[link={value}]{visit_label}[/link]"
        f" / [link={copy_link}]{copy_label}[/link]"
    )


def _display_profile_value(val: object) -> str:
    if isinstance(val, list):
        if val and isinstance(val[0], dict):
            chunks: list[str] = []
            for item in val:
                if isinstance(item, dict):
                    value = _render_url_actions(str(item.get("valoro") or ""))
                    tag = str(item.get("etikedo") or "")
                    primary = bool(item.get("prima"))
                    suffix = " (prima)" if primary else ""
                    chunks.append(f"{value} ({tag}){suffix}")
                else:
                    chunks.append(_render_url_actions(str(item)))
            return "; ".join(chunks)
        return ", ".join(_render_url_actions(str(x)) for x in val)
    if isinstance(val, dict):
        return _toml_dumps(val).strip()
    return _render_url_actions(str(val))


def _normalize_multi_contact_item(raw: str, *, kind: str) -> dict:
    # Format: value:etikedo[:prima]
    parts = [p.strip() for p in raw.split(":")]
    if len(parts) < 2:
        raise ValueError("Atendita formato: valoro:etikedo[:prima]")
    value = parts[0]
    etikedo = parts[1]
    prima = len(parts) >= 3 and parts[2].lower() in ("prima", "primary", "1", "jes")
    if kind == "telefono":
        if not re.match(r"^00\d{2,5}\d+$", value):
            raise ValueError(
                "Telefonnumero devas komenci per regiona kodo, ekz. 0033..."
            )
    elif kind == "retposhto":
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", value):
            raise ValueError("Nevalida retpoŝta adreso.")
    return {"valoro": value, "etikedo": etikedo, "prima": bool(prima)}


def _normalize_multi_contact_list(items: list[str], *, kind: str) -> list[dict]:
    out = [_normalize_multi_contact_item(item, kind=kind) for item in items]
    primary_idx = [i for i, item in enumerate(out) if item.get("prima")]
    if len(primary_idx) > 1:
        raise ValueError("Nur unu eniro povas esti prima.")
    if out and not primary_idx:
        out[0]["prima"] = True
    return out

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


def _load_profile(*, quiet: bool = False) -> dict:
    """Load the user profile. Returns {} if not found.

    quiet=True suppresses user-facing errors and falls back to {} when the
    profile cannot be read (useful for non-interactive locale probing).
    """
    from autish.commands._crypto import decrypt, is_encrypted  # noqa: PLC0415

    # Try encrypted file first
    if _PROFILE_ENC_FILE.exists():
        master = _get_master_password()
        if not master:
            if quiet:
                return {}
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
                if quiet:
                    return {}
                typer.echo(f"[!] Ne povis malcifri profilon: {exc}", err=True)
                raise typer.Exit(1) from exc
        try:
            return _toml_loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            if quiet:
                return {}
            typer.echo(f"[!] Profilo estas nevalida: {exc}", err=True)
            raise typer.Exit(1) from exc

    # Plain file
    if _PROFILE_FILE.exists():
        try:
            return _toml_loads(_PROFILE_FILE.read_text(encoding="utf-8"))
        except ValueError as exc:
            if quiet:
                return {}
            typer.echo(f"[!] Profilo estas nevalida: {exc}", err=True)
            raise typer.Exit(1) from exc

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
    naskig_loko: bool = typer.Option(
        False, "--naskig-loko", help="Show place of birth."
    ),
    lingvoj: bool = typer.Option(False, "-L", "--lingvoj", help="Show languages."),
    organizo: bool = typer.Option(False, "-o", "--organizo", help="Show organisation."),
    organiza_identiga_numero: bool = typer.Option(
        False, "--organiza-identiga-numero", help="Show organisation identifier."
    ),
    telefonnumeroj: bool = typer.Option(
        False, "--telefonnumeroj", help="Show stored phone numbers."
    ),
    retposhtadresoj: bool = typer.Option(
        False, "--retposhtadresoj", help="Show stored email addresses."
    ),
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
        "naskig_loko": naskig_loko,
        "lingvoj": lingvoj,
        "organizo": organizo,
        "organiza_identiga_numero": organiza_identiga_numero,
        "telefonnumeroj": telefonnumeroj,
        "retposhtadresoj": retposhtadresoj,
    }
    selected = [k for k, v in flags.items() if v]

    if kampo:
        custom = profile.get("kampoj", {})
        val = custom.get(kampo)
        if val is None:
            typer.echo(f"[!] Kampo ne trovita: {kampo}", err=True)
            raise typer.Exit(1)
        console.print(f"{kampo}: {_display_profile_value(val)}")
        return

    if not selected:
        # Show everything
        if not profile:
            typer.echo("Neniu profilo trovita.")
            return
        table = Table(title="Uzanta Profilo")
        table.add_column("Kampo", style="cyan", overflow="fold")
        table.add_column("Valoro", overflow="fold")
        for key in _STANDARD_FIELDS:
            val = profile.get(key)
            if val is not None:
                display = _display_profile_value(val)
                table.add_row(key.replace("_", "-"), display)
        custom = profile.get("kampoj", {})
        for k, v in custom.items():
            table.add_row(f"[kampoj] {k}", str(v))
        console.print(table)
        return

    # Show only selected fields
    for key in selected:
        val = profile.get(key)
        display = _display_profile_value(val) if val is not None else "—"
        console.print(f"{key.replace('_', '-')}: {display}")


@profilo_app.command("modifi")
def profilo_modifi(
    nomo: str | None = typer.Option(None, "-N", "--nomo", help="Set given name(s)."),
    familia_nomo: str | None = typer.Option(
        None, "-F", "--familia-nomo", help="Set family name."
    ),
    naskig_dato: str | None = typer.Option(
        None, "-d", "--naskig-dato", help="Set date of birth (YYYY-MM-DD)."
    ),
    naskig_loko: str | None = typer.Option(
        None, "--naskig-loko", help="Set place of birth."
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
    organiza_identiga_numero: str | None = typer.Option(
        None, "--organiza-identiga-numero", help="Set organisation identifier."
    ),
    telefonnumero: list[str] | None = typer.Option(
        None,
        "--telefonnumero",
        help="Repeat as numero:etikedo[:prima], e.g. 0033123456789:hejmo:prima",
    ),
    retposhtadreso: list[str] | None = typer.Option(
        None,
        "--retposhtadreso",
        help="Repeat as adreso:etikedo[:prima], e.g. user@example.com:labora:prima",
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
    if naskig_loko is not None:
        profile["naskig_loko"] = naskig_loko
    if organizo is not None:
        profile["organizo"] = organizo
    if organiza_identiga_numero is not None:
        profile["organiza_identiga_numero"] = organiza_identiga_numero
    if telefonnumero is not None:
        try:
            profile["telefonnumeroj"] = _normalize_multi_contact_list(
                telefonnumero, kind="telefono"
            )
        except ValueError as exc:
            typer.echo(f"[!] {exc}", err=True)
            raise typer.Exit(1) from exc
    if retposhtadreso is not None:
        try:
            profile["retposhtadresoj"] = _normalize_multi_contact_list(
                retposhtadreso, kind="retposhto"
            )
        except ValueError as exc:
            typer.echo(f"[!] {exc}", err=True)
            raise typer.Exit(1) from exc

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
