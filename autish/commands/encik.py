"""encik — personal knowledge management microapp.

Usage:
    encik                       — interactive welcome screen
    encik aldoni <file.enc>     — add a new knowledge node from an .enc file
    encik vidi <titolo|UUID>    — view an existing node
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
import re
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
    terminologio TEXT NOT NULL DEFAULT '{}',
    difinoj     TEXT NOT NULL DEFAULT '{}',
    enhavo      TEXT NOT NULL DEFAULT '',
    superklaso  TEXT NOT NULL DEFAULT '[]',
    ligilo      TEXT NOT NULL DEFAULT '[]',
    fonto       TEXT NOT NULL DEFAULT '[]',
    kreita_je   TEXT NOT NULL,
    modifita_je TEXT NOT NULL
);
"""

_ISO_690_TIPOJ: dict[str, str] = {
    "lib": "libroj",
    "art": "artikoloj",
    "ret": "retejoj",
    "fil": "filmoj",
    "tez": "tezoj",
    "rap": "raportoj",
    "pod": "podkastoj",
    "pre": "prelegoj",
}

# ──────────────────────────────────────────────────────────────────────────────
# DB helpers
# ──────────────────────────────────────────────────────────────────────────────


def _init_db() -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_FILE)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(_CREATE_ENCIK)
        _migrate_db(conn)
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


def _migrate_db(conn: sqlite3.Connection) -> None:
    cols = {
        row[1]
        for row in conn.execute("PRAGMA table_info(encik)").fetchall()
        if len(row) > 1
    }
    if "terminologio" not in cols:
        conn.execute(
            "ALTER TABLE encik ADD COLUMN terminologio TEXT NOT NULL DEFAULT '{}'"
        )
    if "difinoj" not in cols:
        conn.execute("ALTER TABLE encik ADD COLUMN difinoj TEXT NOT NULL DEFAULT '{}'")
    if "enhavo" not in cols:
        conn.execute("ALTER TABLE encik ADD COLUMN enhavo TEXT NOT NULL DEFAULT ''")
    if "fonto" not in cols:
        conn.execute("ALTER TABLE encik ADD COLUMN fonto TEXT NOT NULL DEFAULT '[]'")
        if "source" in cols:
            conn.execute(
                "UPDATE encik SET fonto = source WHERE (fonto = '[]' OR fonto = '')"
            )


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    for field in ("superklaso", "ligilo", "fonto", "source"):
        if isinstance(d.get(field), str):
            d[field] = json.loads(d[field])
    for field in ("terminologio", "difinoj"):
        if isinstance(d.get(field), str):
            d[field] = json.loads(d[field])
    if "fonto" not in d and "source" in d:
        d["fonto"] = d.get("source") or []
    if "terminologio" not in d:
        titolo = str(d.get("titolo") or "").strip()
        d["terminologio"] = {"eo": titolo} if titolo else {}
    if "difinoj" not in d:
        definio = str(d.get("definio") or "").strip()
        d["difinoj"] = {"eo": definio} if definio else {}
    if "enhavo" not in d:
        d["enhavo"] = ""
    if not d.get("titolo"):
        d["titolo"] = next(iter(d.get("terminologio", {}).values()), "")
    if not d.get("definio"):
        d["definio"] = next(iter(d.get("difinoj", {}).values()), "")
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
    matches = []
    for e in all_entries:
        titolo = str(e.get("titolo") or "")
        terms = [str(v) for v in (e.get("terminologio") or {}).values()]
        haystack = [titolo, *terms]
        positions = [text.lower().find(lower) for text in haystack if text]
        valid_positions = [p for p in positions if p >= 0]
        if valid_positions:
            e_copy = dict(e)
            e_copy["_match_pos"] = min(valid_positions)
            matches.append(e_copy)
    # Sort by position of match (earlier = better)
    matches.sort(key=lambda e: int(e.get("_match_pos", 9999)))
    return matches[:max_results]


def _insert_entry(entry: dict) -> None:
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO encik"
            " (uuid, titolo, definio, terminologio, difinoj, enhavo,"
            " superklaso, ligilo, fonto,"
            " kreita_je, modifita_je)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                entry["uuid"],
                entry["titolo"],
                entry.get("definio", ""),
                json.dumps(entry.get("terminologio", {}), ensure_ascii=False),
                json.dumps(entry.get("difinoj", {}), ensure_ascii=False),
                entry.get("enhavo", ""),
                json.dumps(entry.get("superklaso", []), ensure_ascii=False),
                json.dumps(entry.get("ligilo", []), ensure_ascii=False),
                json.dumps(entry.get("fonto", []), ensure_ascii=False),
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
               titolo=?, definio=?, terminologio=?, difinoj=?, enhavo=?,
               superklaso=?, ligilo=?, fonto=?, modifita_je=?
               WHERE uuid=?""",
            (
                entry["titolo"],
                entry.get("definio", ""),
                json.dumps(entry.get("terminologio", {}), ensure_ascii=False),
                json.dumps(entry.get("difinoj", {}), ensure_ascii=False),
                entry.get("enhavo", ""),
                json.dumps(entry.get("superklaso", []), ensure_ascii=False),
                json.dumps(entry.get("ligilo", []), ensure_ascii=False),
                json.dumps(entry.get("fonto", []), ensure_ascii=False),
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
{terminologio}
{difinoj}

\"\"\"
{enhavo}
\"\"\"

# Superklasoj: listo de ["Terminologio", "uuid"] paroj
superklaso = {superklaso}

# Ligiloj: listo de ["Terminologio", "uuid"] paroj
ligilo = {ligilo}

# Fontoj: listo de {{author="", year="", type="", title.xx=""}} tabeloj
fonto = {fonto}
"""


def _entry_to_enc(entry: dict) -> str:
    """Serialise an encik entry to .enc text."""
    terminologio = entry.get("terminologio") or {}
    difinoj = entry.get("difinoj") or {}
    superklaso = entry.get("superklaso") or []
    ligilo = entry.get("ligilo") or []
    fonto = entry.get("fonto") or []
    enhavo = entry.get("enhavo", "")

    def _toml_list(lst: list) -> str:
        """Format a Python list as a TOML array (compact JSON-style)."""
        if not lst:
            return "[]"
        return json.dumps(lst, ensure_ascii=False)

    def _fonto_list(lst: list) -> str:
        if not lst:
            return "[]"
        parts = []
        for s in lst:
            items = ", ".join(
                f'{k} = {json.dumps(v)}' for k, v in s.items() if v
            )
            parts.append(f"{{{items}}}")
        return "[" + ", ".join(parts) + "]"

    def _lang_map_lines(prefix: str, mapping: dict[str, str]) -> str:
        lines = []
        for lang in sorted(mapping):
            value = str(mapping[lang] or "")
            lines.append(f"{prefix}.{lang} = {json.dumps(value)}")
        return "\n".join(lines)

    return _ENC_TEMPLATE.format(
        terminologio=_lang_map_lines("terminologio", terminologio),
        difinoj=_lang_map_lines("definio", difinoj),
        enhavo=enhavo,
        superklaso=_toml_list(superklaso),
        ligilo=_toml_list(ligilo),
        fonto=_fonto_list(fonto),
    )


def _parse_enc_file(path: Path) -> dict:
    """Parse an .enc file and return a dict with the entry fields.

    The .enc format is TOML with an optional leading comment ``# title``.
    If the TOML itself contains a ``titolo`` key that takes precedence;
    otherwise the first ``# …`` comment is used as the title.
    """
    raw = path.read_text(encoding="utf-8")
    raw_core, enhavo = _extract_enhavo_block(raw)

    # Extract title from the first non-empty comment line
    title_from_comment = ""
    for line in raw_core.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") and not stripped.startswith("##"):
            candidate = stripped.lstrip("#").strip()
            if candidate:
                title_from_comment = candidate
                break

    # Parse the TOML part (comments are automatically ignored)
    try:
        data = tomllib.loads(raw_core)
    except Exception as exc:
        raise ValueError(f"Malformed .enc file: {exc}") from exc

    terminologio, difinoj = _collect_lang_fields(data)
    if not terminologio and title_from_comment:
        terminologio = {"eo": title_from_comment}
    if not difinoj and isinstance(data.get("definio"), str):
        maybe = data.get("definio", "").strip()
        if maybe:
            difinoj["eo"] = maybe

    if not _has_minimum_term_definition_pair(terminologio, difinoj):
        raise ValueError(
            "Nevalida .enc: bezonata almenaŭ unu lingvo kun ambaŭ "
            "terminologio.xx kaj definio.xx."
        )

    titolo = next(iter(terminologio.values()))
    definio = difinoj.get(next(iter(terminologio.keys())), "")
    if not definio:
        definio = next(iter(difinoj.values()))

    # superklaso / ligilo: list of [title, uuid] pairs
    superklaso = _normalise_pairs(data.get("superklaso", []))
    ligilo = _normalise_pairs(data.get("ligilo", []))

    # fonto: list of dicts
    fonto: list[dict] = []
    raw_fonto = data.get("fonto", data.get("source", []))
    for item in raw_fonto:
        if isinstance(item, dict):
            normalized = {k: str(v) for k, v in item.items()}
            if normalized.get("type"):
                normalized["type"] = _normalize_fonto_tipo(normalized["type"])
            fonto.append(normalized)

    return {
        "titolo": titolo,
        "definio": definio,
        "terminologio": terminologio,
        "difinoj": difinoj,
        "enhavo": enhavo,
        "superklaso": superklaso,
        "ligilo": ligilo,
        "fonto": fonto,
    }


def _extract_enhavo_block(raw: str) -> tuple[str, str]:
    pattern = re.compile(r'^\s*"""\n(.*?)\n"""\s*$', re.MULTILINE | re.DOTALL)
    match = pattern.search(raw)
    if not match:
        return raw, ""
    enhavo = match.group(1).strip()
    without = raw[: match.start()] + "\n" + raw[match.end() :]
    return without, enhavo


def _collect_lang_fields(data: dict) -> tuple[dict[str, str], dict[str, str]]:
    terminologio: dict[str, str] = {}
    difinoj: dict[str, str] = {}

    for key, value in data.items():
        if not isinstance(value, str):
            continue
        if key.startswith("terminologio."):
            lang = key.split(".", 1)[1].strip().lower()
            if lang and value.strip():
                terminologio[lang] = value.strip()
        if key.startswith("definio."):
            lang = key.split(".", 1)[1].strip().lower()
            if lang and value.strip():
                difinoj[lang] = value.strip()

    if not terminologio and isinstance(data.get("terminologio"), dict):
        for lang, value in data["terminologio"].items():
            if str(value).strip():
                terminologio[str(lang).strip().lower()] = str(value).strip()

    definio_obj = data.get("definio")
    if not difinoj and isinstance(definio_obj, dict):
        for lang, value in definio_obj.items():
            if str(value).strip():
                difinoj[str(lang).strip().lower()] = str(value).strip()

    if not terminologio and isinstance(data.get("titolo"), str):
        titolo = data.get("titolo", "").strip()
        if titolo:
            terminologio["eo"] = titolo

    return terminologio, difinoj


def _has_minimum_term_definition_pair(
    terminologio: dict[str, str], difinoj: dict[str, str]
) -> bool:
    for lang, term in terminologio.items():
        if term.strip() and difinoj.get(lang, "").strip():
            return True
    return False


def _normalize_fonto_tipo(raw_tipo: str) -> str:
    value = raw_tipo.strip().lower()
    if value in _ISO_690_TIPOJ:
        return _ISO_690_TIPOJ[value]
    if value in _ISO_690_TIPOJ.values():
        return value
    allowed = ", ".join(sorted(_ISO_690_TIPOJ.values()))
    aliases = ", ".join(f"{k}->{v}" for k, v in sorted(_ISO_690_TIPOJ.items()))
    raise ValueError(
        f"Nevalida fonto.type: {raw_tipo!r}. Uzu ISO-690 tipon ({allowed}) "
        f"aŭ aliason ({aliases})."
    )


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


def _display_entry(
    entry: dict, *, lingvo: str | None = None, montri_cxion: bool = False
) -> None:
    uid_short = entry["uuid"][:8]
    terminologio = entry.get("terminologio") or {}
    difinoj = entry.get("difinoj") or {}
    selected_lang = (lingvo or "").strip().lower() or _preferred_lang(
        terminologio, difinoj
    )
    title = (
        terminologio.get(selected_lang)
        or entry["titolo"]
        or next(iter(terminologio.values()), "")
    )
    panel_lines: list[str] = []
    panel_lines.append(f"  [dim]{'uuid:':<14}[/dim] {uid_short}")
    panel_lines.append(f"  [dim]{'lingvo:':<14}[/dim] {selected_lang or '-'}")

    definio = (
        difinoj.get(selected_lang)
        or entry.get("definio", "")
        or next(iter(difinoj.values()), "")
    ).strip()
    if definio:
        panel_lines.append(f"  [dim]{'definio:':<14}[/dim]")
        for ln in definio.splitlines():
            panel_lines.append(f"    {ln}")

    if montri_cxion and terminologio:
        panel_lines.append(f"  [dim]{'terminologio:':<14}[/dim]")
        for lang, term in sorted(terminologio.items()):
            panel_lines.append(f"    {lang}: {term}")
    if montri_cxion and difinoj:
        panel_lines.append(f"  [dim]{'difinoj:':<14}[/dim]")
        for lang, term_def in sorted(difinoj.items()):
            panel_lines.append(f"    {lang}: {term_def}")

    enhavo = (entry.get("enhavo") or "").strip()
    if enhavo and montri_cxion:
        panel_lines.append(f"  [dim]{'enhavo:':<14}[/dim]")
        for ln in enhavo.splitlines():
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

    fonto = entry.get("fonto") or []
    if fonto:
        panel_lines.append(f"  [dim]{'fonto:':<14}[/dim]")
        for s in fonto:
            parts = []
            if s.get("author"):
                parts.append(s["author"])
            if s.get("year"):
                parts.append(f"({s['year']})")
            if s.get("title"):
                parts.append(f'"{s["title"]}"')
            if s.get("type"):
                parts.append(f"tipo={s['type']}")
            title_lang_items = sorted(
                (k, v) for k, v in s.items() if k.startswith("title.")
            )
            for k, v in title_lang_items:
                parts.append(f"{k}={json.dumps(v, ensure_ascii=False)}")
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
        display_title = e.get("titolo") or next(
            iter((e.get("terminologio") or {}).values()), ""
        )
        table.add_row(str(i), e["uuid"][:8], display_title)
    console.print(table)


def _preferred_lang(terminologio: dict[str, str], difinoj: dict[str, str]) -> str:
    raw_env_lang = os.environ.get("LC_ALL") or os.environ.get("LANG") or ""
    env_lang = raw_env_lang.split(".")[0]
    env_lang = env_lang.split("_")[0].lower()
    if env_lang and terminologio.get(env_lang) and difinoj.get(env_lang):
        return env_lang
    for lang in ("eo", "en"):
        if terminologio.get(lang) and difinoj.get(lang):
            return lang
    shared = [lang for lang in terminologio if difinoj.get(lang)]
    if shared:
        return shared[0]
    if terminologio:
        return next(iter(terminologio.keys()))
    if difinoj:
        return next(iter(difinoj.keys()))
    return ""


# ──────────────────────────────────────────────────────────────────────────────
# Resolve title-or-UUID to an entry
# ──────────────────────────────────────────────────────────────────────────────


def _resolve_entry(ref: str, *, interactive: bool = True) -> dict | None:
    """Return the entry matching *ref* (UUID prefix or partial title).

    If multiple candidates exist and *interactive* is True, prompt the user to
    pick one; otherwise return None.
    """
    normalized_ref = ref.strip()
    if normalized_ref.startswith("#"):
        normalized_ref = normalized_ref[1:]

    # 1. Try exact UUID / prefix
    by_uuid = _find_by_uuid(normalized_ref)
    if by_uuid:
        return by_uuid

    # 2. Try exact title
    by_title = _find_by_title_exact(normalized_ref)
    if by_title:
        return by_title

    # 2.5 Try exact multilingual terminologio match
    all_entries = _load_all()
    exact_lang_matches = [
        e
        for e in all_entries
        if normalized_ref.lower()
        in {
            str(v).strip().lower()
            for v in (e.get("terminologio") or {}).values()
            if str(v).strip()
        }
    ]
    if len(exact_lang_matches) == 1:
        return exact_lang_matches[0]
    if len(exact_lang_matches) > 1:
        candidates = exact_lang_matches[:5]
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
            return None

    # 3. Fuzzy title search
    candidates = _fuzzy_title_matches(normalized_ref, max_results=5)
    if not candidates:
        # 4. Fuzzy match multilingual terminologio
        q = normalized_ref.lower()
        lang_matches = []
        for e in all_entries:
            terms = [str(v) for v in (e.get("terminologio") or {}).values()]
            best_pos = None
            for t in terms:
                pos = t.lower().find(q)
                if pos >= 0 and (best_pos is None or pos < best_pos):
                    best_pos = pos
            if best_pos is not None:
                lang_matches.append((best_pos, e))
        lang_matches.sort(key=lambda item: item[0])
        candidates = [e for _, e in lang_matches[:5]]
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
            "  [dim]vidi[/dim]       encik vidi <titolo|uuid>\n"
            "  [dim]modifi[/dim]     encik modifi <titolo|uuid>\n"
            "  [dim]serci[/dim]      encik serci -t <teksto>",
            title="[bold]Encik — Sciaro[/bold]",
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
        ...,
        help=(
            "Vojo al .enc dosiero. Formato: terminologio.xx, definio.xx, "
            '"""libera teksto""", superklaso, ligilo, fonto.'
        ),
    ),
) -> None:
    """Aldoni novan nodon el .enc dosiero."""
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
            terminologio=parsed["terminologio"],
            difinoj=parsed["difinoj"],
            enhavo=parsed["enhavo"],
            superklaso=parsed["superklaso"],
            ligilo=parsed["ligilo"],
            fonto=parsed["fonto"],
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
        ..., help="Terminologio (parta aŭ ekzakta) aŭ UUID de redaktota nodo."
    ),
) -> None:
    """Redakti ekzistantan nodon en $EDITOR kiel provizora .enc dosiero."""
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

    existing = _find_by_title_exact(parsed["titolo"])
    if existing is not None and existing["uuid"] != entry["uuid"]:
        typer.echo(
            f"Nodo kun titolo \"{parsed['titolo']}\" jam ekzistas "
            f"(#{existing['uuid'][:8]}).",
            err=True,
        )
        raise typer.Exit(code=1)

    entry.update(
        titolo=parsed["titolo"],
        definio=parsed["definio"],
        terminologio=parsed["terminologio"],
        difinoj=parsed["difinoj"],
        enhavo=parsed["enhavo"],
        superklaso=parsed["superklaso"],
        ligilo=parsed["ligilo"],
        fonto=parsed["fonto"],
        modifita_je=_now_iso(),
    )
    _update_entry(entry)
    typer.echo(f"Modifis #{entry['uuid'][:8]}  \"{entry['titolo']}\"")


@app.command("vidi")
def vidi(
    ref: str = typer.Argument(
        ...,
        help="UUID, #UUID, aŭ terminologio (aproksimativa serĉo subtenata).",
    ),
    lingvo: str | None = typer.Option(
        None,
        "-L",
        "--lingvo",
        help="Montri en difinita lingvo (ekz. eo, en, id).",
    ),
    montri_cxion: bool = typer.Option(
        False,
        "-a",
        "--cxio",
        help="Montri ĉiujn disponeblajn lingvojn kaj kampojn.",
    ),
) -> None:
    """Montri unu nodon laŭ UUID aŭ terminologio."""
    entry = _resolve_entry(ref, interactive=True)
    if entry is None:
        typer.echo(f"Nodo ne trovita: {ref!r}", err=True)
        raise typer.Exit(code=1)
    _display_entry(entry, lingvo=lingvo, montri_cxion=montri_cxion)


@app.command("serci")
def serci(
    ctx: typer.Context,
    titolo: str | None = typer.Option(
        None,
        "-t",
        "--titolo",
        help="Malfirma serĉo laŭ titolo; montras maksimume 5 kandidatojn.",
    ),
    subklasoj: str | None = typer.Option(
        None,
        "-s",
        "--subklasoj",
        help="Serĉi subklasojn de termino (titolo aŭ UUID).",
    ),
    superklasoj: str | None = typer.Option(
        None,
        "-S",
        "--superklasoj",
        help="Serĉi superklasojn de termino (titolo aŭ UUID).",
    ),
    paralela: bool = typer.Option(
        False,
        "-p",
        "--paralela",
        help="Serĉi paralelajn klasojn (nodoj kun sama superklaso).",
    ),
    limo: int = typer.Option(
        5,
        "-L",
        "--limo",
        help=(
            "Por -s/-S: maksimuma profundo (0 = senlima). "
            "Por -p: maksimumaj rezultoj."
        ),
    ),
    paralela_limo: int = typer.Option(
        100,
        "--paralela-limo",
        hidden=True,
        help="Maksimumaj rezultoj por --paralela (defaŭlte 100).",
    ),
) -> None:
    """Serĉi nodojn."""
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
