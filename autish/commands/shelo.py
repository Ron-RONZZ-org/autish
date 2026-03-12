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
from pathlib import Path

import typer

app = typer.Typer(
    help="Start an interactive autish shell (no need to type 'autish' each time).",
    invoke_without_command=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)

_PROMPT = "autish> "
_EXIT_WORDS = frozenset({"eliru", "exit", "q", "quit"})

_HISTORY_FILE = Path.home() / ".local" / "share" / "autish" / "shelo_history"
_MAX_HISTORY = 500


def _autish_cmd() -> list[str]:
    """Return the command list needed to invoke autish."""
    exe = shutil.which("autish")
    if exe:
        return [exe]
    return [sys.executable, "-m", "autish"]


def _setup_readline() -> None:
    """Configure readline for history navigation and persistence."""
    try:
        import readline  # noqa: PLC0415

        readline.set_history_length(_MAX_HISTORY)
        if _HISTORY_FILE.exists():
            readline.read_history_file(str(_HISTORY_FILE))
    except Exception:
        pass


def _save_history() -> None:
    """Persist readline history to disk."""
    try:
        import readline  # noqa: PLC0415

        _HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        readline.write_history_file(str(_HISTORY_FILE))
    except Exception:
        pass


def _search_history(query: str) -> None:
    """Print the last 5 history entries that contain *query*."""
    try:
        import readline  # noqa: PLC0415

        found: list[str] = []
        hist_len = readline.get_current_history_length()
        for i in range(hist_len, 0, -1):
            item = readline.get_history_item(i)
            if item and query.lower() in item.lower() and not item.startswith("/"):
                found.append(item)
                if len(found) >= 5:
                    break
        if found:
            typer.echo("Trovita en historio:")
            for j, cmd in enumerate(found, 1):
                typer.echo(f"  {j}) {cmd}")
        else:
            typer.echo(f"Neniu historio trovita por: {query!r}")
    except Exception:
        typer.echo("Historio ne disponebla en ĉi tiu medio.")


@app.callback(invoke_without_command=True)
def shelo(ctx: typer.Context) -> None:
    """Enter interactive shell — autish commands run without the 'autish' prefix."""
    if ctx.invoked_subcommand is not None:
        return

    prefix = _autish_cmd()
    _setup_readline()
    typer.echo("autish interactive shell — type 'eliru' or 'exit' to quit.")
    typer.echo("History: ↑/↓ navigate  Ctrl+R reverse-search  /query search history")

    try:
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

            # /query — search history
            if line.startswith("/") and len(line) > 1:
                _search_history(line[1:])
                continue

            try:
                args = shlex.split(line)
            except ValueError as exc:
                typer.echo(f"Parse error: {exc}", err=True)
                continue

            subprocess.run(prefix + args, check=False)
    finally:
        _save_history()
