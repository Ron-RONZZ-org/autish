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

_ALLOWED_ENC_PLAIN_KEYS: frozenset[str] = frozenset({
    "terminologio",
    "difinio",
    "difino",
    "titolo",
    "superklaso",
    "ligilo",
    "fonto",
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
        difinio = str(d.get("difinio") or "").strip()
        d["difinoj"] = {"eo": difinio} if difinio else {}
    if "enhavo" not in d:
        d["enhavo"] = ""
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
            " superklaso, ligilo, fonto,"
            " kreita_je, modifita_je)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
               superklaso=?, ligilo=?, fonto=?, modifita_je=?
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

# Ligiloj: listo de UUID-oj (tekstoĉenoj aŭ listo)
# Ekzemploj: ligilo = "uuid1"  aŭ  ligilo = ["uuid1", "uuid2"]
ligilo = {ligilo}

# Fontoj: listo de tabeloj kun titolo, autoro, jaro, tipo, noto, ligilo
# Ekzemplo: fonto = [{{titolo="...", autoro="...", jaro=2020, tipo="lib", 
#                      noto="...", ligilo="https://..."}}]
# Validaj tipoj: libroj, artikoloj, retejoj, filmoj, tezoj, raportoj,
#                podkastoj, prelegoj
# Aliasoj: lib, art, ret, fil, tez, rap, pod, pre
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
        pattern = r'^\s*(ligilo|superklaso)\s*=\s*[a-f0-9\-]+\s*$'
        if re.match(pattern, line, re.IGNORECASE):
            # Extract the value and quote it
            match_pattern = r'^(\s*(?:ligilo|superklaso)\s*=\s*)([a-f0-9\-]+)\s*$'
            match = re.match(match_pattern, line, re.IGNORECASE)
            if match:
                lines.append(f'{match.group(1)}"{match.group(2)}"')
                continue
        
        # Fix ligilo/superklaso with array of unquoted UUIDs: ligilo=[abc, def]
        if re.match(r'^\s*(ligilo|superklaso)\s*=\s*\[', line, re.IGNORECASE):
            # Quote unquoted values in the array
            # Pattern: [abc, def] or [abc,def] -> ["abc", "def"]
            # But preserve already-quoted values
            def quote_uuid(match):
                val = match.group(1)
                # If already quoted, leave it
                if val.startswith('"') or val.startswith("'"):
                    return match.group(0)
                # Quote it
                return f'"{val}"'
            
            # Match array elements (after [ or ,) that aren't quoted
            fixed = re.sub(
                r'(?<=[\[,])\s*([a-f0-9\-]+)\s*(?=[,\]])',
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

    # superklaso kaj ligilo: listoj de UUID-oj
    superklaso = _normalise_uuids(data.get("superklaso", []))
    ligilo = _normalise_uuids(data.get("ligilo", []))

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
                    lingvo = str(v).strip().lower()
                    if re.fullmatch(r"[a-z]{2}", lingvo):
                        normalized["lingvo"] = lingvo
                    else:
                        raise ValueError(
                            f"Nevalida fonto.lingvo: {v!r}. Uzu 2-literan kodon."
                        )
                elif key_lower == "noto":
                    normalized["noto"] = str(v)
                elif key_lower == "ligilo":
                    normalized["ligilo"] = str(v)
                else:
                    # Preserve other fields as-is (like title.en, title.fr, etc.)
                    normalized[k] = str(v)
            fonto.append(normalized)

    return {
        "titolo": titolo,
        "difinio": difinio,
        "terminologio": terminologio,
        "difinoj": difinoj,
        "enhavo": enhavo,
        "superklaso": superklaso,
        "ligilo": ligilo,
        "fonto": fonto,
    }


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
        # Normalize first-level list indentation to column 0.
        if re.match(r"^(\s+)([-*]|\d+\.)\s+", line):
            indent = len(line) - len(stripped)
            marker = re.match(r"^([-*]|\d+\.)\s+", stripped)
            if marker and indent <= 4:
                out.append(stripped)
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
    allowed_dotted_prefixes = {"terminologio", "difino", "difinio"}
    for key in data:
        if "." in key:
            prefix = key.split(".", 1)[0]
            if prefix in allowed_dotted_prefixes:
                continue
            suggestion = _suggest_enc_dotted_key(key)
            raise ValueError(
                f"Nevalida .enc: nekonata kampo '{key}'. "
                f"Uzu ekz. terminologio.xx aŭ difino.xx.{suggestion}"
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


def _normalise_uuids(raw: list | str) -> list[str]:
    """Normalise ligilo values to a list of UUIDs.
    
    Accepts:
    - String: single UUID
    - List of strings: list of UUIDs
    - List of [title, uuid] pairs: extracts UUIDs (backward compat)
    """
    if isinstance(raw, str):
        return [raw.strip()] if raw.strip() else []
    
    if not isinstance(raw, list):
        return []
    
    result: list[str] = []
    for item in raw:
        if isinstance(item, str):
            # Direct UUID
            if item.strip():
                result.append(item.strip())
        elif isinstance(item, list) and len(item) >= 2:
            # Backward compat: [title, uuid] pair - extract UUID
            uid = str(item[1]).strip()
            if uid:
                result.append(uid)
        elif isinstance(item, list) and len(item) == 1:
            # Single-element list containing UUID
            uid = str(item[0]).strip()
            if uid:
                result.append(uid)
    return result


def _resolve_uuid_to_title(uuid: str) -> str:
    """Resolve a UUID to its entry title. Returns shortened UUID if not found.
    
    Supports prefix matching (e.g., 'c487fa8b' matches 'c487fa8b-...-...').
    """
    conn = _get_conn()
    try:
        # Try exact match first
        row = conn.execute(
            "SELECT titolo FROM encik WHERE uuid = ?", (uuid,)
        ).fetchone()
        if row:
            return str(row["titolo"])
        
        # Try prefix match
        rows = conn.execute(
            "SELECT titolo FROM encik WHERE uuid LIKE ?", (uuid + "%",)
        ).fetchall()
        if len(rows) == 1:
            return str(rows[0]["titolo"])
        elif len(rows) > 1:
            # Multiple matches - return UUID with indicator
            return f"#{uuid[:8]}*"
        
        # Not found - return shortened UUID
        return f"#{uuid[:8]}"
    finally:
        conn.close()


def _normalize_uuid_list(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for v in values:
        s = str(v or "").strip()
        if not s:
            continue
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


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
        for link_ref in _normalize_uuid_list(source.get("ligilo") or []):
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
    current_lig = _normalize_uuid_list(current.get("ligilo") or [])
    current_sup = _normalize_uuid_list(current.get("superklaso") or [])
    current["ligilo"] = current_lig
    current["superklaso"] = current_sup
    current["modifita_je"] = _now_iso()
    changed.append(current)

    # Bidirectional ligilo
    for other_ref in current_lig:
        other = _find_by_uuid(other_ref)
        if other is None:
            continue
        other_lig = _normalize_uuid_list(other.get("ligilo") or [])
        if current["uuid"] not in other_lig:
            other_lig.append(current["uuid"])
            other["ligilo"] = _normalize_uuid_list(other_lig)
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

    ligilo = _normalize_uuid_list(entry.get("ligilo") or [])
    if ligilo:
        panel_lines.append(f"  [dim]{'ligilo:':<14}[/dim]")
        for uuid in ligilo:
            title = _resolve_uuid_to_title(uuid)
            panel_lines.append(f"    {_render_relation_cli_link(title, str(uuid))}")

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
        ref = match.group(2).strip().lstrip("#")
        target = _find_by_uuid(ref)
        if not target:
            return f"{label} [dim]#{ref[:8]}[/dim]"
        target_html = _render_entry_html(target, link_depth=1)
        target_path = _write_html_document(target_html)
        uid_short = str(target.get("uuid") or "")[:8]
        return (
            f"[link=file://{target_path}]{label}[/link] "
            f"[dim]#{uid_short}[/dim]"
        )

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
    if not target:
        if label:
            return f"{label} [dim]#{short_ref}[/dim]"
        return f"[dim]#{short_ref}[/dim]"
    target_html = _render_entry_html(target, link_depth=1)
    target_path = _write_html_document(target_html)
    short_target = str(target.get("uuid") or "")[:8]
    shown_label = label or str(target.get("titolo") or "")
    return (
        f"[link=file://{target_path}]{shown_label}[/link] "
        f"[dim]#{short_target}[/dim]"
    )


def _render_relation_html_link(label: str, ref: str, *, link_depth: int = 0) -> str:
    """Render an HTML relation link for an encik UUID reference."""
    normalized_ref = str(ref or "").strip().lstrip("#")
    target = _find_by_uuid(normalized_ref)
    short_ref = normalized_ref[:8]
    if not target:
        if label:
            return f"{escape(label)} #{escape(short_ref)}"
        return f"#{escape(short_ref)}"
    shown_label = label or str(target.get("titolo") or "")
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

    ligilo = entry.get("ligilo") or []
    if ligilo:
        links = "<br>".join(
            _render_relation_html_link(
                _resolve_uuid_to_title(str(uid)), str(uid), link_depth=link_depth
            )
            for uid in ligilo
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
        "</body></html>"
    )


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
            "Vojo al .enc dosiero. Formato: terminologio.xx = \"...\", "
            "difino.xx = \"...\", laŭvola "
            '"""libera teksto""", superklaso = ["uuid1", "uuid2"], '
            'ligilo = ["uuid1", "uuid2"], '
            "fonto = [{titolo=\"...\", autoro=\"...\", jaro=2020, tipo=\"libroj\", "
            "noto=\"...\", ligilo=\"https://...\"}]. "
            "Validaj tipoj: libroj, artikoloj, retejoj, filmoj, tezoj, raportoj, "
            "podkastoj, prelegoj (aŭ aliasoj: lib, art, ret, fil, tez, rap, pod, pre)."
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
            difinio=parsed["difinio"],
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
        None, "--ligilo", help="Anstataŭigi ligilo-liston (ripetebla)."
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
        entry.update(
            titolo=parsed["titolo"],
            difinio=parsed["difinio"],
            terminologio=parsed["terminologio"],
            difinoj=parsed["difinoj"],
            enhavo=parsed["enhavo"],
            superklaso=parsed["superklaso"],
            ligilo=parsed["ligilo"],
            fonto=parsed["fonto"],
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
        entry["ligilo"] = _normalize_uuid_list(ligilo)

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
    active = [x for x in (subklasoj, superklasoj) if x is not None]
    if not active and not paralela and not demando:
        typer.echo(ctx.get_help())
        return

    if nova_unue and malnova_unue:
        typer.echo("Uzu nur unu el --nova-unue aŭ --malnova-unue.", err=True)
        raise typer.Exit(code=1)
    if alta_unue and malalta_unue:
        typer.echo("Uzu nur unu el --alta-unue aŭ --malalta-unue.", err=True)
        raise typer.Exit(code=1)

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
