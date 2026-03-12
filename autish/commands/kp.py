"""kp — clipboard copy helper.

Usage:
    autish kp <command>   run <command>, print output, AND copy it to clipboard
    autish kp             copy the last captured kp output (no re-execution)

Strategy (Option B from TODO.md):
    When `kp <command>` is used, stdout is stored in a temp file so that
    bare `autish kp` can retrieve it without re-running the command.
    This requires no shell configuration.
"""

from __future__ import annotations

import getpass
import subprocess
import tempfile
from pathlib import Path

import pyperclip
import typer

app = typer.Typer(
    help="Execute a command and copy its output to clipboard.",
    invoke_without_command=True,
)

_CACHE_FILE = Path(tempfile.gettempdir()) / f"autish_kp_{getpass.getuser()}.txt"


def _copy(text: str) -> None:
    try:
        pyperclip.copy(text)
    except pyperclip.PyperclipException as exc:
        typer.echo(f"Warning: could not copy to clipboard: {exc}", err=True)


@app.callback(invoke_without_command=True)
def kp(
    ctx: typer.Context,
    command: list[str] | None = typer.Argument(
        None,
        help="Command (and arguments) to run. Omit to paste last captured output.",
    ),
) -> None:
    """Run a command and copy its output to clipboard, or recall last output."""
    if ctx.invoked_subcommand is not None:
        return

    if not command:
        # Recall mode — read from cache file
        if not _CACHE_FILE.exists():
            typer.echo(
                "No previous kp output found. Run 'autish kp <command>' first.",
                err=True,
            )
            raise typer.Exit(code=1)
        text = _CACHE_FILE.read_text()
        _copy(text)
        typer.echo(text, nl=False)
        return

    # Execute mode — run the command
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    output = result.stdout
    if result.stderr:
        typer.echo(result.stderr, nl=False, err=True)
    if result.returncode != 0:
        raise typer.Exit(code=result.returncode)

    # Print and copy
    typer.echo(output, nl=False)
    _CACHE_FILE.write_text(output)
    _copy(output)
