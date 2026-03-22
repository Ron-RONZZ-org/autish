"""disko — storage device management CLI.

Usage:
    disko ls                        — list connected storage devices
    disko sano <nomo>               — check disk health with SMART
    disko munti <nomo> [-l/--loko]  — mount disk at location
    disko malmunti <nomo>           — unmount disk

Data is retrieved from system tools (lsblk, smartctl, mount/umount).
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

# ──────────────────────────────────────────────────────────────────────────────
# Typer app
# ──────────────────────────────────────────────────────────────────────────────

app = typer.Typer(
    name="disko",
    help="Disko — storage device management.",
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help", "--helpo"]},
)

console = Console()


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _run_command(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run a shell command and return the result."""
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, check=check
        )
    except subprocess.CalledProcessError as e:
        typer.echo(f"Eraro: {e.stderr.strip()}", err=True)
        raise typer.Exit(code=1) from e
    except FileNotFoundError as e:
        typer.echo(f"Komando ne trovita: {cmd[0]}", err=True)
        raise typer.Exit(code=1) from e


def _format_size(size_bytes: int) -> str:
    """Format size in bytes to human-readable format."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f}{unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f}PB"


# ──────────────────────────────────────────────────────────────────────────────
# Commands
# ──────────────────────────────────────────────────────────────────────────────


@app.command("ls")
def ls_disks() -> None:
    """List all connected storage devices."""
    result = _run_command([
        "lsblk",
        "--json",
        "--output", "NAME,TYPE,MOUNTPOINT,SIZE,FSTYPE,RM,RO,MODEL,FSAVAIL",
        "--bytes"
    ])
    
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        typer.echo("Eraro: Ne povis analizi lsblk eligon.", err=True)
        raise typer.Exit(code=1) from e
    
    devices = data.get("blockdevices", [])
    if not devices:
        typer.echo("Neniu disko trovita.")
        return
    
    # Create table
    table = Table(
        show_header=True,
        header_style="bold cyan",
        border_style="dim",
        expand=False,
    )
    table.add_column("Nomo", style="yellow")
    table.add_column("Tipo")
    table.add_column("Loko")
    table.add_column("Grandeco", justify="right")
    table.add_column("Spaco", justify="right")
    table.add_column("Dosiersistemo")
    table.add_column("RM", justify="center")
    table.add_column("RO", justify="center")
    table.add_column("Modelo")
    
    def add_device(dev: dict, indent: int = 0):
        """Recursively add device and its children to table."""
        name = ("  " * indent) + dev.get("name", "?")
        tipo = dev.get("type", "?")
        # Map type to Esperanto
        tipo_map = {
            "disk": "disko",
            "part": "subdisko",
            "rom": "rom",
            "loop": "buklo",
        }
        tipo = tipo_map.get(tipo, tipo)
        
        mountpoint = dev.get("mountpoint") or ""
        size = dev.get("size")
        size_str = _format_size(size) if size else ""
        
        fsavail = dev.get("fsavail")
        fsavail_str = _format_size(fsavail) if fsavail else ""
        
        fstype = dev.get("fstype") or ""
        rm = "1" if dev.get("rm") else "0"
        ro = "1" if dev.get("ro") else "0"
        model = (dev.get("model") or "").strip() or ""
        
        table.add_row(
            name, tipo, mountpoint, size_str, fsavail_str,
            fstype, rm, ro, model
        )
        
        # Add children recursively
        for child in dev.get("children", []):
            add_device(child, indent + 1)
    
    for device in devices:
        add_device(device)
    
    console.print(table)


@app.command("sano")
def check_health(
    nomo: str = typer.Argument(..., help="Device name (e.g., sda, nvme0n1)"),
) -> None:
    """Check disk health using SMART (requires sudo)."""
    # Verify smartctl is available
    smartctl_paths = ["/usr/sbin/smartctl", "/usr/bin/smartctl"]
    if not any(os.path.exists(p) for p in smartctl_paths):
        typer.echo(
            "smartctl ne trovita. Instalu ĝin: sudo apt install smartmontools",
            err=True
        )
        raise typer.Exit(code=1)
    
    # Build device path
    dev_path = f"/dev/{nomo}" if not nomo.startswith("/dev/") else nomo
    
    # Run smartctl
    typer.echo(f"Kontrolante sanon de {dev_path}...")
    typer.echo("(Bezonas sudo rajtojn)")
    typer.echo("")
    
    result = _run_command(
        ["sudo", "smartctl", "-a", dev_path],
        check=False
    )
    
    if result.returncode not in (0, 4):  # 0=OK, 4=some SMART errors but readable
        typer.echo("Eraro: Ne povis legi SMART informojn.", err=True)
        typer.echo(result.stderr, err=True)
        raise typer.Exit(code=1)
    
    # Parse and display key information
    lines = result.stdout.split("\n")
    
    # Display header
    console.print(f"[bold cyan]SMART Informoj por {dev_path}[/bold cyan]\n")
    
    # Extract key fields
    in_attributes = False
    table = Table(show_header=True, header_style="bold", border_style="dim")
    table.add_column("Atributo")
    table.add_column("Valoro", justify="right")
    table.add_column("Plej Malbona", justify="right")
    table.add_column("Sojlo", justify="right")
    table.add_column("RAW Valoro", justify="right")
    
    for line in lines:
        # Overall health
        if "SMART overall-health" in line or "SMART Health Status" in line:
            status = line.split(":")[-1].strip()
            status_color = "green" if "PASSED" in status or "OK" in status else "red"
            console.print(f"Ĝenerala Sano: [{status_color}]{status}[/{status_color}]\n")
        
        # SMART Attributes section
        if "ID# ATTRIBUTE_NAME" in line:
            in_attributes = True
            continue
        
        if in_attributes:
            if not line.strip() or line.startswith("="):
                in_attributes = False
                continue
            
            parts = line.split()
            if len(parts) >= 10 and parts[0].isdigit():
                attr_name = parts[1]
                value = parts[3]
                worst = parts[4]
                thresh = parts[5]
                raw = " ".join(parts[9:])
                
                # Highlight critical attributes
                style = ""
                if attr_name in ("Reallocated_Sector_Ct", "Current_Pending_Sector"):
                    if int(raw.split()[0] if raw.split() else "0") > 0:
                        style = "red"
                elif attr_name == "Temperature_Celsius":
                    temp = int(raw.split()[0] if raw.split() else "0")
                    if temp > 60:
                        style = "yellow"
                
                if style:
                    table.add_row(
                        f"[{style}]{attr_name}[/{style}]",
                        f"[{style}]{value}[/{style}]",
                        f"[{style}]{worst}[/{style}]",
                        f"[{style}]{thresh}[/{style}]",
                        f"[{style}]{raw}[/{style}]",
                    )
                else:
                    table.add_row(attr_name, value, worst, thresh, raw)
    
    if table.row_count > 0:
        console.print(table)
    
    # Show raw output option
    typer.echo("\nPor vidi plenan eligon: sudo smartctl -a " + dev_path)


@app.command("munti")
def mount_disk(
    nomo: str = typer.Argument(..., help="Device name (e.g., sda1, nvme0n1p1)"),
    loko: str | None = typer.Option(
        None, "-l", "--loko", help="Mount point (default: $HOME/{label or name})"
    ),
) -> None:
    """Mount a disk at the specified location."""
    # Build device path
    dev_path = f"/dev/{nomo}" if not nomo.startswith("/dev/") else nomo
    
    # Check if device exists
    if not Path(dev_path).exists():
        typer.echo(f"Disko ne trovita: {dev_path}", err=True)
        raise typer.Exit(code=1)
    
    # Check if already mounted
    result = _run_command(["mount"], check=True)
    if dev_path in result.stdout:
        # Extract mountpoint
        for line in result.stdout.split("\n"):
            if dev_path in line:
                mount_point = line.split()[2]
                typer.echo(f"{dev_path} jam muntita ĉe: {mount_point}")
                return
    
    # Determine mount point
    if loko is None:
        # Try to get disk label
        result = _run_command(["lsblk", "-no", "LABEL", dev_path], check=False)
        label = result.stdout.strip()
        
        if label:
            loko = str(Path.home() / label)
        else:
            # Use device name
            loko = str(Path.home() / nomo.replace("/", "_"))
    
    mount_path = Path(loko)
    
    # Check if mount point exists
    if not mount_path.exists():
        typer.echo(f"Muntpunkto ne ekzistas: {mount_path}")
        create = typer.confirm("Ĉu krei ĝin?", default=True)
        if not create:
            typer.echo("Nuligita.")
            raise typer.Exit(code=0)
        
        try:
            mount_path.mkdir(parents=True, exist_ok=True)
            typer.echo(f"Kreis dosierujon: {mount_path}")
        except OSError as e:
            typer.echo(f"Eraro kreante dosierujon: {e}", err=True)
            raise typer.Exit(code=1) from e
    
    # Mount the disk
    typer.echo(f"Muntante {dev_path} ĉe {mount_path}...")
    typer.echo("(Bezonas sudo rajtojn)")
    
    result = _run_command(
        ["sudo", "mount", dev_path, str(mount_path)],
        check=False
    )
    
    if result.returncode != 0:
        typer.echo(f"Eraro muntante: {result.stderr.strip()}", err=True)
        raise typer.Exit(code=1)
    
    typer.echo(f"[✓] Sukcese muntis {dev_path} ĉe {mount_path}")


@app.command("malmunti")
def unmount_disk(
    nomo: str = typer.Argument(..., help="Device name or mount point"),
) -> None:
    """Unmount a disk."""
    # Could be device path or mount point
    if nomo.startswith("/dev/"):
        target = nomo
    elif nomo.startswith("/"):
        target = nomo
    else:
        target = f"/dev/{nomo}"
    
    # Check if mounted
    result = _run_command(["mount"], check=True)
    mounted = False
    mount_point = None
    
    for line in result.stdout.split("\n"):
        if target in line:
            mounted = True
            parts = line.split()
            if len(parts) >= 3:
                mount_point = parts[2]
            break
    
    if not mounted:
        typer.echo(f"{target} ne estas muntita.")
        return
    
    # Unmount
    typer.echo(f"Malmuntante {target}...")
    typer.echo("(Bezonas sudo rajtojn)")
    
    result = _run_command(
        ["sudo", "umount", target],
        check=False
    )
    
    if result.returncode != 0:
        typer.echo(f"Eraro malmuntante: {result.stderr.strip()}", err=True)
        raise typer.Exit(code=1)
    
    typer.echo(f"[✓] Sukcese malmuntis {target}")
    if mount_point:
        typer.echo(f"    (antaŭe ĉe: {mount_point})")
