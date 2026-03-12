"""bluetooth — Bluetooth management commands.

Uses bluetoothctl (BlueZ) which is available by default on Debian/Ubuntu.

Subcommands:
    autish bluhdento ls [MAC]           list paired devices; optional filter by MAC
    autish bluhdento konekti <MAC>      connect a paired device
    autish bluhdento malkonekti [MAC]   disconnect a device (or all if no MAC given)
"""

from __future__ import annotations

import subprocess

import typer

from autish.utils import echo_padded

app = typer.Typer(
    help="Bluetooth device management commands.",
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _bluetoothctl(*args: str) -> subprocess.CompletedProcess[str]:
    return _run(["bluetoothctl", *args])


@app.command("ls")
def ls(
    mac: str | None = typer.Argument(
        None,
        help="Device MAC address to show details for. Omit to list all paired devices.",
    ),
) -> None:
    """List paired Bluetooth devices, with connected ones first."""
    if mac:
        result = _bluetoothctl("info", mac)
        if result.returncode != 0:
            typer.echo(result.stderr.strip() or "Device not found.", err=True)
            raise typer.Exit(code=result.returncode)
        echo_padded(result.stdout.strip())
        return

    paired = _bluetoothctl("devices", "Paired")
    if paired.returncode != 0:
        typer.echo(paired.stderr.strip() or "Could not list devices.", err=True)
        raise typer.Exit(code=paired.returncode)

    devices = paired.stdout.strip().splitlines()

    # Get connected MACs in a single call instead of N info queries
    connected_result = _bluetoothctl("devices", "Connected")
    connected_macs = {
        line.split(" ", 2)[1]
        for line in connected_result.stdout.strip().splitlines()
        if len(line.split(" ", 2)) >= 2
    }

    connected: list[str] = []
    other: list[str] = []

    for line in devices:
        # line format: "Device AA:BB:CC:DD:EE:FF Name"
        parts = line.split(" ", 2)
        if len(parts) < 2:
            continue
        device_mac = parts[1]
        if device_mac in connected_macs:
            connected.append(f"* {line}")
        else:
            other.append(f"  {line}")

    all_lines = connected + other
    if all_lines:
        echo_padded("\n".join(all_lines))
    else:
        typer.echo("No paired devices found.")


@app.command("konekti")
def konekti(
    mac: str = typer.Argument(..., help="MAC address of the device to connect."),
) -> None:
    """Connect a paired Bluetooth device."""
    result = _bluetoothctl("connect", mac)
    if result.returncode != 0:
        typer.echo(result.stderr.strip() or "Connection failed.", err=True)
        raise typer.Exit(code=result.returncode)
    echo_padded(result.stdout.strip())


@app.command("malkonekti")
def malkonekti(
    mac: str | None = typer.Argument(
        None,
        help="MAC address of the device to disconnect. Omit to disconnect all.",
    ),
) -> None:
    """Disconnect a Bluetooth device, or all connected devices if no MAC is given."""
    if mac:
        result = _bluetoothctl("disconnect", mac)
        if result.returncode != 0:
            typer.echo(result.stderr.strip() or "Disconnect failed.", err=True)
            raise typer.Exit(code=result.returncode)
        echo_padded(result.stdout.strip())
        return

    # Disconnect all connected devices using a single query
    connected_result = _bluetoothctl("devices", "Connected")
    disconnected_any = False
    for line in connected_result.stdout.strip().splitlines():
        parts = line.split(" ", 2)
        if len(parts) < 2:
            continue
        device_mac = parts[1]
        r = _bluetoothctl("disconnect", device_mac)
        if r.returncode == 0:
            echo_padded(r.stdout.strip())
            disconnected_any = True
        else:
            typer.echo(
                r.stderr.strip() or f"Failed to disconnect {device_mac}.", err=True
            )

    if not disconnected_any:
        typer.echo("No connected Bluetooth devices found.")
