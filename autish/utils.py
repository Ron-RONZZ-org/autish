"""Shared utilities for autish commands."""

from __future__ import annotations

import typer

_SEP = "---"


def echo_padded(content: str) -> None:
    """Print *content* wrapped in --- separators with surrounding blank lines."""
    typer.echo("")
    typer.echo(_SEP)
    typer.echo(content)
    typer.echo(_SEP)
    typer.echo("")
