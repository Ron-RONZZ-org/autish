"""sekurkopio — backup and restore all autish user data.

Usage:
    sekurkopio eksporti <dosiero>   — export all autish data (encrypted .7z or .zip)
    sekurkopio importi <dosiero>    — restore from export
    sekurkopio auto [dosierujo]     — manage automatic scheduled backups
    sekurkopio historio             — show change history (last 5 entries)
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="sekurkopio",
    help="Sekurkopio — backup & restore all autish user data.",
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help", "--helpo"]},
)

console = Console()

# ──────────────────────────────────────────────────────────────────────────────
# Paths & constants
# ──────────────────────────────────────────────────────────────────────────────

_DATA_DIR: Path = Path.home() / ".local" / "share" / "autish"
_SEKURKOPIO_DB: Path = _DATA_DIR / "sekurkopio.db"

_HISTORY_MAX = 5       # number of history entries to keep
_AUTO_INTERVAL_DEFAULT = 60   # minutes
_AUTO_NOMBRO_DEFAULT = 5      # maximum auto-backup copies


# ──────────────────────────────────────────────────────────────────────────────
# DB helpers (history & auto-backup strategy)
# ──────────────────────────────────────────────────────────────────────────────

_CREATE_HISTORY = """
CREATE TABLE IF NOT EXISTS historio (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    okazis_je  TEXT NOT NULL,
    ago        TEXT NOT NULL,
    detaloj    TEXT NOT NULL DEFAULT '{}'
);
"""

_CREATE_AUTO_STRATEGY = """
CREATE TABLE IF NOT EXISTS auto_strategio (
    id         INTEGER PRIMARY KEY CHECK (id = 1),
    dosierujo  TEXT NOT NULL,
    intervalo  INTEGER NOT NULL DEFAULT 60,
    nombro     INTEGER NOT NULL DEFAULT 5,
    aktiva     INTEGER NOT NULL DEFAULT 1
);
"""


def _get_db() -> sqlite3.Connection:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(_SEKURKOPIO_DB), timeout=5.0)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL;")
    con.executescript(_CREATE_HISTORY + _CREATE_AUTO_STRATEGY)
    return con


def _push_history(ago: str, detaloj: dict | None = None) -> None:
    """Record a history entry, keeping at most _HISTORY_MAX rows."""
    now = datetime.now(timezone.utc).isoformat()
    with _get_db() as con:
        con.execute(
            "INSERT INTO historio (okazis_je, ago, detaloj) VALUES (?, ?, ?)",
            (now, ago, json.dumps(detaloj or {})),
        )
        # Prune to keep only latest _HISTORY_MAX rows
        con.execute(
            "DELETE FROM historio WHERE id NOT IN "
            f"(SELECT id FROM historio ORDER BY id DESC LIMIT {_HISTORY_MAX})"
        )
        con.commit()


def _load_history() -> list[dict]:
    with _get_db() as con:
        rows = con.execute(
            "SELECT * FROM historio ORDER BY id DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def _load_auto_strategy() -> dict | None:
    with _get_db() as con:
        row = con.execute("SELECT * FROM auto_strategio WHERE id = 1").fetchone()
    return dict(row) if row else None


def _save_auto_strategy(dosierujo: str, intervalo: int, nombro: int) -> None:
    with _get_db() as con:
        con.execute(
            """INSERT INTO auto_strategio (id, dosierujo, intervalo, nombro, aktiva)
               VALUES (1, ?, ?, ?, 1)
               ON CONFLICT(id) DO UPDATE
               SET dosierujo=excluded.dosierujo,
                   intervalo=excluded.intervalo,
                   nombro=excluded.nombro,
                   aktiva=1""",
            (dosierujo, intervalo, nombro),
        )
        con.commit()


# ──────────────────────────────────────────────────────────────────────────────
# Archive helpers
# ──────────────────────────────────────────────────────────────────────────────


def _collect_autish_data_files() -> list[Path]:
    """Return a list of autish data files that should be backed up."""
    candidates = [
        _DATA_DIR / "vorto.db",
        _DATA_DIR / "retposto.db",
        _DATA_DIR / "shelo_history",
        _DATA_DIR / "sekurkopio.db",
    ]
    return [p for p in candidates if p.exists()]


def _export_to_archive(
    archive_path: Path,
    password: str,
    formato: str = "7z",
) -> int:
    """Create an encrypted archive of all autish data. Returns file count."""
    files = _collect_autish_data_files()
    if not files:
        return 0

    if formato == "zip":
        # Build an in-memory zip then encrypt the whole thing
        import io  # noqa: PLC0415
        import zipfile  # noqa: PLC0415

        from autish.commands._crypto import encrypt  # noqa: PLC0415

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for fp in files:
                zf.write(fp, fp.name)
        encrypted = encrypt(buf.getvalue(), password)
        archive_path.write_bytes(encrypted)
    else:
        # 7z (default)
        import py7zr  # noqa: PLC0415

        with py7zr.SevenZipFile(
            str(archive_path), "w", password=password
        ) as szf:
            for fp in files:
                szf.write(fp, fp.name)

    return len(files)


def _import_from_archive(
    archive_path: Path,
    password: str,
    formato: str,
    overwrite: bool = False,
) -> int:
    """Restore data files from an encrypted archive. Returns file count."""
    if formato == "zip":
        import io  # noqa: PLC0415
        import zipfile  # noqa: PLC0415

        from autish.commands._crypto import decrypt, is_encrypted  # noqa: PLC0415

        raw = archive_path.read_bytes()
        if is_encrypted(raw):
            raw = decrypt(raw, password)
        buf = io.BytesIO(raw)
        with zipfile.ZipFile(buf, "r") as zf:
            count = 0
            for member in zf.namelist():
                dest = _DATA_DIR / member
                if dest.exists() and not overwrite:
                    continue
                _DATA_DIR.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(zf.read(member))
                count += 1
        return count
    else:
        # 7z — extract to a temp dir, then copy only the files we want
        import py7zr  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path_obj = Path(tmp_dir)
            with py7zr.SevenZipFile(
                str(archive_path), "r", password=password
            ) as szf:
                szf.extractall(path=tmp_dir)
            count = 0
            for extracted in tmp_path_obj.rglob("*"):
                if extracted.is_dir():
                    continue
                dest = _DATA_DIR / extracted.name
                if dest.exists() and not overwrite:
                    continue
                _DATA_DIR.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(extracted.read_bytes())
                count += 1
        return count


def _detect_formato(path: Path) -> str:
    """Detect archive format from file extension."""
    suffix = path.suffix.lower()
    if suffix == ".zip":
        return "zip"
    return "7z"


def _auto_backup_filename(dosierujo: Path, idx: int) -> Path:
    """Return the i-th rotation filename."""
    return dosierujo / f"autish_backup_{idx:04d}.aut"


def _rotate_auto_backups(dosierujo: Path, nombro: int) -> None:
    """Keep at most *nombro* backup files by removing the oldest."""
    # Sort by modification time so the truly oldest file is always removed first.
    files = sorted(
        dosierujo.glob("autish_backup_*.aut"),
        key=lambda p: p.stat().st_mtime,
    )
    while len(files) >= nombro:
        files[0].unlink(missing_ok=True)
        files = files[1:]


def _do_auto_backup(dosierujo: Path, password: str, nombro: int) -> Path:
    """Create one auto-backup file. Returns the path created."""
    dosierujo.mkdir(parents=True, exist_ok=True)
    _rotate_auto_backups(dosierujo, nombro)
    now_str = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    out = dosierujo / f"autish_backup_{now_str}.aut"
    _export_to_archive(out, password, formato="7z")
    return out


def _confirm_esperante(prompt: str, *, default_yes: bool) -> bool:
    """J/n or j/N confirmation prompt."""
    hint = "J/n" if default_yes else "j/N"
    answer = typer.prompt(f"{prompt} [{hint}]", default="").strip().lower()
    if not answer:
        return default_yes
    return answer in ("j", "ja", "jes", "y", "yes")


def _validate_strong_password(password: str) -> str | None:
    from autish.commands._crypto import validate_strong_password  # noqa: PLC0415

    return validate_strong_password(password)


# ──────────────────────────────────────────────────────────────────────────────
# CLI subcommands
# ──────────────────────────────────────────────────────────────────────────────


@app.command("eksporti")
def eksporti(
    dosiero: str = typer.Argument(..., help="Output file path (.7z by default)."),
    pasvorto: str | None = typer.Option(
        None,
        "-p",
        "--pasvorto",
        help="Encryption password (asked interactively if omitted).",
    ),
    formato: str = typer.Option(
        "7z",
        "-f",
        "--formato",
        help="Archive format: '7z' (default) or 'zip'.",
    ),
) -> None:
    """Export all autish user data as an encrypted archive."""
    from autish.commands._crypto import validate_strong_password  # noqa: PLC0415

    if formato not in ("7z", "zip"):
        typer.echo("[!] Formato devas esti '7z' aŭ 'zip'.", err=True)
        raise typer.Exit(1)

    if not pasvorto:
        pasvorto = typer.prompt("Pasvorto", hide_input=True, confirmation_prompt=True)

    err = validate_strong_password(pasvorto)
    if err:
        typer.echo(f"[!] {err}", err=True)
        raise typer.Exit(1)

    out_path = Path(dosiero)
    count = _export_to_archive(out_path, pasvorto, formato=formato)
    if count == 0:
        typer.echo("[!] Neniuj datumoj por eksporti.", err=True)
        raise typer.Exit(1)

    _push_history("eksporti", {"dosiero": str(out_path), "formato": formato})
    typer.echo(
        f"[✓] Eksportis {count} dosiero(j)n al {out_path} "
        f"(formato={formato}, ĉifrita)."
    )


@app.command("importi")
def importi(
    dosiero: str = typer.Argument(..., help="Input archive path."),
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
        help="Overwrite existing files. Asks for typed confirmation.",
    ),
) -> None:
    """Restore autish user data from an encrypted archive."""
    in_path = Path(dosiero)
    if not in_path.exists():
        typer.echo(f"[!] Dosiero ne trovita: {in_path}", err=True)
        raise typer.Exit(1)

    formato = _detect_formato(in_path)

    if not pasvorto:
        pasvorto = typer.prompt("Pasvorto", hide_input=True)

    if anstatauigi:
        typed = typer.prompt(
            "Por konfirmi anstataŭigon, tajpu: anstatauigi"
        ).strip()
        # Accept with or without special accent character
        if typed not in ("anstatauigi", "anstataŭigi"):
            typer.echo("[!] Konfirmo malsukcesis. Operacio nuligita.", err=True)
            raise typer.Exit(1)

    try:
        count = _import_from_archive(in_path, pasvorto, formato, overwrite=anstatauigi)
    except Exception as exc:
        typer.echo(f"[!] Importado malsukcesis: {exc}", err=True)
        raise typer.Exit(1) from exc

    _push_history(
        "importi",
        {"dosiero": str(in_path), "anstatauigi": anstatauigi},
    )
    typer.echo(f"[✓] Importis {count} dosiero(j)n el {in_path}.")


@app.command("auto")
def auto(
    dosierujo: str | None = typer.Argument(
        None, help="Directory to store backup files."
    ),
    intervalo: int | None = typer.Option(
        None,
        "-i",
        "--intervalo",
        help=f"Backup interval in minutes (default {_AUTO_INTERVAL_DEFAULT}).",
    ),
    nombro: int | None = typer.Option(
        None,
        "-n",
        "--nombro",
        help=(
            f"Maximum number of backup copies to keep "
            f"(default {_AUTO_NOMBRO_DEFAULT})."
        ),
    ),
) -> None:
    """Manage automatic periodic backups.

    With no arguments, shows the current backup strategy.
    Pass --intervalo or --nombro to modify it.
    Pass a directory to create or update the strategy.
    """
    strategy = _load_auto_strategy()

    if dosierujo is None and intervalo is None and nombro is None:
        # Show current strategy
        if not strategy:
            create = _confirm_esperante(
                "Neniu aŭtomata sekurkopio konfigurita. Ĉu krei unu?",
                default_yes=True,
            )
            if not create:
                return
            dosierujo = typer.prompt(
                "Dosierujo por sekurkopioj",
                default=str(_DATA_DIR / "sekurkopioj"),
            )
            intervalo = typer.prompt(
                f"Intervalo (minutoj, defaŭlte {_AUTO_INTERVAL_DEFAULT})",
                default=_AUTO_INTERVAL_DEFAULT,
            )
            nombro = typer.prompt(
                f"Maksimuma nombro da kopioj (defaŭlte {_AUTO_NOMBRO_DEFAULT})",
                default=_AUTO_NOMBRO_DEFAULT,
            )
        else:
            table = Table(title="Aŭtomata sekurkopio-strategio")
            table.add_column("Kampo", style="cyan")
            table.add_column("Valoro")
            table.add_row("Dosierujo", strategy["dosierujo"])
            table.add_row("Intervalo", f"{strategy['intervalo']} min")
            table.add_row("Maks. kopioj", str(strategy["nombro"]))
            table.add_row("Aktiva", "jes" if strategy["aktiva"] else "ne")
            console.print(table)
            return

    # Modification / creation path
    if strategy:
        new_dir = dosierujo or strategy["dosierujo"]
        new_intervalo = intervalo if intervalo is not None else strategy["intervalo"]
        new_nombro = nombro if nombro is not None else strategy["nombro"]

        # Show summary and ask for confirmation
        typer.echo(
            f"\nNova strategio:\n"
            f"  Dosierujo : {new_dir}\n"
            f"  Intervalo : {new_intervalo} min\n"
            f"  Maks. kopioj: {new_nombro}\n"
        )
        if not _confirm_esperante("Ĉu konfirmi ĉi tiun strategion?", default_yes=True):
            typer.echo("Nuligita.")
            return
    else:
        new_dir = dosierujo or str(_DATA_DIR / "sekurkopioj")
        new_intervalo = intervalo if intervalo is not None else _AUTO_INTERVAL_DEFAULT
        new_nombro = nombro if nombro is not None else _AUTO_NOMBRO_DEFAULT

    _save_auto_strategy(new_dir, new_intervalo, new_nombro)
    Path(new_dir).mkdir(parents=True, exist_ok=True)
    typer.echo(
        f"[✓] Aŭtomata sekurkopio agordita:\n"
        f"  Dosierujo : {new_dir}\n"
        f"  Intervalo : {new_intervalo} min\n"
        f"  Maks. kopioj: {new_nombro}"
    )

    # Offer to trigger one backup now
    if _confirm_esperante("Cu fari sekurkopion nun?", default_yes=True):
        pasvorto = typer.prompt("Pasvorto", hide_input=True, confirmation_prompt=True)
        from autish.commands._crypto import validate_strong_password  # noqa: PLC0415

        err = validate_strong_password(pasvorto)
        if err:
            typer.echo(f"[!] {err}", err=True)
            raise typer.Exit(1)
        out = _do_auto_backup(Path(new_dir), pasvorto, new_nombro)
        _push_history("auto", {"dosiero": str(out)})
        typer.echo(f"[v] Sekurkopio kreita: {out}")

        # Prompt user to save the recovery key for restoration in case of
        # crash > complete reinstall of autish
        typer.echo(
            "\n[!] Grava: Konservu vian cif-pasvorton en sekura loko"
            " (ekz. pasvorta administranto)."
        )
        typer.echo(
            "    Vi bezonos gin por restarigi viajn datumojn post kompleta reinstalo."
        )
        if _confirm_esperante(
            "Cu konservi pasvortan gvidon en dosiero?", default_yes=False
        ):
            default_hint = str(Path.home() / "autish_recovery_hint.txt")
            hint_file = typer.prompt(
                "Dosiero por konservi gvidon", default=default_hint
            ).strip()
            hint_path = Path(hint_file)
            if hint_path.is_dir():
                hint_path = hint_path / "autish_recovery_hint.txt"
            hint_path.write_text(
                "autish sekurkopio — ciferlanda restarigado\n"
                f"Sekurkopio-dosierujo : {new_dir}\n"
                f"Skribita             : {datetime.now(timezone.utc).isoformat()}\n\n"
                "Instrukcioj:\n"
                "  1. Instaladu autish denove.\n"
                "  2. Rulu: autish sekurkopio reveni\n"
                "  3. Enigu la cifran pasvorton kiun vi uzis por krei"
                " la sekurkopion.\n\n"
                "AVERTO: Cifi la cifran pasvorton en tiu cifi dosiero"
                " nur se vi stokos\n"
                "        gin en sekura loko (ekz. en cif-sako, cif-ujo, ktp.).\n",
                encoding="utf-8",
            )
            typer.echo(f"[v] Gvido konservita al: {hint_path}")
    
    # Show instructions for setting up automatic backups
    typer.echo("\n" + "=" * 60)
    typer.echo("AVERTO: Aŭtomata sekurkopio estas agordita sed ne aktiva!")
    typer.echo("=" * 60)
    typer.echo(
        "\nPor ke sekurkopioj okazu aŭtomate, vi devas agordi unu el:\n"
        "  1. systemd timer (Debian/Ubuntu):\n"
        "     sekurkopio install-systemd\n"
        "  2. cron job (ĉiuj sistemoj):\n"
        "     sekurkopio install-cron\n"
        "  3. Manlibra daemono (rulu en aparta terminalo):\n"
        "     sekurkopio daemon\n"
    )


@app.command("daemon")
def daemon_cmd(
    password_file: str | None = typer.Option(
        None,
        "-p",
        "--password-file",
        help="Path to file containing encryption password (one line).",
    ),
    once: bool = typer.Option(
        False,
        "--once",
        help="Run one backup and exit (for systemd/cron).",
    ),
) -> None:
    """Run automatic backup daemon.
    
    Without --once: runs continuously in foreground, performing backups
    at the configured interval. Press Ctrl+C to stop.
    
    With --once: performs one backup immediately and exits (for systemd/cron).
    
    The password must be provided via --password-file for unattended operation.
    """
    import signal
    import time
    
    strategy = _load_auto_strategy()
    if not strategy or not strategy.get("aktiva"):
        typer.echo(
            "Eraro: Neniu aktiva aŭtomata strategio.\n"
            "Rulu: sekurkopio auto [dosierujo]",
            err=True,
        )
        raise typer.Exit(1)
    
    if not password_file:
        typer.echo(
            "Eraro: --password-file estas deviga por daemono.\n"
            "Kreu dosieron kun la cifran pasvorton (unu linio) kaj pasu ĝin.",
            err=True,
        )
        raise typer.Exit(1)
    
    # Read password from file
    try:
        password = Path(password_file).expanduser().read_text(encoding="utf-8").strip()
    except FileNotFoundError as e:
        typer.echo(f"Eraro: Pasvorta dosiero ne trovita: {password_file}", err=True)
        raise typer.Exit(1) from e
    
    if not password:
        typer.echo("Eraro: Pasvorta dosiero estas malplena.", err=True)
        raise typer.Exit(1)
    
    dosierujo = Path(strategy["dosierujo"])
    intervalo_min = strategy["intervalo"]
    nombro = strategy["nombro"]
    
    if once:
        # Single backup for systemd/cron
        try:
            typer.echo(f"[*] {datetime.now(timezone.utc).isoformat()}")
            typer.echo("[*] Komencante aŭtomatan sekurkopion...")
            
            out = _do_auto_backup(dosierujo, password, nombro)
            _push_history("auto-daemon", {"dosiero": str(out)})
            
            typer.echo(f"[✓] Sekurkopio kreita: {out.name}")
        except Exception as e:
            typer.echo(f"[!] Eraro dum sekurkopio: {e}", err=True)
            raise typer.Exit(1) from e
        return
    
    # Continuous daemon mode
    typer.echo(
        f"[*] Sekurkopio daemono startita.\n"
        f"    Dosierujo : {dosierujo}\n"
        f"    Intervalo : {intervalo_min} min\n"
        f"    Maks. kopioj: {nombro}\n"
    )
    
    # Set up signal handlers for graceful shutdown
    shutdown_requested = False
    
    def signal_handler(signum, frame):
        nonlocal shutdown_requested
        shutdown_requested = True
        typer.echo("\n[!] Haltigo petita. Atendante...")
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Track last backup time
    last_backup_time = 0.0
    intervalo_sec = intervalo_min * 60
    
    typer.echo(f"[*] Unua sekurkopio post {intervalo_min} min...")
    
    while not shutdown_requested:
        now = time.time()
        
        # Check if it's time for a backup
        if now - last_backup_time >= intervalo_sec:
            try:
                typer.echo(f"\n[*] {datetime.now(timezone.utc).isoformat()}")
                typer.echo("[*] Komencante aŭtomatan sekurkopion...")
                
                out = _do_auto_backup(dosierujo, password, nombro)
                _push_history("auto-daemon", {"dosiero": str(out)})
                
                typer.echo(f"[✓] Sekurkopio kreita: {out.name}")
                last_backup_time = now
                
            except Exception as e:
                typer.echo(f"[!] Eraro dum sekurkopio: {e}", err=True)
                # Continue running even if one backup fails
        
        # Sleep in small increments to allow for responsive shutdown
        for _ in range(60):  # Check every second for 60 seconds
            if shutdown_requested:
                break
            time.sleep(1)
    
    typer.echo("[✓] Daemono haltigita.")


@app.command("install-systemd")
def install_systemd_cmd() -> None:
    """Generate and install systemd user service and timer for automatic backups.
    
    This creates:
    - ~/.config/systemd/user/autish-sekurkopio.service
    - ~/.config/systemd/user/autish-sekurkopio.timer
    
    And enables the timer to run automatically.
    """
    strategy = _load_auto_strategy()
    if not strategy or not strategy.get("aktiva"):
        typer.echo(
            "Eraro: Neniu aktiva aŭtomata strategio.\n"
            "Rulu: sekurkopio auto [dosierujo]",
            err=True,
        )
        raise typer.Exit(1)
    
    intervalo_min = strategy["intervalo"]
    
    # Prompt for password file location
    typer.echo(
        "\n[!] Vi bezonos dosieron enhavanta la cifran pasvorton.\n"
        "    Tio estas necesa por neatendata operacio.\n"
    )
    default_pw_file = str(Path.home() / ".config" / "autish" / "backup_password.txt")
    pw_file = typer.prompt(
        "Dosiero por pasvorto",
        default=default_pw_file,
    ).strip()
    
    pw_path = Path(pw_file).expanduser()
    
    if not pw_path.exists():
        if _confirm_esperante("Dosiero ne ekzistas. Ĉu krei ĝin?", default_yes=True):
            pw = typer.prompt("Pasvorto", hide_input=True, confirmation_prompt=True)
            pw_path.parent.mkdir(parents=True, exist_ok=True)
            pw_path.write_text(pw, encoding="utf-8")
            pw_path.chmod(0o600)  # Read/write for owner only
            typer.echo(f"[✓] Pasvorto konservita al: {pw_path}")
        else:
            typer.echo("Nuligita.")
            raise typer.Exit(0)
    
    # Create systemd unit files
    systemd_dir = Path.home() / ".config" / "systemd" / "user"
    systemd_dir.mkdir(parents=True, exist_ok=True)
    
    service_file = systemd_dir / "autish-sekurkopio.service"
    timer_file = systemd_dir / "autish-sekurkopio.timer"
    
    # Get the path to the sekurkopio command
    import shutil
    sekurkopio_bin = shutil.which("sekurkopio") or "sekurkopio"
    
    service_content = f"""[Unit]
Description=Autish automatic backup service
After=network.target

[Service]
Type=oneshot
ExecStart={sekurkopio_bin} daemon --password-file {pw_path} --once
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
"""
    
    timer_content = f"""[Unit]
Description=Autish automatic backup timer
Requires=autish-sekurkopio.service

[Timer]
OnBootSec=5min
OnUnitInactiveSec={intervalo_min}min
Persistent=true

[Install]
WantedBy=timers.target
"""
    
    service_file.write_text(service_content, encoding="utf-8")
    timer_file.write_text(timer_content, encoding="utf-8")
    
    typer.echo(f"[✓] Systemd dosieroj kreitaj:\n  {service_file}\n  {timer_file}")
    
    # Enable and start the timer
    import subprocess
    
    try:
        subprocess.run(
            ["systemctl", "--user", "daemon-reload"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["systemctl", "--user", "enable", "autish-sekurkopio.timer"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["systemctl", "--user", "start", "autish-sekurkopio.timer"],
            check=True,
            capture_output=True,
        )
        typer.echo("[✓] Systemd timer ebligita kaj startita.")
        typer.echo(
            "\nPor vidi staton:\n"
            "  systemctl --user status autish-sekurkopio.timer\n"
            "  journalctl --user -u autish-sekurkopio.service -f"
        )
    except subprocess.CalledProcessError as e:
        typer.echo(
            f"[!] Averto: Ne povis aŭtomate ebligi/starti la timer: {e}\n"
            "Manlibraj paŝoj:\n"
            "  systemctl --user daemon-reload\n"
            "  systemctl --user enable autish-sekurkopio.timer\n"
            "  systemctl --user start autish-sekurkopio.timer",
            err=True,
        )


@app.command("install-cron")
def install_cron_cmd() -> None:
    """Add a cron job for automatic backups.
    
    This adds a line to the user's crontab to run the backup daemon.
    """
    strategy = _load_auto_strategy()
    if not strategy or not strategy.get("aktiva"):
        typer.echo(
            "Eraro: Neniu aktiva aŭtomata strategio.\n"
            "Rulu: sekurkopio auto [dosierujo]",
            err=True,
        )
        raise typer.Exit(1)
    
    intervalo_min = strategy["intervalo"]
    
    # Prompt for password file location
    typer.echo(
        "\n[!] Vi bezonos dosieron enhavanta la cifran pasvorton.\n"
        "    Tio estas necesa por neatendata operacio.\n"
    )
    default_pw_file = str(Path.home() / ".config" / "autish" / "backup_password.txt")
    pw_file = typer.prompt(
        "Dosiero por pasvorto",
        default=default_pw_file,
    ).strip()
    
    pw_path = Path(pw_file).expanduser()
    
    if not pw_path.exists():
        if _confirm_esperante("Dosiero ne ekzistas. Ĉu krei ĝin?", default_yes=True):
            pw = typer.prompt("Pasvorto", hide_input=True, confirmation_prompt=True)
            pw_path.parent.mkdir(parents=True, exist_ok=True)
            pw_path.write_text(pw, encoding="utf-8")
            pw_path.chmod(0o600)  # Read/write for owner only
            typer.echo(f"[✓] Pasvorto konservita al: {pw_path}")
        else:
            typer.echo("Nuligita.")
            raise typer.Exit(0)
    
    # Get the path to sekurkopio
    import shutil
    sekurkopio_bin = shutil.which("sekurkopio") or "sekurkopio"
    
    # Generate cron schedule expression
    cron_expr = f"*/{intervalo_min} * * * *"  # Every N minutes
    cron_cmd = f"{sekurkopio_bin} daemon --password-file {pw_path} --once"
    cron_line = f"{cron_expr} {cron_cmd} >/dev/null 2>&1\n"
    
    typer.echo(f"\nAldononta cron linion:\n{cron_line}")
    
    if not _confirm_esperante("Ĉu aldoni ĉi tion al via crontab?", default_yes=True):
        typer.echo("Nuligita.")
        raise typer.Exit(0)
    
    import subprocess
    
    try:
        # Get current crontab
        result = subprocess.run(
            ["crontab", "-l"],
            capture_output=True,
            text=True,
            check=False,
        )
        current_crontab = result.stdout if result.returncode == 0 else ""
        
        # Check if entry already exists
        if "autish-sekurkopio" in current_crontab or sekurkopio_bin in current_crontab:
            typer.echo("[!] Sekurkopio jam estas en crontab. Nuligita.")
            return
        
        # Append new line
        new_crontab = current_crontab + f"# autish-sekurkopio\n{cron_line}"
        
        # Install new crontab
        subprocess.run(
            ["crontab", "-"],
            input=new_crontab,
            text=True,
            check=True,
        )
        
        typer.echo("[✓] Cron job aldonita.")
        typer.echo("\nPor vidi vian crontab:\n  crontab -l")
        
    except subprocess.CalledProcessError as e:
        typer.echo(f"[!] Eraro: {e}", err=True)
        typer.echo(
            f"\nManlibra paŝo:\n  crontab -e\n"
            f"Aldonu: {cron_line}",
            err=True,
        )
        raise typer.Exit(1) from e


@app.command("historio")
def historio_cmd() -> None:
    """Show a summary of the last 5 sekurkopio operations."""
    entries = _load_history()
    if not entries:
        typer.echo("Neniu historio trovita.")
        return
    table = Table(title=f"Historio (lastaj {_HISTORY_MAX})")
    table.add_column("#", style="dim")
    table.add_column("Okazis", style="cyan")
    table.add_column("Ago")
    table.add_column("Detaloj")
    for i, entry in enumerate(entries, 1):
        ts = entry["okazis_je"][:19].replace("T", " ")
        detaloj = json.loads(entry["detaloj"])
        detail_str = ", ".join(f"{k}={v}" for k, v in detaloj.items())
        table.add_row(str(i), ts, entry["ago"], detail_str)
    console.print(table)


@app.command("reveni")
def reveni(
    tempo: int | None = typer.Option(
        None,
        "-t",
        "--tempo",
        help=(
            "Specify a time offset from now in minutes. "
            "The two closest backup candidates will be proposed."
        ),
    ),
) -> None:
    """Restore autish data from a specific auto backup.

    Without arguments: list available backups and ask you to select one.
    With --tempo/-t MINUTES: propose the two closest backups in time.
    In both cases a j/N confirmation is required before restoring.
    """
    strategy = _load_auto_strategy()
    if not strategy:
        typer.echo(
            "[!] Neniu automata sekurkopio konfigurita. Uzu: sekurkopio auto",
            err=True,
        )
        raise typer.Exit(1)

    dosierujo = Path(strategy["dosierujo"])
    if not dosierujo.exists():
        typer.echo(f"[!] Dosierujo ne trovita: {dosierujo}", err=True)
        raise typer.Exit(1)

    # Collect available backup files sorted newest-first
    files = sorted(
        dosierujo.glob("autish_backup_*.aut"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not files:
        typer.echo("[!] Neniuj sekurkopidosieroj trovitaj.", err=True)
        raise typer.Exit(1)

    selected: Path | None = None

    if tempo is not None:
        # Find the two backups closest to (now - tempo minutes)
        target_ts = datetime.now(timezone.utc).timestamp() - tempo * 60
        sorted_by_diff = sorted(
            files, key=lambda p: abs(p.stat().st_mtime - target_ts)
        )
        candidates = sorted_by_diff[:2]

        typer.echo(f"\nPlej proksimaj sekurkopidosieroj al -{tempo} minutoj:\n")
        for i, fp in enumerate(candidates, 1):
            mtime = datetime.fromtimestamp(fp.stat().st_mtime, tz=timezone.utc)
            typer.echo(
                f"  {i}. {fp.name}  —  {mtime.strftime('%Y-%m-%d %H:%M:%S')} UTC"
            )

        while True:
            choice = typer.prompt(f"Elektu (1-{len(candidates)})", default="1").strip()
            if choice.isdigit() and 1 <= int(choice) <= len(candidates):
                selected = candidates[int(choice) - 1]
                break
            typer.echo(f"[!] Bonvolu tajpi nombron inter 1 kaj {len(candidates)}.")
    else:
        # Full interactive list
        typer.echo("\nDisponibleaj sekurkopidosieroj:\n")
        for i, fp in enumerate(files, 1):
            mtime = datetime.fromtimestamp(fp.stat().st_mtime, tz=timezone.utc)
            typer.echo(
                f"  {i:2d}. {fp.name}  —  {mtime.strftime('%Y-%m-%d %H:%M:%S')} UTC"
            )

        while True:
            choice = typer.prompt(f"Elektu (1-{len(files)})").strip()
            if choice.isdigit() and 1 <= int(choice) <= len(files):
                selected = files[int(choice) - 1]
                break
            typer.echo(f"[!] Bonvolu tajpi nombron inter 1 kaj {len(files)}.")

    if not _confirm_esperante(
        f"\nRestarigi el: {selected.name}?", default_yes=False
    ):
        typer.echo("Nuligita.")
        return

    pasvorto = typer.prompt("Pasvorto", hide_input=True)

    try:
        count = _import_from_archive(
            selected, pasvorto, formato="7z", overwrite=True
        )
    except Exception as exc:
        typer.echo(f"[!] Restarigado malsukcesis: {exc}", err=True)
        raise typer.Exit(1) from exc

    _push_history("reveni", {"dosiero": str(selected)})
    typer.echo(f"[v] Restarigis {count} dosiero(j)n el {selected.name}.")
