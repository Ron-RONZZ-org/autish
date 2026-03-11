"""sistemo — system information command.

Usage:
    autish sistemo

Prints: OS, CPU, RAM, storage, battery, network, and Bluetooth state.
"""

from __future__ import annotations

import platform
import socket
import subprocess

import psutil
import typer

app = typer.Typer(help="Print system information.", invoke_without_command=True)


def _bytes_to_gib(n: int) -> str:
    return f"{n / 1024**3:.1f} GiB"


def _run(cmd: list[str]) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=5)
        return r.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""


@app.callback(invoke_without_command=True)
def sistemo(ctx: typer.Context) -> None:
    """Print system details: OS, hardware, RAM, storage, battery, network, Bluetooth."""
    if ctx.invoked_subcommand is not None:
        return

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
    lines.append(
        f"RAM      : {_bytes_to_gib(vm.used)} / {_bytes_to_gib(vm.total)} used"
    )

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

    typer.echo("\n".join(lines))
