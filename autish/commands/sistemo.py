"""sistemo — system information and bash alias management.

Usage:
    autish sistemo info      # Print system information
    autish sistemo bash alias ...  # Manage bash aliases
"""

from __future__ import annotations

import platform
import socket
import sqlite3
import subprocess
from pathlib import Path

import psutil
import typer
from rich.console import Console
from rich.table import Table

from autish.services.bash_alias import BashAliasDB
from autish.utils import echo_padded

app = typer.Typer(
    help="Sistemaj utilaĵoj: informoj kaj bash alias-oj.",
    context_settings={"help_option_names": ["-h", "--help", "--helpo"]},
)

# Subapp for bash alias management
bash_alias_app = typer.Typer(
    help="Administri bash alias-ojn.",
    context_settings={"help_option_names": ["-h", "--help", "--helpo"]},
)


def _bytes_to_gib(n: int) -> str:
    return f"{n / 1024**3:.1f} GiB"


def _run(cmd: list[str]) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=5)
        return r.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""


def _get_bash_alias_db_path() -> Path:
    """Get path to bash alias database."""
    config_dir = Path.home() / ".config" / "autish"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "bash_aliases.db"


# ============================================================================
# INFO SUBCOMMAND (original sistemo functionality)
# ============================================================================


@app.command(name="info", help="Montri sistemajn informojn.")
def info() -> None:
    """Print system details: OS, hardware, RAM, storage, battery, network, Bluetooth."""
    lines: list[str] = []

    # OS
    uname = platform.uname()
    lines.append(f"OS       : {uname.system} {uname.release} ({uname.machine})")
    try:
        os_pretty = platform.freedesktop_os_release().get("PRETTY_NAME", "")
        if os_pretty:
            lines.append(f"         : {os_pretty}")
    except (AttributeError, OSError):
        pass

    # CPU
    cpu_model = platform.processor() or uname.processor or "unknown"
    cpu_pct = psutil.cpu_percent(interval=0.5)
    lines.append(f"CPU      : {cpu_model}  ({cpu_pct}% used)")

    # RAM
    vm = psutil.virtual_memory()
    ram_used = _bytes_to_gib(vm.used)
    ram_total = _bytes_to_gib(vm.total)
    lines.append(f"RAM      : {ram_used} / {ram_total} used")

    # Storage
    lines.append("Storage  :")
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except PermissionError:
            continue
        lines.append(
            f"  {part.mountpoint:20s} "
            f"{_bytes_to_gib(usage.used)} / {_bytes_to_gib(usage.total)}"
        )

    # Battery
    battery = psutil.sensors_battery()
    if battery is not None:
        status = "charging" if battery.power_plugged else "discharging"
        lines.append(f"Battery  : {battery.percent:.0f}% ({status})")
    else:
        lines.append("Battery  : n/a")

    # Network
    try:
        hostname = socket.gethostname()
        ip = socket.gethostbyname(hostname)
    except OSError:
        hostname, ip = "unknown", "unknown"
    lines.append(f"Network  : {hostname} ({ip})")

    # Active network interfaces
    net_if = psutil.net_if_stats()
    active = [iface for iface, stat in net_if.items() if stat.isup and iface != "lo"]
    if active:
        lines.append(f"           interfaces up: {', '.join(active)}")

    # Bluetooth
    bt_output = _run(["bluetoothctl", "show"])
    if bt_output:
        powered = "yes" if "Powered: yes" in bt_output else "no"
        bt_devices = _run(["bluetoothctl", "devices", "Connected"])
        connected_count = len([ln for ln in bt_devices.splitlines() if ln.strip()])
        lines.append(
            f"Bluetooth: powered={powered}, {connected_count} device(s) connected"
        )
    else:
        lines.append("Bluetooth: unavailable")

    echo_padded("\n".join(lines))


# ============================================================================
# BASH ALIAS SUBCOMMANDS (new functionality)
# ============================================================================


@bash_alias_app.command(name="aldoni", help="Aldoni novan bash-alias.")
def bash_alias_aldoni(
    alias: str = typer.Option(..., "--alias", "-a", help="Bash-alias nomo"),
    function: str = typer.Option(..., "--function", "-f", help="Bash-alias funkcio"),
    notes: str = typer.Option("", "--notes", "-n", help="Opciaj notoj (markdown)"),
) -> None:
    """Add new bash alias to database and shell configuration."""
    db = BashAliasDB()

    try:
        uid = db.add_alias(alias, function, notes or None)
        db.sync_shell_config()
        typer.echo(f"[✓] Aldoni: UID {uid} '{alias}'")
    except sqlite3.IntegrityError as err:
        typer.echo(f"[!] Alias '{alias}' jam ekzistas", err=True)
        raise typer.Exit(1) from err


@bash_alias_app.command(name="modifi", help="Modifi ekzistantan bash-alias.")
def bash_alias_modifi(
    uid: int = typer.Argument(..., help="Bash-alias UID"),
    alias: str = typer.Option(None, "--alias", "-a", help="Nova alias nomo"),
    function: str = typer.Option(None, "--function", "-f", help="Nova funkcio"),
    notes: str = typer.Option(None, "--notes", "-n", help="Novaj notoj"),
) -> None:
    """Modify existing bash alias."""
    db = BashAliasDB()

    if not db.update_alias(uid, alias, function, notes):
        typer.echo(f"[!] Bash-alias UID {uid} ne trovita", err=True)
        raise typer.Exit(1)

    db.sync_shell_config()
    typer.echo(f"[✓] Modifita: UID {uid}")


@bash_alias_app.command(name="forigi", help="Forigi bash-alias(ojn).")
def bash_alias_forigi(
    uids: list[int] = typer.Argument(..., help="Bash-alias UID(j)"),
    justa: bool = typer.Option(False, "--justa", "-j", help="Forigi sen konfirmo"),
) -> None:
    """Delete one or more bash aliases."""
    if not uids:
        typer.echo("[!] Al minas unu UID bezonata", err=True)
        raise typer.Exit(1)

    db = BashAliasDB()

    # Verify all UIDs exist first
    alias_objs = []
    for uid in uids:
        alias_obj = db.get_alias(uid)
        if alias_obj is None:
            typer.echo(f"[!] Bash-alias UID {uid} ne trovita", err=True)
            raise typer.Exit(1)
        alias_objs.append((uid, alias_obj))

    # Show what will be deleted
    if not justa:
        typer.echo("[i] Forigos:")
        for uid, alias_obj in alias_objs:
            typer.echo(f"  UID {uid}: {alias_obj.alias}")
        confirm = typer.confirm("Ĉu forigi?")
        if not confirm:
            typer.echo("Nuligita")
            raise typer.Exit(0)

    # Delete all
    for uid, alias_obj in alias_objs:
        db.delete_alias(uid)
    db.sync_shell_config()

    if len(uids) == 1:
        typer.echo(f"[✓] Forigita: UID {uids[0]}")
    else:
        typer.echo(f"[✓] Forigita: {len(uids)} alias-oj")


@bash_alias_app.command(name="vidi", help="Vidi bash-alias detale.")
def bash_alias_vidi(
    uid: int = typer.Argument(..., help="Bash-alias UID"),
) -> None:
    """View single bash alias details."""
    db = BashAliasDB()

    alias_obj = db.get_alias(uid)
    if alias_obj is None:
        typer.echo(f"[!] Bash-alias UID {uid} ne trovita", err=True)
        raise typer.Exit(1)

    console = Console()
    table = Table(title=f"Bash-alias UID {uid}")
    table.add_column("Kampo", style="cyan")
    table.add_column("Valoro")

    table.add_row("Nomo", alias_obj.alias)
    table.add_row("Funkcio", alias_obj.function)
    if alias_obj.notes:
        table.add_row("Notoj", alias_obj.notes)
    if alias_obj.created_at:
        table.add_row("Kreita", alias_obj.created_at.isoformat())
    if alias_obj.updated_at:
        table.add_row("Modifita", alias_obj.updated_at.isoformat())

    console.print(table)


@bash_alias_app.command(name="ls", help="Listigi ĉiujn bash-alias-ojn.")
def bash_alias_ls(
    alfabeto: bool = typer.Option(
        False, "--alfabeto", "-al", help="Alfabeta ordo (ne laŭ kreado)"
    ),
    inversigi: bool = typer.Option(False, "--inversigi", "-i", help="Inversa ordo"),
) -> None:
    """List all bash aliases with optional paging."""
    db = BashAliasDB()

    sort_by = "alias" if alfabeto else "created_at"
    descending = not inversigi  # Default: newest first or alpha first
    aliases = db.list_aliases(sort_by=sort_by, descending=descending)

    if not aliases:
        typer.echo("[i] Neniuj bash-alias-oj trovitaj")
        return

    console = Console()
    table = Table(title="Bash-alias-oj")
    table.add_column("UID", style="cyan")
    table.add_column("Alias", style="green")
    table.add_column("Funkcio (unuaj 50 ĉaroj)", style="dim")
    table.add_column("Notoj (unuaj 40 ĉaroj)", style="dim")

    for alias_obj in aliases:
        func_display = (
            (alias_obj.function[:50] + "...")
            if len(alias_obj.function) > 50
            else alias_obj.function
        )
        notes_display = (
            (alias_obj.notes[:40] + "...")
            if alias_obj.notes and len(alias_obj.notes) > 40
            else (alias_obj.notes or "")
        )
        table.add_row(str(alias_obj.uid), alias_obj.alias, func_display, notes_display)

    console.print(table)


@bash_alias_app.command(name="serci", help="Serĉi bash-alias-ojn.")
def bash_alias_serci(
    query: str = typer.Argument("", help="Serĉa termino (fuzzy)"),
) -> None:
    """Search bash aliases with fuzzy matching and user selection."""
    db = BashAliasDB()

    if not query:
        query = typer.prompt("Serĉa termino")

    results = db.search_aliases(query)

    if not results:
        typer.echo(f"[i] Neniuj rezultoj por '{query}'")
        return

    console = Console()
    table = Table(title=f"Serĉrezultoj: '{query}'")
    table.add_column("UID", style="cyan")
    table.add_column("Alias", style="green")
    table.add_column("Funkcio (unuaj 50 ĉaroj)", style="dim")

    for alias_obj in results:
        func_display = (
            (alias_obj.function[:50] + "...")
            if len(alias_obj.function) > 50
            else alias_obj.function
        )
        table.add_row(str(alias_obj.uid), alias_obj.alias, func_display)

    console.print(table)

    # Prompt user to select and view
    if len(results) > 0:
        uid_input = typer.prompt(
            "Elektu UID por vidi detale (aŭ premu Enter por elsalti)"
        )
        if uid_input:
            try:
                selected_uid = int(uid_input)
                bash_alias_vidi(selected_uid)
            except (ValueError, typer.Exit):
                pass


# Register bash_alias_app as subcommand
app.add_typer(bash_alias_app, name="bash-alias")


# ============================================================================
# CALLBACK: Allow default behavior (show info when no subcommand)
# ============================================================================


@app.callback(invoke_without_command=True)
def sistemo_callback(ctx: typer.Context) -> None:
    """Main sistemo callback - delegates to subcommands or shows info by default."""
    if ctx.invoked_subcommand is None:
        # No subcommand specified, show info by default
        info()
