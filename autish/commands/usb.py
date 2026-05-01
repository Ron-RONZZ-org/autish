"""usb — USB device listing and bind/unbind controls.

Subcommands:
    usb ls [-a]                 list USB devices (compact or detailed)
    usb konekti <device>        bind a USB device back to its driver
    usb malkonekti <device>     unbind a USB device from its driver

Device format:
    Bus and device numbers, e.g. `001:002`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import typer

from autish.utils import echo_padded

app = typer.Typer(
    help="Komandoj por administri USB-aparatojn.",
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help", "--helpo"]},
)


def _run(cmd: list[str], timeout: int = 10) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd, capture_output=True, text=True, check=False, timeout=timeout
    )


def _lsusb() -> list[str]:
    result = _run(["lsusb"])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Ne povis listigi USB-aparatojn.")
    return [ln for ln in result.stdout.splitlines() if ln.strip()]


def _parse_bus_dev(line: str) -> tuple[str, str] | None:
    # Example: "Bus 001 Device 002: ID 8087:0029 Intel Corp."
    parts = line.split()
    if len(parts) < 4 or parts[0] != "Bus" or parts[2] != "Device":
        return None
    bus = parts[1]
    dev = parts[3].rstrip(":")
    if not (bus.isdigit() and dev.isdigit()):
        return None
    return bus.zfill(3), dev.zfill(3)


def _resolve_device_token(token: str) -> tuple[str, str]:
    text = token.strip()
    if ":" in text:
        bus, dev = text.split(":", 1)
        if bus.isdigit() and dev.isdigit():
            return bus.zfill(3), dev.zfill(3)
    raise ValueError("Uzu aparaton kiel BUS:DEV, ekz. 001:002.")


def _sysfs_device_path(bus: str, dev: str, root: Path | None = None) -> Path | None:
    root = root or Path("/sys/bus/usb/devices")
    if not root.exists():
        return None
    for child in root.iterdir():
        if not child.is_dir():
            continue
        busnum = child / "busnum"
        devnum = child / "devnum"
        if not busnum.exists() or not devnum.exists():
            continue
        try:
            b = busnum.read_text(encoding="utf-8").strip().zfill(3)
            d = devnum.read_text(encoding="utf-8").strip().zfill(3)
        except OSError:
            continue
        if b == bus and d == dev:
            return child
    return None


def _driver_bind_path(dev_path: Path) -> tuple[Path, Path] | None:
    driver_link = dev_path / "driver"
    if not driver_link.exists():
        return None
    try:
        real_driver = driver_link.resolve()
    except OSError:
        return None
    return (real_driver / "bind", real_driver / "unbind")


@app.command("ls")
def ls(
    pli_detale: bool = typer.Option(
        False, "-a", help="Montri pli da detaloj por ĉiu USB-aparato."
    ),
) -> None:
    """List USB devices."""
    lines = _lsusb()
    if not lines:
        echo_padded("Neniuj USB-aparatoj trovitaj.")
        return
    if not pli_detale:
        echo_padded("\n".join(lines))
        return

    out: list[str] = []
    for line in lines:
        parsed = _parse_bus_dev(line)
        out.append(line)
        if not parsed:
            continue
        bus, dev = parsed
        dev_path = _sysfs_device_path(bus, dev)
        if dev_path is None:
            out.append("  state: nekonata")
            continue
        bind_unbind = _driver_bind_path(dev_path)
        if bind_unbind is None:
            out.append("  state: malkonektita (sen ŝoforo)")
        else:
            out.append(f"  state: konektita ({bind_unbind[0].parent.name})")
    echo_padded("\n".join(out))


def _toggle_bind(device: str, *, connect: bool) -> None:
    bus, dev = _resolve_device_token(device)
    dev_path = _sysfs_device_path(bus, dev)
    if dev_path is None:
        typer.echo(
            f"USB-aparato ne trovita en sysfs por {bus}:{dev}.", err=True
        )
        raise typer.Exit(1)

    bind_unbind = _driver_bind_path(dev_path)
    busdev = dev_path.name
    if connect:
        if bind_unbind is None:
            typer.echo(
                "Ne eblas konekti: neniu aktiva ŝoforo trovita por tiu aparato.",
                err=True,
            )
            raise typer.Exit(1)
        bind_path, _ = bind_unbind
        try:
            bind_path.write_text(busdev, encoding="utf-8")
        except OSError as exc:
            typer.echo(f"Konekto malsukcesis: {exc}", err=True)
            raise typer.Exit(1) from exc
        echo_padded(f"Konektita USB-aparato {bus}:{dev}.")
        return

    if bind_unbind is None:
        typer.echo("Aparato jam malkonektita.", err=True)
        raise typer.Exit(1)
    _, unbind_path = bind_unbind
    try:
        unbind_path.write_text(busdev, encoding="utf-8")
    except OSError as exc:
        typer.echo(f"Malkonekto malsukcesis: {exc}", err=True)
        raise typer.Exit(1) from exc
    echo_padded(f"Malkonektita USB-aparato {bus}:{dev}.")


@app.command("konekti")
def konekti(
    device: str = typer.Argument(..., help="USB-aparato kiel BUS:DEV (ekz. 001:002)."),
) -> None:
    """Bind a USB device to its driver."""
    _toggle_bind(device, connect=True)


@app.command("malkonekti")
def malkonekti(
    device: str = typer.Argument(..., help="USB-aparato kiel BUS:DEV (ekz. 001:002)."),
) -> None:
    """Unbind a USB device from its driver."""
    _toggle_bind(device, connect=False)
