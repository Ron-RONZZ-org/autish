"""encik — personal knowledge management microapp.

Usage:
    encik                       — interactive welcome screen
    encik aldoni <file.enc>     — add a new knowledge node from an .enc file
    encik vidi <titolo|UUID>    — view an existing node
    encik modifi <title|UUID>   — edit an existing node in $EDITOR as a temp .enc file
    encik serci <demando>       — search nodes (title by default)
      -t/--teksto               — search full entry text instead of title only
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
import webbrowser
from collections import deque
from datetime import datetime, timezone
from difflib import get_close_matches
from html import escape
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
    context_settings={"help_option_names": ["-h", "--help", "--helpo"]},
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
    difinio     TEXT NOT NULL DEFAULT '',
    terminologio TEXT NOT NULL DEFAULT '{}',
    difinoj     TEXT NOT NULL DEFAULT '{}',
    enhavo      TEXT NOT NULL DEFAULT '',
    superklaso  TEXT NOT NULL DEFAULT '[]',
    ligilo      TEXT NOT NULL DEFAULT '[]',
    fonto       TEXT NOT NULL DEFAULT '[]',
    citajo      TEXT NOT NULL DEFAULT '[]',
    datumo      TEXT NOT NULL DEFAULT '{}',
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

_SEMANTIKAJ_LIGILOJ: dict[str, str] = {
    "rdf:type": "rdf:type",
    "type": "rdf:type",
    "estas tipo de": "rdf:type",
    "rdfs:subclassof": "rdfs:subClassOf",
    "subklaso de": "rdfs:subClassOf",
    "owl:disjointwith": "owl:disjointWith",
    "malkongrua kun": "owl:disjointWith",
    "owl:inverseof": "owl:inverseOf",
    "inversa de": "owl:inverseOf",
    "rdfs:superclassof": "rdfs:superClassOf",
    "rdf:hasinstance": "rdf:hasInstance",
}
_AUTO_REVERSE_DATUMO_KEY = "__autish_auto_reverse_ligilo__"

_ALLOWED_ENC_PLAIN_KEYS: frozenset[str] = frozenset({
    "terminologio",
    "difinio",
    "difino",
    "titolo",
    "superklaso",
    "ligilo",
    "fonto",
    "citajo",
    "datumo",
    "source",
})
_ALLOWED_ENC_PLAIN_KEYS_SORTED: tuple[str, ...] = tuple(
    sorted(_ALLOWED_ENC_PLAIN_KEYS)
)

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
    if "citajo" not in cols:
        conn.execute("ALTER TABLE encik ADD COLUMN citajo TEXT NOT NULL DEFAULT '[]'")
    if "datumo" not in cols:
        conn.execute("ALTER TABLE encik ADD COLUMN datumo TEXT NOT NULL DEFAULT '{}'")


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    for field in ("superklaso", "ligilo", "fonto", "citajo", "source"):
        if isinstance(d.get(field), str):
            d[field] = json.loads(d[field])
    for field in ("terminologio", "difinoj", "datumo"):
        if isinstance(d.get(field), str):
            d[field] = json.loads(d[field])
    if "fonto" not in d and "source" in d:
        d["fonto"] = d.get("source") or []
    if "terminologio" not in d:
        titolo = str(d.get("titolo") or "").strip()
        d["terminologio"] = {"eo": titolo} if titolo else {}
    if "difinoj" not in d:
        difinio = str(d.get("difinio") or "").strip()
        d["difinoj"] = {"eo": difinio} if difinio else {}
    if "enhavo" not in d:
        d["enhavo"] = ""
    if "citajo" not in d:
        d["citajo"] = []
    if "datumo" not in d:
        d["datumo"] = {}
    if not d.get("titolo"):
        d["titolo"] = next(iter(d.get("terminologio", {}).values()), "")
    if not d.get("difinio") and d.get("difino"):
        d["difinio"] = str(d.get("difino") or "")
    if not d.get("difinio"):
        d["difinio"] = next(iter(d.get("difinoj", {}).values()), "")
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


def _count_matches(text: str, needle: str) -> int:
    if not text or not needle:
        return 0
    return len(re.findall(re.escape(needle), text.lower()))


def _build_subklaso_count_map(entries: list[dict]) -> dict[str, int]:
    uuids = {str(e.get("uuid") or "") for e in entries}
    out: dict[str, int] = {uid: 0 for uid in uuids if uid}
    for entry in entries:
        for parent_ref in _normalize_uuid_list(entry.get("superklaso") or []):
            ref = str(parent_ref or "").strip()
            if not ref:
                continue
            parent_uuid = ref if ref in uuids else ""
            if not parent_uuid:
                pref = [uid for uid in uuids if uid.startswith(ref)]
                if len(pref) == 1:
                    parent_uuid = pref[0]
            if parent_uuid:
                out[parent_uuid] = out.get(parent_uuid, 0) + 1
    return out


def _search_entries(
    query: str,
    *,
    full_text: bool,
    max_results: int,
    prefer_newest: bool = True,
    prefer_high_level: bool = True,
) -> list[dict]:
    needle = query.strip().lower()
    if not needle:
        return []
    entries = _load_all()
    sub_count_map = _build_subklaso_count_map(entries)
    scored: list[dict] = []
    for e in entries:
        titolo = str(e.get("titolo") or "")
        terminologio_vals = [str(v) for v in (e.get("terminologio") or {}).values()]
        difinoj_vals = [str(v) for v in (e.get("difinoj") or {}).values()]
        enhavo = str(e.get("enhavo") or "")
        if full_text:
            pool = [
                titolo,
                *terminologio_vals,
                str(e.get("difinio") or ""),
                *difinoj_vals,
                enhavo,
            ]
        else:
            pool = [titolo, *terminologio_vals]
        match_count = sum(_count_matches(p, needle) for p in pool if p)
        if match_count <= 0:
            continue
        e_copy = dict(e)
        e_copy["_match_count"] = match_count
        e_copy["_subklaso_count"] = int(sub_count_map.get(str(e.get("uuid") or ""), 0))
        e_copy["_time"] = str(e.get("modifita_je") or e.get("kreita_je") or "")
        scored.append(e_copy)

    def _sort_key(item: dict) -> tuple:
        match_key = -int(item.get("_match_count", 0))
        level_val = int(item.get("_subklaso_count", 0))
        level_key = -level_val if prefer_high_level else level_val
        time_val = str(item.get("_time") or "")
        time_key = (
            "".join(chr(255 - ord(c)) for c in time_val)
            if prefer_newest
            else time_val
        )
        return (match_key, level_key, time_key)

    scored.sort(key=_sort_key)
    return scored[:max_results]


def _fuzzy_title_matches(partial: str, max_results: int = 5) -> list[dict]:
    return _search_entries(
        partial, full_text=False, max_results=max_results, prefer_newest=True
    )


def _insert_entry(entry: dict) -> None:
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO encik"
            " (uuid, titolo, difinio, terminologio, difinoj, enhavo,"
            " superklaso, ligilo, fonto, citajo, datumo,"
            " kreita_je, modifita_je)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                entry["uuid"],
                entry["titolo"],
                entry.get("difinio", ""),
                json.dumps(entry.get("terminologio", {}), ensure_ascii=False),
                json.dumps(entry.get("difinoj", {}), ensure_ascii=False),
                entry.get("enhavo", ""),
                json.dumps(entry.get("superklaso", []), ensure_ascii=False),
                json.dumps(entry.get("ligilo", []), ensure_ascii=False),
                json.dumps(entry.get("fonto", []), ensure_ascii=False),
                json.dumps(entry.get("citajo", []), ensure_ascii=False),
                json.dumps(entry.get("datumo", {}), ensure_ascii=False),
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
               titolo=?, difinio=?, terminologio=?, difinoj=?, enhavo=?,
               superklaso=?, ligilo=?, fonto=?, citajo=?, datumo=?, modifita_je=?
               WHERE uuid=?""",
            (
                entry["titolo"],
                entry.get("difinio", ""),
                json.dumps(entry.get("terminologio", {}), ensure_ascii=False),
                json.dumps(entry.get("difinoj", {}), ensure_ascii=False),
                entry.get("enhavo", ""),
                json.dumps(entry.get("superklaso", []), ensure_ascii=False),
                json.dumps(entry.get("ligilo", []), ensure_ascii=False),
                json.dumps(entry.get("fonto", []), ensure_ascii=False),
                json.dumps(entry.get("citajo", []), ensure_ascii=False),
                json.dumps(entry.get("datumo", {}), ensure_ascii=False),
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

# Komentoj en .enc dosiero:
#   - Komencu per '#'
#   - Ĉio post '#' en la sama linio estas komento

\"\"\"
{enhavo}
\"\"\"

# Superklasoj: listo de ["Terminologio", "uuid"] paroj
superklaso = {superklaso}

# Ligiloj: listo de UUID-oj aŭ [UUID, semantika_tipo]
# Ekzemploj:
#   ligilo = "uuid1"
#   ligilo = ["uuid1", "#uuid2", ["uuid3", "rdf:type"], ["uuid4", "owl:inverseOf"]]
ligilo = {ligilo}

# Fontoj: listo de tabeloj kun titolo, autoro, jaro, tipo, noto, ligilo
# Ekzemplo: fonto = [{{titolo="...", autoro="...", jaro=2020, tipo="lib", 
#                      noto="...", ligilo="https://..."}}]
# Validaj tipoj: libroj, artikoloj, retejoj, filmoj, tezoj, raportoj,
#                podkastoj, prelegoj
# Aliasoj: lib, art, ret, fil, tez, rap, pod, pre
fonto = {fonto}

# Citaĵoj: listo de tabeloj {{teksto, autoro, verko, jaro}}
citajo = {citajo}

# Datumoj: datumo.{{nomo}} = \"\"\"{{...json...}}\"\"\"
{datumo}
"""


def _entry_to_enc(entry: dict) -> str:
    """Serialise an encik entry to .enc text."""
    terminologio = entry.get("terminologio") or {}
    difinoj = entry.get("difinoj") or {}
    superklaso = entry.get("superklaso") or []
    ligilo = _serialize_ligilo_items(_public_ligilo_items(entry))
    fonto = entry.get("fonto") or []
    citajo = entry.get("citajo") or []
    datumo = _public_datumo(entry)
    enhavo = entry.get("enhavo", "")

    def _decode_visible_newlines(value: str) -> str:
        return value.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\r", "\n")

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
            # Output in Esperanto format with proper types
            items = []
            for k, v in s.items():
                if not v:
                    continue
                if k == "jaro":
                    # Output jaro as integer without quotes
                    items.append(f"{k} = {v}")
                else:
                    items.append(f'{k} = {json.dumps(v)}')
            parts.append(f"{{{', '.join(items)}}}")
        return "[" + ", ".join(parts) + "]"

    def _citajo_list(lst: list) -> str:
        if not lst:
            return "[]"
        parts = []
        for c in lst:
            items = []
            for k in ("teksto", "autoro", "verko", "jaro", "lingvo"):
                if c.get(k) is not None and str(c.get(k)).strip():
                    items.append(f'{k} = {json.dumps(str(c.get(k)))}')
            parts.append(f"{{{', '.join(items)}}}")
        return "[" + ", ".join(parts) + "]"

    def _datumo_block(datasets: dict) -> str:
        if not datasets:
            return ""
        lines: list[str] = []
        for name in sorted(datasets):
            payload = json.dumps(datasets[name], ensure_ascii=False, indent=2)
            lines.append(f"datumo.{name} = \"\"\"\n{payload}\n\"\"\"")
        return "\n\n".join(lines)

    def _lang_map_lines(prefix: str, mapping: dict[str, str]) -> str:
        lines = []
        for lang in sorted(mapping):
            value = _decode_visible_newlines(str(mapping[lang] or ""))
            if "\n" in value:
                safe = value.replace('"""', '\\"""')
                lines.append(f'{prefix}.{lang} = """\n{safe}\n"""')
            else:
                lines.append(f"{prefix}.{lang} = {json.dumps(value)}")
        return "\n".join(lines)

    return _ENC_TEMPLATE.format(
        terminologio=_lang_map_lines("terminologio", terminologio),
        difinoj=_lang_map_lines("difino", difinoj),
        enhavo=enhavo,
        superklaso=_toml_list(superklaso),
        ligilo=_toml_list(ligilo),
        fonto=_fonto_list(fonto),
        citajo=_citajo_list(citajo),
        datumo=_datumo_block(datumo),
    )


def _invalid_edit_dir() -> Path:
    return _DATA_DIR / "encik-invalidaj"


def _invalid_edit_path(uuid: str) -> Path:
    return _invalid_edit_dir() / f"{uuid}.enc"


def _fix_inline_table_commas(text: str) -> str:
    """Add missing commas and fix bracket syntax in inline tables (fonto lines).
    
    Fixes patterns like:
    - {a="x" b="y"} -> {a="x", b="y"}  (missing commas)
    - [[{...}]] -> [{...}]              (wrong brackets for inline table array)
    
    Only applies to fonto= lines to avoid breaking other valid TOML.
    """
    lines = []
    for line in text.splitlines():
        # Only fix lines that look like fonto assignments
        if re.match(r'^\s*fonto\s*=', line):
            # First, fix bracket syntax: [[ -> [ and ]] -> ]
            # This converts array-of-arrays notation to array-of-inline-tables
            fixed = re.sub(r'=\s*\[\[', '=[{', line)  # [[ -> [{
            fixed = re.sub(r'\]\]', '}]', fixed)       # ]] -> }]
            
            # Then add missing commas between fields in inline tables
            # Pattern: Look for " followed by space and a letter/underscore (next field)
            # This matches: year="2021" author="..." 
            # Replace with: year="2021", author="..."
            fixed = re.sub(
                r'"\s+([a-zA-Z_])',  # " followed by whitespace and letter
                r'", \1',             # Replace with ", followed by letter
                fixed
            )
            lines.append(fixed)
        else:
            lines.append(line)
    return '\n'.join(lines)


def _fix_unquoted_uuids(text: str) -> str:
    """Auto-quote unquoted UUID-like values in ligilo and superklaso fields.
    
    Fixes patterns like:
    - ligilo=abc123 -> ligilo="abc123"
    - ligilo=[abc123, def456] -> ligilo=["abc123", "def456"]
    
    Only applies to ligilo/superklaso lines to avoid breaking other TOML.
    """
    lines = []
    for line in text.splitlines():
        # Fix ligilo/superklaso with single unquoted UUID: ligilo=abc123
        pattern = r"^\s*(ligilo|superklaso)\s*=\s*[#a-zA-Z0-9_:\-\.]+\s*$"
        if re.match(pattern, line, re.IGNORECASE):
            # Extract the value and quote it
            match_pattern = (
                r"^(\s*(?:ligilo|superklaso)\s*=\s*)([#a-zA-Z0-9_:\-\.]+)\s*$"
            )
            match = re.match(match_pattern, line, re.IGNORECASE)
            if match:
                lines.append(f'{match.group(1)}"{match.group(2)}"')
                continue
        
        # Fix ligilo/superklaso with array of unquoted UUIDs: ligilo=[abc, def]
        if re.match(r'^\s*(ligilo|superklaso)\s*=\s*\[', line, re.IGNORECASE):
            # Quote unquoted tokens in arrays, including #uuid and rdf/owl tags.
            fixed = re.sub(
                r'(?<=[\[,])\s*([#a-zA-Z0-9_:\-\.]+)\s*(?=[,\]])',
                lambda m: f'"{m.group(1).strip()}"',
                line
            )
            lines.append(fixed)
            continue
        
        lines.append(line)
    return '\n'.join(lines)


def _parse_enc_file(path: Path) -> dict:
    """Parse an .enc file and return a dict with the entry fields.

    The .enc format is TOML with an optional leading comment ``# title``.
    If the TOML itself contains a ``titolo`` key that takes precedence;
    otherwise the first ``# …`` comment is used as the title.
    """
    raw = _normalize_multiline_value_spacing(path.read_text(encoding="utf-8"))
    raw = _escape_latex_style_backslashes(raw)
    # Apply permissive fixes for common syntax errors
    raw = _fix_inline_table_commas(raw)
    raw = _fix_unquoted_uuids(raw)
    # Start with raw TOML text, then retry after stripping standalone enhavo block
    # if initial parse fails.
    raw_core = raw
    enhavo = ""

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
        stripped_core, extracted_enhavo = _extract_enhavo_block(raw)
        if stripped_core != raw:
            try:
                data = tomllib.loads(stripped_core)
                raw_core = stripped_core
                enhavo = extracted_enhavo
            except Exception as exc2:
                raise ValueError(_format_enc_parse_error(raw_core, exc)) from exc2
        else:
            raise ValueError(_format_enc_parse_error(raw_core, exc)) from exc

    _validate_enc_keys(data)

    terminologio, difinoj = _collect_lang_fields(data)
    if not terminologio and title_from_comment:
        terminologio = {"eo": title_from_comment}
    if not difinoj and isinstance(data.get("difinio"), str):
        maybe = data.get("difinio", "").strip()
        if maybe:
            difinoj["eo"] = maybe
    if not difinoj and isinstance(data.get("difino"), str):
        maybe = data.get("difino", "").strip()
        if maybe:
            difinoj["eo"] = maybe

    difinoj = {lang: _normalize_markdown_text(text) for lang, text in difinoj.items()}
    if not _has_minimum_term_definition_pair(terminologio, difinoj):
        raise ValueError(
            "Nevalida .enc: bezonata almenaŭ unu lingvo kun ambaŭ "
            "terminologio.xx kaj difino.xx."
        )

    titolo = next(iter(terminologio.values()))
    difinio = difinoj.get(next(iter(terminologio.keys())), "")
    if not difinio:
        difinio = next(iter(difinoj.values()))

    # superklaso: nur UUID-oj; ligilo: UUID aŭ [UUID, semantika_tipo]
    superklaso = _normalise_superklaso_refs(data.get("superklaso", []))
    ligilo = _serialize_ligilo_items(_normalize_ligilo_items(data.get("ligilo", [])))

    # fonto: list of dicts
    fonto: list[dict] = []
    raw_fonto = data.get("fonto", data.get("source", []))
    for item in raw_fonto:
        if isinstance(item, dict):
            normalized = {}
            for k, v in item.items():
                # Accept both English and Esperanto field names
                key_lower = k.lower()
                if key_lower in ("title", "titolo"):
                    normalized["titolo"] = str(v)
                elif key_lower in ("author", "autoro"):
                    normalized["autoro"] = str(v)
                elif key_lower in ("year", "jaro"):
                    # Enforce integer for year/jaro
                    try:
                        normalized["jaro"] = int(v)
                    except (ValueError, TypeError) as e:
                        raise ValueError(
                            f"Nevalida fonto.jaro: {v!r}. Devas esti entjero."
                        ) from e
                elif key_lower in ("type", "tipo"):
                    normalized["tipo"] = _normalize_fonto_tipo(str(v))
                elif key_lower in ("lang", "language", "lingvo"):
                    parsed_lingvoj = _normalize_lingvo_codes(
                        str(v), field="fonto.lingvo"
                    )
                    if parsed_lingvoj:
                        normalized["lingvo"] = ",".join(parsed_lingvoj)
                    else:
                        raise ValueError(f"Nevalida fonto.lingvo: {v!r}.")
                elif key_lower == "noto":
                    normalized["noto"] = str(v)
                elif key_lower == "ligilo":
                    normalized["ligilo"] = str(v)
                else:
                    # Preserve other fields as-is (like title.en, title.fr, etc.)
                    normalized[k] = str(v)
            fonto.append(normalized)

    # citajo: list of dicts
    citajo: list[dict] = []
    raw_citajo = data.get("citajo", [])
    if isinstance(raw_citajo, list):
        for item in raw_citajo:
            if not isinstance(item, dict):
                continue
            normalized_quote: dict[str, str] = {}
            for key in ("teksto", "autoro", "verko", "jaro"):
                if key in item and str(item[key]).strip():
                    normalized_quote[key] = str(item[key]).strip()
            if "lingvo" in item and str(item["lingvo"]).strip():
                parsed_lingvoj = _normalize_lingvo_codes(
                    str(item["lingvo"]), field="citajo.lingvo"
                )
                if parsed_lingvoj:
                    normalized_quote["lingvo"] = ",".join(parsed_lingvoj)
            if normalized_quote.get("teksto"):
                citajo.append(normalized_quote)

    # datumo: parse datumo.<name> JSON strings or datumo table object
    datumo: dict[str, dict] = {}
    for key, value in data.items():
        if not isinstance(key, str) or not key.startswith("datumo."):
            continue
        dataset_name = key.split(".", 1)[1].strip()
        if not dataset_name:
            continue
        if not isinstance(value, str):
            raise ValueError(f"Nevalida datumo.{dataset_name}: devas esti JSON-teksto.")
        try:
            parsed_json = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Nevalida datumo.{dataset_name}: JSON nevalida ({exc.msg})."
            ) from exc
        _validate_dataset_payload(dataset_name, parsed_json)
        datumo[dataset_name] = parsed_json
    datumo_obj = data.get("datumo")
    if isinstance(datumo_obj, dict):
        for dataset_name, payload in datumo_obj.items():
            if isinstance(payload, str):
                try:
                    parsed_json = json.loads(payload)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"Nevalida datumo.{dataset_name}: JSON nevalida ({exc.msg})."
                    ) from exc
                _validate_dataset_payload(str(dataset_name), parsed_json)
                datumo[str(dataset_name)] = parsed_json
            elif isinstance(payload, dict):
                _validate_dataset_payload(str(dataset_name), payload)
                datumo[str(dataset_name)] = payload

    return {
        "titolo": titolo,
        "difinio": difinio,
        "terminologio": terminologio,
        "difinoj": difinoj,
        "enhavo": enhavo,
        "superklaso": superklaso,
        "ligilo": ligilo,
        "fonto": fonto,
        "citajo": citajo,
        "datumo": datumo,
    }


def _validate_dataset_payload(name: str, payload: object) -> None:
    if not isinstance(payload, dict):
        raise ValueError(f"Nevalida datumo.{name}: devas esti JSON-objekto.")
    rows = payload.get("datumo")
    if not isinstance(rows, list) or not rows:
        raise ValueError(
            f"Nevalida datumo.{name}: 'datumo' devas esti ne-malplena listo."
        )


def _normalize_lingvo_codes(raw: str, *, field: str) -> list[str]:
    values = [part.strip().lower() for part in raw.split(",") if part.strip()]
    if not values:
        return []
    for code in values:
        if not re.fullmatch(r"[a-z]{2}", code):
            raise ValueError(
                f"Nevalida {field}: {raw!r}. "
                "Uzu 2-literajn kodojn apartigitajn per komoj."
            )
    deduped: list[str] = []
    for code in values:
        if code not in deduped:
            deduped.append(code)
    return deduped


def _escape_latex_style_backslashes(raw: str) -> str:
    """Escape common LaTeX-style backslash commands inside TOML strings.

    TOML treats backslash as escape in basic strings. Inputs like `\\uparrow`
    are invalid (`Invalid hex value`). We convert unknown escapes to literal
    backslashes while preserving valid TOML escapes.
    """
    if not raw:
        return raw
    out: list[str] = []
    in_basic = False
    in_multi_basic = False
    i = 0
    valid_single = set('btnfr"\\/')
    while i < len(raw):
        if not in_basic and not in_multi_basic and raw.startswith('"""', i):
            in_multi_basic = True
            out.append('"""')
            i += 3
            continue
        if in_multi_basic and raw.startswith('"""', i):
            in_multi_basic = False
            out.append('"""')
            i += 3
            continue
        ch = raw[i]
        if not in_multi_basic and ch == '"':
            escaped_quote = False
            if in_basic:
                backslashes = 0
                j = i - 1
                while j >= 0 and raw[j] == "\\":
                    backslashes += 1
                    j -= 1
                escaped_quote = (backslashes % 2) == 1
            if not escaped_quote:
                in_basic = not in_basic
            out.append(ch)
            i += 1
            continue
        if (in_basic or in_multi_basic) and ch == "\\" and i + 1 < len(raw):
            nxt = raw[i + 1]
            if nxt in valid_single:
                out.append(ch)
                out.append(nxt)
                i += 2
                continue
            if nxt == "u" and i + 6 <= len(raw):
                hex_part = raw[i + 2 : i + 6]
                if re.fullmatch(r"[0-9a-fA-F]{4}", hex_part):
                    out.append(ch)
                    out.append(nxt)
                    i += 2
                    continue
            if nxt == "U" and i + 10 <= len(raw):
                hex_part = raw[i + 2 : i + 10]
                if re.fullmatch(r"[0-9a-fA-F]{8}", hex_part):
                    out.append(ch)
                    out.append(nxt)
                    i += 2
                    continue
            out.append("\\\\")
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _extract_enhavo_block(raw: str) -> tuple[str, str]:
    lines = raw.splitlines()
    for start in range(len(lines)):
        if lines[start].strip() != '"""':
            continue
        prev_line = lines[start - 1].strip() if start > 0 else ""
        if "=" in prev_line and (
            re.search(r"=\s*$", prev_line) or re.search(r'=\s*"""$', prev_line)
        ):
            continue
        end = start + 1
        while end < len(lines) and lines[end].strip() != '"""':
            end += 1
        if end >= len(lines):
            continue
        enhavo = "\n".join(lines[start + 1 : end]).strip()
        kept: list[str] = []
        kept.extend(lines[:start])
        kept.extend(lines[end + 1 :])
        without = "\n".join(kept)
        if raw.endswith("\n"):
            without += "\n"
        return without, enhavo
    return raw, ""


def _normalize_markdown_text(text: str) -> str:
    """Normalize common markdown formatting issues for better readability."""
    if not text:
        return ""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        stripped = line.lstrip()
        if not stripped:
            out.append("")
            i += 1
            continue
        # Normalize headings and ensure one blank line after heading.
        if stripped.startswith("#"):
            out.append(stripped)
            if i + 1 < len(lines) and lines[i + 1].strip():
                out.append("")
            i += 1
            continue
        # Normalize indentation to multiples of 2 spaces.
        indent = len(line) - len(stripped)
        if indent:
            indent = (indent // 2) * 2
            out.append((" " * indent) + stripped)
        else:
            out.append(stripped)
        i += 1
    # Collapse excessive blank lines
    normalized: list[str] = []
    blank = 0
    for line in out:
        if line == "":
            blank += 1
            if blank <= 1:
                normalized.append(line)
        else:
            blank = 0
            normalized.append(line)
    return "\n".join(normalized).strip()


def _normalize_multiline_value_spacing(raw: str) -> str:
    """Accept extra spacing/newlines between '=' and triple-quoted difino values.

    This tolerance is intentionally scoped to difino.* fields.
    """
    pattern = re.compile(
        r"(^\s*(?:(?:difino|difinio)(?:\.[A-Za-z0-9_-]+)?)\s*=)\s*\n+\s*\"\"\"",
        re.MULTILINE,
    )
    return pattern.sub(r'\1 """', raw)


def _format_enc_parse_error(raw_toml: str, exc: Exception) -> str:
    message = f"Malformed .enc file: {exc}"
    lineno = getattr(exc, "lineno", None)
    colno = getattr(exc, "colno", None)
    if not isinstance(lineno, int):
        match = re.search(r"\(at line (\d+), column (\d+)\)", str(exc))
        if match:
            lineno = int(match.group(1))
            colno = int(match.group(2))
    if not isinstance(lineno, int) or lineno < 1:
        return message

    lines = raw_toml.splitlines()
    if lineno > len(lines):
        return message

    line = lines[lineno - 1]
    pointer = ""
    if isinstance(colno, int) and colno > 0:
        pointer = " " * max(colno - 1, 0) + "^"
    hints = _build_parse_hints(str(exc), line)
    hint_block = "\n".join(f"  - {hint}" for hint in hints)
    pointer_block = f"{pointer}\n" if pointer else ""
    return (
        f"{message}\n"
        f"Problema linio {lineno}: {line}\n"
        f"{pointer_block}"
        f"Sugestoj:\n{hint_block}"
    )


def _build_parse_hints(error_text: str, line: str) -> list[str]:
    lowered = error_text.lower()
    hints = [
        (
            "Uzu validan TOML-sintekson: ŝlosilo = valoro "
            '(ekz. terminologio.eo = "RS232").'
        ),
        "Kontrolu kampnomojn: terminologio.xx, difino.xx, superklaso, ligilo, fonto.",
    ]
    if "invalid value" in lowered:
        hints.append(
            "Kontrolu ĉu tekstoj estas en citiloj kaj listoj/tabeloj estas ĝuste "
            "fermitaj per ] aŭ }."
        )
    if "expected '=' after a key" in lowered:
        hints.append("Verŝajne mankas '=' inter kampnomo kaj valoro.")
    if "cannot overwrite a value" in lowered:
        hints.append("Sama ŝlosilo aperas plurfoje; forigu duplikatan kampon.")
    if "unterminated" in lowered or "unclosed" in lowered:
        hints.append("Mankas ferma citilo, ] aŭ }.")
    left_side = line.split("=", 1)[0].strip().lower()
    dotted_key_like = bool(re.match(r"^[a-z_][a-z0-9_]*(\.[a-z0-9_]+)+$", left_side))
    if (
        line.strip().endswith("=")
        and "invalid value" in lowered
        and dotted_key_like
    ):
        hints.append(
            "Por plurlinia teksto (`\"\"\"`), metu la malferman `\"\"\"` sur la "
            "sama linio kiel `=` (ekz. difino.fr = \"\"\"...)."
        )
    if "=" not in line:
        hints.append("Ĉiu kampolinio devus aspekti kiel: nomo = valoro")
    return hints


def _validate_enc_keys(data: dict) -> None:
    allowed_dotted_prefixes = {"terminologio", "difino", "difinio", "datumo"}
    for key in data:
        if "." in key:
            prefix = key.split(".", 1)[0]
            if prefix in allowed_dotted_prefixes:
                continue
            suggestion = _suggest_enc_dotted_key(key)
            raise ValueError(
                f"Nevalida .enc: nekonata kampo '{key}'. "
                f"Uzu ekz. terminologio.xx, difino.xx aŭ datumo.nomo.{suggestion}"
            )
        if key not in _ALLOWED_ENC_PLAIN_KEYS:
            suggestion = _suggest_enc_key(key, _ALLOWED_ENC_PLAIN_KEYS_SORTED)
            raise ValueError(
                f"Nevalida .enc: nekonata kampo '{key}'.{suggestion}"
            )


def _suggest_enc_key(key: str, allowed: tuple[str, ...]) -> str:
    match = get_close_matches(key, allowed, n=1, cutoff=0.6)
    if not match:
        return ""
    return f" Ĉu vi celis '{match[0]}'?"


def _suggest_enc_dotted_key(key: str) -> str:
    prefix = key.split(".", 1)[0].strip().lower()
    if not prefix:
        return ""
    match = get_close_matches(prefix, ["terminologio", "difino"], n=1, cutoff=0.6)
    if not match:
        return ""
    return f" Ĉu vi celis '{match[0]}.eo'?"


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
        if key.startswith("difino.") or key.startswith("difinio."):
            lang = key.split(".", 1)[1].strip().lower()
            if lang and value.strip():
                difinoj[lang] = value.strip().replace("\\n", "\n")

    if not terminologio and isinstance(data.get("terminologio"), dict):
        for lang, value in data["terminologio"].items():
            if str(value).strip():
                terminologio[str(lang).strip().lower()] = str(value).strip()

    difinio_obj = data.get("difinio")
    if not difinoj and isinstance(difinio_obj, dict):
        for lang, value in difinio_obj.items():
            if str(value).strip():
                difinoj[str(lang).strip().lower()] = str(value).strip().replace(
                    "\\n", "\n"
                )
    difino_obj = data.get("difino")
    if not difinoj and isinstance(difino_obj, dict):
        for lang, value in difino_obj.items():
            if str(value).strip():
                difinoj[str(lang).strip().lower()] = str(value).strip().replace(
                    "\\n", "\n"
                )

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


def _normalize_semantika_ligilo(raw: str | None) -> str | None:
    if raw is None:
        return None
    value = str(raw).strip()
    if not value:
        return None
    return _SEMANTIKAJ_LIGILOJ.get(value.lower(), value)


def _reverse_semantika_ligilo(raw: str | None) -> str | None:
    rel = _normalize_semantika_ligilo(raw)
    if rel == "rdfs:subClassOf":
        return "rdfs:superClassOf"
    if rel == "rdf:type":
        return "rdf:hasInstance"
    return rel


def _directional_semantic_family(rel: str | None) -> set[str]:
    normalized = _normalize_semantika_ligilo(rel)
    if normalized in {"rdf:type", "rdf:hasInstance"}:
        return {"rdf:type", "rdf:hasInstance"}
    if normalized in {"rdfs:subClassOf", "rdfs:superClassOf"}:
        return {"rdfs:subClassOf", "rdfs:superClassOf"}
    return {normalized} if normalized else set()


def _reconcile_all_semantic_reverse_links() -> None:
    all_entries = _load_all()
    changed: dict[str, dict] = {}
    expected_by_target: dict[str, set[tuple[str, str | None]]] = {}

    for source in all_entries:
        source_uuid = str(source.get("uuid") or "")
        if not source_uuid:
            continue
        for item in _public_ligilo_items(source):
            target = _find_by_uuid(str(item.get("uuid") or ""))
            if target is None:
                continue
            target_uuid = str(target.get("uuid") or "")
            reverse_sem = _reverse_semantika_ligilo(item.get("tipo"))
            expected_by_target.setdefault(target_uuid, set()).add(
                (source_uuid, reverse_sem)
            )

    def _load_auto_pairs(entry: dict) -> set[tuple[str, str | None]]:
        datumo = entry.get("datumo") if isinstance(entry.get("datumo"), dict) else {}
        raw = datumo.get(_AUTO_REVERSE_DATUMO_KEY) if isinstance(datumo, dict) else None
        items = _normalize_ligilo_items(raw or [])
        return {
            (str(i.get("uuid") or ""), _normalize_semantika_ligilo(i.get("tipo")))
            for i in items
            if str(i.get("uuid") or "")
        }

    def _save_auto_pairs(entry: dict, pairs: set[tuple[str, str | None]]) -> None:
        datumo = dict(entry.get("datumo") or {})
        ordered_pairs = sorted(pairs, key=lambda item: (item[0], item[1] or ""))
        payload = _serialize_ligilo_items(
            [{"uuid": uid, "tipo": sem} for uid, sem in ordered_pairs]
        )
        if payload:
            datumo[_AUTO_REVERSE_DATUMO_KEY] = payload
        else:
            datumo.pop(_AUTO_REVERSE_DATUMO_KEY, None)
        entry["datumo"] = datumo

    for target in all_entries:
        target_uuid = str(target.get("uuid") or "")
        if not target_uuid:
            continue
        expected_pairs = expected_by_target.get(target_uuid, set())
        auto_pairs = _load_auto_pairs(target)
        target_items_original = _normalize_ligilo_items(target.get("ligilo") or [])
        target_items = list(target_items_original)

        # Remove stale auto-managed reverse links.
        target_items = [
            item
            for item in target_items
            if (
                str(item.get("uuid") or ""),
                _normalize_semantika_ligilo(item.get("tipo")),
            )
            not in (auto_pairs - expected_pairs)
        ]

        # Add or repair expected reverse links, including wrong-direction cleanup.
        for source_uuid, reverse_sem in sorted(
            expected_pairs, key=lambda item: (item[0], item[1] or "")
        ):
            family = _directional_semantic_family(reverse_sem)
            target_items = [
                item
                for item in target_items
                if not (
                    str(item.get("uuid") or "") == source_uuid
                    and _normalize_semantika_ligilo(item.get("tipo")) in family
                    and _normalize_semantika_ligilo(item.get("tipo")) != reverse_sem
                )
            ]
            if not any(
                str(item.get("uuid") or "") == source_uuid
                and _normalize_semantika_ligilo(item.get("tipo")) == reverse_sem
                for item in target_items
            ):
                target_items.append({"uuid": source_uuid, "tipo": reverse_sem})

        original_serialized = _serialize_ligilo_items(target_items_original)
        reconciled_serialized = _serialize_ligilo_items(target_items)
        if original_serialized != reconciled_serialized or auto_pairs != expected_pairs:
            target["ligilo"] = reconciled_serialized
            _save_auto_pairs(target, expected_pairs)
            target["modifita_je"] = _now_iso()
            changed[target_uuid] = target

    for updated in changed.values():
        _update_entry(updated)


def _public_datumo(entry: dict) -> dict:
    data = entry.get("datumo")
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if k != _AUTO_REVERSE_DATUMO_KEY}


def _public_ligilo_items(entry: dict) -> list[dict[str, str | None]]:
    ligilo_items = _normalize_ligilo_items(entry.get("ligilo") or [])
    data = entry.get("datumo")
    if not isinstance(data, dict):
        return ligilo_items
    auto_raw = data.get(_AUTO_REVERSE_DATUMO_KEY)
    auto_items = _normalize_ligilo_items(auto_raw or [])
    auto_pairs = {
        (str(item.get("uuid") or ""), _normalize_semantika_ligilo(item.get("tipo")))
        for item in auto_items
    }
    return [
        item
        for item in ligilo_items
        if (
            str(item.get("uuid") or ""),
            _normalize_semantika_ligilo(item.get("tipo")),
        )
        not in auto_pairs
    ]


def _semantic_conflicts_for_entry(entry: dict, all_entries: list[dict]) -> list[str]:
    by_uuid = {str(e.get("uuid") or ""): e for e in all_entries if e.get("uuid")}
    source_uuid = str(entry.get("uuid") or "")
    if not source_uuid:
        return []
    by_uuid[source_uuid] = entry

    conflicts: list[str] = []
    source_links = _public_ligilo_items(entry)
    source_pairs: set[tuple[str, str | None]] = set()

    for link in source_links:
        target = _find_by_uuid(str(link.get("uuid") or ""))
        if target is None:
            continue
        target_uuid = str(target.get("uuid") or "")
        sem = _normalize_semantika_ligilo(link.get("tipo"))
        source_pairs.add((target_uuid, sem))

    for target_uuid, sem in sorted(
        source_pairs, key=lambda item: (item[0], item[1] or "")
    ):
        if sem in {"rdf:type", "rdf:hasInstance"} and (
            (target_uuid, "rdf:type") in source_pairs
            and (target_uuid, "rdf:hasInstance") in source_pairs
        ):
            title = _resolve_uuid_to_title(target_uuid)
            conflicts.append(
                f"- Kontraŭdiro inter rdf:type kaj rdf:hasInstance al {title} "
                f"(#{target_uuid[:8]}). Sugesto: konservu nur unu direkton."
            )
        if sem in {"rdfs:subClassOf", "rdfs:superClassOf"} and (
            (target_uuid, "rdfs:subClassOf") in source_pairs
            and (target_uuid, "rdfs:superClassOf") in source_pairs
        ):
            title = _resolve_uuid_to_title(target_uuid)
            conflicts.append(
                f"- Kontraŭdiro inter rdfs:subClassOf kaj rdfs:superClassOf al {title} "
                f"(#{target_uuid[:8]}). Sugesto: konservu nur unu direkton."
            )

        target_entry = by_uuid.get(target_uuid)
        if target_entry is None:
            continue
        reverse_links = _public_ligilo_items(target_entry)
        has_same_back = False
        for item in reverse_links:
            raw_back_ref = str(item.get("uuid") or "")
            resolved_back = _find_by_uuid(raw_back_ref)
            back_uuid = (
                str(resolved_back.get("uuid") or "")
                if resolved_back
                else raw_back_ref
            )
            if (
                back_uuid == source_uuid
                and _normalize_semantika_ligilo(item.get("tipo")) == sem
            ):
                has_same_back = True
                break
        if not has_same_back:
            continue
        title = _resolve_uuid_to_title(target_uuid)
        if sem == "rdf:hasInstance":
            conflicts.append(
                f"- Logika konflikto: #{source_uuid[:8]} kaj #{target_uuid[:8]} ambaŭ "
                f"uzas rdf:hasInstance. Sugesto: en la kontraŭa direkto uzu rdf:type."
            )
        elif sem == "rdf:type":
            conflicts.append(
                f"- Logika konflikto: #{source_uuid[:8]} kaj #{target_uuid[:8]} ambaŭ "
                "uzas rdf:type. Sugesto: la klasa flanko uzu rdf:hasInstance "
                f"al {title}."
            )
        elif sem == "rdfs:subClassOf":
            conflicts.append(
                f"- Logika konflikto: #{source_uuid[:8]} kaj #{target_uuid[:8]} ambaŭ "
                "uzas rdfs:subClassOf. Sugesto: en la kontraŭa direkto uzu "
                "rdfs:superClassOf."
            )
        elif sem == "rdfs:superClassOf":
            conflicts.append(
                f"- Logika konflikto: #{source_uuid[:8]} kaj #{target_uuid[:8]} ambaŭ "
                "uzas rdfs:superClassOf. Sugesto: en la kontraŭa direkto uzu "
                "rdfs:subClassOf."
            )
    return sorted(set(conflicts))


def _raise_if_semantic_conflicts(entry: dict) -> None:
    _reconcile_all_semantic_reverse_links()
    conflicts = _semantic_conflicts_for_entry(entry, _load_all())
    if not conflicts:
        return
    typer.echo("Semantika logika konflikto trovita en ligilo:", err=True)
    for line in conflicts:
        typer.echo(line, err=True)
    raise typer.Exit(code=1)


def _clean_uuid_ref(raw: str | None) -> str:
    return str(raw or "").strip().lstrip("#").strip()


def _normalise_uuids(raw: list | str) -> list:
    """Normalize superklaso/ligilo raw values while preserving semantic ligilo tags.

    Returns mixed list where each element is either:
    - "uuid"
    - ["uuid", "semantic-tag"]
    """
    if isinstance(raw, str):
        cleaned = _clean_uuid_ref(raw)
        return [cleaned] if cleaned else []
    if not isinstance(raw, list):
        return []
    result: list = []
    for item in raw:
        if isinstance(item, str):
            cleaned = _clean_uuid_ref(item)
            if cleaned:
                result.append(cleaned)
            continue
        if isinstance(item, list) and item:
            first = _clean_uuid_ref(str(item[0]))
            if not first:
                continue
            if len(item) >= 2:
                sem = _normalize_semantika_ligilo(str(item[1]))
                result.append([first, sem] if sem else first)
            else:
                result.append(first)
            continue
    return result


def _normalise_superklaso_refs(raw: list | str) -> list[str]:
    if isinstance(raw, str):
        cleaned = _clean_uuid_ref(raw)
        return [cleaned] if cleaned else []
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        if isinstance(item, str):
            cleaned = _clean_uuid_ref(item)
            if cleaned:
                out.append(cleaned)
            continue
        if isinstance(item, list):
            candidate = ""
            if len(item) >= 2:
                candidate = str(item[1])
            elif item:
                candidate = str(item[0])
            cleaned = _clean_uuid_ref(candidate)
            if cleaned:
                out.append(cleaned)
    return _normalize_uuid_list(out)


def _normalize_ligilo_items(raw: list | str) -> list[dict[str, str | None]]:
    normalized = _normalise_uuids(raw)
    items: list[dict[str, str | None]] = []
    for item in normalized:
        if isinstance(item, str):
            items.append({"uuid": item, "tipo": None})
        elif isinstance(item, list) and item:
            uuid_ref = _clean_uuid_ref(str(item[0]))
            if not uuid_ref:
                continue
            sem = _normalize_semantika_ligilo(str(item[1])) if len(item) > 1 else None
            items.append({"uuid": uuid_ref, "tipo": sem})
    deduped: list[dict[str, str | None]] = []
    seen: set[tuple[str, str | None]] = set()
    for item in items:
        key = (str(item["uuid"]), item.get("tipo"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _serialize_ligilo_items(items: list[dict[str, str | None]]) -> list:
    out: list = []
    for item in items:
        uid = _clean_uuid_ref(str(item.get("uuid") or ""))
        sem = _normalize_semantika_ligilo(item.get("tipo"))
        if not uid:
            continue
        if sem:
            out.append([uid, sem])
        else:
            out.append(uid)
    return out


def _resolve_uuid_to_title(uuid: str) -> str:
    """Resolve a UUID to its entry title. Returns shortened UUID if not found.
    
    Supports prefix matching (e.g., 'c487fa8b' matches 'c487fa8b-...-...').
    """
    normalized_uuid = str(uuid or "").strip().lstrip("#")
    conn = _get_conn()
    try:
        # Try exact match first
        row = conn.execute(
            "SELECT titolo FROM encik WHERE uuid = ?", (normalized_uuid,)
        ).fetchone()
        if row:
            return str(row["titolo"])
        
        # Try prefix match
        rows = conn.execute(
            "SELECT titolo FROM encik WHERE uuid LIKE ?", (normalized_uuid + "%",)
        ).fetchall()
        if len(rows) == 1:
            return str(rows[0]["titolo"])
        elif len(rows) > 1:
            # Multiple matches - return UUID with indicator
            return f"#{normalized_uuid[:8]}*"

        # Not found - return shortened UUID
        return f"#{normalized_uuid[:8]}"
    finally:
        conn.close()


def _proper_noun_sort_key(text: str) -> tuple[str, str]:
    cleaned = re.sub(r"[^0-9A-Za-zÀ-ÖØ-öø-ÿĈĜĤĴŜŬĉĝĥĵŝŭ]+", " ", str(text or ""))
    tokens = [tok for tok in cleaned.split() if tok]
    for tok in tokens:
        if tok[:1].isupper():
            return (tok.casefold(), str(text or "").casefold())
    return (str(text or "").casefold(), str(text or "").casefold())


def _ligilo_rank(item: dict[str, str | None]) -> tuple[int, tuple[str, str]]:
    sem = str(item.get("tipo") or "")
    rank_map = {
        "rdf:type": 0,
        "rdfs:subClassOf": 1,
        "owl:inverseOf": 2,
        "owl:disjointWith": 3,
    }
    rank = rank_map.get(sem, 4)
    title = _resolve_uuid_to_title(str(item.get("uuid") or ""))
    return (rank, _proper_noun_sort_key(title))


def _normalize_uuid_list(values: list) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for v in values:
        if isinstance(v, list) and v:
            s = _clean_uuid_ref(str(v[0]))
        else:
            s = _clean_uuid_ref(str(v or ""))
        if not s:
            continue
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _parse_ligilo_cli_values(values: list[str]) -> list:
    items: list[dict[str, str | None]] = []
    for raw in values:
        token = str(raw or "").strip()
        if not token:
            continue
        if ":" in token:
            uuid_part, tipo_part = token.split(":", 1)
            uuid_part = _clean_uuid_ref(uuid_part)
            tipo_norm = _normalize_semantika_ligilo(tipo_part)
            if uuid_part:
                items.append({"uuid": uuid_part, "tipo": tipo_norm})
        else:
            uuid_part = _clean_uuid_ref(token)
            if uuid_part:
                items.append({"uuid": uuid_part, "tipo": None})
    return _serialize_ligilo_items(items)


def _extract_markdown_ligilo_refs(text: str) -> list[dict[str, str | None]]:
    refs: list[dict[str, str | None]] = []
    for match in re.finditer(r"\[[^\]]+\]\(#([^)]+)\)", text or ""):
        raw = match.group(1).strip()
        if not raw:
            continue
        first, sep, second = raw.partition(",")
        uuid_raw = first.strip().lstrip("#")
        if not uuid_raw:
            continue
        sem = _normalize_semantika_ligilo(second.strip()) if sep else None
        target = _find_by_uuid(uuid_raw)
        resolved_uuid = str(target.get("uuid")) if target else uuid_raw
        refs.append({"uuid": resolved_uuid, "tipo": sem})
    return refs


def _extract_auto_ligilo_refs(parsed: dict) -> list[dict[str, str | None]]:
    refs: list[dict[str, str | None]] = []
    for value in (parsed.get("terminologio") or {}).values():
        refs.extend(_extract_markdown_ligilo_refs(str(value)))
    for value in (parsed.get("difinoj") or {}).values():
        refs.extend(_extract_markdown_ligilo_refs(str(value)))
    refs.extend(_extract_markdown_ligilo_refs(str(parsed.get("difinio") or "")))
    refs.extend(_extract_markdown_ligilo_refs(str(parsed.get("enhavo") or "")))
    for payload in (parsed.get("datumo") or {}).values():
        refs.extend(
            _extract_markdown_ligilo_refs(
                json.dumps(payload, ensure_ascii=False)
            )
        )
    return refs


def _merge_auto_ligilo_refs(parsed: dict) -> dict:
    current_items = _normalize_ligilo_items(parsed.get("ligilo") or [])
    auto_refs = _extract_auto_ligilo_refs(parsed)
    merged_items = current_items + auto_refs
    deduped: list[dict[str, str | None]] = []
    seen: set[tuple[str, str | None]] = set()
    for item in merged_items:
        uid = _clean_uuid_ref(str(item.get("uuid") or ""))
        tipo = _normalize_semantika_ligilo(item.get("tipo"))
        if not uid:
            continue
        key = (uid, tipo)
        if key in seen:
            continue
        seen.add(key)
        deduped.append({"uuid": uid, "tipo": tipo})
    parsed["ligilo"] = _serialize_ligilo_items(deduped)
    return parsed


def _parse_lang_assignments(values: list[str], *, field: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for item in values:
        raw = str(item or "").strip()
        if not raw:
            continue
        if ":" in raw:
            lang, value = raw.split(":", 1)
        elif "=" in raw:
            lang, value = raw.split("=", 1)
        else:
            raise ValueError(
                f"Nevalida {field} valoro: {item!r}. Uzu formatojn kiel eo:teksto."
            )
        lang = lang.strip().lower()
        value = value.strip()
        if not re.fullmatch(r"[a-z]{2}", lang):
            raise ValueError(
                f"Nevalida lingvokodo en {field}: {lang!r}. Uzu 2-literan kodon."
            )
        if not value:
            raise ValueError(f"Nevalida {field} valoro: malplena teksto por {lang}.")
        parsed[lang] = value
    return parsed


def _collect_encik_incoming_refs(
    all_entries: list[dict], target_uuids: set[str]
) -> list[str]:
    warnings: list[str] = []
    for source in all_entries:
        source_uuid = str(source.get("uuid") or "")
        if source_uuid in target_uuids:
            continue
        source_title = str(source.get("titolo") or source_uuid[:8] or "-")
        for parent_ref in _normalize_uuid_list(source.get("superklaso") or []):
            if parent_ref in target_uuids:
                warnings.append(
                    "- "
                    f"{source_title} (#{source_uuid[:8]}) -> superklaso al "
                    f"#{parent_ref[:8]}"
                )
        for link_item in _normalize_ligilo_items(source.get("ligilo") or []):
            link_ref = str(link_item.get("uuid") or "")
            if link_ref in target_uuids:
                warnings.append(
                    "- "
                    f"{source_title} (#{source_uuid[:8]}) -> ligilo al "
                    f"#{link_ref[:8]}"
                )
    return warnings


def _sync_bidirectional_relations_for_entry(entry: dict) -> None:
    """Keep ligilo/superklaso relationships consistent in both directions.

    - A.ligilo contains B  => B.ligilo contains A
    - B.superklaso contains A => A has B as subklaso (derived in display/search)
      and we ensure parent references are normalized.
    """
    all_entries = _load_all()
    by_uuid = {e["uuid"]: e for e in all_entries}
    current = by_uuid.get(entry["uuid"])
    if current is None:
        return

    changed: list[dict] = []
    current_lig_items = _normalize_ligilo_items(current.get("ligilo") or [])
    current_sup = _normalize_uuid_list(current.get("superklaso") or [])
    current["ligilo"] = _serialize_ligilo_items(current_lig_items)
    current["superklaso"] = current_sup
    current["modifita_je"] = _now_iso()
    changed.append(current)

    # Bidirectional ligilo with semantic inverse mapping where needed
    for item in current_lig_items:
        other_ref = str(item.get("uuid") or "")
        sem = _normalize_semantika_ligilo(item.get("tipo"))
        reverse_sem = _reverse_semantika_ligilo(sem)
        other = _find_by_uuid(other_ref)
        if other is None:
            continue
        other_lig_items = _normalize_ligilo_items(other.get("ligilo") or [])
        if not any(
            str(x.get("uuid") or "") == current["uuid"]
            and _normalize_semantika_ligilo(x.get("tipo")) == reverse_sem
            for x in other_lig_items
        ):
            other_lig_items.append({"uuid": current["uuid"], "tipo": reverse_sem})
            other["ligilo"] = _serialize_ligilo_items(other_lig_items)
            other["modifita_je"] = _now_iso()
            changed.append(other)

    # Normalize parent links (superklaso only stores UUID refs)
    for parent_ref in current_sup:
        parent = _find_by_uuid(parent_ref)
        if parent is None:
            continue
        # touch parent timestamp only when relation exists for visibility freshness
        parent["modifita_je"] = _now_iso()
        changed.append(parent)

    # Persist deduplicated updates
    updated: set[str] = set()
    for e in changed:
        uid = e["uuid"]
        if uid in updated:
            continue
        updated.add(uid)
        _update_entry(e)

    # Reconcile older records globally to keep semantic reverse links consistent.
    _reconcile_all_semantic_reverse_links()


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

    if montri_cxion and terminologio:
        panel_lines.append(f"  [dim]{'terminologio:':<14}[/dim]")
        for lang, term in sorted(terminologio.items()):
            panel_lines.append(f"    {lang}: {_render_markdown_text(term)}")

    difinio = (
        difinoj.get(selected_lang)
        or entry.get("difinio", "")
        or next(iter(difinoj.values()), "")
    ).strip()
    if montri_cxion and difinoj:
        panel_lines.append(f"  [dim]{'difino:':<14}[/dim]")
        for lang, term_def in sorted(difinoj.items()):
            panel_lines.append(f"    {lang}: {_render_markdown_text(term_def)}")
    elif difinio:
        panel_lines.append(f"  [dim]{'difino:':<14}[/dim]")
        for ln in difinio.splitlines():
            panel_lines.append(f"    {_render_markdown_text(ln)}")

    enhavo = (entry.get("enhavo") or "").strip()
    if enhavo and montri_cxion:
        panel_lines.append(f"  [dim]{'enhavo:':<14}[/dim]")
        for ln in enhavo.splitlines():
            panel_lines.append(f"    {_render_markdown_text(ln)}")

    superklaso = _normalize_uuid_list(entry.get("superklaso") or [])
    if superklaso:
        panel_lines.append(f"  [dim]{'superklaso:':<14}[/dim]")
        for parent_ref in superklaso:
            parent = _find_by_uuid(parent_ref)
            if parent is None:
                panel_lines.append(
                    f"    {_render_relation_cli_link('', str(parent_ref))}"
                )
            else:
                parent_title = str(parent["titolo"])
                parent_uuid = str(parent["uuid"])
                panel_lines.append(
                    f"    {_render_relation_cli_link(parent_title, parent_uuid)}"
                )

    if montri_cxion:
        sub = _subklasoj_of(entry["uuid"], max_depth=1)
        if sub:
            panel_lines.append(f"  [dim]{'subklaso:':<14}[/dim]")
            for child in sub:
                panel_lines.append(
                    f"    {child['titolo']}  [dim]#{child['uuid'][:8]}[/dim]"
                )

    ligilo_items = sorted(
        _normalize_ligilo_items(entry.get("ligilo") or []),
        key=_ligilo_rank,
    )
    if ligilo_items:
        panel_lines.append(f"  [dim]{'ligilo:':<14}[/dim]")
        for item in ligilo_items:
            uuid = str(item.get("uuid") or "")
            sem = item.get("tipo")
            linked_title = _resolve_uuid_to_title(uuid)
            line = _render_relation_cli_link(linked_title, uuid)
            if sem:
                detail = _resolve_uuid_to_title(uuid)
                line = f"[dim]{sem}[/dim] {line}"
                if detail and detail != f"#{uuid[:8]}":
                    line = (
                        f"[dim]{sem}[/dim] {detail} "
                        f"[dim]#{uuid[:8]}[/dim]"
                    )
            panel_lines.append(f"    {line}")

    fonto = entry.get("fonto") or []
    if fonto:
        panel_lines.append(f"  [dim]{'fonto:':<14}[/dim]")
        for s in fonto:
            parts = []
            if s.get("autoro"):
                parts.append(s["autoro"])
            if s.get("jaro"):
                parts.append(f"({s['jaro']})")
            if s.get("titolo"):
                parts.append(f'"{_render_markdown_text(str(s["titolo"]))}"')
            if s.get("tipo"):
                parts.append(f"tipo={s['tipo']}")
            if s.get("lingvo"):
                parts.append(f"lingvo={s['lingvo']}")
            if s.get("noto"):
                note_text = _render_markdown_text(str(s["noto"]))
                parts.append(
                    f"noto={json.dumps(note_text, ensure_ascii=False)}"
                )
            if s.get("ligilo"):
                parts.append(f"ligilo={_render_markdown_text(str(s['ligilo']))}")
            title_lang_items = sorted(
                (k, v) for k, v in s.items() if k.startswith("titolo.")
            )
            for k, v in title_lang_items:
                val_text = _render_markdown_text(str(v))
                parts.append(
                    f"{k}={json.dumps(val_text, ensure_ascii=False)}"
                )
            panel_lines.append(f"    {' '.join(parts)}")

    citajo = entry.get("citajo") or []
    if citajo:
        preferred_langs, should_show_hint = _load_user_language_preferences()
        visible_quotes = (
            citajo
            if montri_cxion
            else _filter_quotes_by_languages(citajo, preferred_langs)
        )
        panel_lines.append(f"  [dim]{'citajo:':<14}[/dim]")
        for quote in visible_quotes:
            text = _render_markdown_text(str(quote.get("teksto") or ""))
            autoro = str(quote.get("autoro") or "").strip()
            verko = str(quote.get("verko") or "").strip()
            jaro = str(quote.get("jaro") or "").strip()
            suffix_parts = [p for p in (autoro, verko, jaro) if p]
            suffix = f" — {'; '.join(suffix_parts)}" if suffix_parts else ""
            panel_lines.append(f"    \"{text}\"{suffix}")
        if should_show_hint and not montri_cxion:
            panel_lines.append(f"    [dim]{_language_preference_hint()}[/dim]")

    datumo = entry.get("datumo") or {}
    datumo = _public_datumo(entry)
    if datumo:
        panel_lines.append(f"  [dim]{'datumo:':<14}[/dim]")
        for ds_name, payload in sorted(datumo.items()):
            rows = payload.get("datumo") if isinstance(payload, dict) else None
            row_count = len(rows) if isinstance(rows, list) else 0
            panel_lines.append(f"    {ds_name}: {row_count} vico(j)")

    if montri_cxion:
        kj = entry.get("kreita_je", "")[:10]
        mj = entry.get("modifita_je", "")[:10]
        panel_lines.append(f"  [dim]{'kreita_je:':<14}[/dim] {kj}")
        panel_lines.append(f"  [dim]{'modifita_je:':<14}[/dim] {mj}")

    display_title = _render_markdown_text(title)
    console.print(
        Panel(
            "\n".join(panel_lines),
            title=f"[bold]{display_title}[/bold]",
            expand=False,
        )
    )


def _markdown_to_html_fragment(md_text: str) -> str:
    return _markdown_to_html_fragment_with_links(md_text, link_depth=0)


def _render_markdown_text(text: str) -> str:
    """Render markdown-ish text for CLI output with clickable links when possible."""
    if not text:
        return ""

    def _replace_internal(match: re.Match[str]) -> str:
        label = match.group(1).strip()
        raw_ref = match.group(2).strip()
        ref = raw_ref.split(",", 1)[0].strip().lstrip("#")
        target = _find_by_uuid(ref)
        if not target:
            return label
        target_html = _render_entry_html(target, link_depth=1)
        target_path = _write_html_document(target_html)
        return f"[link=file://{target_path}]{label}[/link]"

    def _replace_external(match: re.Match[str]) -> str:
        label = match.group(1).strip()
        href = match.group(2).strip()
        if href.startswith(("http://", "https://", "file://")):
            return f"[link={href}]{label}[/link]"
        return label

    rendered = re.sub(r"\[([^\]]+)\]\(#([^)]+)\)", _replace_internal, text)
    rendered = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", _replace_external, rendered)
    rendered = re.sub(r"(\*\*|__|\*|_|`)", "", rendered)
    return rendered


def _render_relation_cli_link(label: str, ref: str) -> str:
    """Render a clickable CLI relation link for an encik UUID reference."""
    normalized_ref = str(ref or "").strip().lstrip("#")
    target = _find_by_uuid(normalized_ref)
    short_ref = normalized_ref[:8]
    clean_label = str(label or "").strip()
    if clean_label.startswith("##"):
        clean_label = "#" + clean_label.lstrip("#")
    if re.fullmatch(r"#?[0-9a-fA-F]{1,8}\*?", clean_label):
        clean_label = f"#{short_ref}"
    if not target:
        if clean_label:
            if clean_label == f"#{short_ref}":
                return f"[dim]{clean_label}[/dim]"
            return f"{clean_label} [dim]#{short_ref}[/dim]"
        return f"[dim]#{short_ref}[/dim]"
    target_html = _render_entry_html(target, link_depth=1)
    target_path = _write_html_document(target_html)
    short_target = str(target.get("uuid") or "")[:8]
    shown_label = clean_label or str(target.get("titolo") or "")
    return (
        f"[link=file://{target_path}]{shown_label}[/link] "
        f"[dim]#{short_target}[/dim]"
    )


def _render_relation_html_link(label: str, ref: str, *, link_depth: int = 0) -> str:
    """Render an HTML relation link for an encik UUID reference."""
    normalized_ref = str(ref or "").strip().lstrip("#")
    target = _find_by_uuid(normalized_ref)
    short_ref = normalized_ref[:8]
    clean_label = str(label or "").strip()
    if clean_label.startswith("##"):
        clean_label = "#" + clean_label.lstrip("#")
    if re.fullmatch(r"#?[0-9a-fA-F]{1,8}\*?", clean_label):
        clean_label = f"#{short_ref}"
    if not target:
        if clean_label:
            if clean_label == f"#{short_ref}":
                return escape(clean_label)
            return f"{escape(clean_label)} #{escape(short_ref)}"
        return f"#{escape(short_ref)}"
    shown_label = clean_label or str(target.get("titolo") or "")
    short_target = str(target.get("uuid") or "")[:8]
    if link_depth > 0:
        return f"{escape(shown_label)} #{escape(short_target)}"
    target_html = _render_entry_html(target, link_depth=1)
    target_path = _write_html_document(target_html)
    return (
        f'<a href="file://{escape(target_path)}">{escape(shown_label)}</a> '
        f"#{escape(short_target)}"
    )


def _markdown_to_html_fragment_with_links(md_text: str, *, link_depth: int = 0) -> str:
    if link_depth <= 0:
        md_text = _replace_internal_markdown_links_with_file_urls(md_text)
    try:
        import markdown  # type: ignore[import-untyped]
    except ImportError:
        return f"<pre>{escape(md_text)}</pre>"
    extensions = ["extra", "toc", "tables", "fenced_code", "codehilite"]
    try:
        return markdown.markdown(md_text, extensions=extensions)
    except Exception:
        return markdown.markdown(md_text)


def _replace_internal_markdown_links_with_file_urls(md_text: str) -> str:
    if not md_text:
        return ""

    def _replace(match: re.Match[str]) -> str:
        label = match.group(1).strip()
        ref = match.group(2).strip().lstrip("#")
        target = _find_by_uuid(ref)
        if not target:
            return f"{label} (#{ref[:8]})"
        target_html = _render_entry_html(target, link_depth=1)
        target_path = _write_html_document(target_html)
        return f"[{label}](file://{target_path})"

    return re.sub(r"\[([^\]]+)\]\(#([^)]+)\)", _replace, md_text)


def _json_to_html_pretty(payload: object) -> str:
    dumped = json.dumps(payload, ensure_ascii=False, indent=2)
    return f"<pre>{escape(dumped)}</pre>"


def _render_entry_html(
    entry: dict,
    *,
    lingvo: str | None = None,
    montri_cxion: bool = False,
    link_depth: int = 0,
) -> str:
    terminologio = entry.get("terminologio") or {}
    difinoj = entry.get("difinoj") or {}
    selected_lang = (lingvo or "").strip().lower() or _preferred_lang(
        terminologio, difinoj
    )
    title = (
        terminologio.get(selected_lang)
        or entry.get("titolo", "")
        or next(iter(terminologio.values()), "")
    )
    difinio = (
        difinoj.get(selected_lang)
        or entry.get("difinio", "")
        or next(iter(difinoj.values()), "")
    ).strip()
    difinio_html = (
        _markdown_to_html_fragment_with_links(difinio, link_depth=link_depth)
        if difinio
        else ""
    )

    rows: list[tuple[str, str]] = [
        ("uuid", escape((entry.get("uuid") or "")[:8])),
        ("lingvo", escape(selected_lang or "-")),
    ]
    if montri_cxion and terminologio:
        terms = "<br>".join(
            f"{escape(lang)}: "
            f"{_markdown_to_html_fragment_with_links(str(term), link_depth=link_depth)}"
            for lang, term in sorted(terminologio.items())
        )
        rows.append(("terminologio", terms))
    if montri_cxion and difinoj:
        defs = "<br>".join(
            f"{escape(lang)}: "
            f"{_markdown_to_html_fragment_with_links(term_def, link_depth=link_depth)}"
            for lang, term_def in sorted(difinoj.items())
        )
        rows.append(("difino", defs))
    elif difinio_html:
        rows.append(("difino", difinio_html))

    enhavo = (entry.get("enhavo") or "").strip()
    if enhavo and montri_cxion:
        rows.append(
            (
                "enhavo",
                _markdown_to_html_fragment_with_links(enhavo, link_depth=link_depth),
            )
        )

    superklaso = _normalize_uuid_list(entry.get("superklaso") or [])
    if superklaso:
        sup = "<br>".join(
            _render_relation_html_link(
                _resolve_uuid_to_title(str(uid)), str(uid), link_depth=link_depth
            )
            for uid in superklaso
        )
        rows.append(("superklaso", sup))

    if montri_cxion:
        sub = _subklasoj_of(entry["uuid"], max_depth=1)
        if sub:
            sub_rows = "<br>".join(
                f"{escape(e['titolo'])} #{escape(e['uuid'][:8])}" for e in sub
            )
            rows.append(("subklaso", sub_rows))

    ligilo_items = sorted(
        _normalize_ligilo_items(entry.get("ligilo") or []),
        key=_ligilo_rank,
    )
    if ligilo_items:
        links = "<br>".join(
            (
                (
                    f"<span style='color:#9aa;'>{escape(str(item.get('tipo')))}</span> "
                    if item.get("tipo")
                    else ""
                )
                + _render_relation_html_link(
                    _resolve_uuid_to_title(str(item.get("uuid") or "")),
                    str(item.get("uuid") or ""),
                    link_depth=link_depth,
                )
            )
            for item in ligilo_items
        )
        rows.append(("ligilo", links))

    fonto = entry.get("fonto") or []
    if fonto:
        fonto_lines: list[str] = []
        for s in fonto:
            parts: list[str] = []
            if s.get("autoro"):
                parts.append(
                    _markdown_to_html_fragment_with_links(
                        str(s["autoro"]), link_depth=link_depth
                    )
                )
            if s.get("jaro"):
                parts.append(f"({escape(str(s['jaro']))})")
            if s.get("titolo"):
                title_html = _markdown_to_html_fragment_with_links(
                    str(s["titolo"]), link_depth=link_depth
                )
                parts.append(
                    f'"{title_html}"'
                )
            if s.get("tipo"):
                parts.append(f"tipo={escape(str(s['tipo']))}")
            if s.get("lingvo"):
                parts.append(f"lingvo={escape(str(s['lingvo']))}")
            title_lang_items = sorted(
                (k, v)
                for k, v in s.items()
                if isinstance(k, str) and k.startswith("title.")
            )
            for k, v in title_lang_items:
                val_html = _markdown_to_html_fragment_with_links(
                    str(v), link_depth=link_depth
                )
                parts.append(
                    f"{escape(k)}="
                    f"{val_html}"
                )
            fonto_lines.append(" ".join(parts))
        rows.append(("fonto", "<br>".join(fonto_lines)))

    citajo = entry.get("citajo") or []
    if citajo:
        preferred_langs, should_show_hint = _load_user_language_preferences()
        visible_quotes = (
            citajo
            if montri_cxion
            else _filter_quotes_by_languages(citajo, preferred_langs)
        )
        quote_lines: list[str] = []
        for quote in visible_quotes:
            text_html = _markdown_to_html_fragment_with_links(
                str(quote.get("teksto") or ""), link_depth=link_depth
            )
            meta_parts = [
                escape(str(quote.get("autoro") or "")),
                escape(str(quote.get("verko") or "")),
                escape(str(quote.get("jaro") or "")),
            ]
            meta = " ; ".join([m for m in meta_parts if m])
            if meta:
                quote_lines.append(f"“{text_html}” — {meta}")
            else:
                quote_lines.append(f"“{text_html}”")
        if should_show_hint and not montri_cxion:
            quote_lines.append(f"<em>{escape(_language_preference_hint())}</em>")
        rows.append(("citajo", "<br>".join(quote_lines)))

    datumo = _public_datumo(entry)
    if datumo:
        data_sections: list[str] = []
        for ds_name, payload in sorted(datumo.items()):
            section = f"<h3>{escape(str(ds_name))}</h3>{_json_to_html_pretty(payload)}"
            data_sections.append(section)
        rows.append(("datumo", "".join(data_sections)))

    if montri_cxion:
        rows.extend(
            [
                ("kreita_je", escape((entry.get("kreita_je") or "")[:10])),
                ("modifita_je", escape((entry.get("modifita_je") or "")[:10])),
            ]
        )
    table_rows = "".join(
        f"<tr><th>{escape(label)}</th><td>{value}</td></tr>" for label, value in rows
    )
    html_title = _markdown_to_html_fragment_with_links(title, link_depth=link_depth)
    # Keep <title> plain-text-ish for browser tab labels.
    meta_title = re.sub(r"[\[\]()`*_#]", "", title).strip() or "encik"
    return (
        "<!DOCTYPE html>"
        '<html lang="eo"><head><meta charset="utf-8">'
        f"<title>{escape(meta_title)}</title>"
        '<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css">'
        '<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js"></script>'
        '<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.min.js"></script>'
        "<style>"
        "body{font-family:system-ui,-apple-system,sans-serif;max-width:980px;"
        "margin:2rem auto;padding:0 1rem;color:#333;line-height:1.5;}"
        "table{width:100%;border-collapse:collapse;}"
        "th,td{border:1px solid #ddd;padding:.6rem;vertical-align:top;}"
        "th{width:180px;background:#f5f5f5;text-align:left;}"
        "pre{margin:0;white-space:pre-wrap;background:#fafafa;padding:.6rem;border-radius:4px;}"
        "</style></head><body>"
        f"<h1>{html_title}</h1>"
        f"<table>{table_rows}</table>"
        "<script>"
        "document.addEventListener('DOMContentLoaded', function(){"
        "if(window.renderMathInElement){"
        "renderMathInElement(document.body,{"
        "delimiters:[{left:'$$',right:'$$',display:true},{left:'$',right:'$',display:false}]"
        "});"
        "}"
        "});"
        "</script>"
        "</body></html>"
    )


def _filter_quotes_by_languages(
    quotes: list[dict], preferred_langs: list[str]
) -> list[dict]:
    if not preferred_langs:
        return quotes
    preferred = {code.lower() for code in preferred_langs}
    filtered: list[dict] = []
    for quote in quotes:
        raw = str(quote.get("lingvo") or "").strip().lower()
        if not raw:
            filtered.append(quote)
            continue
        quote_langs = {part.strip() for part in raw.split(",") if part.strip()}
        if quote_langs & preferred:
            filtered.append(quote)
    return filtered


def _load_user_language_preferences() -> tuple[list[str], bool]:
    """Return (languages, show_hint) from uzanto profile.

    show_hint is True when no valid language preference exists.
    """
    try:
        from autish.commands.uzanto import _load_profile  # noqa: PLC0415
    except Exception:
        return [], True
    try:
        profile = _load_profile()
    except Exception:
        return [], True
    raw_langs = profile.get("lingvoj")
    if not isinstance(raw_langs, list):
        return [], True
    valid: list[str] = []
    invalid_found = False
    for item in raw_langs:
        code = str(item).strip().lower()
        if re.fullmatch(r"[a-z]{2}", code):
            if code not in valid:
                valid.append(code)
        elif code:
            invalid_found = True
    if not valid:
        return [], True
    return valid, invalid_found


def _language_preference_hint() -> str:
    langs, _ = _load_user_language_preferences()
    ui_lang = langs[0] if langs and langs[0] in {"eo", "en", "fr"} else "eo"
    messages = {
        "eo": (
            "Konsilo: agordu lingvojn per "
            "uzanto profilo modifi -L eo,en,fr por personecigi citaĵojn."
        ),
        "en": (
            "Hint: set languages with "
            "uzanto profilo modifi -L eo,en,fr to personalize quote display."
        ),
        "fr": (
            "Astuce : définissez vos langues avec "
            "uzanto profilo modifi -L eo,en,fr pour personnaliser les citations."
        ),
    }
    return messages.get(ui_lang, messages["eo"])


def _write_html_document(html_doc: str) -> str:
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".html", delete=False, encoding="utf-8"
    ) as fh:
        fh.write(html_doc)
        return fh.name


def _open_html_document(html_doc: str) -> str:
    tmp_path = _write_html_document(html_doc)
    # Keep the file for browser access; temporary browser previews may accumulate.
    webbrowser.open(f"file://{tmp_path}")
    return tmp_path


def _print_candidates(candidates: list[dict]) -> None:
    env_lang = (os.environ.get("LC_ALL") or os.environ.get("LANG") or "").split(".")[0]
    env_lang = env_lang.split("_")[0].lower()
    table = Table(show_header=True, header_style="dim", box=None)
    table.add_column("#", style="dim", width=3)
    table.add_column("UUID", style="dim", width=10)
    table.add_column("Titolo")
    for i, e in enumerate(candidates, 1):
        terms = e.get("terminologio") or {}
        display_title = (
            terms.get(env_lang)
            or terms.get("eo")
            or e.get("titolo")
            or next(iter(terms.values()), "")
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

    root = _find_by_uuid(root_uuid)
    if root is None:
        return []
    root_full_uuid = root["uuid"]

    # Build a parent-UUID → list-of-child-entries index
    children_of: dict[str, list[dict]] = {}
    for entry in all_entries:
        for parent_ref in _normalize_uuid_list(entry.get("superklaso") or []):
            parent = _find_by_uuid(parent_ref)
            if parent is None:
                continue
            parent_uuid = parent["uuid"]
            children_of.setdefault(parent_uuid, []).append(entry)

    visited: set[str] = {root_full_uuid}
    results: list[dict] = []
    queue: deque[tuple[str, int]] = deque([(root_full_uuid, 0)])

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
    root = _find_by_uuid(root_uuid)
    if root is None:
        return []
    root_full_uuid = root["uuid"]

    visited: set[str] = {root_full_uuid}
    results: list[dict] = []
    queue: deque[tuple[str, int]] = deque([(root_full_uuid, 0)])

    while queue:
        current_uuid, depth = queue.popleft()
        if max_depth > 0 and depth >= max_depth:
            continue
        entry = _find_by_uuid(current_uuid)
        if entry is None:
            continue
        for parent_ref in _normalize_uuid_list(entry.get("superklaso") or []):
            parent = _find_by_uuid(parent_ref)
            if parent is None:
                continue
            parent_uuid = parent["uuid"]
            if parent_uuid in visited:
                continue
            visited.add(parent_uuid)
            results.append(parent)
            queue.append((parent_uuid, depth + 1))
    return results


def _linked_graph_of(
    root_uuid: str, max_depth: int
) -> tuple[list[dict], list[tuple[str, str, str, str | None]]]:
    all_entries = _load_all()
    by_uuid = {str(e.get("uuid") or ""): e for e in all_entries}
    root = _find_by_uuid(root_uuid)
    if root is None:
        return [], []
    start_uuid = str(root["uuid"])
    children_of: dict[str, list[str]] = {}
    parents_of: dict[str, list[str]] = {}
    links_of: dict[str, list[str]] = {}
    for entry in all_entries:
        uid = str(entry.get("uuid") or "")
        if not uid:
            continue
        for parent_ref in _normalize_uuid_list(entry.get("superklaso") or []):
            parent = _find_by_uuid(parent_ref)
            if not parent:
                continue
            parent_uuid = str(parent["uuid"])
            parents_of.setdefault(uid, []).append(parent_uuid)
            children_of.setdefault(parent_uuid, []).append(uid)
        links = []
        for link_item in _normalize_ligilo_items(entry.get("ligilo") or []):
            target = _find_by_uuid(str(link_item.get("uuid") or ""))
            if target:
                links.append(str(target["uuid"]))
        if links:
            links_of.setdefault(uid, [])
            links_of[uid].extend(_normalize_uuid_list(links))
            for linked_uuid in links:
                links_of.setdefault(linked_uuid, [])
                links_of[linked_uuid].append(uid)

    visited: set[str] = {start_uuid}
    queue: deque[tuple[str, int]] = deque([(start_uuid, 0)])
    edges: list[tuple[str, str, str, str | None]] = []
    seen_edges: set[tuple[str, str, str, str | None]] = set()
    while queue:
        current_uuid, depth = queue.popleft()
        if max_depth > 0 and depth >= max_depth:
            continue
        for child_uuid in children_of.get(current_uuid, []):
            edge = (current_uuid, child_uuid, "subklaso", None)
            if edge not in seen_edges:
                seen_edges.add(edge)
                edges.append(edge)
            if child_uuid not in visited:
                visited.add(child_uuid)
                queue.append((child_uuid, depth + 1))
        for parent_uuid in parents_of.get(current_uuid, []):
            edge = (current_uuid, parent_uuid, "superklaso", None)
            if edge not in seen_edges:
                seen_edges.add(edge)
                edges.append(edge)
            if parent_uuid not in visited:
                visited.add(parent_uuid)
                queue.append((parent_uuid, depth + 1))
        for linked_uuid in links_of.get(current_uuid, []):
            edge = (current_uuid, linked_uuid, "ligilo", None)
            if edge not in seen_edges:
                seen_edges.add(edge)
                edges.append(edge)
            if linked_uuid not in visited:
                visited.add(linked_uuid)
                queue.append((linked_uuid, depth + 1))
        current_entry = by_uuid.get(current_uuid)
        if current_entry:
            for link_item in _normalize_ligilo_items(current_entry.get("ligilo") or []):
                target = _find_by_uuid(str(link_item.get("uuid") or ""))
                if not target:
                    continue
                target_uuid = str(target["uuid"])
                sem = link_item.get("tipo")
                edge = (current_uuid, target_uuid, "ligilo", sem)
                if edge not in seen_edges:
                    seen_edges.add(edge)
                    edges.append(edge)
                if target_uuid not in visited:
                    visited.add(target_uuid)
                    queue.append((target_uuid, depth + 1))
    nodes = [by_uuid[uid] for uid in visited if uid in by_uuid]
    nodes.sort(key=lambda e: str(e.get("titolo") or "").lower())
    return nodes, edges


def _render_linked_graph_html(
    root: dict, nodes: list[dict], edges: list[tuple[str, str, str, str | None]]
) -> str:
    node_json = []
    for entry in nodes:
        uid = str(entry.get("uuid") or "")
        node_json.append({
            "id": uid,
            "label": str(entry.get("titolo") or uid[:8]),
            "title": f"#{uid[:8]}",
            "shape": "dot",
            "size": 22 if uid == str(root.get("uuid")) else 14,
            "color": "#f5a524" if uid == str(root.get("uuid")) else "#5dade2",
        })
    edge_json = []
    for src, dst, rel, sem in edges:
        if rel == "ligilo":
            label = sem or "ligilo"
            edge_json.append(
                {
                    "from": src,
                    "to": dst,
                    "label": label,
                    "color": {"color": "#27ae60"},
                }
            )
        elif rel == "subklaso":
            edge_json.append(
                {
                    "from": src,
                    "to": dst,
                    "label": "sub",
                    "arrows": "to",
                    "color": {"color": "#8e44ad"},
                }
            )
        else:
            edge_json.append(
                {
                    "from": src,
                    "to": dst,
                    "label": "sup",
                    "arrows": "to",
                    "color": {"color": "#e67e22"},
                }
            )
    root_label = escape(str(root.get("titolo") or root.get("uuid") or "nodo"))
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>encik ligilo mapo</title>"
        "<script src='https://unpkg.com/vis-network@9.1.9/"
        "dist/vis-network.min.js'></script>"
        "<style>body{font-family:system-ui,sans-serif;margin:0;padding:1rem;"
        "background:#111;color:#eee;}"
        "#net{height:85vh;border:1px solid #333;border-radius:8px;"
        "background:#1b1b1b;}h1{font-size:1rem;}</style>"
        "</head><body>"
        f"<h1>Rilata mapo por {root_label}</h1>"
        "<div id='net'></div><script>"
        f"const nodes = new vis.DataSet({json.dumps(node_json, ensure_ascii=False)});"
        f"const edges = new vis.DataSet({json.dumps(edge_json, ensure_ascii=False)});"
        "const container=document.getElementById('net');"
        "const data={nodes,edges};"
        "const options={interaction:{hover:true},"
        "physics:{stabilization:true},edges:{font:{align:'middle'}}};"
        "new vis.Network(container,data,options);"
        "</script></body></html>"
    )


def _paralela_of(root_uuid: str, max_results: int) -> list[dict]:
    """Find sister classes: entries that share at least one parent with *root_uuid*."""
    root = _find_by_uuid(root_uuid)
    if root is None:
        return []
    root_parents: set[str] = set()
    for parent_ref in _normalize_uuid_list(root.get("superklaso") or []):
        parent = _find_by_uuid(parent_ref)
        if parent is not None:
            root_parents.add(parent["uuid"])
    if not root_parents:
        return []

    all_entries = _load_all()
    sisters: list[dict] = []
    for entry in all_entries:
        if entry["uuid"] == root_uuid:
            continue
        entry_parents: set[str] = set()
        for parent_ref in _normalize_uuid_list(entry.get("superklaso") or []):
            parent = _find_by_uuid(parent_ref)
            if parent is not None:
                entry_parents.add(parent["uuid"])
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
            "  [dim]serci[/dim]      encik serci <demando>",
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
            "Vojo al .enc dosiero.\n"
            "\n"
            "Formato (ĉiu elemento sur nova linio):\n"
            "  terminologio.xx = \"...\"\n"
            "  difino.xx = \"...\"\n"
            "  \"\"\"laŭvola libera teksto\"\"\"\n"
            "  superklaso = [\"uuid1\", \"uuid2\"]\n"
            "  ligilo = [\"uuid1\", [\"uuid2\", \"rdf:type\"],\n"
            "            [\"uuid3\", \"owl:inverseOf\"]]\n"
            "  fonto = [{titolo=\"...\", autoro=\"...\", jaro=2020, tipo=\"libroj\", "
            "noto=\"...\", ligilo=\"https://...\", lingvo=\"eo,en\"}]\n"
            "  citajo = [{teksto=\"...\", autoro=\"...\", verko=\"...\", "
            "jaro=\"...\", lingvo=\"eo,fr\"}]\n"
            "  datumo.<nomo> = \"\"\"{...json...}\"\"\"  # nomo devas esti unika\n"
            "\n"
            "Komentoj en .enc dosiero:\n"
            "  # tiu ĉi estas komento\n"
            "\n"
            "JSON-datumo: datumo.<nomo> = \"\"\"{...}\"\"\".\n"
            "Datumo-kampoj:\n"
            "  - metriko (laŭvola): ĉeno aŭ plurlingva objekto.\n"
            "  - meta (laŭvola): objekto kun identigaj metadatumoj; valoroj povas esti "
            "unuopaj aŭ plurlingvaj objektoj.\n"
            "  - datumo (deviga): listo de vicoj; "
            "unua vico povas esti kolumnetikedoj.\n"
            "  - etikedo (laŭvola): plurlingvaj kolumnaj etikedoj.\n"
            "\n"
            "Semantikaj ligiloj (laŭvolaj en ligilo):\n"
            "  rdf:type         # estas tipo de\n"
            "  rdfs:subClassOf  # subklaso de\n"
            "  owl:disjointWith # malkongrua kun\n"
            "  owl:inverseOf    # inversa de\n"
            "\n"
            "Validaj fonto.tipo:\n"
            "  libroj, artikoloj, retejoj, filmoj, tezoj, raportoj, podkastoj, "
            "prelegoj\n"
            "Aliasoj:\n"
            "  lib, art, ret, fil, tez, rap, pod, pre"
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
    parsed = _merge_auto_ligilo_refs(parsed)

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
            difinio=parsed["difinio"],
            terminologio=parsed["terminologio"],
            difinoj=parsed["difinoj"],
            enhavo=parsed["enhavo"],
            superklaso=parsed["superklaso"],
            ligilo=parsed["ligilo"],
            fonto=parsed["fonto"],
            citajo=parsed["citajo"],
            datumo=parsed["datumo"],
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
    _raise_if_semantic_conflicts(entry)
    _insert_entry(entry)
    _sync_bidirectional_relations_for_entry(entry)
    typer.echo(f"Aldonis #{entry['uuid'][:8]}  \"{entry['titolo']}\"")


@app.command("modifi")
def modifi(
    ref: str | None = typer.Argument(
        None, help="Terminologio (parta aŭ ekzakta) aŭ UUID de redaktota nodo."
    ),
    dosiero: Path | None = typer.Argument(
        None,
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help="Nova .enc dosiero por rekta anstataŭigo (sen redaktilo).",
    ),
    titolo: str | None = typer.Option(None, "--titolo", help="Nova ĉefa titolo."),
    difinio: str | None = typer.Option(
        None, "--difinio", help="Nova ĉefa difino."
    ),
    termino: list[str] | None = typer.Option(
        None,
        "-t",
        "--terminologio",
        help="Anstataŭigi/aldoni terminon laŭ lingvo: xx:teksto (ripetebla).",
    ),
    termino_difino: list[str] | None = typer.Option(
        None,
        "-d",
        "--difino",
        help="Anstataŭigi/aldoni difinon laŭ lingvo: xx:teksto (ripetebla).",
    ),
    enhavo: str | None = typer.Option(None, "--enhavo", help="Nova enhavo."),
    superklaso: list[str] | None = typer.Option(
        None, "--superklaso", help="Anstataŭigi superklaso-liston (ripetebla)."
    ),
    ligilo: list[str] | None = typer.Option(
        None,
        "--ligilo",
        help=(
            "Anstataŭigi ligilo-liston (ripetebla). Formoj: UUID aŭ UUID:semantiko "
            "(ekz. #abc:rdf:type)."
        ),
    ),
) -> None:
    """Modifi ekzistantan nodon per redaktilo, .enc dosiero, aŭ CLI-opcioj."""
    if not ref:
        typer.echo(
            "Mankas argumento REF. Se vi uzas UUID kun #, citu ĝin:\n"
            '  encik modifi "#e0a5d3b7"',
            err=True,
        )
        raise typer.Exit(code=2)
    entry = _resolve_entry(ref)
    if entry is None:
        typer.echo(f"Nodo ne trovita: {ref!r}", err=True)
        raise typer.Exit(code=1)

    parsed: dict | None = None
    has_cli_updates = any(
        value is not None
        for value in (
            titolo,
            difinio,
            termino,
            termino_difino,
            enhavo,
            superklaso,
            ligilo,
        )
    )
    invalid_path = _invalid_edit_path(entry["uuid"])

    if dosiero is not None:
        try:
            parsed = _parse_enc_file(dosiero)
        except ValueError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc
    elif not has_cli_updates:
        enc_text = _entry_to_enc(entry)
        editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "nano"
        if invalid_path.exists():
            enc_text = invalid_path.read_text(encoding="utf-8")

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
                _invalid_edit_dir().mkdir(parents=True, exist_ok=True)
                invalid_text = tmp_path.read_text(encoding="utf-8")
                invalid_path.write_text(invalid_text, encoding="utf-8")
                typer.echo(str(exc), err=True)
                typer.echo(
                    "Nevalida redakto konservita por korekto:\n"
                    f"  encik modifi -- {entry['uuid']}\n"
                    f"  (dosiero: {invalid_path})",
                    err=True,
                )
                raise typer.Exit(code=1) from exc
        finally:
            tmp_path.unlink(missing_ok=True)

    if parsed is not None:
        parsed = _merge_auto_ligilo_refs(parsed)
        entry.update(
            titolo=parsed["titolo"],
            difinio=parsed["difinio"],
            terminologio=parsed["terminologio"],
            difinoj=parsed["difinoj"],
            enhavo=parsed["enhavo"],
            superklaso=parsed["superklaso"],
            ligilo=parsed["ligilo"],
            fonto=parsed["fonto"],
            citajo=parsed["citajo"],
            datumo=parsed["datumo"],
        )

    if termino:
        try:
            parsed_terms = _parse_lang_assignments(termino, field="terminologio")
        except ValueError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc
        merged_terms = dict(entry.get("terminologio") or {})
        merged_terms.update(parsed_terms)
        entry["terminologio"] = merged_terms
    if termino_difino:
        try:
            parsed_defs = _parse_lang_assignments(termino_difino, field="difino")
        except ValueError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc
        merged_defs = dict(entry.get("difinoj") or {})
        merged_defs.update(parsed_defs)
        entry["difinoj"] = merged_defs
    if titolo is not None:
        terms = dict(entry.get("terminologio") or {})
        terms["eo"] = titolo
        entry["terminologio"] = terms
    if difinio is not None:
        defs = dict(entry.get("difinoj") or {})
        defs["eo"] = _normalize_markdown_text(difinio)
        entry["difinoj"] = defs
    if enhavo is not None:
        entry["enhavo"] = enhavo
    if superklaso is not None:
        entry["superklaso"] = _normalize_uuid_list(superklaso)
    if ligilo is not None:
        entry["ligilo"] = _parse_ligilo_cli_values(ligilo)

    terms = dict(entry.get("terminologio") or {})
    defs = {
        lang: _normalize_markdown_text(text)
        for lang, text in (entry.get("difinoj") or {}).items()
    }
    if not _has_minimum_term_definition_pair(terms, defs):
        typer.echo(
            "Nevalida modifo: bezonata almenaŭ unu lingvo kun ambaŭ "
            "terminologio.xx kaj difino.xx.",
            err=True,
        )
        raise typer.Exit(code=1)
    entry["terminologio"] = terms
    entry["difinoj"] = defs
    entry["titolo"] = next(iter(terms.values())).strip()
    primary_lang = next(iter(terms.keys()))
    entry["difinio"] = defs.get(primary_lang, "").strip() or next(
        iter(defs.values())
    ).strip()

    existing = _find_by_title_exact(entry["titolo"])
    if existing is not None and existing["uuid"] != entry["uuid"]:
        typer.echo(
            f"Nodo kun titolo \"{entry['titolo']}\" jam ekzistas "
            f"(#{existing['uuid'][:8]}).",
            err=True,
        )
        raise typer.Exit(code=1)

    _raise_if_semantic_conflicts(entry)
    entry["modifita_je"] = _now_iso()
    _update_entry(entry)
    _sync_bidirectional_relations_for_entry(entry)
    invalid_path.unlink(missing_ok=True)
    typer.echo(f"Modifis #{entry['uuid'][:8]}  \"{entry['titolo']}\"")


@app.command("vidi")
def vidi(
    ref: str | None = typer.Argument(
        None,
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
    html: bool = typer.Option(
        False,
        "-H",
        "--html",
        help="Montri la nodon kiel bildigita HTML-tabelo en la defaŭlta retumilo.",
    ),
) -> None:
    """Montri unu nodon laŭ UUID aŭ terminologio."""
    if not ref:
        typer.echo(
            "Mankas argumento REF. Se vi uzas UUID kun #, citu ĝin:\n"
            '  encik vidi "#e0a5d3b7"',
            err=True,
        )
        raise typer.Exit(code=2)
    entry = _resolve_entry(ref, interactive=True)
    if entry is None:
        typer.echo(f"Nodo ne trovita: {ref!r}", err=True)
        raise typer.Exit(code=1)
    if html:
        html_doc = _render_entry_html(entry, lingvo=lingvo, montri_cxion=montri_cxion)
        out_path = _open_html_document(html_doc)
        typer.echo(f"Malfermas en retumilo: {out_path}")
        return
    _display_entry(entry, lingvo=lingvo, montri_cxion=montri_cxion)


@app.command("serci")
def serci(
    ctx: typer.Context,
    demando: str | None = typer.Argument(
        None,
        help="Demando por serĉo (titolo defaŭlte, aŭ plena teksto kun -t).",
    ),
    teksto: bool = typer.Option(
        False,
        "-t",
        "--teksto",
        help="Serĉi tra plena enhavo de nodoj (ne nur titolo).",
    ),
    nova_unue: bool = typer.Option(
        False,
        "--nova-unue",
        help="Anstataŭigi defaŭltan ordigon por preferi pli novajn rezultojn.",
    ),
    malnova_unue: bool = typer.Option(
        False,
        "--malnova-unue",
        help="Anstataŭigi defaŭltan ordigon por preferi pli malnovajn rezultojn.",
    ),
    alta_unue: bool = typer.Option(
        False,
        "--alta-unue",
        help="Preferi pli altnivelajn nodojn (pli da subklasoj).",
    ),
    malalta_unue: bool = typer.Option(
        False,
        "--malalta-unue",
        help="Preferi pli malaltnivelajn nodojn (malpli da subklasoj).",
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
    ligilo_ref: str | None = typer.Option(
        None,
        "-l",
        "--ligilo",
        help="Montri rilatan mapon (super/sub/ligilo) de nodo en HTML.",
    ),
    semantiko: str | None = typer.Option(
        None,
        "--semantiko",
        help=(
            "Filtri laŭ semantika ligilo (ekz: rdf:type, rdfs:subClassOf, "
            "owl:disjointWith, owl:inverseOf)."
        ),
    ),
    al_ref: str | None = typer.Option(
        None,
        "--al",
        help="Kun --semantiko: celi specifan nodon (UUID/titolo).",
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
    relation_mode = any(
        value is not None for value in (subklasoj, superklasoj, ligilo_ref, semantiko)
    ) or paralela
    if not relation_mode and not demando:
        typer.echo(ctx.get_help())
        return

    if nova_unue and malnova_unue:
        typer.echo("Uzu nur unu el --nova-unue aŭ --malnova-unue.", err=True)
        raise typer.Exit(code=1)
    if alta_unue and malalta_unue:
        typer.echo("Uzu nur unu el --alta-unue aŭ --malalta-unue.", err=True)
        raise typer.Exit(code=1)
    if semantiko and ligilo_ref is not None:
        typer.echo("Uzu aŭ --ligilo aŭ --semantiko, ne ambaŭ samtempe.", err=True)
        raise typer.Exit(code=1)
    if al_ref and not semantiko:
        typer.echo("--al postulas --semantiko.", err=True)
        raise typer.Exit(code=1)

    if semantiko:
        rel = _normalize_semantika_ligilo(semantiko)
        if not rel:
            typer.echo("Nevalida --semantiko valoro.", err=True)
            raise typer.Exit(code=1)
        target_uuid: str | None = None
        if al_ref:
            target = _resolve_entry(al_ref, interactive=False)
            if target is None:
                typer.echo(f"Cela nodo ne trovita por --al: {al_ref!r}", err=True)
                raise typer.Exit(code=1)
            target_uuid = str(target["uuid"])
        matches: list[tuple[dict, str]] = []
        for entry in _load_all():
            for link in _normalize_ligilo_items(entry.get("ligilo") or []):
                if link.get("tipo") != rel:
                    continue
                to_uuid = str(link.get("uuid") or "")
                resolved = _find_by_uuid(to_uuid)
                if not resolved:
                    continue
                resolved_uuid = str(resolved["uuid"])
                if target_uuid and resolved_uuid != target_uuid:
                    continue
                matches.append((entry, resolved_uuid))
        if not matches:
            typer.echo("Neniu semantika ligilo trovita.")
            return
        typer.echo(f"Semantikaj ligiloj ({rel}):")
        for source, to_uuid in matches:
            target_title = _resolve_uuid_to_title(to_uuid)
            typer.echo(
                f"  #{source['uuid'][:8]} {source['titolo']} -> "
                f"{rel} -> {target_title} #{to_uuid[:8]}"
            )
        return

    # For -s/-S/-l/-p we need to resolve the root node.
    # `encik serci -p <ref>` uses positional `demando` as the root reference.
    root_ref = subklasoj or superklasoj or ligilo_ref
    if root_ref is None and paralela:
        root_ref = demando

    if paralela and root_ref is None:
        typer.echo("Mankas radika nodo por --paralela (uzu UUID aŭ titolon).", err=True)
        raise typer.Exit(code=1)

    if root_ref is not None:
        root = _resolve_entry(root_ref)
        if root is None:
            typer.echo(f"Nodo ne trovita: {root_ref!r}", err=True)
            raise typer.Exit(code=1)
        depth = abs(limo)

        # ── -s / --subklasoj ───────────────────────────────────────────────
        if subklasoj is not None and not paralela:
            results = _subklasoj_of(root["uuid"], max_depth=depth)
            if not results:
                typer.echo(f"Neniu subklaso trovita por '{root['titolo']}'.")
                return
            typer.echo(f"Subklasoj de '{root['titolo']}' (nivelo ≤{depth or '∞'}):")
            for e in results:
                typer.echo(f"  #{e['uuid'][:8]}  {e['titolo']}")
            return

        # ── -S / --superklasoj ─────────────────────────────────────────────
        if superklasoj is not None and not paralela:
            results = _superklasoj_of(root["uuid"], max_depth=depth)
            if not results:
                typer.echo(f"Neniu superklaso trovita por '{root['titolo']}'.")
                return
            typer.echo(f"Superklasoj de '{root['titolo']}' (nivelo ≤{depth or '∞'}):")
            for e in results:
                typer.echo(f"  #{e['uuid'][:8]}  {e['titolo']}")
            return

        # ── -p / --paralela ────────────────────────────────────────────────
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
            return

        # ── -l / --ligilo ──────────────────────────────────────────────────
        if ligilo_ref is not None:
            graph_nodes, graph_edges = _linked_graph_of(root["uuid"], max_depth=depth)
            if not graph_nodes:
                typer.echo(f"Neniu rilata nodo trovita por '{root['titolo']}'.")
                return
            html_doc = _render_linked_graph_html(root, graph_nodes, graph_edges)
            out_path = _open_html_document(html_doc)
            typer.echo(f"Malfermas rilatan mapon en retumilo: {out_path}")
            return

    # ── serĉo laŭ demando (defaŭlte titolo, kun -t plena teksto) ──────────
    if demando is not None:
        candidates = _search_entries(
            demando,
            full_text=teksto,
            max_results=abs(limo),
            prefer_newest=not malnova_unue,
            prefer_high_level=not malalta_unue,
        )
        if not candidates:
            typer.echo(f"Neniu nodo trovita por '{demando}'.")
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


@app.command("ls")
def ls(
    ctx: typer.Context,
    pagho: int = typer.Option(
        1, "-p", "--pagho", help="Page number (1-indexed).", min=1
    ),
    inversa: bool = typer.Option(
        False, "-i", "--inversa", help="List from oldest instead of newest."
    ),
    per_pagho: int = typer.Option(
        10, "--per-pagho", help="Number of entries per page.", min=1, max=100
    ),
) -> None:
    """List encik entries with pagination.
    
    By default, shows the newest 10 entries. Use -p to paginate and -i to reverse order.
    """
    conn = _get_conn()
    try:
        # Get total count
        total = conn.execute("SELECT COUNT(*) FROM encik").fetchone()[0]
        
        if total == 0:
            typer.echo("Neniu eniro en la datumbazo.")
            raise typer.Exit(code=0)
        
        # Calculate pagination
        offset = (pagho - 1) * per_pagho
        if offset >= total:
            max_pages = (total + per_pagho - 1) // per_pagho
            typer.echo(
                f"Paĝo {pagho} ne ekzistas (nur {max_pages} paĝo(j)).",
                err=True
            )
            raise typer.Exit(code=1)
        
        # Fetch entries with sorting
        order = "ASC" if inversa else "DESC"
        rows = conn.execute(
            f"""SELECT uuid, titolo, kreita_je, modifita_je
                FROM encik
                ORDER BY kreita_je {order}
                LIMIT ? OFFSET ?""",
            (per_pagho, offset),
        ).fetchall()
        
        # Display as table
        table = Table(
            show_header=True,
            header_style="dim",
            border_style="dim",
            expand=False,
        )
        table.add_column("UUID", style="dim", width=10, no_wrap=True)
        table.add_column("Titolo", min_width=30)
        table.add_column("Kreita", width=12)
        table.add_column("Modifita", width=12)
        
        for row in rows:
            uid_short = row[0][:8]
            titolo = row[1]
            kreita = row[2][:10] if row[2] else ""
            modifita = row[3][:10] if row[3] else ""
            table.add_row(uid_short, titolo, kreita, modifita)
        
        # Display summary and table
        start_idx = offset + 1
        end_idx = min(offset + per_pagho, total)
        total_pages = (total + per_pagho - 1) // per_pagho
        
        console.print(
            f"[dim]Montras {start_idx}-{end_idx} el {total} eniro(j) | "
            f"Paĝo {pagho}/{total_pages}[/dim]"
        )
        console.print(table)
    finally:
        conn.close()


@app.command("forigi")
def forigi(
    uuids: list[str] | None = typer.Argument(
        None,
        help="One or more UUIDs to delete (full or 8-char prefix).",
    ),
    force: bool = typer.Option(
        False,
        "-f",
        "--force",
        help="Delete without confirmation.",
    ),
) -> None:
    """Delete one or more encik entries by UUID."""
    if not uuids:
        typer.echo(
            "Mankas UUID. Se vi uzas UUID kun #, citu ĝin:\n"
            '  encik forigi "#e0a5d3b7"',
            err=True,
        )
        raise typer.Exit(code=2)
    conn = _get_conn()
    try:
        # Resolve UUIDs and collect entries to delete
        to_delete = []
        for uuid_input in uuids:
            uuid_input = uuid_input[1:] if uuid_input.startswith("#") else uuid_input
            # Try exact match first
            row = conn.execute(
                "SELECT uuid, titolo FROM encik WHERE uuid = ?", (uuid_input,)
            ).fetchone()
            
            if not row:
                # Try prefix match (8-char)
                rows = conn.execute(
                    "SELECT uuid, titolo FROM encik WHERE uuid LIKE ?",
                    (uuid_input + "%",),
                ).fetchall()
                
                if not rows:
                    typer.echo(f"UUID ne trovita: {uuid_input}", err=True)
                    raise typer.Exit(code=1)
                elif len(rows) > 1:
                    typer.echo(
                        f"Pluredaj trovoj por {uuid_input}. "
                        "Uzu pli longan UUID-on.",
                        err=True,
                    )
                    raise typer.Exit(code=1)
                row = rows[0]
            
            to_delete.append({"uuid": row["uuid"], "titolo": row["titolo"]})
        
        # Confirmation
        all_entries = _load_all()
        refs = _collect_encik_incoming_refs(
            all_entries, {item["uuid"] for item in to_delete}
        )
        if refs:
            typer.echo("[!] Averto: forigo rompos referencojn en aliaj encik-eroj:")
            for line in refs:
                typer.echo(f"  {line}")
        if not force:
            typer.echo("Forigontaj eniroj:")
            for entry in to_delete:
                typer.echo(f"  - {entry['titolo']} (#{entry['uuid'][:8]})")
            confirm = typer.prompt("Ĉu daŭrigi? (j/n)", default="n")
            if confirm.strip().lower() not in ("j", "jes", "y", "yes"):
                typer.echo("Nuligita.")
                return
        
        # Delete
        for entry in to_delete:
            conn.execute("DELETE FROM encik WHERE uuid = ?", (entry["uuid"],))
        
        conn.commit()
        typer.echo(f"[✓] Forigis {len(to_delete)} eniro(j).")
    
    except Exception as exc:
        conn.rollback()
        raise exc
    finally:
        conn.close()
