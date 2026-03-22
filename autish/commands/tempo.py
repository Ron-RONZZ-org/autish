"""tempo — print current local time and day of week.

Usage:
    autish tempo
    autish tempo --horzono 9
    autish tempo -z              # prints all UTC offsets
"""

from __future__ import annotations

import datetime
import locale

import typer

from autish.utils import echo_padded

app = typer.Typer(
    help="Print current local time and day of week.",
    invoke_without_command=True,
    context_settings={"help_option_names": ["-h", "--help", "--helpo"]},
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


@app.callback(invoke_without_command=True)
def tempo(
    ctx: typer.Context,
    horzono: int | None = typer.Option(
        None,
        "--horzono",
        help="UTC timezone offset (-12 to +14) to display time for.",
    ),
    chiuj: bool = typer.Option(
        False,
        "-z",
        "--chiuj-horzonoj",
        help="Print current time for all UTC offsets (-12 to +14).",
    ),
) -> None:
    """Print current local time (ISO 8601) and day of week."""
    if ctx.invoked_subcommand is not None:
        return

    if chiuj:
        # -z flag: print all UTC offsets
        lines = []
        for offset in range(_UTC_MIN, _UTC_MAX + 1):
            dt = _time_for_offset(offset)
            utcoff = dt.utcoffset()
            prefix = (
                f"UTC{utcoff.total_seconds() / 3600:+g}  "
                if utcoff is not None
                else ""
            )
            lines.append(f"{prefix}{dt.isoformat(timespec='seconds')}")
        echo_padded("\n".join(lines))
        return

    if horzono is not None:
        # Specific UTC offset
        if not (_UTC_MIN <= horzono <= _UTC_MAX):
            typer.echo(
                f"Error: horzono {horzono} is out of range ({_UTC_MIN}…{_UTC_MAX}).",
                err=True,
            )
            raise typer.Exit(code=1)
        dt = _time_for_offset(horzono)
        echo_padded(f"{dt.isoformat(timespec='seconds')}\n{_day_name(dt)}")
        return

    # Default — print local system time
    now = datetime.datetime.now(tz=datetime.timezone.utc).astimezone()
    echo_padded(f"{now.isoformat(timespec='seconds')}\n{_day_name(now)}")
