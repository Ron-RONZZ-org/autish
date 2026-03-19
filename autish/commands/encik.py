"""encik — personal knowledge management microapp.

Usage:
    encik                       — interactive welcome screen
    encik aldoni <file.enc>     — add a new knowledge node from an .enc file
    encik modifi <title|UUID>   — edit an existing node in $EDITOR as a temp .enc file
    encik serci                 — search nodes (see flags below)
      -t/--titolo <partial>     — fuzzy title search (max 5 candidates)
      -s/--subklasoj <term>     — recursive subclass search
      -S/--superklasoj <term>   — recursive superclass search
      -p/--paralela             — sister-class search (same parent)
      -L/--limo <int>           — depth limit for -s/-S (default 5),
                                  max results for -p (default 100)

Data is stored in an SQLite database at ~/.local/share/autish/encik.db.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import uuid as _uuid_mod
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib  # type: ignore[no-redef]
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef, assignment]

try:
    import tomli_w as _tomli_w
except ImportError:
    _tomli_w = None  # type: ignore[assignment]

# ──────────────────────────────────────────────────────────────────────────────
# Typer app
# ──────────────────────────────────────────────────────────────────────────────

app = typer.Typer(
    name="encik",
    help="Encik — personal knowledge management microapp.",
    no_args_is_help=False,
    invoke_without_command=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)

console = Console()

# ──────────────────────────────────────────────────────────────────────────────
# Storage paths
# ──────────────────────────────────────────────────────────────────────────────

_DATA_DIR: Path = Path.home() / ".local" / "share" / "autish"
_DB_FILE: Path = _DATA_DIR / "encik.db"

# ──────────────────────────────────────────────────────────────────────────────
# DB schema
# ──────────────────────────────────────────────────────────────────────────────

_CREATE_ENCIK = """
CREATE TABLE IF NOT EXISTS encik (
    uuid        TEXT PRIMARY KEY,
    titolo      TEXT NOT NULL,
    definio     TEXT NOT NULL DEFAULT '',
    superklaso  TEXT NOT NULL DEFAULT '[]',
    ligilo      TEXT NOT NULL DEFAULT '[]',
    source      TEXT NOT NULL DEFAULT '[]',
    kreita_je   TEXT NOT NULL,
    modifita_je TEXT NOT NULL
);
"""

# ──────────────────────────────────────────────────────────────────────────────
# DB helpers
# ──────────────────────────────────────────────────────────────────────────────


def _init_db() -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_FILE)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(_CREATE_ENCIK)
        conn.commit()
    finally:
        conn.close()


def _get_conn() -> sqlite3.Connection:
    _init_db()
    conn = sqlite3.connect(_DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    for field in ("superklaso", "ligilo", "source"):
        if isinstance(d.get(field), str):
            d[field] = json.loads(d[field])
    return d


def _load_all() -> list[dict]:
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM encik ORDER BY titolo COLLATE NOCASE"
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def _find_by_uuid(uid: str) -> dict | None:
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM encik WHERE uuid = ? OR uuid LIKE ?",
            (uid, f"{uid}%"),
        ).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def _find_by_title_exact(titolo: str) -> dict | None:
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM encik WHERE titolo = ? COLLATE NOCASE",
            (titolo,),
        ).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def _fuzzy_title_matches(partial: str, max_results: int = 5) -> list[dict]:
    """Return up to *max_results* entries whose title contains *partial*
    (case-insensitive), ordered by how early the match appears."""
    all_entries = _load_all()
    lower = partial.lower()
    matches = [e for e in all_entries if lower in e["titolo"].lower()]
    # Sort by position of match (earlier = better)
    matches.sort(key=lambda e: e["titolo"].lower().find(lower))
    return matches[:max_results]


def _insert_entry(entry: dict) -> None:
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO encik"
            " (uuid, titolo, definio, superklaso, ligilo, source,"
            " kreita_je, modifita_je)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                entry["uuid"],
                entry["titolo"],
                entry.get("definio", ""),
                json.dumps(entry.get("superklaso", []), ensure_ascii=False),
                json.dumps(entry.get("ligilo", []), ensure_ascii=False),
                json.dumps(entry.get("source", []), ensure_ascii=False),
                entry["kreita_je"],
                entry["modifita_je"],
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _update_entry(entry: dict) -> None:
    conn = _get_conn()
    try:
        conn.execute(
            """UPDATE encik SET
               titolo=?, definio=?, superklaso=?, ligilo=?, source=?, modifita_je=?
               WHERE uuid=?""",
            (
                entry["titolo"],
                entry.get("definio", ""),
                json.dumps(entry.get("superklaso", []), ensure_ascii=False),
                json.dumps(entry.get("ligilo", []), ensure_ascii=False),
                json.dumps(entry.get("source", []), ensure_ascii=False),
                entry["modifita_je"],
                entry["uuid"],
            ),
        )
        conn.commit()
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# .enc file format helpers
# ──────────────────────────────────────────────────────────────────────────────

_ENC_TEMPLATE = """\
# {titolo}

definio = \"\"\"
{definio}
\"\"\"

# Parent classes: list of ["Term Title", "uuid"] pairs
superklaso = {superklaso}

# Linked concepts: list of ["Term Title", "uuid"] pairs
ligilo = {ligilo}

# Sources: list of {{title = "", author = "", year = "", type = ""}} tables
source = {source}
"""


def _entry_to_enc(entry: dict) -> str:
    """Serialise an encik entry to .enc text."""
    superklaso = entry.get("superklaso") or []
    ligilo = entry.get("ligilo") or []
    source = entry.get("source") or []

    def _toml_list(lst: list) -> str:
        """Format a Python list as a TOML array (compact JSON-style)."""
        if not lst:
            return "[]"
        return json.dumps(lst, ensure_ascii=False)

    def _source_list(lst: list) -> str:
        if not lst:
            return "[]"
        parts = []
        for s in lst:
            items = ", ".join(
                f'{k} = {json.dumps(v)}' for k, v in s.items() if v
            )
            parts.append(f"{{{items}}}")
        return "[" + ", ".join(parts) + "]"

    return _ENC_TEMPLATE.format(
        titolo=entry.get("titolo", ""),
        definio=entry.get("definio", ""),
        superklaso=_toml_list(superklaso),
        ligilo=_toml_list(ligilo),
        source=_source_list(source),
    )


def _parse_enc_file(path: Path) -> dict:
    """Parse an .enc file and return a dict with the entry fields.

    The .enc format is TOML with an optional leading comment ``# title``.
    If the TOML itself contains a ``titolo`` key that takes precedence;
    otherwise the first ``# …`` comment is used as the title.
    """
    raw = path.read_text(encoding="utf-8")

    # Extract title from the first non-empty comment line
    title_from_comment = ""
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") and not stripped.startswith("##"):
            candidate = stripped.lstrip("#").strip()
            if candidate:
                title_from_comment = candidate
                break

    # Parse the TOML part (comments are automatically ignored)
    try:
        data = tomllib.loads(raw)
    except Exception as exc:
        raise ValueError(f"Malformed .enc file: {exc}") from exc

    titolo = data.get("titolo") or title_from_comment
    if not titolo:
        raise ValueError(
            "No title found in .enc file"
            " (add '# Title' or 'titolo = \"…\"')"
        )

    definio = data.get("definio", "").strip()

    # superklaso / ligilo: list of [title, uuid] pairs
    superklaso = _normalise_pairs(data.get("superklaso", []))
    ligilo = _normalise_pairs(data.get("ligilo", []))

    # source: list of dicts
    source: list[dict] = []
    for item in data.get("source", []):
        if isinstance(item, dict):
            source.append({k: str(v) for k, v in item.items()})

    return {
        "titolo": titolo,
        "definio": definio,
        "superklaso": superklaso,
        "ligilo": ligilo,
        "source": source,
    }


def _normalise_pairs(raw: list) -> list[list[str]]:
    """Normalise superklaso/ligilo values to a list of [title, uuid] pairs."""
    result: list[list[str]] = []
    for item in raw:
        if isinstance(item, list) and len(item) == 2:
            result.append([str(item[0]), str(item[1])])
        elif isinstance(item, dict):
            title = str(item.get("titolo") or item.get("title") or "")
            uid = str(item.get("uuid") or "")
            result.append([title, uid])
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Display helpers
# ──────────────────────────────────────────────────────────────────────────────


def _display_entry(entry: dict) -> None:
    uid_short = entry["uuid"][:8]
    title = entry["titolo"]
    panel_lines: list[str] = []
    panel_lines.append(f"  [dim]{'uuid:':<14}[/dim] {uid_short}")

    definio = entry.get("definio", "").strip()
    if definio:
        panel_lines.append(f"  [dim]{'definio:':<14}[/dim]")
        for ln in definio.splitlines():
            panel_lines.append(f"    {ln}")

    superklaso = entry.get("superklaso") or []
    if superklaso:
        panel_lines.append(f"  [dim]{'superklaso:':<14}[/dim]")
        for pair in superklaso:
            lbl = pair[0] if pair else "?"
            uid2 = pair[1][:8] if len(pair) > 1 and pair[1] else ""
            panel_lines.append(f"    {lbl}  [dim]#{uid2}[/dim]")

    ligilo = entry.get("ligilo") or []
    if ligilo:
        panel_lines.append(f"  [dim]{'ligilo:':<14}[/dim]")
        for pair in ligilo:
            lbl = pair[0] if pair else "?"
            uid2 = pair[1][:8] if len(pair) > 1 and pair[1] else ""
            panel_lines.append(f"    {lbl}  [dim]#{uid2}[/dim]")

    source = entry.get("source") or []
    if source:
        panel_lines.append(f"  [dim]{'source:':<14}[/dim]")
        for s in source:
            parts = []
            if s.get("author"):
                parts.append(s["author"])
            if s.get("year"):
                parts.append(f"({s['year']})")
            if s.get("title"):
                parts.append(f'"{s["title"]}"')
            if s.get("type"):
                parts.append(f"[{s['type']}]")
            panel_lines.append(f"    {' '.join(parts)}")

    kj = entry.get("kreita_je", "")[:10]
    mj = entry.get("modifita_je", "")[:10]
    panel_lines.append(f"  [dim]{'kreita_je:':<14}[/dim] {kj}")
    panel_lines.append(f"  [dim]{'modifita_je:':<14}[/dim] {mj}")

    console.print(
        Panel("\n".join(panel_lines), title=f"[bold]{title}[/bold]", expand=False)
    )


def _print_candidates(candidates: list[dict]) -> None:
    table = Table(show_header=True, header_style="dim", box=None)
    table.add_column("#", style="dim", width=3)
    table.add_column("UUID", style="dim", width=10)
    table.add_column("Titolo")
    for i, e in enumerate(candidates, 1):
        table.add_row(str(i), e["uuid"][:8], e["titolo"])
    console.print(table)


# ──────────────────────────────────────────────────────────────────────────────
# Resolve title-or-UUID to an entry
# ──────────────────────────────────────────────────────────────────────────────


def _resolve_entry(ref: str, *, interactive: bool = True) -> dict | None:
    """Return the entry matching *ref* (UUID prefix or partial title).

    If multiple candidates exist and *interactive* is True, prompt the user to
    pick one; otherwise return None.
    """
    # 1. Try exact UUID / prefix
    by_uuid = _find_by_uuid(ref)
    if by_uuid:
        return by_uuid

    # 2. Try exact title
    by_title = _find_by_title_exact(ref)
    if by_title:
        return by_title

    # 3. Fuzzy title search
    candidates = _fuzzy_title_matches(ref, max_results=5)
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    if not interactive:
        return None

    typer.echo(f"Pluraj kandidatoj por '{ref}':")
    _print_candidates(candidates)
    raw = typer.prompt("Elektu numeron (aŭ Enter por nuligi)", default="")
    if not raw.strip():
        return None
    try:
        idx = int(raw.strip()) - 1
        if 0 <= idx < len(candidates):
            return candidates[idx]
    except ValueError:
        pass
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Graph traversal helpers
# ──────────────────────────────────────────────────────────────────────────────


def _subklasoj_of(root_uuid: str, max_depth: int) -> list[dict]:
    """BFS: find all entries whose superklaso list includes *root_uuid*.

    Loads the full entry table once and builds a parent→children index to
    avoid repeated SELECT * queries inside the traversal loop.
    """
    all_entries = _load_all()

    # Build a parent-UUID → list-of-child-entries index
    children_of: dict[str, list[dict]] = {}
    for entry in all_entries:
        for pair in entry.get("superklaso") or []:
            if len(pair) < 2:
                continue
            parent_uuid = pair[1]
            children_of.setdefault(parent_uuid, []).append(entry)

    visited: set[str] = {root_uuid}
    results: list[dict] = []
    queue: deque[tuple[str, int]] = deque([(root_uuid, 0)])

    while queue:
        current_uuid, depth = queue.popleft()
        if max_depth > 0 and depth >= max_depth:
            continue
        for child in children_of.get(current_uuid, []):
            if child["uuid"] in visited:
                continue
            visited.add(child["uuid"])
            results.append(child)
            queue.append((child["uuid"], depth + 1))
    return results


def _superklasoj_of(root_uuid: str, max_depth: int) -> list[dict]:
    """BFS: follow superklaso links upward from *root_uuid*."""
    visited: set[str] = {root_uuid}
    results: list[dict] = []
    queue: deque[tuple[str, int]] = deque([(root_uuid, 0)])

    while queue:
        current_uuid, depth = queue.popleft()
        if max_depth > 0 and depth >= max_depth:
            continue
        entry = _find_by_uuid(current_uuid)
        if entry is None:
            continue
        for pair in entry.get("superklaso") or []:
            if len(pair) < 2:
                continue
            parent_uuid = pair[1]
            if parent_uuid in visited:
                continue
            parent = _find_by_uuid(parent_uuid)
            if parent is None:
                continue
            visited.add(parent_uuid)
            results.append(parent)
            queue.append((parent_uuid, depth + 1))
    return results


def _paralela_of(root_uuid: str, max_results: int) -> list[dict]:
    """Find sister classes: entries that share at least one parent with *root_uuid*."""
    root = _find_by_uuid(root_uuid)
    if root is None:
        return []
    root_parents = {p[1] for p in (root.get("superklaso") or []) if len(p) > 1}
    if not root_parents:
        return []

    all_entries = _load_all()
    sisters: list[dict] = []
    for entry in all_entries:
        if entry["uuid"] == root_uuid:
            continue
        entry_parents = {
            p[1] for p in (entry.get("superklaso") or []) if len(p) > 1
        }
        if root_parents & entry_parents:
            sisters.append(entry)
        if len(sisters) >= max_results:
            break
    return sisters


# ──────────────────────────────────────────────────────────────────────────────
# Welcome screen (interactive mode)
# ──────────────────────────────────────────────────────────────────────────────


def _welcome() -> None:
    conn = _get_conn()
    try:
        count = conn.execute("SELECT COUNT(*) FROM encik").fetchone()[0]
    finally:
        conn.close()
    console.print(
        Panel(
            f"  [dim]nodoj:[/dim] {count}\n\n"
            "  [dim]aldoni[/dim]     encik aldoni <dosiero.enc>\n"
            "  [dim]modifi[/dim]     encik modifi <titolo|uuid>\n"
            "  [dim]serci[/dim]      encik serci -t <teksto>",
            title="[bold]Encik — Knowledge Graph[/bold]",
            expand=False,
        )
    )


# ──────────────────────────────────────────────────────────────────────────────
# CLI commands
# ──────────────────────────────────────────────────────────────────────────────


@app.callback(invoke_without_command=True)
def _main(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        _welcome()


@app.command("aldoni")
def aldoni(
    dosiero: str = typer.Argument(
        ..., help="Path to the .enc file describing the knowledge node to add."
    ),
) -> None:
    """Add a new knowledge node from an .enc file."""
    path = Path(dosiero).expanduser().resolve()
    if not path.exists():
        typer.echo(f"Dosiero ne trovita: {path}", err=True)
        raise typer.Exit(code=1)
    if not path.is_file():
        typer.echo(f"Ne estas dosiero: {path}", err=True)
        raise typer.Exit(code=1)

    try:
        parsed = _parse_enc_file(path)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    # Duplicate title check
    existing = _find_by_title_exact(parsed["titolo"])
    if existing is not None:
        typer.echo(
            f"Nodo kun titolo \"{existing['titolo']}\" jam ekzistas "
            f"(#{existing['uuid'][:8]})."
        )
        raw = typer.prompt("Ĉu anstataŭigi? (j/n)", default="n")
        if raw.strip().lower() not in ("j", "jes", "y", "yes"):
            typer.echo("Nuligita.")
            return
        existing.update(
            titolo=parsed["titolo"],
            definio=parsed["definio"],
            superklaso=parsed["superklaso"],
            ligilo=parsed["ligilo"],
            source=parsed["source"],
            modifita_je=_now_iso(),
        )
        _update_entry(existing)
        typer.echo(f"Modifis #{existing['uuid'][:8]}  \"{existing['titolo']}\"")
        return

    now = _now_iso()
    entry: dict = {
        "uuid": str(_uuid_mod.uuid4()),
        "kreita_je": now,
        "modifita_je": now,
        **parsed,
    }
    _insert_entry(entry)
    typer.echo(f"Aldonis #{entry['uuid'][:8]}  \"{entry['titolo']}\"")


@app.command("modifi")
def modifi(
    ref: str = typer.Argument(
        ..., help="Term title (partial or exact) or UUID of the node to edit."
    ),
) -> None:
    """Edit an existing knowledge node in $EDITOR as a temporary .enc file."""
    entry = _resolve_entry(ref)
    if entry is None:
        typer.echo(f"Nodo ne trovita: {ref!r}", err=True)
        raise typer.Exit(code=1)

    enc_text = _entry_to_enc(entry)

    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "nano"

    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".enc",
        prefix="encik_",
        delete=False,
        encoding="utf-8",
    ) as tmp:
        tmp.write(enc_text)
        tmp_path = Path(tmp.name)

    try:
        result = subprocess.run([editor, str(tmp_path)])
        if result.returncode != 0:
            typer.echo(
                f"Redaktilo eliris kun kodo {result.returncode}.", err=True
            )
            raise typer.Exit(code=1)

        try:
            parsed = _parse_enc_file(tmp_path)
        except ValueError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    entry.update(
        titolo=parsed["titolo"],
        definio=parsed["definio"],
        superklaso=parsed["superklaso"],
        ligilo=parsed["ligilo"],
        source=parsed["source"],
        modifita_je=_now_iso(),
    )
    _update_entry(entry)
    typer.echo(f"Modifis #{entry['uuid'][:8]}  \"{entry['titolo']}\"")


@app.command("serci")
def serci(
    ctx: typer.Context,
    titolo: str | None = typer.Option(
        None,
        "-t",
        "--titolo",
        help="Fuzzy title search. Shows up to 5 candidates.",
    ),
    subklasoj: str | None = typer.Option(
        None,
        "-s",
        "--subklasoj",
        help="Search for subclasses of a given term (title or UUID).",
    ),
    superklasoj: str | None = typer.Option(
        None,
        "-S",
        "--superklasoj",
        help="Search for superclasses of a given term (title or UUID).",
    ),
    paralela: bool = typer.Option(
        False,
        "-p",
        "--paralela",
        help="Search for sister classes (nodes sharing the same parent).",
    ),
    limo: int = typer.Option(
        5,
        "-L",
        "--limo",
        help=(
            "For -s/-S: max recursion depth (default 5; 0 = unlimited). "
            "For -p: max results to return (default 100, use --limo with -p)."
        ),
    ),
    paralela_limo: int = typer.Option(
        100,
        "--paralela-limo",
        hidden=True,
        help="Max results for --paralela (default 100). Overrides -L when using -p.",
    ),
) -> None:
    """Search knowledge nodes."""
    active = [x for x in (titolo, subklasoj, superklasoj) if x is not None]
    if not active and not paralela:
        typer.echo(ctx.get_help())
        return

    # ── -t / --titolo ──────────────────────────────────────────────────────
    if titolo is not None:
        candidates = _fuzzy_title_matches(titolo, max_results=5)
        if not candidates:
            typer.echo(f"Neniu nodo trovita por '{titolo}'.")
            return
        if len(candidates) == 1:
            _display_entry(candidates[0])
            return
        _print_candidates(candidates)
        raw = typer.prompt(
            "Elektu numeron por vidi detalojn (aŭ Enter por preteriri)",
            default="",
        )
        if raw.strip():
            try:
                idx = int(raw.strip()) - 1
                if 0 <= idx < len(candidates):
                    _display_entry(candidates[idx])
            except ValueError:
                pass
        return

    # For -s/-S/-p we need to resolve the root node
    root_ref = subklasoj or superklasoj
    if root_ref is None and paralela:
        typer.echo(
            "Uzu -p kun -s/--subklasoj aŭ -S/--superklasoj por specifi radikon.",
            err=True,
        )
        raise typer.Exit(code=1)

    # Resolve root
    root = _resolve_entry(root_ref or "")
    if root is None:
        typer.echo(f"Nodo ne trovita: {root_ref!r}", err=True)
        raise typer.Exit(code=1)

    depth = abs(limo)

    # ── -s / --subklasoj ───────────────────────────────────────────────────
    if subklasoj is not None and not paralela:
        results = _subklasoj_of(root["uuid"], max_depth=depth)
        if not results:
            typer.echo(f"Neniu subklaso trovita por '{root['titolo']}'.")
            return
        typer.echo(f"Subklasoj de '{root['titolo']}' (nivelo ≤{depth or '∞'}):")
        for e in results:
            typer.echo(f"  #{e['uuid'][:8]}  {e['titolo']}")
        return

    # ── -S / --superklasoj ─────────────────────────────────────────────────
    if superklasoj is not None and not paralela:
        results = _superklasoj_of(root["uuid"], max_depth=depth)
        if not results:
            typer.echo(f"Neniu superklaso trovita por '{root['titolo']}'.")
            return
        typer.echo(f"Superklasoj de '{root['titolo']}' (nivelo ≤{depth or '∞'}):")
        for e in results:
            typer.echo(f"  #{e['uuid'][:8]}  {e['titolo']}")
        return

    # ── -p / --paralela ────────────────────────────────────────────────────
    if paralela:
        # Use paralela_limo as the default when limo hasn't been explicitly set
        max_r = paralela_limo if limo == 5 else abs(limo)
        results = _paralela_of(root["uuid"], max_results=max_r)
        if not results:
            typer.echo(f"Neniu paralela nodo trovita por '{root['titolo']}'.")
            return
        typer.echo(f"Paralela ({root['titolo']}) — max {max_r}:")
        for e in results:
            typer.echo(f"  #{e['uuid'][:8]}  {e['titolo']}")
