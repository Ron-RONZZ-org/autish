"""sistemo — system information and bash alias management.

Usage:
    autish sistemo info      # Print system information
    autish sistemo bash alias ...  # Manage bash aliases
"""

from __future__ import annotations

import os
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
    for uid, _alias_obj in alias_objs:
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


# ============================================================================
# INSTALL: Set up autish for system-wide or user-scoped access
# ============================================================================


def _generate_command_aliases() -> str:
    """Generate bash aliases for all autish commands.
    
    Returns a multi-line string of bash aliases that wrap autish subcommands.
    """
    commands = [
        "vorto", "retposto", "kontakto", "bluhdento", "wifi",
        "sistemo", "tempo", "kp", "shelo", "sekurkopio",
        "uzanto", "md", "encik", "disko", "usb", "filmeto",
        "kalendaro", "etikedo", "todo", "taglibro", "verki", "rubo"
    ]
    
    aliases = ["# autish command shortcuts"]
    for cmd in commands:
        aliases.append(f'{cmd}="autish {cmd}"')
    
    return "\n".join(aliases)


def _extract_description(help_text: str) -> str:
    """Extract description line from help text."""
    lines = help_text.split("\n")
    for line in lines:
        line = line.strip()
        if line and not line.startswith("╭") and "Usage:" not in line:
            return line.replace("│", "").strip()
    return ""


def _create_man_page(cmd: str, help_text: str) -> str:
    """Create groff/troff formatted man page."""
    desc = _extract_description(help_text)
    
    man_content = f'''.TH AUTISH\\-{cmd.upper()} 1 "2026-04-27" "autish" "autish CLI Reference"
.SH NAME
autish\\-{cmd} \\- {desc or f'{cmd} command'}
.SH SYNOPSIS
.B autish {cmd}
[OPTIONS] [SUBCOMMAND]
.SH DESCRIPTION
The \\fI{cmd}\\fR subcommand of autish — a cross-platform CLI tool for essential 
desktop tasks with minimum sensory stimulation.
.SH OPTIONS
For all available options, run:
.IP
autish {cmd} \\-\\-help
.SH EXAMPLES
.IP
View help for this command:
.IP
  autish {cmd} \\-\\-help
.IP
View help for a specific subcommand:
.IP
  autish {cmd} SUBCOMMAND \\-\\-help
.SH SEE ALSO
.BR autish(1)
.SH AUTHOR
Autish contributors
'''
    return man_content


def _install_man_pages() -> None:
    """Install groff man pages to ~/.local/share/man/man1."""
    commands = [
        "tempo", "wifi", "bluhdento", "sistemo", "kp", "shelo", "vorto",
        "retposto", "kontakto", "sekurkopio", "uzanto", "verki", "md",
        "encik", "kalendaro", "disko", "usb", "filmeto", "etikedo",
        "todo", "taglibro", "rubo",
    ]
    
    man_dir = Path.home() / ".local" / "share" / "man" / "man1"
    man_dir.mkdir(parents=True, exist_ok=True)
    
    for cmd in commands:
        try:
            result = subprocess.run(
                ["poetry", "run", "autish", cmd, "--help"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                man_content = _create_man_page(cmd, result.stdout)
                man_file = man_dir / f"autish-{cmd}.1"
                man_file.write_text(man_content)
        except Exception:
            pass
    
    # Main autish man page
    main_man = """.TH AUTISH 1 "2026-04-27" "autish" "autish CLI Reference"
.SH NAME
autish \\- cross-platform CLI for essential tasks with minimum sensory stimulation
.SH SYNOPSIS
.B autish
[COMMAND] [OPTIONS]
.SH DESCRIPTION
autish is a cross-platform CLI software for essential desktop tasks with minimum 
stimulation. Designed with neurodiversity in mind for calm, predictable output.
.SH COMMANDS
For a complete list of commands and options:
.IP
autish \\-\\-help
.SH EXAMPLES
.IP
Show current time:
.IP
  autish tempo
.IP
List Wi-Fi networks:
.IP
  autish wifi ls
.IP
Show system information:
.IP
  autish sistemo
.SH SEE ALSO
.BR autish-tempo(1),
.BR autish-wifi(1),
.BR autish-vorto(1),
.BR autish-encik(1)
.SH AUTHOR
Autish contributors
.SH WEBSITE
https://github.com/Ron-RONZZ-org/autish
"""
    
    (man_dir / "autish.1").write_text(main_man)
    
    # Set up MANPATH in shell config
    for rc_file in [Path.home() / ".bashrc", Path.home() / ".zshrc"]:
        if rc_file.exists():
            content = rc_file.read_text()
            manpath_line = 'export MANPATH="$HOME/.local/share/man:$MANPATH"'
            if "MANPATH" not in content:
                with open(rc_file, "a") as f:
                    f.write(f"\n# autish man pages\n{manpath_line}\n")


@app.command("install")
def install(
    sistema: bool = typer.Option(
        False,
        "-s",
        "--sistema",
        help="Instali ĉie (sisteme) — devo ruli per 'sudo'. Default: uzanto-ĉambro.",
    ),
) -> None:
    """Instali autish ĝlobale por ke aliaj komandoj kaj bash-alias-oj funkciu.

    Per defaŭlto, instalas al ~/.local/bin (uzanto-ĉambro).
    Por sistema instalado, uzu --sistema kaj rulu per sudo.

    Ĉi tio kreas ligon por ke `autish` funkcii en ĉiu ŝelo-sesio
    sen devo aktivigi la Poetry-medion.

    Examples:
        autish sistemo install                # Instali en ~/.local/bin (defaŭlte)
        sudo autish sistemo install --sistema # Instali en /usr/local/bin
    """

    # Get the poetry environment path
    try:
        result = subprocess.run(
            ["poetry", "env", "info", "--path"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if result.returncode != 0:
            typer.echo(
                (
                    "[!] Ne povis trovi Poetry medion. "
                    "Ĉu vi estas en autish-dosierujo?"
                ),
                err=True,
            )
            raise typer.Exit(1)
        poetry_env_path = result.stdout.strip()
    except subprocess.TimeoutExpired:
        typer.echo(
            "[!] Poetry timeout - ĉu poetry estas instalita?",
            err=True,
        )
        raise typer.Exit(1) from None

    autish_src = Path(poetry_env_path) / "bin" / "autish"
    if not autish_src.exists():
        typer.echo(
            f"[!] autish binarooj ne trovita ĉe {autish_src}",
            err=True,
        )
        raise typer.Exit(1)

    # Default is user-scoped, unless --sistema is specified
    if sistema:
        dest_dir = Path("/usr/local/bin")
    else:
        dest_dir = Path.home() / ".local" / "bin"

    try:
        if not dest_dir.exists():
            dest_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        scope_label = "sisteme" if sistema else "uzanto-ĉambro"
        typer.echo(
            (
                f"[!] Neniaj permesoj por kreado de {dest_dir}\n"
                f"    Por {scope_label}: "
                + (
                    "rulu per sudo"
                    if sistema
                    else "kontrolu ĉu ~/.local/bin ekzistas"
                )
            ),
            err=True,
        )
        raise typer.Exit(1) from None

    autish_dst = dest_dir / "autish"

    # Check if destination exists
    if autish_dst.exists() or autish_dst.is_symlink():
        if autish_dst.is_symlink() and autish_dst.resolve() == autish_src:
            typer.echo(f"[i] autish jam instalita ĉe {autish_dst}")
            
            # Ask if they want to reinstall (useful for fixing bugs, etc.)
            reinstall = typer.confirm(
                "[?] Ĉu repreparinstitali por ripari eblajn erarojn?",
                default=False,
            )
            if not reinstall:
                typer.echo("Nuligita.")
                raise typer.Exit(0)
            
            autish_dst.unlink()
        else:
            overwrite = typer.confirm(
                f"[?] {autish_dst} jam ekzistas. Ĉu anstataŭigi?",
                default=False,
            )
            if not overwrite:
                typer.echo("Nuligita.")
                raise typer.Exit(0)

            autish_dst.unlink()

    # Create symlink
    try:
        autish_dst.symlink_to(autish_src)
        scope_label = "uzanto-ĉambro" if not sistema else "sisteme"
        typer.echo(f"[✓] Instalita autish en {scope_label}: {autish_dst}")

        # Ensure ~/.bashrc sources the aliases file
        bashrc_path = Path.home() / ".bashrc"
        source_line = "source ~/.autish_aliases"
        
        try:
            if bashrc_path.exists():
                content = bashrc_path.read_text()
                if source_line not in content:
                    with open(bashrc_path, "a") as f:
                        f.write(f"\n# autish bash aliases\n{source_line}\n")
                    typer.echo("[✓] ~/.bashrc ĝisdatigita por fonti alias-ojn")
            else:
                # Create .bashrc if it doesn't exist
                bashrc_path.write_text(f"# autish bash aliases\n{source_line}\n")
                typer.echo("[✓] Kreitaj ~/.bashrc kun alias-oj")
        except Exception as e:
            typer.echo(
                f"[!] Ne povis ĝisdatigi ~/.bashrc: {e}",
                err=True,
            )

        # Update PATH hint if user scope
        if not sistema:
            path_env = os.environ.get("PATH", "").split(":")
            if str(Path.home() / ".local" / "bin") not in path_env:
                typer.echo(
                    "[!] Aldonu ~/.local/bin al via PATH:\n"
                    "    echo 'export PATH=\"$HOME/.local/bin:$PATH\"' >> ~/.bashrc\n"
                    "    source ~/.bashrc"
                )

        # Regenerate aliases if they exist
        try:
            db = BashAliasDB()
            aliases = db.list_aliases()
            if aliases:
                typer.echo("[i] Regeneranta bash alias-ojn...")
                db.sync_shell_config()
                typer.echo("[✓] Bash alias-oj regeneritaj")
        except Exception as e:
            typer.echo(
                f"[!] Ne povis regeneri alias-ojn: {e}",
                err=True,
            )
        
        # Add command shortcuts to ~/.autish_aliases
        try:
            autish_aliases = Path.home() / ".autish_aliases"
            cmd_aliases = _generate_command_aliases()
            autish_aliases.write_text(cmd_aliases + "\n")
            typer.echo("[✓] Komanda alias-oj ĝisdatigitaj en ~/.autish_aliases")
        except Exception as e:
            typer.echo(
                f"[!] Ne povis ĝisdatigi ~/.autish_aliases: {e}",
                err=True,
            )
        # Install man pages
        try:
            _install_man_pages()
            typer.echo("[✓] Man-paĝoj instalitaj en ~/.local/share/man/man1")
        except Exception as e:
            typer.echo(
                f"[!] Ne povis instali man-paĝojn: {e}",
                err=True,
            )
    except PermissionError as e:
        scope_label = "sisteme" if sistema else "uzanto-ĉambro"
        typer.echo(
            (
                f"[!] Neniaj permesoj dum instalado en {scope_label}: {e}\n"
                + (
                    "    Rulu: sudo autish sistemo install --sistema"
                    if not sistema
                    else "    Kontrolu la permesojn de /usr/local/bin"
                )
            ),
            err=True,
        )
        raise typer.Exit(1) from None
    except Exception as e:
        typer.echo(f"[!] Eraro dum instalado: {e}", err=True)
        raise typer.Exit(1) from None



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
