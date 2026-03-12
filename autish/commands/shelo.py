"""shelo — interactive autish shell mode.

Usage:
    autish shelo

Starts an interactive prompt where autish commands can be entered without
typing 'autish' each time.  Type 'eliru' or 'exit' to quit.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
import sys

import typer

app = typer.Typer(
    help="Start an interactive autish shell (no need to type 'autish' each time).",
    invoke_without_command=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)

_PROMPT = "autish> "
_EXIT_WORDS = frozenset({"eliru", "exit", "q", "quit"})


def _autish_cmd() -> list[str]:
    """Return the command list needed to invoke autish."""
    exe = shutil.which("autish")
    if exe:
        return [exe]
    return [sys.executable, "-m", "autish"]


@app.callback(invoke_without_command=True)
def shelo(ctx: typer.Context) -> None:
    """Enter interactive shell — autish commands run without the 'autish' prefix."""
    if ctx.invoked_subcommand is not None:
        return

    prefix = _autish_cmd()
    typer.echo("autish interactive shell — type 'eliru' or 'exit' to quit.")

    while True:
        try:
            line = input(_PROMPT).strip()
        except (EOFError, KeyboardInterrupt):
            typer.echo("\nGoodbye.")
            break

        if not line:
            continue

        if line in _EXIT_WORDS:
            typer.echo("Goodbye.")
            break

        try:
            args = shlex.split(line)
        except ValueError as exc:
            typer.echo(f"Parse error: {exc}", err=True)
            continue

        subprocess.run(prefix + args, check=False)
