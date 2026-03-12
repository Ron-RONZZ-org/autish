"""tempo — print current local time and day of week.

Usage:
    autish tempo
    autish tempo --horzono 9
    autish tempo --horzono        # prints all UTC offsets
"""

from __future__ import annotations

import datetime
import locale

import typer

app = typer.Typer(
    help="Print current local time and day of week.",
    invoke_without_command=True,
)

_UTC_MIN = -12
_UTC_MAX = 14


def _time_for_offset(offset: int) -> datetime.datetime:
    tz = datetime.timezone(datetime.timedelta(hours=offset))
    return datetime.datetime.now(tz=tz)


def _day_name(dt: datetime.datetime) -> str:
    """Return the localised day-of-week name using the system locale."""
    try:
        locale.setlocale(locale.LC_TIME, "")
    except locale.Error:
        pass
    return dt.strftime("%A")


def _print_time(dt: datetime.datetime, *, show_offset: bool = False) -> None:
    utcoff = dt.utcoffset()
    if show_offset and utcoff is not None:
        prefix = f"UTC{utcoff.total_seconds() / 3600:+g}  "
    else:
        prefix = ""
    typer.echo(f"{prefix}{dt.isoformat(timespec='seconds')}")
    if not show_offset:
        typer.echo(_day_name(dt))


@app.callback(invoke_without_command=True)
def tempo(
    ctx: typer.Context,
    horzono: str | None = typer.Option(
        None,
        "--horzono",
        "-z",
        help=(
            "UTC timezone offset (-12 to +14). "
            "Omit the value entirely to print all offsets."
        ),
        is_eager=False,
    ),
) -> None:
    """Print current local time (ISO 8601) and day of week."""
    if ctx.invoked_subcommand is not None:
        return

    # Flag given with no value: horzono == "" (empty string from CLI)
    # Flag not given at all: horzono is None
    if horzono is None:
        # No flag — print local system time
        now = datetime.datetime.now(tz=datetime.timezone.utc).astimezone()
        _print_time(now)
        return

    if horzono == "":
        # Flag present but no value — print all offsets
        for offset in range(_UTC_MIN, _UTC_MAX + 1):
            _print_time(_time_for_offset(offset), show_offset=True)
        return

    # Flag with a value — validate and display that offset
    try:
        offset = int(horzono)
    except ValueError:
        typer.echo(
            f"Error: horzono must be an integer between {_UTC_MIN} and {_UTC_MAX}.",
            err=True,
        )
        raise typer.Exit(code=1) from None

    if not (_UTC_MIN <= offset <= _UTC_MAX):
        typer.echo(
            f"Error: horzono {offset} is out of range ({_UTC_MIN}…{_UTC_MAX}).",
            err=True,
        )
        raise typer.Exit(code=1)

    _print_time(_time_for_offset(offset))
