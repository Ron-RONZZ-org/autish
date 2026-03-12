"""wifi — Wi-Fi management commands.

Uses nmcli (NetworkManager CLI) which is available by default on Debian/Ubuntu.

Subcommands:
    autish wifi ls [name]          list connections; optional filter by name
    autish wifi konekti <name>     connect to a network
    autish wifi malkonekti         disconnect active Wi-Fi
    autish wifi forigi <name>      delete a saved network profile
"""

from __future__ import annotations

import subprocess

import typer

from autish.utils import echo_padded

app = typer.Typer(
    help="Wi-Fi management commands.",
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


@app.command("ls")
def ls(
    name: str | None = typer.Argument(
        None, help="SSID to show details for. Omit to list all connections."
    ),
    pasvorto: bool = typer.Option(
        False, "-p", help="Show saved password (requires elevated privileges)."
    ),
) -> None:
    """List Wi-Fi connections, with the active one first."""
    if name:
        extra = ["--show-secrets"] if pasvorto else []
        result = _run(["nmcli", *extra, "connection", "show", name])
    else:
        result = _run(
            ["nmcli", "-f", "ACTIVE,SSID,SIGNAL,SECURITY", "device", "wifi", "list"]
        )

    if result.returncode != 0:
        typer.echo(result.stderr.strip() or "nmcli error.", err=True)
        raise typer.Exit(code=result.returncode)

    echo_padded(result.stdout.strip())


@app.command("konekti")
def konekti(
    nomo: str = typer.Argument(..., help="SSID of the network to connect to."),
    pasvorto: str | None = typer.Option(
        None, "-p", "--pasvorto", help="Wi-Fi password."
    ),
    uzanto: str | None = typer.Option(
        None, "-u", "--uzanto", help="Username (for enterprise networks)."
    ),
) -> None:
    """Connect to a Wi-Fi network."""
    cmd = ["nmcli", "device", "wifi", "connect", nomo]
    if pasvorto:
        cmd += ["password", pasvorto]
    if uzanto:
        cmd += ["identity", uzanto]

    result = _run(cmd)
    if result.returncode != 0:
        typer.echo(result.stderr.strip() or "Connection failed.", err=True)
        raise typer.Exit(code=result.returncode)

    echo_padded(result.stdout.strip())


@app.command("malkonekti")
def malkonekti() -> None:
    """Disconnect from the active Wi-Fi connection."""
    # Detect active Wi-Fi interfaces via nmcli before attempting disconnect
    iface_result = _run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "device", "status"])
    wifi_ifaces = [
        line.split(":")[0]
        for line in iface_result.stdout.splitlines()
        if ":wifi:" in line and ":connected" in line
    ]
    if not wifi_ifaces:
        typer.echo("No active Wi-Fi connection found.")
        return
    for iface in wifi_ifaces:
        r = _run(["nmcli", "device", "disconnect", iface])
        if r.returncode != 0:
            typer.echo(r.stderr.strip() or f"Failed to disconnect {iface}.", err=True)
            raise typer.Exit(code=r.returncode)
        echo_padded(r.stdout.strip())


@app.command("forigi")
def forigi(
    nomo: str = typer.Argument(..., help="SSID of the network profile to delete."),
) -> None:
    """Delete a saved Wi-Fi network profile."""
    confirm = typer.confirm(f"Delete network profile '{nomo}'?")
    if not confirm:
        typer.echo("Cancelled.")
        return

    result = _run(["nmcli", "connection", "delete", nomo])
    if result.returncode != 0:
        typer.echo(result.stderr.strip() or "Deletion failed.", err=True)
        raise typer.Exit(code=result.returncode)

    echo_padded(result.stdout.strip())
