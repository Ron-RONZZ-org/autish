"""vorto — personal wordbook microapp (Mia Vorto).

Usage:
    vorto                    — interactive mode (welcome screen)
    vorto aldoni <teksto>    — add an entry
    vorto vidi   <uuid>      — view an entry
    vorto modifi <uuid>      — modify an entry
    vorto serci  [teksto]    — search entries
    vorto forigi <uuid>      — delete an entry
    vorto malfari            — undo the last change (up to 10)

Data is stored in an SQLite database at ~/.local/share/autish/vorto.db.
The undo stack (last 10 operations) is kept in the same database.
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
import uuid as _uuid_mod
from datetime import datetime, timedelta, timezone
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# ──────────────────────────────────────────────────────────────────────────────
# Typer app
# ──────────────────────────────────────────────────────────────────────────────

app = typer.Typer(
    name="vorto",
    help="Mia Vorto — personal wordbook microapp.",
    no_args_is_help=False,
    invoke_without_command=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)

console = Console()

# ──────────────────────────────────────────────────────────────────────────────
# Storage paths
# ──────────────────────────────────────────────────────────────────────────────

_DATA_DIR: Path = Path.home() / ".local" / "share" / "autish"
_DB_FILE: Path = _DATA_DIR / "vorto.db"
_MAX_UNDO: int = 10

# ──────────────────────────────────────────────────────────────────────────────
# SQLite helpers
# ──────────────────────────────────────────────────────────────────────────────

_CREATE_VORTO = """
CREATE TABLE IF NOT EXISTS vorto (
    uuid        TEXT PRIMARY KEY,
    teksto      TEXT NOT NULL,
    lingvo      TEXT,
    kategorio   TEXT,
    tipo        TEXT,
    temo        TEXT,
    tono        TEXT,
    nivelo      REAL,
    difinoj     TEXT NOT NULL DEFAULT '[]',
    etikedoj    TEXT NOT NULL DEFAULT '{}',
    ligiloj     TEXT NOT NULL DEFAULT '[]',
    kreita_je   TEXT NOT NULL,
    modifita_je TEXT NOT NULL
);
"""

_CREATE_RUBUJO = """
CREATE TABLE IF NOT EXISTS rubujo (
    uuid        TEXT PRIMARY KEY,
    teksto      TEXT NOT NULL,
    lingvo      TEXT,
    kategorio   TEXT,
    tipo        TEXT,
    temo        TEXT,
    tono        TEXT,
    nivelo      REAL,
    difinoj     TEXT NOT NULL DEFAULT '[]',
    etikedoj    TEXT NOT NULL DEFAULT '{}',
    ligiloj     TEXT NOT NULL DEFAULT '[]',
    kreita_je   TEXT NOT NULL,
    modifita_je TEXT NOT NULL,
    forigita_je TEXT NOT NULL
);
"""

_CREATE_UNDO = """
CREATE TABLE IF NOT EXISTS undo_stack (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    operation TEXT NOT NULL
);
"""


def _get_db() -> sqlite3.Connection:
    """Open (and initialise) the SQLite database, returning a connection."""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(_DB_FILE), timeout=5.0)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA foreign_keys=ON;")
    con.executescript(_CREATE_VORTO + _CREATE_RUBUJO + _CREATE_UNDO)
    return con


def _row_to_dict(row: sqlite3.Row) -> dict:
    """Convert a *vorto* table row to a plain dict, parsing JSON columns."""
    d = dict(row)
    for col, default in (("difinoj", "[]"), ("etikedoj", "{}"), ("ligiloj", "[]")):
        raw = d.get(col) or default
        try:
            d[col] = json.loads(raw)
        except json.JSONDecodeError:
            d[col] = json.loads(default)
    return d


def _dict_to_params(entry: dict) -> tuple:
    """Return the parameter tuple used for INSERT/UPDATE statements."""
    return (
        entry["uuid"],
        entry["teksto"],
        entry.get("lingvo"),
        entry.get("kategorio"),
        entry.get("tipo"),
        entry.get("temo"),
        entry.get("tono"),
        entry.get("nivelo"),
        json.dumps(entry.get("difinoj") or [], ensure_ascii=False),
        json.dumps(entry.get("etikedoj") or {}, ensure_ascii=False),
        json.dumps(entry.get("ligiloj") or [], ensure_ascii=False),
        entry["kreita_je"],
        entry["modifita_je"],
    )

# ──────────────────────────────────────────────────────────────────────────────
# Lookup tables (Esperanto type/tonality abbreviations)
# ──────────────────────────────────────────────────────────────────────────────

_TIPO_MAP: dict[str, str] = {
    # word subtypes
    "su": "substantivo",
    "substantivo": "substantivo",
    "ve": "verbo",
    "verbo": "verbo",
    "aj": "adjektivo",
    "adjektivo": "adjektivo",
    "av": "adverbo",
    "adverbo": "adverbo",
    # phrase subtypes
    "pa": "parola",
    "parola": "parola",
    "sk": "skriba",
    "skriba": "skriba",
    # sentence subtypes
    "ci": "citaĵo",
    "citaĵo": "citaĵo",
    "ŝe": "ŝerco",
    "ŝerco": "ŝerco",
    "pr": "proverbo",
    "proverbo": "proverbo",
    "po": "poemo",
    "poemo": "poemo",
    "ek": "ekzemplo",
    "ekzemplo": "ekzemplo",
}

_TONO_MAP: dict[str, str] = {
    "in": "informala",
    "informala": "informala",
    "fo": "formala",
    "formala": "formala",
    "am": "ambaŭ",
    "ambaŭ": "ambaŭ",
}

# ──────────────────────────────────────────────────────────────────────────────
# Data I/O  (SQLite-backed; signatures are identical to the old JSON layer so
# that existing tests that mock these functions continue to work unchanged)
# ──────────────────────────────────────────────────────────────────────────────


def _load_entries() -> list[dict]:
    """Return all wordbank entries ordered by creation date (oldest first)."""
    with _get_db() as con:
        rows = con.execute(
            "SELECT * FROM vorto ORDER BY kreita_je ASC"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def _save_entries(entries: list[dict]) -> None:
    """Replace the entire entry table with *entries* in a single transaction.

    This is used exclusively by the undo system which must restore an arbitrary
    prior snapshot.  Normal CRUD operations call the granular helpers below.
    """
    with _get_db() as con:
        con.execute("DELETE FROM vorto")
        con.executemany(
            """
            INSERT INTO vorto
                (uuid, teksto, lingvo, kategorio, tipo, temo, tono,
                 nivelo, difinoj, etikedoj, ligiloj, kreita_je, modifita_je)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [_dict_to_params(e) for e in entries],
        )
        con.commit()


def _load_undo_stack() -> list[dict]:
    """Return the undo stack (oldest operation first, max _MAX_UNDO items)."""
    with _get_db() as con:
        rows = con.execute(
            "SELECT operation FROM undo_stack ORDER BY id ASC"
        ).fetchall()
    return [json.loads(r["operation"]) for r in rows]


def _save_undo_stack(stack: list[dict]) -> None:
    """Persist *stack*, keeping only the last _MAX_UNDO entries."""
    stack = stack[-_MAX_UNDO:]
    with _get_db() as con:
        con.execute("DELETE FROM undo_stack")
        con.executemany(
            "INSERT INTO undo_stack (operation) VALUES (?)",
            [(json.dumps(op, ensure_ascii=False),) for op in stack],
        )
        con.commit()


def _push_undo(operation: dict) -> None:
    stack = _load_undo_stack()
    stack.append(operation)
    if len(stack) > _MAX_UNDO:
        stack = stack[-_MAX_UNDO:]
    _save_undo_stack(stack)


# ──────────────────────────────────────────────────────────────────────────────
# Rubujo (recycle bin) helpers
# ──────────────────────────────────────────────────────────────────────────────

_RUBUJO_INSERT = """
INSERT INTO rubujo
    (uuid, teksto, lingvo, kategorio, tipo, temo, tono, nivelo,
     difinoj, etikedoj, ligiloj, kreita_je, modifita_je, forigita_je)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_RUBUJO_DAYS = 30  # entries older than this are auto-purged


def _move_to_rubujo(entry: dict) -> None:
    """Move *entry* from the vorto table into the rubujo table."""
    forigita_je = _now_iso()
    params = _dict_to_params(entry) + (forigita_je,)
    with _get_db() as con:
        con.execute("DELETE FROM vorto WHERE uuid = ?", (entry["uuid"],))
        con.execute(_RUBUJO_INSERT, params)
        con.commit()


def _load_rubujo() -> list[dict]:
    """Return all rubujo entries ordered by deletion date (most recent first)."""
    with _get_db() as con:
        rows = con.execute(
            "SELECT * FROM rubujo ORDER BY forigita_je DESC"
        ).fetchall()
    result: list[dict] = []
    for r in rows:
        d = _row_to_dict(r)
        d["forigita_je"] = r["forigita_je"]
        result.append(d)
    return result


def _recover_from_rubujo(uuid: str) -> dict | None:
    """Restore an entry from rubujo to vorto; return the entry or None."""
    with _get_db() as con:
        row = con.execute("SELECT * FROM rubujo WHERE uuid = ?", (uuid,)).fetchone()
        if row is None:
            return None
        entry = _row_to_dict(row)
        con.execute("DELETE FROM rubujo WHERE uuid = ?", (uuid,))
        con.execute(
            """
            INSERT OR REPLACE INTO vorto
                (uuid, teksto, lingvo, kategorio, tipo, temo, tono, nivelo,
                 difinoj, etikedoj, ligiloj, kreita_je, modifita_je)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            _dict_to_params(entry),
        )
        con.commit()
    return entry


def _permanent_delete_from_rubujo(uuid: str) -> bool:
    """Permanently delete one entry from rubujo; return True if it existed."""
    with _get_db() as con:
        cur = con.execute("DELETE FROM rubujo WHERE uuid = ?", (uuid,))
        con.commit()
        return cur.rowcount > 0


def _cleanup_old_rubujo() -> int:
    """Delete rubujo entries older than _RUBUJO_DAYS days; return count removed."""
    cutoff_str = (
        datetime.now(tz=timezone.utc) - timedelta(days=_RUBUJO_DAYS)
    ).isoformat(timespec="seconds")
    with _get_db() as con:
        cur = con.execute(
            "DELETE FROM rubujo WHERE forigita_je < ?", (cutoff_str,)
        )
        con.commit()
        return cur.rowcount


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


def _detect_kategorio(teksto: str) -> str:
    """Auto-detect entry category: 'vorto', 'frazo', or 'frazdaro'."""
    words = teksto.strip().split()
    if not words or len(words) == 1:
        return "vorto"
    if re.search(r"[.?!;…]", teksto):
        return "frazdaro"
    return "frazo"


def _normalize_tipo(tipo: str | None) -> str | None:
    if not tipo:
        return None
    return _TIPO_MAP.get(tipo.lower(), tipo)


def _normalize_tono(tono: str | None) -> str | None:
    if not tono:
        return None
    return _TONO_MAP.get(tono.lower(), tono)


def _parse_etikedo(items: list[str] | None) -> dict[str, str]:
    """Parse a list of 'KEY:VALUE' strings into a dict."""
    if not items:
        return {}
    result: dict[str, str] = {}
    for item in items:
        k, _, v = item.partition(":")
        result[k.strip()] = v.strip()
    return result


def _find_entry(uid_or_teksto: str, entries: list[dict]) -> dict | None:
    """Locate an entry by exact UUID, UUID prefix, or case-insensitive exact text."""
    # Exact UUID match
    for e in entries:
        if e["uuid"] == uid_or_teksto:
            return e
    # UUID prefix match
    prefix_matches = [e for e in entries if e["uuid"].startswith(uid_or_teksto)]
    if len(prefix_matches) == 1:
        return prefix_matches[0]
    if len(prefix_matches) > 1:
        typer.echo(
            f"Ambiguous UUID prefix '{uid_or_teksto}' — "
            f"{len(prefix_matches)} entries match. Use a longer prefix.",
            err=True,
        )
        return None
    # Case-insensitive text match
    text_matches = [
        e for e in entries if e["teksto"].lower() == uid_or_teksto.lower()
    ]
    if len(text_matches) == 1:
        return text_matches[0]
    if len(text_matches) > 1:
        typer.echo(
            f"Multiple entries match text '{uid_or_teksto}'. Use UUID instead.",
            err=True,
        )
        return None
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Display helpers
# ──────────────────────────────────────────────────────────────────────────────


def _display_entry(entry: dict) -> None:
    """Render one entry using a Rich panel."""
    uid_short = entry["uuid"][:8]
    lines: list[str] = [
        f"[bold]{entry['teksto']}[/bold]  [dim]#{uid_short}[/dim]",
        "",
    ]

    def _row(label: str, value: str) -> None:
        if value:
            lines.append(f"  [dim]{label:<12}[/dim] {value}")

    _row("lingvo:", entry.get("lingvo") or "")
    kategorio = entry.get("kategorio") or ""
    tipo = entry.get("tipo") or ""
    tipo_str = kategorio + ("/" + tipo if tipo else "")
    _row("tipo:", tipo_str)
    _row("temo:", entry.get("temo") or "")
    _row("tono:", entry.get("tono") or "")
    nivelo = entry.get("nivelo")
    _row("nivelo:", f"{nivelo:.1f}" if nivelo is not None else "")

    difinoj: list[str] = entry.get("difinoj") or []
    if difinoj:
        lines.append(f"  [dim]{'difinoj:':<12}[/dim]")
        for i, d in enumerate(difinoj, 1):
            lines.append(f"    {i}. {d}")

    etikedoj: dict[str, str] = entry.get("etikedoj") or {}
    if etikedoj:
        lines.append(f"  [dim]{'etikedoj:':<12}[/dim]")
        for k, v in etikedoj.items():
            lines.append(f"    {k}: {v}")

    ligiloj: list[str] = entry.get("ligiloj") or []
    if ligiloj:
        _row("ligiloj:", ", ".join(ligiloj))

    lines.append("")
    _row("kreita:", (entry.get("kreita_je") or "")[:19])
    modifita = entry.get("modifita_je") or ""
    kreita = entry.get("kreita_je") or ""
    if modifita and modifita != kreita:
        _row("modifita:", modifita[:19])

    console.print(Panel("\n".join(lines), border_style="dim", expand=False))


def _display_results(entries: list[dict]) -> None:
    """Render a list of entries as a Rich table."""
    if not entries:
        typer.echo("Neniu rezulto trovita. (No results found.)")
        return
    table = Table(
        show_header=True,
        header_style="dim",
        border_style="dim",
        expand=False,
    )
    table.add_column("UUID", style="dim", width=10, no_wrap=True)
    table.add_column("Teksto", min_width=20)
    table.add_column("Lingvo", width=8)
    table.add_column("Tipo", width=18)
    table.add_column("Niv.", width=5)
    table.add_column("Dato", width=12)
    for e in entries:
        uid_short = e["uuid"][:8]
        kategorio = e.get("kategorio") or ""
        tipo = e.get("tipo") or ""
        tipo_str = kategorio + ("/" + tipo if tipo else "")
        date_str = (e.get("kreita_je") or "")[:10]
        nivelo = e.get("nivelo")
        table.add_row(
            uid_short,
            e["teksto"],
            e.get("lingvo") or "",
            tipo_str,
            f"{nivelo:.1f}" if nivelo is not None else "",
            date_str,
        )
    console.print(table)


def _show_diff_confirmation(
    action_label: str, entry: dict, old_entry: dict | None = None
) -> bool:
    """Print a summary of the proposed change and ask for confirmation."""
    _FIELDS = (
        "teksto",
        "lingvo",
        "kategorio",
        "tipo",
        "temo",
        "tono",
        "nivelo",
        "difinoj",
        "etikedoj",
        "ligiloj",
    )
    typer.echo("")
    typer.echo(f"── Konfirmo : {action_label} ──────────────────────────")
    if old_entry:
        for f in _FIELDS:
            old_v = old_entry.get(f)
            new_v = entry.get(f)
            if old_v != new_v:
                typer.echo(f"  {f}: {old_v!r}  →  {new_v!r}")
    else:
        for f in _FIELDS:
            v = entry.get(f)
            if v:
                typer.echo(f"  {f}: {v!r}")
    typer.echo("──────────────────────────────────────────────────────────")
    return typer.confirm("Daŭrigi? (Continue?)", default=True)


# ──────────────────────────────────────────────────────────────────────────────
# Subcommands
# ──────────────────────────────────────────────────────────────────────────────


@app.command("aldoni")
def aldoni(
    teksto: str = typer.Argument(..., help="Word, phrase, or sentence to add."),
    lingvo: str | None = typer.Option(
        None, "-l", "--lingvo", help="2-letter language code (e.g. eo, en)."
    ),
    tipo: str | None = typer.Option(
        None,
        "-t",
        "--tipo",
        help="Subtype: substantivo/su, verbo/ve, adjektivo/aj, adverbo/av, "
        "parola/pa, skriba/sk, citaĵo/ci, ŝerco/ŝe, proverbo/pr, poemo/po, "
        "ekzemplo/ek.",
    ),
    temo: str | None = typer.Option(None, "--temo", help="Theme (free text)."),
    tono: str | None = typer.Option(
        None,
        "--tono",
        help="Tonality: informala/in, formala/fo, ambaŭ/am.",
    ),
    nivelo: float | None = typer.Option(
        None, "-n", "--nivelo", help="Lexical complexity 1–10."
    ),
    difino: list[str] | None = typer.Option(
        None, "-d", "--difino", help="Definition. Repeat flag for multiple."
    ),
    etikedo: list[str] | None = typer.Option(
        None,
        "-e",
        "--etikedo",
        help="Custom tag KEY:VALUE. Repeat flag for multiple.",
    ),
    ligilo: list[str] | None = typer.Option(
        None, "--ligilo", help="Linked entry UUID(s). Repeat flag for multiple."
    ),
) -> None:
    """Add a new word, phrase, or sentence to the wordbank."""
    if nivelo is not None and not (1.0 <= nivelo <= 10.0):
        typer.echo("Error: nivelo must be between 1 and 10.", err=True)
        raise typer.Exit(code=1)

    now = _now_iso()
    entry: dict = {
        "uuid": str(_uuid_mod.uuid4()),
        "teksto": teksto,
        "lingvo": lingvo,
        "kategorio": _detect_kategorio(teksto),
        "tipo": _normalize_tipo(tipo),
        "temo": temo,
        "tono": _normalize_tono(tono),
        "nivelo": nivelo,
        "difinoj": difino or [],
        "etikedoj": _parse_etikedo(etikedo),
        "ligiloj": ligilo or [],
        "kreita_je": now,
        "modifita_je": now,
    }

    if not _show_diff_confirmation("aldoni", entry):
        typer.echo("Nuligita. (Cancelled.)")
        return

    entries = _load_entries()
    entries.append(entry)
    _save_entries(entries)
    _push_undo({"op": "aldoni", "uuid": entry["uuid"]})
    typer.echo(f"Aldonis #{entry['uuid'][:8]}  \"{entry['teksto']}\"")


@app.command("vidi")
def vidi(
    uid: str | None = typer.Argument(
        None,
        help="UUID (or prefix) of the entry to view. Omit to list latest 50.",
    ),
    inverse: bool = typer.Option(
        False, "-i", "--inverse", help="List oldest 50 first (only without UUID)."
    ),
) -> None:
    """View a wordbank entry, or list the latest 50 entries when called
    without argument."""
    entries = _load_entries()
    if uid is None:
        # Show latest (or oldest) 50
        if inverse:
            results = entries[:50]
        else:
            results = list(reversed(entries))[:50]
        typer.echo(f"{len(results)} rezulto(j).")
        _display_results(results)
        return
    entry = _find_entry(uid, entries)
    if entry is None:
        typer.echo(f"Eniro ne trovita: {uid!r}", err=True)
        raise typer.Exit(code=1)
    _display_entry(entry)


@app.command("modifi")
def modifi(
    ctx: typer.Context,
    uid: str = typer.Argument(..., help="UUID (or prefix) of the entry to modify."),
    teksto: str | None = typer.Option(None, "--teksto", help="New text."),
    lingvo: str | None = typer.Option(
        None, "-l", "--lingvo", help="New 2-letter language code."
    ),
    tipo: str | None = typer.Option(None, "-t", "--tipo", help="New subtype."),
    temo: str | None = typer.Option(None, "--temo", help="New theme."),
    tono: str | None = typer.Option(None, "--tono", help="New tonality."),
    nivelo: float | None = typer.Option(
        None, "-n", "--nivelo", help="New lexical complexity 1–10."
    ),
    difino: list[str] | None = typer.Option(
        None, "-d", "--difino", help="New definitions (replaces existing)."
    ),
    etikedo: list[str] | None = typer.Option(
        None, "-e", "--etikedo", help="New tags KEY:VALUE (replaces existing)."
    ),
    ligilo: list[str] | None = typer.Option(
        None, "--ligilo", help="New linked UUIDs (replaces existing)."
    ),
) -> None:
    """Modify a wordbank entry. Pass at least one option to update."""
    opts = (teksto, lingvo, tipo, temo, tono, nivelo, difino, etikedo, ligilo)
    if all(o is None for o in opts):
        typer.echo(ctx.get_help())
        return

    if nivelo is not None and not (1.0 <= nivelo <= 10.0):
        typer.echo("Error: nivelo must be between 1 and 10.", err=True)
        raise typer.Exit(code=1)

    entries = _load_entries()
    entry = _find_entry(uid, entries)
    if entry is None:
        typer.echo(f"Eniro ne trovita: {uid!r}", err=True)
        raise typer.Exit(code=1)

    old_entry = dict(entry)

    if teksto is not None:
        entry["teksto"] = teksto
        entry["kategorio"] = _detect_kategorio(teksto)
    if lingvo is not None:
        entry["lingvo"] = lingvo
    if tipo is not None:
        entry["tipo"] = _normalize_tipo(tipo)
    if temo is not None:
        entry["temo"] = temo
    if tono is not None:
        entry["tono"] = _normalize_tono(tono)
    if nivelo is not None:
        entry["nivelo"] = nivelo
    if difino is not None:
        entry["difinoj"] = difino
    if etikedo is not None:
        entry["etikedoj"] = _parse_etikedo(etikedo)
    if ligilo is not None:
        entry["ligiloj"] = ligilo
    entry["modifita_je"] = _now_iso()

    if not _show_diff_confirmation("modifi", entry, old_entry):
        typer.echo("Nuligita. (Cancelled.)")
        return

    idx = next(i for i, e in enumerate(entries) if e["uuid"] == entry["uuid"])
    entries[idx] = entry
    _save_entries(entries)
    _push_undo({"op": "modifi", "old": old_entry})
    typer.echo(f"Modifis #{entry['uuid'][:8]}  \"{entry['teksto']}\"")


@app.command("serci")
def serci(
    teksto: str | None = typer.Argument(
        None, help="Text to search for (default: show all)."
    ),
    lingvo: str | None = typer.Option(
        None, "-l", "--lingvo", help="Filter by language code."
    ),
    tipo: str | None = typer.Option(None, "-t", "--tipo", help="Filter by subtype."),
    temo: str | None = typer.Option(None, "--temo", help="Filter by theme."),
    tono: str | None = typer.Option(None, "--tono", help="Filter by tonality."),
    nivelo_min: float | None = typer.Option(
        None, "--nivelo-min", help="Minimum lexical level."
    ),
    nivelo_max: float | None = typer.Option(
        None, "--nivelo-max", help="Maximum lexical level."
    ),
    dato_de: str | None = typer.Option(
        None, "--dato-de", help="Start date YYYY-MM-DD."
    ),
    dato_gis: str | None = typer.Option(
        None, "--dato-gis", help="End date YYYY-MM-DD."
    ),
    regex: bool = typer.Option(
        False, "-r", "--regex", help="Interpret teksto as a POSIX regex."
    ),
    limo: int = typer.Option(50, "--limo", help="Max number of results (default 50)."),
    ordo: str = typer.Option(
        "graveco",
        "-o",
        "--ordo",
        help="Order: graveco/g (relevance), dato/d (newest), inversa-dato/id (oldest).",
    ),
) -> None:
    """Search the wordbank. No filters → list all entries up to --limo."""
    entries = _load_entries()
    results = list(entries)

    # Text filter
    if teksto:
        if regex:
            try:
                pattern = re.compile(teksto, re.IGNORECASE)
            except re.error as exc:
                typer.echo(f"Invalid regex: {exc}", err=True)
                raise typer.Exit(code=1) from exc
            results = [e for e in results if pattern.search(e["teksto"])]
        else:
            low = teksto.lower()
            results = [e for e in results if low in e["teksto"].lower()]

    # Property filters
    if lingvo:
        results = [e for e in results if e.get("lingvo") == lingvo]
    if tipo:
        norm = _normalize_tipo(tipo)
        results = [
            e
            for e in results
            if e.get("tipo") == norm or e.get("kategorio") == norm
        ]
    if temo:
        low_temo = temo.lower()
        results = [e for e in results if low_temo in (e.get("temo") or "").lower()]
    if tono:
        norm_tono = _normalize_tono(tono)
        results = [e for e in results if e.get("tono") == norm_tono]
    if nivelo_min is not None:
        results = [e for e in results if (e.get("nivelo") or 0) >= nivelo_min]
    if nivelo_max is not None:
        results = [e for e in results if (e.get("nivelo") or 0) <= nivelo_max]
    if dato_de:
        results = [e for e in results if (e.get("kreita_je") or "") >= dato_de]
    if dato_gis:
        end = dato_gis + "T23:59:59"
        results = [e for e in results if (e.get("kreita_je") or "") <= end]

    # Sorting
    norm_ordo = ordo.lower()
    if norm_ordo in ("dato", "d"):
        results.sort(key=lambda e: e.get("kreita_je") or "", reverse=True)
    elif norm_ordo in ("inversa-dato", "id"):
        results.sort(key=lambda e: e.get("kreita_je") or "")

    # Limit
    if limo > 0:
        results = results[:limo]

    typer.echo(f"{len(results)} rezulto(j) trovita(j).")
    _display_results(results)


@app.command("forigi")
def forigi(
    uid_or_teksto: str = typer.Argument(
        ..., help="UUID (or prefix) or exact text of the entry to delete."
    ),
) -> None:
    """Move a wordbank entry to the recycle bin (with confirmation).

    Entries in the recycle bin are permanently deleted after 30 days.
    Use  vorto rubujo reakiri <uuid>  to restore.
    """
    entries = _load_entries()
    entry = _find_entry(uid_or_teksto, entries)
    if entry is None:
        typer.echo(f"Eniro ne trovita: {uid_or_teksto!r}", err=True)
        raise typer.Exit(code=1)

    if not _show_diff_confirmation("forigi (→ rubujo)", entry):
        typer.echo("Nuligita. (Cancelled.)")
        return

    _move_to_rubujo(entry)
    _push_undo({"op": "forigi", "uuid": entry["uuid"]})
    typer.echo(
        f"Sendis al rubujo: #{entry['uuid'][:8]}  \"{entry['teksto']}\""
        f"  (aŭtomate forigita post {_RUBUJO_DAYS} tagoj)"
    )


@app.command("malfari")
def malfari() -> None:
    """Undo the last wordbank change (stackable up to 10 operations)."""
    stack = _load_undo_stack()
    if not stack:
        typer.echo("Nenio por malfari. (Nothing to undo.)")
        return

    op = stack.pop()
    entries = _load_entries()

    if op["op"] == "aldoni":
        uid = op["uuid"]
        entries = [e for e in entries if e["uuid"] != uid]
        _save_entries(entries)
        typer.echo(f"Malfaris aldoni — forigis #{uid[:8]}.")
    elif op["op"] == "modifi":
        old = op["old"]
        idx = next(
            (i for i, e in enumerate(entries) if e["uuid"] == old["uuid"]), None
        )
        if idx is not None:
            entries[idx] = old
        _save_entries(entries)
        typer.echo(f"Malfaris modifi — restaŭris #{old['uuid'][:8]}.")
    elif op["op"] == "forigi":
        uuid = op.get("uuid") or (op.get("entry") or {}).get("uuid")
        if uuid:
            recovered = _recover_from_rubujo(uuid)
            if recovered:
                typer.echo(
                    f"Malfaris forigi — restaŭris "
                    f"#{uuid[:8]}  \"{recovered['teksto']}\"."
                )
            else:
                # Fallback: old format stored the full entry
                old = op.get("entry")
                if old:
                    entries.append(old)
                    _save_entries(entries)
                    typer.echo(
                        f"Malfaris forigi — restaŭris "
                        f"#{old['uuid'][:8]}  \"{old['teksto']}\"."
                    )
                else:
                    typer.echo(
                        "Ne povis restaŭri: eniro ne trovita en rubujo.",
                        err=True,
                    )
        else:
            typer.echo(
                "Ne povis restaŭri: malvalida malfar-operacio.", err=True
            )

    _save_undo_stack(stack)


# ──────────────────────────────────────────────────────────────────────────────
# Interactive mode — full-screen curses TUI
# ──────────────────────────────────────────────────────────────────────────────


def _entry_to_lines(entry: dict) -> list[str]:
    """Convert an entry dict to a list of plain-text lines for the pager."""
    uid_short = entry["uuid"][:8]
    lines: list[str] = [
        f"{entry['teksto']}  #{uid_short}",
        "",
    ]

    def _row(label: str, value: str) -> None:
        if value:
            lines.append(f"  {label:<14}{value}")

    _row("lingvo:", entry.get("lingvo") or "")
    kategorio = entry.get("kategorio") or ""
    tipo = entry.get("tipo") or ""
    tipo_str = kategorio + ("/" + tipo if tipo else "")
    _row("tipo:", tipo_str)
    _row("temo:", entry.get("temo") or "")
    _row("tono:", entry.get("tono") or "")
    nivelo = entry.get("nivelo")
    _row("nivelo:", f"{nivelo:.1f}" if nivelo is not None else "")

    difinoj: list[str] = entry.get("difinoj") or []
    if difinoj:
        lines.append(f"  {'difinoj:':<14}")
        for i, d in enumerate(difinoj, 1):
            lines.append(f"    {i}. {d}")

    etikedoj: dict[str, str] = entry.get("etikedoj") or {}
    if etikedoj:
        lines.append(f"  {'etikedoj:':<14}")
        for k, v in etikedoj.items():
            lines.append(f"    {k}: {v}")

    ligiloj: list[str] = entry.get("ligiloj") or []
    if ligiloj:
        _row("ligiloj:", ", ".join(ligiloj))

    lines.append("")
    _row("kreita:", (entry.get("kreita_je") or "")[:19])
    modifita = entry.get("modifita_je") or ""
    kreita = entry.get("kreita_je") or ""
    if modifita and modifita != kreita:
        _row("modifita:", modifita[:19])

    return lines


def _entries_to_lines(entries: list[dict]) -> list[str]:
    """Convert a list of entries to pager-ready plain-text lines."""
    if not entries:
        return ["Neniu rezulto trovita. (No results found.)"]
    col_uuid = 10
    col_teksto = 28
    col_lingvo = 8
    col_tipo = 18
    col_niv = 5
    col_dato = 12
    header = (
        f"{'UUID':<{col_uuid}} {'Teksto':<{col_teksto}} "
        f"{'Lingvo':<{col_lingvo}} {'Tipo':<{col_tipo}} "
        f"{'Niv.':<{col_niv}} {'Dato':<{col_dato}}"
    )
    sep = "─" * len(header)
    lines = [header, sep]
    for e in entries:
        uid_short = e["uuid"][:col_uuid]
        kategorio = e.get("kategorio") or ""
        tipo = e.get("tipo") or ""
        tipo_str = (kategorio + ("/" + tipo if tipo else ""))[:col_tipo]
        date_str = (e.get("kreita_je") or "")[:10]
        nivelo = e.get("nivelo")
        niv_str = f"{nivelo:.1f}" if nivelo is not None else ""
        teksto = e["teksto"][:col_teksto]
        lines.append(
            f"{uid_short:<{col_uuid}} {teksto:<{col_teksto}} "
            f"{(e.get('lingvo') or ''):<{col_lingvo}} {tipo_str:<{col_tipo}} "
            f"{niv_str:<{col_niv}} {date_str:<{col_dato}}"
        )
    return lines


def _undo_action() -> str:
    """Run undo and return a status string."""
    stack = _load_undo_stack()
    if not stack:
        return "Nenio por malfari. (Nothing to undo.)"

    op = stack.pop()
    entries = _load_entries()

    if op["op"] == "aldoni":
        uid = op["uuid"]
        entries = [e for e in entries if e["uuid"] != uid]
        _save_entries(entries)
        msg = f"Malfaris aldoni — forigis #{uid[:8]}."
    elif op["op"] == "modifi":
        old = op["old"]
        idx = next(
            (i for i, e in enumerate(entries) if e["uuid"] == old["uuid"]), None
        )
        if idx is not None:
            entries[idx] = old
        _save_entries(entries)
        msg = f"Malfaris modifi — restaŭris #{old['uuid'][:8]}."
    elif op["op"] == "forigi":
        uuid = op.get("uuid") or (op.get("entry") or {}).get("uuid")
        if uuid:
            recovered = _recover_from_rubujo(uuid)
            if recovered:
                msg = (
                    f"Malfaris forigi — restaŭris "
                    f"#{uuid[:8]}  \"{recovered['teksto']}\"."
                )
            else:
                old = op.get("entry")
                if old:
                    entries.append(old)
                    _save_entries(entries)
                    msg = (
                        f"Malfaris forigi — restaŭris "
                        f"#{old['uuid'][:8]}  \"{old['teksto']}\"."
                    )
                else:
                    msg = "Ne povis restaŭri: eniro ne trovita en rubujo."
        else:
            msg = "Ne povis restaŭri: malvalida malfar-operacio."
    else:
        msg = "Nekonata operacio."

    _save_undo_stack(stack)
    return msg


def _tui_save_new(entry: dict) -> None:
    all_entries = _load_entries()
    all_entries.append(entry)
    _save_entries(all_entries)
    _push_undo({"op": "aldoni", "uuid": entry["uuid"]})


def _tui_save_modified(entry: dict, old_entry: dict) -> None:
    all_entries = _load_entries()
    idx = next(
        (i for i, e in enumerate(all_entries) if e["uuid"] == entry["uuid"]), None
    )
    if idx is not None:
        all_entries[idx] = entry
    _save_entries(all_entries)
    _push_undo({"op": "modifi", "old": old_entry})


def _tui_delete(entry: dict) -> None:
    _move_to_rubujo(entry)
    _push_undo({"op": "forigi", "uuid": entry["uuid"]})


def _rubujo_entries_to_lines(entries: list[dict]) -> list[str]:
    """Convert a list of rubujo entries to pager-ready plain-text lines."""
    if not entries:
        return ["Rubujo estas malplena. (Recycle bin is empty.)"]
    col_uuid = 10
    col_teksto = 28
    col_lingvo = 8
    col_tipo = 18
    col_dato = 14
    header = (
        f"{'UUID':<{col_uuid}} {'Teksto':<{col_teksto}} "
        f"{'Lingvo':<{col_lingvo}} {'Tipo':<{col_tipo}} "
        f"{'Forigita':<{col_dato}}"
    )
    sep = "─" * len(header)
    lines = [header, sep]
    for e in entries:
        uid_short = e["uuid"][:col_uuid]
        kategorio = e.get("kategorio") or ""
        tipo = e.get("tipo") or ""
        tipo_str = (kategorio + ("/" + tipo if tipo else ""))[:col_tipo]
        forigita = (e.get("forigita_je") or "")[:13]
        teksto = e["teksto"][:col_teksto]
        lines.append(
            f"{uid_short:<{col_uuid}} {teksto:<{col_teksto}} "
            f"{(e.get('lingvo') or ''):<{col_lingvo}} {tipo_str:<{col_tipo}} "
            f"{forigita:<{col_dato}}"
        )
    return lines


# ──────────────────────────────────────────────────────────────────────────────
# rubujo subcommands
# ──────────────────────────────────────────────────────────────────────────────

rubujo_app = typer.Typer(
    name="rubujo",
    help="Recycle bin — view, recover, or permanently delete trashed entries.",
    no_args_is_help=False,
)
app.add_typer(rubujo_app)


@rubujo_app.callback(invoke_without_command=True)
def rubujo_callback(ctx: typer.Context) -> None:
    """List entries in the recycle bin when called without a subcommand."""
    if ctx.invoked_subcommand is not None:
        return
    # Auto-purge stale entries first
    purged = _cleanup_old_rubujo()
    entries = _load_rubujo()
    if purged:
        typer.echo(f"Aŭtomate forigis {purged} maljunaj eniro(j) (>{_RUBUJO_DAYS}d).")
    typer.echo(f"{len(entries)} eniro(j) en rubujo.")
    if not entries:
        return
    table = Table(
        show_header=True,
        header_style="dim",
        border_style="dim",
        expand=False,
    )
    table.add_column("UUID", style="dim", width=10, no_wrap=True)
    table.add_column("Teksto", min_width=20)
    table.add_column("Lingvo", width=8)
    table.add_column("Tipo", width=18)
    table.add_column("Forigita", width=13)
    for e in entries:
        uid_short = e["uuid"][:8]
        kategorio = e.get("kategorio") or ""
        tipo = e.get("tipo") or ""
        tipo_str = kategorio + ("/" + tipo if tipo else "")
        forigita = (e.get("forigita_je") or "")[:10]
        table.add_row(
            uid_short,
            e["teksto"],
            e.get("lingvo") or "",
            tipo_str,
            forigita,
        )
    console.print(table)


@rubujo_app.command("reakiri")
def rubujo_reakiri(
    uid: str = typer.Argument(..., help="UUID (or prefix) of the entry to recover."),
) -> None:
    """Restore an entry from the recycle bin back to the wordbank."""
    entries = _load_rubujo()
    # Try prefix match
    matches = [e for e in entries if e["uuid"].startswith(uid)]
    if not matches:
        typer.echo(f"Ne trovita en rubujo: {uid!r}", err=True)
        raise typer.Exit(code=1)
    if len(matches) > 1:
        typer.echo(
            f"Ambigua UUID prefikso '{uid}' — {len(matches)} enirojn matĉas.", err=True
        )
        raise typer.Exit(code=1)
    uuid = matches[0]["uuid"]
    recovered = _recover_from_rubujo(uuid)
    if recovered:
        typer.echo(f"Reakivis #{uuid[:8]}  \"{recovered['teksto']}\"")
    else:
        typer.echo(f"Ne povis reakiri: {uid!r}", err=True)
        raise typer.Exit(code=1)


@rubujo_app.command("forigi")
def rubujo_forigi(
    uid: str = typer.Argument(
        ..., help="UUID (or prefix) of the entry to permanently delete."
    ),
    justa: bool = typer.Option(
        False, "-j", "--justa", help="Skip confirmation prompt."
    ),
) -> None:
    """Permanently delete one entry from the recycle bin."""
    entries = _load_rubujo()
    matches = [e for e in entries if e["uuid"].startswith(uid)]
    if not matches:
        typer.echo(f"Ne trovita en rubujo: {uid!r}", err=True)
        raise typer.Exit(code=1)
    if len(matches) > 1:
        typer.echo(
            f"Ambigua UUID prefikso '{uid}' — {len(matches)} enirojn matĉas.", err=True
        )
        raise typer.Exit(code=1)
    entry = matches[0]
    if not justa:
        typer.echo(
            f"Ĉu definitive forigi #{entry['uuid'][:8]}  \"{entry['teksto']}\"? (y/N)"
        )
        ans = typer.prompt("", default="N")
        if ans.lower() not in ("y", "j"):
            typer.echo("Nuligita.")
            return
    ok = _permanent_delete_from_rubujo(entry["uuid"])
    if ok:
        typer.echo(f"Definitive forigis #{entry['uuid'][:8]}  \"{entry['teksto']}\"")
    else:
        typer.echo("Ne povis forigi.", err=True)
        raise typer.Exit(code=1)


@rubujo_app.command("vakigi")
def rubujo_vakigi(
    justa: bool = typer.Option(
        False, "-j", "--justa", help="Skip confirmation prompt."
    ),
) -> None:
    """Permanently delete ALL entries in the recycle bin."""
    entries = _load_rubujo()
    if not entries:
        typer.echo("Rubujo estas malplena.")
        return
    if not justa:
        typer.echo(f"Ĉu definitive forigi ĈIUJN {len(entries)} eniro(j)n? (y/N)")
        ans = typer.prompt("", default="N")
        if ans.lower() not in ("y", "j"):
            typer.echo("Nuligita.")
            return
    with _get_db() as con:
        con.execute("DELETE FROM rubujo")
        con.commit()
    typer.echo(f"Vakigis rubujon: forigis {len(entries)} eniro(j)n.")


# ──────────────────────────────────────────────────────────────────────────────
# Interactive mode — full-screen curses TUI
# ──────────────────────────────────────────────────────────────────────────────


def _interactive_mode() -> None:
    """Launch the Mia Vorto full-screen TUI (requires a TTY)."""
    if not sys.stdin.isatty():
        typer.echo(
            "Interactive mode requires a terminal. Use subcommands directly.",
            err=True,
        )
        raise typer.Exit(code=1)

    from autish.commands._vorto_tui import VortoTUI  # noqa: PLC0415

    # Auto-purge old rubujo entries on startup
    _cleanup_old_rubujo()

    tui = VortoTUI(
        load_entries=_load_entries,
        save_new_entry=_tui_save_new,
        save_modified_entry=_tui_save_modified,
        delete_entry=_tui_delete,
        undo=_undo_action,
        render_entry=_entry_to_lines,
        render_results=_entries_to_lines,
        detect_kategorio=_detect_kategorio,
        normalize_tipo=_normalize_tipo,
        normalize_tono=_normalize_tono,
        parse_etikedo=_parse_etikedo,
        find_entry=_find_entry,
        now_iso=_now_iso,
        make_uuid=lambda: str(_uuid_mod.uuid4()),
        load_rubujo=_load_rubujo,
        render_rubujo_results=_rubujo_entries_to_lines,
        recover_from_rubujo=_recover_from_rubujo,
        permanent_delete_from_rubujo=_permanent_delete_from_rubujo,
    )
    tui.run()


# ──────────────────────────────────────────────────────────────────────────────
# App callback — interactive mode when invoked with no subcommand
# ──────────────────────────────────────────────────────────────────────────────


@app.callback(invoke_without_command=True)
def vorto_callback(ctx: typer.Context) -> None:
    """Mia Vorto — personal wordbook. Run without a subcommand for interactive mode."""
    if ctx.invoked_subcommand is not None:
        return
    _interactive_mode()
