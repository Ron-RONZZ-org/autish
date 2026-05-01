"""Shared Console instance for autish commands.

Provides a centralized Console singleton to reduce object churn
and standardize styling across commands.

Usage:
    from autish.console import console
    console.print("Hello")
"""

from __future__ import annotations

from rich.console import Console

# Module-level singleton - created on first import
console = Console(
    theme=None,  # Use default theme
    force_terminal=None,  # Let Rich detect
    markup=True,
    emoji=True,  # Allow emoji in output
    safe_box=True,
)


def get_console() -> Console:
    """Return the shared Console instance.

    For cases where you need a fresh Console with different options.
    """
    return console