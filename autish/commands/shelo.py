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
    context_settings={"help_option_names": ["-h", "--help", "--helpo"]},
)

_PROMPT = "autish> "
_EXIT_WORDS = frozenset({"eliru", "exit", "q", "quit"})

_HISTORY_FILE = Path.home() / ".local" / "share" / "autish" / "shelo_history"
_MAX_HISTORY = 500

# Last /query results — lets the user type a number to execute one
_last_query_results: list[str] = []

# readline is optional — not available on all platforms/environments
try:
    import readline as _readline

    _HAS_READLINE = True
except ImportError:
    _readline = None  # type: ignore[assignment]
    _HAS_READLINE = False


def _autish_cmd() -> list[str]:
    """Return the command list needed to invoke autish."""
    exe = shutil.which("autish")
    if exe:
        return [exe]
    return [sys.executable, "-m", "autish"]


def _setup_readline() -> None:
    """Configure readline history navigation and persistence."""
    if not _HAS_READLINE:
        return
    try:
        _readline.set_history_length(_MAX_HISTORY)
        if _HISTORY_FILE.exists():
            _readline.read_history_file(str(_HISTORY_FILE))
    except Exception:
        pass


def _save_history() -> None:
    """Persist readline history to disk."""
    if not _HAS_READLINE:
        return
    try:
        _HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        _readline.write_history_file(str(_HISTORY_FILE))
    except Exception:
        pass


def _search_history(query: str) -> None:
    """Print the last 5 history entries that contain *query*."""
    global _last_query_results
    if not _HAS_READLINE:
        typer.echo("Historio ne disponebla en ĉi tiu medio.")
        _last_query_results = []
        return
    try:
        found: list[str] = []
        hist_len = _readline.get_current_history_length()
        for i in range(hist_len, 0, -1):
            item = _readline.get_history_item(i)
            if item and query.lower() in item.lower() and not item.startswith("/"):
                found.append(item)
                if len(found) >= 5:
                    break
        if found:
            _last_query_results = found
            typer.echo("Trovita en historio:")
            for j, cmd in enumerate(found, 1):
                typer.echo(f"  {j}) {cmd}")
        else:
            _last_query_results = []
            typer.echo(f"Neniu historio trovita por: {query!r}")
    except Exception:
        _last_query_results = []
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

            # Numeric selection from the last /query results
            if _last_query_results and line.isdigit():
                idx = int(line) - 1
                if 0 <= idx < len(_last_query_results):
                    line = _last_query_results[idx]
                    typer.echo(f"Ekzekutas: {line}")
                else:
                    typer.echo(
                        f"Nevalida elekto: {line!r}  "
                        f"(valida: 1–{len(_last_query_results)})",
                        err=True,
                    )
                    _last_query_results.clear()
                    continue
                _last_query_results.clear()
            else:
                _last_query_results.clear()

            try:
                args = shlex.split(line)
            except ValueError as exc:
                typer.echo(f"Parse error: {exc}", err=True)
                continue

            subprocess.run(prefix + args, check=False)
    finally:
        _save_history()
