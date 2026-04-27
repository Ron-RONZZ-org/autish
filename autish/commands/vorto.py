"""vorto — personal wordbook microapp (Mia Vorto).

Usage:
    vorto                    — interactive mode (welcome screen)
    vorto aldoni <teksto>    — add an entry
    vorto vidi   <uuid>      — view an entry
    vorto modifi <uuid>      — modify an entry
    vorto serci  [teksto]    — search entries
    vorto forigi <uuid>      — delete an entry
    vorto malfari            — undo the last change (up to 10)
    vorto eksporti <dosiero> — export all entries as JSON
    vorto eksporti <ref> <celvojo> — export one entry as TOML

Data is stored in an SQLite database at ~/.local/share/autish/vorto.db.
The undo stack (last 10 operations) is kept in the same database.
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
import tempfile
import unicodedata
import uuid as _uuid_mod
import webbrowser
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from html import escape
from pathlib import Path

import typer
from rich.console import Console, Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from autish.i18n import tr

# ──────────────────────────────────────────────────────────────────────────────
# Typer app
# ──────────────────────────────────────────────────────────────────────────────

app = typer.Typer(
    name="vorto",
    help=tr(
        "Mia Vorto — persona vortaro-mikroapo.",
        "Mia Vorto — personal wordbook microapp.",
        "Mia Vorto — microapplication de vocabulaire personnel.",
    ),
    no_args_is_help=False,
    invoke_without_command=True,
    context_settings={"help_option_names": ["-h", "--help", "--helpo"]},
)

console = Console()

# ──────────────────────────────────────────────────────────────────────────────
# Storage paths
# ──────────────────────────────────────────────────────────────────────────────

_DATA_DIR: Path = Path.home() / ".local" / "share" / "autish"
_DB_FILE: Path = _DATA_DIR / "vorto.db"
_ENCIK_DB_FILE: Path = _DATA_DIR / "encik.db"
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
    uzoj        TEXT NOT NULL DEFAULT '[]',
    etikedoj    TEXT NOT NULL DEFAULT '{}',
    ligiloj     TEXT NOT NULL DEFAULT '[]',
    autoro      TEXT,
    verko       TEXT,
    kreita_je   TEXT NOT NULL,
    modifita_je TEXT NOT NULL
);
"""

_CREATE_VORTO_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_vorto_teksto_lower ON vorto(LOWER(teksto));
CREATE INDEX IF NOT EXISTS idx_vorto_lingvo ON vorto(lingvo);
CREATE INDEX IF NOT EXISTS idx_vorto_kategorio ON vorto(kategorio);
CREATE INDEX IF NOT EXISTS idx_vorto_temo ON vorto(temo);
CREATE INDEX IF NOT EXISTS idx_vorto_tono ON vorto(tono);
CREATE INDEX IF NOT EXISTS idx_vorto_kreita_je ON vorto(kreita_je);
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
    uzoj        TEXT NOT NULL DEFAULT '[]',
    etikedoj    TEXT NOT NULL DEFAULT '{}',
    ligiloj     TEXT NOT NULL DEFAULT '[]',
    autoro      TEXT,
    verko       TEXT,
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
    con.executescript(_CREATE_VORTO + _CREATE_VORTO_INDEXES + _CREATE_RUBUJO + _CREATE_UNDO)
    _migrate_db(con)
    return con


def _migrate_db(con: sqlite3.Connection) -> None:
    for table in ("vorto", "rubujo"):
        cols = {
            row[1]
            for row in con.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if "uzoj" not in cols:
            con.execute(
                f"ALTER TABLE {table} ADD COLUMN uzoj TEXT NOT NULL DEFAULT '[]'"
            )
        if "autoro" not in cols:
            con.execute(f"ALTER TABLE {table} ADD COLUMN autoro TEXT")
        if "verko" not in cols:
            con.execute(f"ALTER TABLE {table} ADD COLUMN verko TEXT")
    con.commit()


def _row_to_dict(row: sqlite3.Row) -> dict:
    """Convert a *vorto* table row to a plain dict, parsing JSON columns."""
    d = dict(row)
    for col, default in (
        ("difinoj", "[]"),
        ("uzoj", "[]"),
        ("etikedoj", "{}"),
        ("ligiloj", "[]"),
        ("tipo", "[]"),  # Parse tipo as JSON list
    ):
        raw = d.get(col) or default
        try:
            d[col] = json.loads(raw)
        except json.JSONDecodeError:
            d[col] = json.loads(default)
    d["difinoj"], d["uzoj"] = _normalize_difinoj_uzoj(
        d.get("difinoj") or [],
        d.get("uzoj") or [],
    )
    # Ensure tipo is always a list (handle legacy single-string values)
    if isinstance(d.get("tipo"), str):
        d["tipo"] = [d["tipo"]] if d["tipo"] else []
    elif not isinstance(d.get("tipo"), list):
        d["tipo"] = []
    return d


def _dict_to_params(entry: dict) -> tuple:
    """Return the parameter tuple used for INSERT/UPDATE statements."""
    return (
        entry["uuid"],
        entry["teksto"],
        entry.get("lingvo"),
        entry.get("kategorio"),
        # Serialize tipo as JSON list
        json.dumps(entry.get("tipo") or [], ensure_ascii=False),
        entry.get("temo"),
        entry.get("tono"),
        entry.get("nivelo"),
        json.dumps(entry.get("difinoj") or [], ensure_ascii=False),
        json.dumps(entry.get("uzoj") or [], ensure_ascii=False),
        json.dumps(entry.get("etikedoj") or {}, ensure_ascii=False),
        json.dumps(entry.get("ligiloj") or [], ensure_ascii=False),
        entry.get("autoro"),
        entry.get("verko"),
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
    "sn": "substantivo-neŭtra",
    "substantivo-neŭtra": "substantivo-neŭtra",
    "sp": "substantivo-plurala",
    "substantivo-plurala": "substantivo-plurala",
    "sip": "substantivo-ina-plurala",
    "substantivo-ina-plurala": "substantivo-ina-plurala",
    "svp": "substantivo-vira-plurala",
    "substantivo-vira-plurala": "substantivo-vira-plurala",
    "sui": "substantivo-ina",
    "si": "substantivo-ina",
    "suf": "substantivo-ina",
    "substantivo-ina": "substantivo-ina",
    "suv": "substantivo-vira",
    "sv": "substantivo-vira",
    "sum": "substantivo-vira",
    "substantivo-vira": "substantivo-vira",
    "ve": "verbo",
    "verbo": "verbo",
    "vt": "verbo-transitiva",
    "transitiva": "verbo-transitiva",
    "verbo-transitiva": "verbo-transitiva",
    "vnt": "verbo-nerekta-transitiva",
    "nerekta-transitiva": "verbo-nerekta-transitiva",
    "verbo-nerekta-transitiva": "verbo-nerekta-transitiva",
    "vn": "verbo-netransitiva",
    "netransitiva": "verbo-netransitiva",
    "verbo-netransitiva": "verbo-netransitiva",
    "vr": "refleksiva-verbo",
    "refleksiva-verbo": "refleksiva-verbo",
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
    "nf": "neformala",
    "neformala": "neformala",
    # legacy alias kept for backwards-compat
    "in": "neformala",
    "informala": "neformala",
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


def _find_existing_by_teksto_in_list(teksto: str, entries: list[dict]) -> dict | None:
    """Find an entry by teksto using Python list search (case-insensitive). Returns None if not found."""
    return next(
        (e for e in entries if e["teksto"].lower() == teksto.lower()),
        None,
    )


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
                 nivelo, difinoj, uzoj, etikedoj, ligiloj,
                 autoro, verko, kreita_je, modifita_je)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
     difinoj, uzoj, etikedoj, ligiloj, autoro, verko,
     kreita_je, modifita_je, forigita_je)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                 difinoj, uzoj, etikedoj, ligiloj, autoro, verko,
                 kreita_je, modifita_je)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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


def _normalize_tipo(tipo: str | None) -> list[str] | None:
    """Normalize tipo string into a list of normalized tipo values.

    Accepts comma or semicolon-separated tipos, e.g.:
    - "aj,su" → ["adjektivo", "substantivo"]
    - "vt;aj" → ["verbo-transitiva", "adjektivo"]
    """
    if not tipo:
        return None
    # Split by comma or semicolon, strip whitespace
    parts = [p.strip() for p in re.split(r'[,;]', tipo) if p.strip()]
    if not parts:
        return None
    # Normalize each part
    normalized = []
    for part in parts:
        norm = _TIPO_MAP.get(part.lower(), part)
        if norm and norm not in normalized:  # Avoid duplicates
            normalized.append(norm)
    return normalized if normalized else None


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


def _apply_french_ligatures(text: str) -> str:
    """Replace digraph 'oe'/'OE' with the proper French ligature œ/Œ."""
    # Replace upper-case first (OE → Œ), then mixed (Oe → Œ), then lower (oe → œ)
    text = re.sub(r"OE", "Œ", text)
    text = re.sub(r"Oe", "Œ", text)
    text = re.sub(r"oe", "œ", text)
    return text


def _normalize_oe(text: str) -> str:
    """Fold œ/Œ → oe/OE for case-insensitive search comparisons."""
    return text.replace("œ", "oe").replace("Œ", "OE")


def _fold_search_text(text: str) -> str:
    folded_oe = _normalize_oe(str(text or ""))
    normalized = unicodedata.normalize("NFKD", folded_oe)
    stripped = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return stripped.casefold()


def _normalize_multiline_text(text: str) -> str:
    """Convert escaped/newline markers into actual multiline text."""
    normalized = str(text or "")
    normalized = re.sub(r"(?i)<br\s*/?>", "\n", normalized)
    normalized = normalized.replace("\\r\\n", "\n").replace("\\n", "\n").replace(
        "\\r", "\n"
    )
    return normalized.strip()


def _split_difino_uzo(raw: str) -> tuple[str, str]:
    """Split definition/example input.

    Supported forms:
    - `difino:{uzo}` (preferred)
    - `difino:*uzo*` (legacy)
    - `difino::uzo` (shell-safe; avoids `!*` history expansion issues)
    """
    text = _normalize_multiline_text(raw)
    if "::" in text:
        left, right = text.split("::", 1)
        return left.strip(), right.strip()
    m_braced = re.match(r"^(.*?):\{(.+)\}$", text)
    if m_braced:
        return m_braced.group(1).strip(), m_braced.group(2).strip()
    m = re.match(r"^(.*?):\*(.+)\*$", text)
    if not m:
        return text, ""
    return m.group(1).strip(), m.group(2).strip()


def _normalize_difinoj_uzoj(
    difinoj: list[str], uzoj: list[str] | None = None
) -> tuple[list[str], list[str]]:
    clean_difinoj: list[str] = []
    clean_uzoj: list[str] = []
    existing_uzoj = list(uzoj or [])
    for i, raw in enumerate(difinoj):
        d, parsed_u = _split_difino_uzo(raw)
        fallback_u = (
            _normalize_multiline_text(existing_uzoj[i])
            if i < len(existing_uzoj)
            else ""
        )
        clean_difinoj.append(d)
        clean_uzoj.append(parsed_u or fallback_u)
    return clean_difinoj, clean_uzoj


def _find_encik_entry(uid_or_prefix: str) -> dict | None:
    normalized = str(uid_or_prefix or "").strip().lstrip("#")
    if not normalized or not _ENCIK_DB_FILE.exists():
        return None
    con = sqlite3.connect(str(_ENCIK_DB_FILE), timeout=2.0)
    con.row_factory = sqlite3.Row
    try:
        row = con.execute(
            "SELECT uuid, titolo, difinio FROM encik WHERE uuid = ?",
            (normalized,),
        ).fetchone()
        if row:
            return dict(row)
        rows = con.execute(
            "SELECT uuid, titolo, difinio FROM encik "
            "WHERE uuid LIKE ? ORDER BY uuid COLLATE NOCASE LIMIT 2",
            (f"{normalized}%",),
        ).fetchall()
        if len(rows) == 1:
            return dict(rows[0])
        return None
    except sqlite3.Error:
        return None
    finally:
        con.close()


def _normalize_inline_ref_token(raw_ref: str) -> str:
    token = str(raw_ref or "").strip().split(",", 1)[0].strip()
    if not token:
        return ""
    lower = token.lower()
    if lower.startswith("vt#"):
        local_ref = token[3:].lstrip("#").strip()
        return f"#{local_ref}" if local_ref else ""
    if lower.startswith("ec#"):
        encik_ref = token[3:].lstrip("#").strip()
        return f"ec#{encik_ref}" if encik_ref else ""
    if token.startswith("#"):
        local_ref = token.lstrip("#").strip()
        return f"#{local_ref}" if local_ref else ""
    return token


_INTERNAL_LINK_RE = re.compile(
    r"\[([^\]]+)\]\(((?:#|[eE][cC]#|[vV][tT]#)[^)]+)\)"
)


def _extract_markdown_link_refs(text: str) -> list[str]:
    refs: list[str] = []
    for match in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", str(text or "")):
        target = _normalize_inline_ref_token(match.group(1))
        if not target:
            continue
        if target.startswith("#") or target.lower().startswith("ec#"):
            refs.append(target)
    return refs


def _extract_markdown_link_refs_from_payload(payload: object) -> list[str]:
    refs: list[str] = []
    if isinstance(payload, str):
        refs.extend(_extract_markdown_link_refs(payload))
        return refs
    if isinstance(payload, list):
        for item in payload:
            refs.extend(_extract_markdown_link_refs_from_payload(item))
        return refs
    if isinstance(payload, dict):
        for value in payload.values():
            refs.extend(_extract_markdown_link_refs_from_payload(value))
    return refs


def _canonicalize_ligilo_ref(raw_ref: str, entries: list[dict]) -> str:
    token = _normalize_inline_ref_token(raw_ref)
    if not token:
        return ""
    if token.lower().startswith("ec#"):
        encik_ref = token[3:]
        if not encik_ref:
            return ""
        target = _find_encik_entry(encik_ref)
        resolved = str(target.get("uuid") or encik_ref).strip() if target else encik_ref
        return f"ec#{resolved}" if resolved else ""
    lookup = token[1:] if token.startswith("#") else token
    if not lookup:
        return ""
    target = _find_entry(lookup, entries)
    if target is not None:
        return str(target.get("uuid") or "")
    return lookup


def _normalize_link_refs(refs: list[str], entries: list[dict]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in refs:
        target_ref = _canonicalize_ligilo_ref(raw, entries)
        if not target_ref:
            continue
        dedup_key = (
            target_ref.lower() if target_ref.lower().startswith("ec#") else target_ref
        )
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        normalized.append(target_ref)
    return normalized


def _merge_links_with_inline_refs(
    base_links: list[str],
    difinoj: list[str],
    uzoj: list[str],
    entries: list[dict],
    *,
    extra_payload: object | None = None,
) -> list[str]:
    inline_refs: list[str] = []
    for part in [*(difinoj or []), *(uzoj or [])]:
        inline_refs.extend(_extract_markdown_link_refs(part))
    if extra_payload is not None:
        inline_refs.extend(_extract_markdown_link_refs_from_payload(extra_payload))
    return _normalize_link_refs([*(base_links or []), *inline_refs], entries)


def _write_preview_html_file(lines: list[str]) -> str:
    body = escape("\n".join(lines))
    html = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<style>"
        "body{font-family:system-ui,sans-serif;margin:1rem;line-height:1.45;}"
        "pre{white-space:pre-wrap;background:#fafafa;border:1px solid #e5e7eb;"
        "border-radius:8px;padding:.75rem;}"
        "</style></head><body><pre>"
        f"{body}"
        "</pre></body></html>"
    )
    return _write_html_document(html)


def _write_encik_preview_file(entry: dict) -> str:
    title = str(entry.get("titolo") or "").strip()
    short_uuid = str(entry.get("uuid") or "")[:8]
    difinio = str(entry.get("difinio") or "").strip()
    lines = [f"{title}  ec#{short_uuid}", ""]
    if difinio:
        lines.append(difinio)
    return _write_preview_html_file(lines)


def _write_html_document(html_doc: str) -> str:
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".html", delete=False, encoding="utf-8"
    ) as fh:
        fh.write(html_doc)
        return fh.name


def _render_internal_ref_html(
    label: str,
    target_token: str,
    all_entries: list[dict] | None,
    *,
    link_depth: int = 0,
) -> str:
    safe_label = escape(label.strip() or target_token)
    normalized = _normalize_inline_ref_token(target_token)
    if normalized.lower().startswith("ec#"):
        encik_ref = normalized[3:]
        if not encik_ref:
            return safe_label
        target = _find_encik_entry(encik_ref)
        if target is None:
            return safe_label
        preview_path = _write_encik_preview_file(target)
        if link_depth > 0:
            return safe_label
        safe_href = escape(f"file://{preview_path}")
        return f"<a href='{safe_href}'>{safe_label}</a>"
    raw_ref = normalized.lstrip("#")
    if not raw_ref:
        return safe_label
    if all_entries is None:
        return safe_label
    target = _find_entry(raw_ref, all_entries)
    if target is None:
        return safe_label
    preview_path = _write_entry_preview_file(
        target,
        all_entries,
        montri_cxion=False,
        link_depth=link_depth + 1,
    )
    if link_depth > 0:
        return safe_label
    safe_href = escape(f"file://{preview_path}")
    return f"<a href='{safe_href}'>{safe_label}</a>"


def _render_html_text_with_internal_links(
    text: str, all_entries: list[dict] | None, *, link_depth: int = 0
) -> str:
    raw_text = str(text or "")
    if not raw_text:
        return ""
    chunks: list[str] = []
    cursor = 0
    for match in _INTERNAL_LINK_RE.finditer(raw_text):
        chunks.append(escape(raw_text[cursor:match.start()]))
        chunks.append(
            _render_internal_ref_html(
                match.group(1),
                match.group(2),
                all_entries,
                link_depth=link_depth,
            )
        )
        cursor = match.end()
    chunks.append(escape(raw_text[cursor:]))
    return "".join(chunks)


def _render_ligilo_html(
    raw_ref: str, all_entries: list[dict] | None, *, link_depth: int = 0
) -> str:
    token = _normalize_inline_ref_token(raw_ref)
    local_ref = token[1:] if token.startswith("#") else token
    if all_entries is not None and local_ref:
        linked = _find_entry(local_ref, all_entries)
        if linked is not None:
            linked_label = (
                str(linked.get("teksto") or "").strip() or f"#{local_ref[:8]}"
            )
            short_uuid = str(linked.get("uuid") or "")[:8]
            if link_depth > 0:
                return (
                    f"{escape(linked_label)} "
                    f"<span class='dim'>(#{escape(short_uuid)})</span>"
                )
            preview_path = _write_entry_preview_file(
                linked,
                all_entries,
                montri_cxion=False,
                link_depth=link_depth + 1,
            )
            safe_href = escape(f"file://{preview_path}")
            return (
                f"<a href='{safe_href}'>{escape(linked_label)}</a> "
                f"<span class='dim'>(#{escape(short_uuid)})</span>"
            )
    if token.lower().startswith("ec#"):
        encik_ref = token[3:]
        if not encik_ref:
            return "ec#"
        target = _find_encik_entry(encik_ref)
        if target is None:
            return escape(f"ec#{encik_ref[:8]}")
        title = str(target.get("titolo") or "").strip() or f"ec#{encik_ref[:8]}"
        short_uuid = str(target.get("uuid") or "")[:8]
        if link_depth > 0:
            return f"{escape(title)} <span class='dim'>(ec#{escape(short_uuid)})</span>"
        preview_path = _write_encik_preview_file(target)
        safe_href = escape(f"file://{preview_path}")
        return (
            f"<a href='{safe_href}'>{escape(title)}</a> "
            f"<span class='dim'>(ec#{escape(short_uuid)})</span>"
        )
    return escape(str(raw_ref or token))


def _render_entry_preview_html(
    entry: dict,
    all_entries: list[dict] | None,
    *,
    montri_cxion: bool = False,
    link_depth: int = 0,
) -> str:
    uid_short = str(entry.get("uuid") or "")[:8]
    title = str(entry.get("teksto") or "").strip() or f"#{uid_short}"
    kategorio = entry.get("kategorio") or ""
    tipos = entry.get("tipo") or []
    tipo_str = (
        ", ".join(str(item) for item in tipos if str(item))
        if isinstance(tipos, list)
        else str(tipos) if tipos else ""
    )
    tipo_full = kategorio + ("/" + tipo_str if tipo_str else "")
    lingvo = str(entry.get("lingvo") or "")
    lingvo_tipo = ""
    if lingvo and tipo_full:
        lingvo_tipo = f"{lingvo} - {tipo_full}"
    elif lingvo or tipo_full:
        lingvo_tipo = lingvo or tipo_full
    metadata_rows: list[tuple[str, str]] = []
    if lingvo_tipo:
        metadata_rows.append(("lingvo/tipo", escape(lingvo_tipo)))
    autoro = str(entry.get("autoro") or "")
    if autoro:
        metadata_rows.append(
            (
                "aŭtoro",
                _render_html_text_with_internal_links(
                    autoro, all_entries, link_depth=link_depth
                ),
            )
        )
    verko = str(entry.get("verko") or "")
    if verko:
        metadata_rows.append(
            (
                "verko",
                _render_html_text_with_internal_links(
                    verko, all_entries, link_depth=link_depth
                ),
            )
        )
    if montri_cxion:
        temo = str(entry.get("temo") or "")
        if temo:
            metadata_rows.append(
                (
                    "temo",
                    _render_html_text_with_internal_links(
                        temo, all_entries, link_depth=link_depth
                    ),
                )
            )
        tono = str(entry.get("tono") or "")
        if tono:
            metadata_rows.append(
                (
                    "tono",
                    _render_html_text_with_internal_links(
                        tono, all_entries, link_depth=link_depth
                    ),
                )
            )
        nivelo = entry.get("nivelo")
        if nivelo is not None:
            metadata_rows.append(("nivelo", escape(f"{float(nivelo):.1f}")))
    metadata_html = ""
    if metadata_rows:
        rows = "".join(
            f"<tr><th>{escape(label)}</th><td>{value}</td></tr>"
            for label, value in metadata_rows
        )
        metadata_html = f"<table class='meta'>{rows}</table>"

    difinoj: list[str] = entry.get("difinoj") or []
    uzoj: list[str] = entry.get("uzoj") or []
    if difinoj:
        if len(difinoj) == 1:
            rendered_difino = _render_html_text_with_internal_links(
                difinoj[0], all_entries, link_depth=link_depth
            )
            item = f"<li><strong>{rendered_difino}</strong>"
            if uzoj and uzoj[0]:
                rendered_uzo = _render_html_text_with_internal_links(
                    uzoj[0], all_entries, link_depth=link_depth
                )
                item += f"<div class='uzo'>{rendered_uzo}</div>"
            item += "</li>"
            difino_html = f"<ol class='difinoj'>{item}</ol>"
        else:
            items: list[str] = []
            for index, difino in enumerate(difinoj):
                rendered_difino = _render_html_text_with_internal_links(
                    difino, all_entries, link_depth=link_depth
                )
                item = f"<li><strong>{rendered_difino}</strong>"
                if index < len(uzoj) and uzoj[index]:
                    rendered_uzo = _render_html_text_with_internal_links(
                        uzoj[index], all_entries, link_depth=link_depth
                    )
                    item += f"<div class='uzo'>{rendered_uzo}</div>"
                item += "</li>"
                items.append(item)
            difino_html = f"<ol class='difinoj'>{''.join(items)}</ol>"
    else:
        difino_html = "<p class='muted'>(neniu difino)</p>"

    etikedoj: dict[str, str] = entry.get("etikedoj") or {}
    etikedoj_html = ""
    if montri_cxion and etikedoj:
        items = "".join(
            f"<li><code>{escape(str(k))}</code>: {escape(str(v))}</li>"
            for k, v in etikedoj.items()
        )
        etikedoj_html = f"<h2>etikedoj</h2><ul>{items}</ul>"

    ligiloj: list[str] = entry.get("ligiloj") or []
    ligiloj_html = ""
    if ligiloj:
        rendered = " | ".join(
            _render_ligilo_html(str(item or ""), all_entries, link_depth=link_depth)
            for item in ligiloj
            if str(item or "").strip()
        )
        ligiloj_html = f"<h2>ligiloj</h2><p>{rendered}</p>"

    timestamp_rows: list[tuple[str, str]] = []
    if montri_cxion:
        kreita = str(entry.get("kreita_je") or "")
        if kreita:
            timestamp_rows.append(("kreita", escape(kreita[:19])))
        modifita = str(entry.get("modifita_je") or "")
        if modifita and modifita != kreita:
            timestamp_rows.append(("modifita", escape(modifita[:19])))
    timestamp_html = ""
    if timestamp_rows:
        rows = "".join(
            f"<tr><th>{escape(label)}</th><td>{value}</td></tr>"
            for label, value in timestamp_rows
        )
        timestamp_html = f"<h2>datoj</h2><table class='meta'>{rows}</table>"

    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<style>"
        "body{font-family:system-ui,sans-serif;margin:1rem;line-height:1.5;}"
        "h1{margin:0 0 .25rem 0;font-size:1.25rem;}"
        ".uuid{color:#6b7280;font-size:.95rem;margin-bottom:1rem;}"
        "table.meta{border-collapse:collapse;margin:0 0 1rem 0;}"
        "table.meta th{padding:.2rem .6rem .2rem 0;text-align:left;"
        "color:#6b7280;font-weight:600;vertical-align:top;}"
        "table.meta td{padding:.2rem 0;}"
        ".difinoj{margin:.5rem 0 1rem 1.25rem;padding:0;}"
        ".difinoj li{margin:.35rem 0;}"
        ".uzo{font-style:italic;color:#4b5563;margin-top:.15rem;white-space:pre-wrap;}"
        ".dim{color:#6b7280;}"
        ".muted{color:#6b7280;}"
        "code{background:#f3f4f6;padding:0 .2rem;border-radius:.2rem;}"
        "h2{font-size:1rem;margin:1rem 0 .4rem 0;}"
        "p{margin:.25rem 0;white-space:pre-wrap;}"
        "a{text-decoration:none;}"
        "a:hover{text-decoration:underline;}"
        "</style></head><body>"
        f"<h1>{escape(title)}</h1>"
        f"<div class='uuid'>#{escape(uid_short)}</div>"
        f"{metadata_html}"
        "<h2>difinoj</h2>"
        f"{difino_html}"
        f"{etikedoj_html}"
        f"{ligiloj_html}"
        f"{timestamp_html}"
        "</body></html>"
    )


def _write_entry_preview_file(
    entry: dict,
    all_entries: list[dict] | None,
    *,
    montri_cxion: bool = False,
    link_depth: int = 0,
) -> str:
    html_doc = _render_entry_preview_html(
        entry,
        all_entries,
        montri_cxion=montri_cxion,
        link_depth=link_depth,
    )
    return _write_html_document(html_doc)


def _open_entry_preview_file(
    entry: dict, all_entries: list[dict], *, montri_cxion: bool = False
) -> str:
    out_path = _write_entry_preview_file(
        entry,
        all_entries,
        montri_cxion=montri_cxion,
        link_depth=0,
    )
    webbrowser.open(f"file://{out_path}")
    return out_path


def _render_encik_ligilo_markdown(label: str, raw_ref: str) -> str:
    token = _normalize_inline_ref_token(raw_ref)
    if not token.lower().startswith("ec#"):
        return ""
    encik_ref = token[3:]
    if not encik_ref:
        return label
    target = _find_encik_entry(encik_ref)
    if target is None:
        return label
    preview_path = _write_encik_preview_file(target)
    return f"[{label}]({preview_path})"


def _render_encik_ligilo_summary(raw_ref: str) -> str | None:
    token = _normalize_inline_ref_token(raw_ref)
    if not token.lower().startswith("ec#"):
        return None
    encik_ref = token[3:]
    if not encik_ref:
        return "ec#"
    target = _find_encik_entry(encik_ref)
    if target is None:
        return f"ec#{encik_ref[:8]}"
    title = str(target.get("titolo") or "").strip() or f"ec#{encik_ref[:8]}"
    preview_path = _write_encik_preview_file(target)
    short_uuid = str(target.get("uuid") or "")[:8]
    return f"[**{title}**](file://{preview_path}) (ec#{short_uuid})"


def _render_internal_markdown_links(text: str, all_entries: list[dict] | None) -> str:
    if not text or all_entries is None:
        return text

    def _replace(match: re.Match[str]) -> str:
        label = match.group(1).strip()
        target_token = _normalize_inline_ref_token(match.group(2))
        if target_token.lower().startswith("ec#"):
            return _render_encik_ligilo_markdown(label, target_token)
        raw_ref = target_token.lstrip("#")
        if not raw_ref:
            return label
        target = _find_entry(raw_ref, all_entries)
        if target is None:
            return label
        preview_path = _write_entry_preview_file(target, all_entries)
        return f"[{label}]({preview_path})"

    return _INTERNAL_LINK_RE.sub(_replace, text)


def _render_ligilo_plain_text(
    raw_ref: str, all_entries: list[dict] | None, *, show_ref: bool = True
) -> str:
    token = _normalize_inline_ref_token(raw_ref)
    local_ref = token[1:] if token.startswith("#") else token
    if all_entries is not None and local_ref:
        linked = _find_entry(local_ref, all_entries)
        if linked is not None:
            linked_label = (
                str(linked.get("teksto") or "").strip() or f"#{local_ref[:8]}"
            )
            if not show_ref:
                return linked_label
            short_uuid = str(linked.get("uuid") or "")[:8]
            return f"{linked_label} (#{short_uuid})"
    if token.lower().startswith("ec#"):
        encik_ref = token[3:]
        if not encik_ref:
            return "ec#"
        target = _find_encik_entry(encik_ref)
        if target is None:
            fallback = f"ec#{encik_ref[:8]}"
            return fallback if show_ref else fallback
        title = str(target.get("titolo") or "").strip() or f"ec#{encik_ref[:8]}"
        if not show_ref:
            return title
        short_uuid = str(target.get("uuid") or "")[:8]
        return f"{title} (ec#{short_uuid})"
    return str(raw_ref or token)


def _render_internal_plain_links(
    text: str,
    all_entries: list[dict] | None,
    *,
    show_ref: bool = False,
) -> str:
    raw_text = str(text or "")
    if not raw_text:
        return raw_text

    def _replace(match: re.Match[str]) -> str:
        label = match.group(1).strip()
        target_token = _normalize_inline_ref_token(match.group(2))
        if target_token.lower().startswith("ec#"):
            return _render_ligilo_plain_text(
                target_token, all_entries, show_ref=show_ref
            )
        raw_ref = target_token.lstrip("#")
        if not raw_ref:
            return label
        if all_entries is None:
            return label
        target = _find_entry(raw_ref, all_entries)
        if target is None:
            return label
        linked_label = (
            str(target.get("teksto") or "").strip() or label or f"#{raw_ref[:8]}"
        )
        if not show_ref:
            return linked_label
        short_uuid = str(target.get("uuid") or raw_ref)[:8]
        return f"{linked_label} (#{short_uuid})"

    return _INTERNAL_LINK_RE.sub(_replace, raw_text)


def _copy_to_clipboard(value: str, success_message: str) -> None:
    try:
        import pyperclip
    except ImportError:
        typer.echo("Tonduja subteno mankas (pyperclip ne disponeblas).", err=True)
        raise typer.Exit(code=1) from None
    try:
        pyperclip.copy(value)
    except pyperclip.PyperclipException as exc:
        typer.echo(f"Ne povis kopii al tondujo: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(success_message)


def _strip_title_disambiguation(title: str) -> str:
    base = str(title or "").strip()
    if not base:
        return ""
    cleaned = base
    while True:
        updated = re.sub(r"\([^()]*\)", " ", cleaned)
        if updated == cleaned:
            break
        cleaned = updated
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned or base


def _copy_entry_reference(entry: dict, *, semantika: bool = False) -> None:
    entry_uuid = str(entry.get("uuid") or "")
    if not entry_uuid:
        typer.echo("Nevalida eniro: mankas UUID por kopii.", err=True)
        raise typer.Exit(code=1)
    short_ref = f"#{entry_uuid[:8]}"
    if semantika:
        label = str(entry.get("teksto") or "").strip() or short_ref
        label = _strip_title_disambiguation(label)
        payload = f"[{label}]({short_ref})"
        _copy_to_clipboard(payload, "Kopiis semantikan referencon al tondujo.")
        return
    _copy_to_clipboard(short_ref, f"Kopiis UUID al tondujo: {short_ref}")


def _sync_bidirectional_links(
    entries: list[dict],
    source_uuid: str,
    requested_links: list[str],
    *,
    previous_links: list[str] | None = None,
) -> None:
    """Keep links symmetric: if A links to B, B links back to A."""
    source = next((e for e in entries if e["uuid"] == source_uuid), None)
    if source is None:
        return

    now = _now_iso()

    normalized_links: list[str] = []
    seen: set[str] = set()
    for raw in requested_links:
        target = _find_entry(raw, entries)
        target_uuid = target["uuid"] if target is not None else raw
        if target_uuid == source_uuid or target_uuid in seen:
            continue
        seen.add(target_uuid)
        normalized_links.append(target_uuid)

    raw_previous = (
        previous_links
        if previous_links is not None
        else (source.get("ligiloj") or [])
    )
    previous_link_set = {
        target["uuid"]
        for raw in raw_previous
        for target in [_find_entry(raw, entries)]
        if target is not None and target["uuid"] != source_uuid
    }
    current_links = {
        target["uuid"]
        for raw in normalized_links
        for target in [_find_entry(raw, entries)]
        if target is not None and target["uuid"] != source_uuid
    }

    source["ligiloj"] = normalized_links
    source["modifita_je"] = now

    for removed_uuid in previous_link_set - current_links:
        linked = next((e for e in entries if e["uuid"] == removed_uuid), None)
        if linked is None:
            continue
        updated_links = [
            item
            for item in (linked.get("ligiloj") or [])
            if _find_entry(item, entries) is None
            or _find_entry(item, entries)["uuid"] != source_uuid
        ]
        if updated_links != (linked.get("ligiloj") or []):
            linked["ligiloj"] = updated_links
            linked["modifita_je"] = now

    for added_uuid in current_links - previous_link_set:
        linked = next((e for e in entries if e["uuid"] == added_uuid), None)
        if linked is None:
            continue
        linked_links = linked.get("ligiloj") or []
        if source_uuid not in linked_links:
            linked["ligiloj"] = [*linked_links, source_uuid]
            linked["modifita_je"] = now


def _collect_vorto_incoming_refs(
    entries: list[dict], target_uuids: set[str]
) -> list[str]:
    warnings: list[str] = []
    for source in entries:
        source_uuid = str(source.get("uuid") or "")
        if source_uuid in target_uuids:
            continue
        source_text = str(source.get("teksto") or source_uuid[:8] or "-")
        for link_ref in source.get("ligiloj") or []:
            if str(link_ref) in target_uuids:
                warnings.append(
                    "- "
                    f"{source_text} (#{source_uuid[:8]}) -> ligilo al "
                    f"#{str(link_ref)[:8]}"
                )
    return warnings


def _parse_forigi_targets(raw_targets: list[str]) -> list[str]:
    """Parse variadic targets or a JSON-style list string."""
    if len(raw_targets) == 1:
        only = str(raw_targets[0] or "").strip()
        if only.startswith("[") and only.endswith("]"):
            try:
                parsed = json.loads(only)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    "Nevalida listo por forigi. Uzu ekz. "
                    '\'["568b1385", "3dfce5f3"]\'.'
                ) from exc
            if not isinstance(parsed, list) or not all(
                isinstance(item, str) for item in parsed
            ):
                raise ValueError(
                    "Nevalida listo por forigi: atendata listo de tekstoj."
                )
            return [item.strip() for item in parsed if item.strip()]
    return [str(item or "").strip() for item in raw_targets if str(item or "").strip()]


def _find_entry(uid_or_teksto: str, entries: list[dict]) -> dict | None:
    """Locate an entry by exact UUID, UUID prefix, or case-insensitive exact text."""
    raw_lookup = str(uid_or_teksto or "").strip()
    if raw_lookup.lower().startswith("vt#"):
        raw_lookup = "#" + raw_lookup[3:]
    lookup = raw_lookup[1:] if raw_lookup.startswith("#") else raw_lookup
    # Exact UUID match
    for e in entries:
        if e["uuid"] == lookup:
            return e
    # UUID prefix match
    prefix_matches = [e for e in entries if e["uuid"].startswith(lookup)]
    if len(prefix_matches) == 1:
        return prefix_matches[0]
    if len(prefix_matches) > 1:
        typer.echo(
            f"Ambiguous UUID prefix '{lookup}' — "
            f"{len(prefix_matches)} entries match. Use a longer prefix.",
            err=True,
        )
        return None
    # Case-insensitive text match
    text_matches = [
        e for e in entries if e["teksto"].lower() == lookup.lower()
    ]
    if len(text_matches) == 1:
        return text_matches[0]
    if len(text_matches) > 1:
        typer.echo(
            f"Multiple entries match text '{lookup}'. Use UUID instead.",
            err=True,
        )
        return None
    return None


def _fuzzy_text_matches(entries: list[dict], query: str, limit: int = 50) -> list[dict]:
    """Return entries whose teksto is close to query, sorted by similarity.

    Treats 'oe' and 'œ' as equivalent and ignores letter case.
    """
    q = _fold_search_text(query.strip())
    if not q:
        return []
    scored: list[tuple[float, dict]] = []
    for entry in entries:
        text = _fold_search_text(entry.get("teksto") or "")
        if not text:
            continue
        ratio = SequenceMatcher(None, q, text).ratio()
        if ratio >= 0.62:
            scored.append((ratio, entry))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [entry for _, entry in scored[:limit]]


def _ligilo_hops_of(root_uuid: str, entries: list[dict], max_depth: int) -> list[dict]:
    """Traverse linked entries from a root UUID up to max_depth hops.

    Traversal is undirected: outgoing and incoming links are both considered,
    matching the relational search spirit used in encik.
    """
    by_uuid = {str(e.get("uuid") or ""): e for e in entries if e.get("uuid")}
    if root_uuid not in by_uuid:
        return []

    adjacency: dict[str, set[str]] = {uid: set() for uid in by_uuid}
    for source in entries:
        source_uuid = str(source.get("uuid") or "")
        if not source_uuid:
            continue
        for raw_ref in source.get("ligiloj") or []:
            target = _find_entry(str(raw_ref), entries)
            if target is None:
                continue
            target_uuid = str(target.get("uuid") or "")
            if not target_uuid or target_uuid == source_uuid:
                continue
            adjacency.setdefault(source_uuid, set()).add(target_uuid)
            adjacency.setdefault(target_uuid, set()).add(source_uuid)

    visited: set[str] = {root_uuid}
    queue: list[tuple[str, int]] = [(root_uuid, 0)]
    ordered_hits: list[dict] = []
    seen_hits: set[str] = set()
    while queue:
        current_uuid, depth = queue.pop(0)
        if max_depth > 0 and depth >= max_depth:
            continue
        for next_uuid in sorted(adjacency.get(current_uuid, set())):
            if next_uuid in visited:
                continue
            visited.add(next_uuid)
            queue.append((next_uuid, depth + 1))
            if next_uuid != root_uuid and next_uuid not in seen_hits:
                hit = by_uuid.get(next_uuid)
                if hit is not None:
                    ordered_hits.append(hit)
                    seen_hits.add(next_uuid)
    return ordered_hits


# ──────────────────────────────────────────────────────────────────────────────
# Display helpers
# ──────────────────────────────────────────────────────────────────────────────


def _render_ligilo_cli_text(
    raw_ref: str, all_entries: list[dict] | None, *, show_ref: bool = True
) -> Text:
    raw_token = str(raw_ref or "").strip()
    token = _normalize_inline_ref_token(raw_token)
    local_ref = token[1:] if token.startswith("#") else token
    if all_entries is not None and local_ref:
        linked = _find_entry(local_ref, all_entries)
        if linked is not None:
            linked_label = str(linked.get("teksto") or "").strip()
            short_uuid = str(linked.get("uuid") or "")[:8]
            preview_path = _write_entry_preview_file(linked, all_entries)
            rendered = Text()
            rendered.append(
                linked_label or f"#{short_uuid}",
                style=f"link file://{preview_path}",
            )
            if show_ref:
                rendered.append(f" (#{short_uuid})", style="dim")
            return rendered
    if token.lower().startswith("ec#"):
        encik_ref = token[3:]
        if not encik_ref:
            return Text("ec#")
        target = _find_encik_entry(encik_ref)
        if target is None:
            return Text(f"ec#{encik_ref[:8]}")
        title = str(target.get("titolo") or "").strip() or f"ec#{encik_ref[:8]}"
        preview_path = _write_encik_preview_file(target)
        short_uuid = str(target.get("uuid") or "")[:8]
        rendered = Text()
        rendered.append(title, style=f"link file://{preview_path}")
        if show_ref:
            rendered.append(f" (ec#{short_uuid})", style="dim")
        return rendered
    return Text(raw_token or token)


def _render_internal_cli_text(text: str, all_entries: list[dict] | None) -> Text:
    raw_text = str(text or "")
    if not raw_text:
        return Text("")
    rendered = Text()
    pos = 0
    for match in _INTERNAL_LINK_RE.finditer(raw_text):
        start, end = match.span()
        if start > pos:
            rendered.append(raw_text[pos:start])
        target_token = _normalize_inline_ref_token(match.group(2))
        if target_token.lower().startswith("ec#"):
            rendered.append_text(
                _render_ligilo_cli_text(target_token, all_entries, show_ref=False)
            )
            pos = end
            continue
        raw_ref = target_token.lstrip("#")
        if all_entries is None or not raw_ref:
            rendered.append(match.group(1).strip() or raw_ref)
            pos = end
            continue
        target = _find_entry(raw_ref, all_entries)
        if target is None:
            rendered.append(match.group(1).strip() or raw_ref)
            pos = end
            continue
        preview_path = _write_entry_preview_file(target, all_entries)
        label = str(target.get("teksto") or "").strip() or match.group(1).strip()
        rendered.append(label or f"#{raw_ref[:8]}", style=f"link file://{preview_path}")
        pos = end
    if pos < len(raw_text):
        rendered.append(raw_text[pos:])
    return rendered


def _display_entry(
    entry: dict,
    all_entries: list[dict] | None = None,
    *,
    montri_cxion: bool = False,
) -> None:
    """Render one entry using a Rich panel."""
    uid_short = entry["uuid"][:8]
    header = _render_internal_cli_text(str(entry.get("teksto") or ""), all_entries)
    if not header.plain:
        header = Text(str(entry.get("teksto") or ""))
    header.stylize("bold")
    header.append(f"  #{uid_short}", style="dim")
    lines: list[str] = []

    def _row(label: str, value: str) -> None:
        if value:
            lines.append(f"{label} {value}")

    kategorio = entry.get("kategorio") or ""
    tipos = entry.get("tipo") or []
    # Join multiple tipos with commas
    tipo_str = (
        ", ".join(tipos)
        if isinstance(tipos, list)
        else str(tipos) if tipos else ""
    )
    tipo_full = kategorio + ("/" + tipo_str if tipo_str else "")
    lang = entry.get("lingvo") or ""
    if lang and tipo_full:
        lines.append(f"{lang} - {tipo_full}")
    elif lang or tipo_full:
        lines.append(lang or tipo_full)
    _row("aŭtoro:", entry.get("autoro") or "")
    _row("verko:", entry.get("verko") or "")
    if montri_cxion:
        lines.append("")
        _row("temo:", entry.get("temo") or "")
        _row("tono:", entry.get("tono") or "")
        nivelo = entry.get("nivelo")
        _row("nivelo:", f"{nivelo:.1f}" if nivelo is not None else "")

    difinoj: list[str] = entry.get("difinoj") or []
    uzoj: list[str] = entry.get("uzoj") or []
    if difinoj:
        if lines and lines[-1] != "":
            lines.append("")
        lines.append("**difinoj:**")
        if len(difinoj) == 1:
            rendered_difino = _render_internal_markdown_links(difinoj[0], all_entries)
            lines.append(f"**{rendered_difino}**")
            if uzoj and uzoj[0]:
                rendered_uzo = _render_internal_markdown_links(uzoj[0], all_entries)
                lines.append(f"*{rendered_uzo}*")
        else:
            for i, d in enumerate(difinoj, 1):
                rendered_difino = _render_internal_markdown_links(d, all_entries)
                lines.append(f"**{i}. {rendered_difino}**")
                if i - 1 < len(uzoj) and uzoj[i - 1]:
                    rendered_uzo = _render_internal_markdown_links(
                        uzoj[i - 1], all_entries
                    )
                    lines.append(f"*{rendered_uzo}*")

    if montri_cxion:
        etikedoj: dict[str, str] = entry.get("etikedoj") or {}
        if etikedoj:
            if lines and lines[-1] != "":
                lines.append("")
            lines.append("**etikedoj:**")
            for k, v in etikedoj.items():
                lines.append(f"{k}: {v}")

    ligiloj: list[str] = entry.get("ligiloj") or []
    ligiloj_line: Text | None = None
    if ligiloj:
        ligiloj_line = Text("ligiloj: ")
        for index, raw_link in enumerate(ligiloj):
            if index:
                ligiloj_line.append(" | ", style="dim")
            ligiloj_line.append_text(
                _render_ligilo_cli_text(str(raw_link or ""), all_entries)
            )

    if montri_cxion:
        lines.append("")
        _row("kreita:", (entry.get("kreita_je") or "")[:19])
        modifita = entry.get("modifita_je") or ""
        kreita = entry.get("kreita_je") or ""
        if modifita and modifita != kreita:
            _row("modifita:", modifita[:19])

    md_obj = Markdown("\n".join(lines))
    body_parts = [header, Text(""), md_obj]
    if ligiloj_line is not None:
        body_parts.extend([Text(""), ligiloj_line])
    panel = Panel(Group(*body_parts), border_style="dim", expand=False)
    console.print(panel)


def _display_results(
    entries: list[dict],
    *,
    all_entries: list[dict] | None = None,
    numerate: bool = False,
) -> None:
    """Render a list of entries as a Rich table."""
    if not entries:
        typer.echo("Neniu rezulto trovita. (No results found.)")
        return
    link_context = all_entries or entries
    show_ligiloj = any(bool(e.get("ligiloj")) for e in entries)
    table = Table(
        show_header=True,
        header_style="dim",
        border_style="dim",
        expand=False,
    )
    if numerate:
        table.add_column("#", style="dim", width=3, no_wrap=True)
    table.add_column("UUID", style="dim", width=10, no_wrap=True)
    table.add_column("Teksto", min_width=20)
    table.add_column("Lingvo", width=8)
    table.add_column("Tipo", width=18)
    table.add_column("Niv.", width=5)
    table.add_column("Dato", width=12)
    if show_ligiloj:
        table.add_column("Ligiloj", overflow="fold")
    for idx, e in enumerate(entries, 1):
        uid_short = e["uuid"][:8]
        kategorio = e.get("kategorio") or ""
        tipos = e.get("tipo") or []
        # Join multiple tipos with commas
        tipo_str_list = (
            ", ".join(tipos)
            if isinstance(tipos, list)
            else str(tipos) if tipos else ""
        )
        tipo_full = kategorio + ("/" + tipo_str_list if tipo_str_list else "")
        date_str = (e.get("kreita_je") or "")[:10]
        nivelo = e.get("nivelo")
        row_cells: list[str | Text] = []
        if numerate:
            row_cells.append(str(idx))
        row_cells.extend(
            [
                uid_short,
                _render_internal_cli_text(str(e.get("teksto") or ""), link_context),
                e.get("lingvo") or "",
                tipo_full,
                f"{nivelo:.1f}" if nivelo is not None else "",
                date_str,
            ]
        )
        if show_ligiloj:
            rendered_links = Text("-")
            ligiloj = e.get("ligiloj") or []
            if ligiloj:
                rendered_links = Text()
                for link_index, raw_link in enumerate(ligiloj):
                    if link_index:
                        rendered_links.append(" | ", style="dim")
                    rendered_links.append_text(
                        _render_ligilo_cli_text(
                            str(raw_link or ""),
                            link_context,
                            show_ref=False,
                        )
                    )
            row_cells.append(rendered_links)
        table.add_row(*row_cells)
    console.print(table)


def _truncate_text_for_display(text: str, *, limit: int = 30) -> str:
    value = str(text or "").strip()
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)] + "..."


def _ligilo_human_label(raw_ref: str, all_entries: list[dict] | None) -> str:
    raw_token = str(raw_ref or "").strip()
    token = _normalize_inline_ref_token(raw_token)
    local_ref = token[1:] if token.startswith("#") else token
    if all_entries:
        linked = _find_entry(local_ref, all_entries)
        if linked is not None:
            label = str(linked.get("teksto") or "").strip() or f"#{local_ref[:8]}"
            return _truncate_text_for_display(label, limit=30)
    if token.lower().startswith("ec#"):
        encik_ref = token[3:]
        target = _find_encik_entry(encik_ref)
        if target is not None:
            title = str(target.get("titolo") or "").strip() or f"ec#{encik_ref[:8]}"
            return _truncate_text_for_display(title, limit=30)
        return f"ec#{encik_ref[:8]}"
    plain_ref = local_ref.lstrip("#")
    if re.fullmatch(r"[0-9a-fA-F-]{8,36}", plain_ref):
        return f"#{plain_ref[:8]}"
    return _truncate_text_for_display(raw_token or token, limit=30)


def _format_ligiloj_for_confirmation(
    value: object, all_entries: list[dict] | None
) -> str:
    if not value:
        return "[]"
    if isinstance(value, list):
        items = value
    else:
        items = [value]
    labels = [
        f"[{_ligilo_human_label(str(item), all_entries)}]"
        for item in items
        if str(item).strip()
    ]
    return ", ".join(labels) if labels else "[]"


def _show_diff_confirmation(
    action_label: str,
    entry: dict,
    old_entry: dict | None = None,
    *,
    all_entries: list[dict] | None = None,
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
        "uzoj",
        "etikedoj",
        "ligiloj",
        "autoro",
        "verko",
    )
    title = entry.get("teksto") or action_label
    uuid_short = (entry.get("uuid") or "")[:8]

    def _fmt(field: str, value: object) -> str:
        if field == "ligiloj":
            return _format_ligiloj_for_confirmation(value, all_entries)
        return repr(value)

    typer.echo("")
    typer.echo(f"── **{title}** #{uuid_short} ──────────────────────────")
    if old_entry:
        for f in _FIELDS:
            old_v = old_entry.get(f)
            new_v = entry.get(f)
            if old_v != new_v:
                typer.echo(f"  {f}: {_fmt(f, old_v)}  →  {_fmt(f, new_v)}")
    else:
        for f in _FIELDS:
            v = entry.get(f)
            if v:
                typer.echo(f"  {f}: {_fmt(f, v)}")
    typer.echo("──────────────────────────────────────────────────────────")
    return _confirm_esperante("Daŭrigi?", default_yes=True)


def _confirm_esperante(prompt: str, *, default_yes: bool) -> bool:
    suffix = "(J/n)" if default_yes else "(j/N)"
    ans = typer.prompt(f"{prompt} {suffix}", default=("J" if default_yes else "N"))
    first = ans.strip()[:1].lower() if ans is not None else ""
    if not first:
        return default_yes
    if first in ("j", "y"):
        return True
    if first == "n":
        return False
    return default_yes


# ──────────────────────────────────────────────────────────────────────────────
# Subcommands
# ──────────────────────────────────────────────────────────────────────────────


@app.command("aldoni")
def aldoni(
    teksto: str = typer.Argument(..., help="Word, phrase, or sentence to add."),
    lingvo: str | None = typer.Option(
        None,
        "-l",
        "--lingvo",
        help="2-letter language code (e.g. eo, en). Example: --lingvo eo",
    ),
    tipo: str | None = typer.Option(
        None,
        "-t",
        "--tipo",
        help="Subtype (comma-separated for multiple): substantivo/su, "
        "substantivo-neŭtra/sn, substantivo-plurala/sp, "
        "substantivo-ina/si, substantivo-ina-plurala/sip, "
        "substantivo-vira/sv, substantivo-vira-plurala/svp, verbo/ve, "
        "verbo-transitiva/vt, verbo-nerekta-transitiva/vnt, verbo-netransitiva/vn, "
        "refleksiva-verbo/vr, "
        "adjektivo/aj, adverbo/av, "
        "parola/pa, skriba/sk, citaĵo/ci, ŝerco/ŝe, proverbo/pr, poemo/po, "
        "ekzemplo/ek. Example: --tipo 'aj,su' for adjective and noun.",
    ),
    temo: str | None = typer.Option(
        None, "--temo", help="Theme (free text). Example: --temo literaturo"
    ),
    tono: str | None = typer.Option(
        None,
        "--tono",
        help="Tonality: informala/in, formala/fo, ambaŭ/am. Example: --tono in",
    ),
    nivelo: float | None = typer.Option(
        None, "-n", "--nivelo", help="Lexical complexity 1–10. Example: --nivelo 4.5"
    ),
    difino: list[str] | None = typer.Option(
        None,
        "-d",
        "--difino",
        help=(
            "Definition. Repeat flag for multiple. "
            'Preferred syntax uses braces for examples: "{definition}:{example}" '
            '(e.g. -d "saluto:{mi uzas tion}"). '
            'Legacy syntax still accepted: "{definition}:*{example}*" or '
            '"{definition}::{example}". '
            "If text contains !, prefer single quotes or escape ! in shell."
        ),
    ),
    etikedo: list[str] | None = typer.Option(
        None,
        "-e",
        "--etikedo",
        help=(
            "Custom tag KEY:VALUE. Repeat flag for multiple. "
            "Example: -e fako:lingvistiko"
        ),
    ),
    ligilo: list[str] | None = typer.Option(
        None,
        "-L",
        "--ligilo",
        help=(
            "Linked ref(s). Repeat flag for multiple. "
            "Examples: -L #952f2079 (vorto), -L ec#4feb123f (encik)"
        ),
    ),
    autoro: str | None = typer.Option(
        None, "-A", "--autoro", help='Author of the text. Example: --autoro "Voltaire"'
    ),
    verko: str | None = typer.Option(
        None,
        "-v",
        "--verko",
        help="Source work in 'Title:Year' format (e.g. 'Le Petit Prince:1943').",
    ),
    kopii_uuid: bool = typer.Option(
        False,
        "-k",
        "--kopii",
        help="Kopii #xxxxxxxx de la aldonita/modifita eniro al tondujo.",
    ),
    semantika_kopii: bool = typer.Option(
        False,
        "-sk",
        "--semantika-kopii",
        help="Kopii [teksto](#xxxxxxxx) de la aldonita/modifita eniro al tondujo.",
    ),
) -> None:
    """Add a new word, phrase, or sentence to the wordbank."""
    if kopii_uuid and semantika_kopii:
        typer.echo("Uzu nur unu el --kopii aŭ --semantika-kopii.", err=True)
        raise typer.Exit(code=1)
    if nivelo is not None and not (1.0 <= nivelo <= 10.0):
        typer.echo("Error: nivelo must be between 1 and 10.", err=True)
        raise typer.Exit(code=1)

    teksto = _normalize_multiline_text(teksto)
    difino = [_normalize_multiline_text(d) for d in (difino or [])]

    # Apply French ligature normalization when language is French
    if (lingvo or "").lower() == "fr":
        teksto = _apply_french_ligatures(teksto)
        difino = [_apply_french_ligatures(d) for d in (difino or [])]

    difinoj, uzoj = _normalize_difinoj_uzoj(difino or [], [])

    # Load all entries early for duplicate checking and link synchronization
    entries = _load_entries()

    # ── Duplicate teksto check ────────────────────────────────────────────────
    existing_entry = _find_existing_by_teksto_in_list(teksto, entries)
    
    if existing_entry is not None:
        typer.echo(
            f"Eniro kun teksto \"{existing_entry['teksto']}\" jam ekzistas "
            f"(#{existing_entry['uuid'][:8]})."
        )
        if not _confirm_esperante(
            "Ĉu anstataŭigi la ekzistantan eniron per la novaj valoroj?",
            default_yes=False,
        ):
            typer.echo("Nuligita. (Cancelled.)")
            return
        # Overwrite: apply modifi-equivalent on the existing entry
        old_entry = dict(existing_entry)
        if lingvo is not None:
            existing_entry["lingvo"] = lingvo
        if tipo is not None:
            existing_entry["tipo"] = _normalize_tipo(tipo)
        if temo is not None:
            existing_entry["temo"] = _normalize_multiline_text(temo)
        if tono is not None:
            existing_entry["tono"] = _normalize_tono(tono)
        if nivelo is not None:
            existing_entry["nivelo"] = nivelo
        if difino is not None:
            existing_entry["difinoj"] = difinoj
            existing_entry["uzoj"] = uzoj
        if etikedo is not None:
            existing_entry["etikedoj"] = _parse_etikedo(etikedo)
        if ligilo is not None:
            existing_entry["ligiloj"] = ligilo or []
        existing_entry["ligiloj"] = _merge_links_with_inline_refs(
            existing_entry.get("ligiloj") or [],
            existing_entry.get("difinoj") or [],
            existing_entry.get("uzoj") or [],
            entries,
            extra_payload=existing_entry,
        )
        if autoro is not None:
            existing_entry["autoro"] = _normalize_multiline_text(autoro)
        if verko is not None:
            existing_entry["verko"] = _normalize_multiline_text(verko)
        existing_entry["modifita_je"] = _now_iso()
        if not _show_diff_confirmation(
            "modifi (anstataŭigi)",
            existing_entry,
            old_entry,
            all_entries=entries,
        ):
            typer.echo("Nuligita. (Cancelled.)")
            return
        idx = next(
            i for i, e in enumerate(entries) if e["uuid"] == existing_entry["uuid"]
        )
        entries[idx] = existing_entry
        _sync_bidirectional_links(
            entries,
            existing_entry["uuid"],
            existing_entry.get("ligiloj") or [],
            previous_links=old_entry.get("ligiloj") or [],
        )
        _save_entries(entries)
        _push_undo({"op": "modifi", "old": old_entry})
        typer.echo(
            f"Modifis #{existing_entry['uuid'][:8]}  \"{existing_entry['teksto']}\""
        )
        if kopii_uuid or semantika_kopii:
            _copy_entry_reference(existing_entry, semantika=semantika_kopii)
        return
    # ── No duplicate — create a new entry ────────────────────────────────────

    now = _now_iso()
    entry: dict = {
        "uuid": str(_uuid_mod.uuid4()),
        "teksto": teksto,
        "lingvo": lingvo,
        "kategorio": _detect_kategorio(teksto),
        "tipo": _normalize_tipo(tipo),
        "temo": _normalize_multiline_text(temo) if temo is not None else None,
        "tono": _normalize_tono(tono),
        "nivelo": nivelo,
        "difinoj": difinoj,
        "uzoj": uzoj,
        "etikedoj": _parse_etikedo(etikedo),
        "ligiloj": [],
        "autoro": _normalize_multiline_text(autoro) if autoro is not None else None,
        "verko": _normalize_multiline_text(verko) if verko is not None else None,
        "kreita_je": now,
        "modifita_je": now,
    }
    entry["ligiloj"] = _merge_links_with_inline_refs(
        ligilo or [],
        entry.get("difinoj") or [],
        entry.get("uzoj") or [],
        entries,
        extra_payload=entry,
    )

    if not _show_diff_confirmation("aldoni", entry, all_entries=entries):
        typer.echo("Nuligita. (Cancelled.)")
        return

    entries.append(entry)
    _sync_bidirectional_links(
        entries,
        entry["uuid"],
        entry.get("ligiloj") or [],
        previous_links=[],
    )
    _save_entries(entries)
    _push_undo({"op": "aldoni", "uuid": entry["uuid"]})
    typer.echo(f"Aldonis #{entry['uuid'][:8]}  \"{entry['teksto']}\"")
    if kopii_uuid or semantika_kopii:
        _copy_entry_reference(entry, semantika=semantika_kopii)


@app.command("vidi")
def vidi(
    uid: str | None = typer.Argument(
        None,
        help=(
            "UUID (or prefix) of the entry to view. Omit to list latest 50. "
            "Example: vorto vidi #952f2079"
        ),
    ),
    teksto_ref: str | None = typer.Option(
        None,
        "-T",
        "--teksto",
        help='Teksta referenco por vidi eniron. Ekzemplo: --teksto "saluton"',
    ),
    inverse: bool = typer.Option(
        False, "-i", "--inversa", help="List oldest 50 first (only without UUID)."
    ),
    montri_cxion: bool = typer.Option(
        False, "-a", "--cxio", help="Montri ĉiujn detalojn (inkluzive datojn)."
    ),
    html: bool = typer.Option(
        False,
        "-H",
        "--html",
        help="Malfermi la eniron kiel formatitan HTML-paĝon en retumilo.",
    ),
    kopii_uuid: bool = typer.Option(
        False,
        "-k",
        "--kopii",
        help="Kopii #xxxxxxxx de la montrita eniro al tondujo.",
    ),
    semantika_kopii: bool = typer.Option(
        False,
        "-sk",
        "--semantika-kopii",
        help="Kopii [teksto](#xxxxxxxx) de la montrita eniro al tondujo.",
    ),
) -> None:
    """View a wordbank entry, or list the latest 50 entries when called
    without argument."""
    if uid is not None and teksto_ref is not None:
        typer.echo("Uzu aŭ pozician referencon aŭ --teksto, ne ambaŭ.", err=True)
        raise typer.Exit(code=1)
    lookup_ref = uid if uid is not None else teksto_ref
    if kopii_uuid and semantika_kopii:
        typer.echo("Uzu nur unu el --kopii aŭ --semantika-kopii.", err=True)
        raise typer.Exit(code=1)
    if (kopii_uuid or semantika_kopii) and html:
        typer.echo("--kopii/--semantika-kopii ne kongruas kun --html.", err=True)
        raise typer.Exit(code=1)
    if lookup_ref is None and (kopii_uuid or semantika_kopii):
        typer.echo(
            "--kopii/--semantika-kopii postulas UUID aŭ tekstan referencon.",
            err=True,
        )
        raise typer.Exit(code=1)
    if lookup_ref is None and html:
        typer.echo("--html postulas UUID aŭ tekstan referencon.", err=True)
        raise typer.Exit(code=1)
    entries = _load_entries()
    if lookup_ref is None:
        # Show latest (or oldest) 50
        if inverse:
            results = entries[:50]
        else:
            results = list(reversed(entries))[:50]
        typer.echo(f"{len(results)} rezulto(j).")
        _display_results(results, all_entries=entries)
        return
    lookup_uid = lookup_ref[1:] if lookup_ref.startswith("#") else lookup_ref
    entry = _find_entry(lookup_uid, entries)
    if entry is None:
        # No exact match — try fuzzy/closest matches (max 5)
        closest = _fuzzy_text_matches(entries, lookup_uid, limit=5)
        if not closest:
            typer.echo(f"Eniro ne trovita: {lookup_ref!r}", err=True)
            raise typer.Exit(code=1)
        if len(closest) == 1:
            typer.echo(
                f"Ekzakta kongruo ne trovita. Montras plej proksiman: "
                f"\"{closest[0]['teksto']}\""
            )
            if html:
                out_path = _open_entry_preview_file(
                    closest[0], entries, montri_cxion=montri_cxion
                )
                typer.echo(f"Malfermas en retumilo: {out_path}")
                return
            if kopii_uuid or semantika_kopii:
                _copy_entry_reference(closest[0], semantika=semantika_kopii)
            _display_entry(closest[0], entries, montri_cxion=montri_cxion)
            return
        # Multiple approximate matches — ask user to pick one
        typer.echo(
            f"Ekzakta kongruo ne trovita por {lookup_ref!r}. Proksimaj rezultoj:"
        )
        for i, match in enumerate(closest, 1):
            typer.echo(
                f"  {i}. [{match['uuid'][:8]}] {match['teksto']}"
                + (f"  ({match.get('lingvo') or ''})" if match.get("lingvo") else "")
            )
        raw = typer.prompt(
            f"Elektu numeron (1-{len(closest)}) aŭ premu Enter por nuligi",
            default="",
        )
        raw = raw.strip()
        if not raw:
            typer.echo("Nuligita.")
            return
        try:
            idx = int(raw) - 1
            if not (0 <= idx < len(closest)):
                raise ValueError
        except ValueError:
            typer.echo("Nevalida elekto.", err=True)
            raise typer.Exit(code=1) from None
        if html:
            out_path = _open_entry_preview_file(
                closest[idx], entries, montri_cxion=montri_cxion
            )
            typer.echo(f"Malfermas en retumilo: {out_path}")
            return
        if kopii_uuid or semantika_kopii:
            _copy_entry_reference(closest[idx], semantika=semantika_kopii)
        _display_entry(closest[idx], entries, montri_cxion=montri_cxion)
        return
    if html:
        out_path = _open_entry_preview_file(entry, entries, montri_cxion=montri_cxion)
        typer.echo(f"Malfermas en retumilo: {out_path}")
        return
    if kopii_uuid or semantika_kopii:
        _copy_entry_reference(entry, semantika=semantika_kopii)
    _display_entry(entry, entries, montri_cxion=montri_cxion)


@app.command("modifi")
def modifi(
    ctx: typer.Context,
    uid: str = typer.Argument(
        ...,
        help=(
            "UUID (or prefix) of the entry to modify. "
            "Example: vorto modifi #952f2079"
        ),
    ),
    teksto: str | None = typer.Option(
        None,
        "--teksto",
        help='New text. Example: --teksto "nova"',
    ),
    lingvo: str | None = typer.Option(
        None,
        "-l",
        "--lingvo",
        help="New 2-letter language code. Example: --lingvo eo",
    ),
    tipo: str | None = typer.Option(
        None,
        "-t",
        "--tipo",
        help="New subtype. Example: --tipo su",
    ),
    temo: str | None = typer.Option(
        None,
        "--temo",
        help="New theme. Example: --temo literaturo",
    ),
    tono: str | None = typer.Option(
        None,
        "--tono",
        help="New tonality. Example: --tono in",
    ),
    nivelo: float | None = typer.Option(
        None,
        "-n",
        "--nivelo",
        help="New lexical complexity 1–10. Example: --nivelo 3.0",
    ),
    difino: list[str] | None = typer.Option(
        None,
        "-d",
        "--difino",
        help='New definitions (replaces existing). Example: -d "saluto:{mi uzas tion}"',
    ),
    etikedo: list[str] | None = typer.Option(
        None,
        "-e",
        "--etikedo",
        help="New tags KEY:VALUE (replaces existing). Example: -e fako:lingvistiko",
    ),
    ligilo: list[str] | None = typer.Option(
        None,
        "-L",
        "--ligilo",
        help=(
            "New linked ref(s), replaces existing. "
            "Examples: -L #952f2079 (vorto), -L ec#4feb123f (encik)"
        ),
    ),
    autoro: str | None = typer.Option(
        None, "-A", "--autoro", help='New author. Example: --autoro "Voltaire"'
    ),
    verko: str | None = typer.Option(
        None,
        "-v",
        "--verko",
        help="New source work in 'Title:Year' format. Example: --verko Candide:1759",
    ),
    kopii_uuid: bool = typer.Option(
        False,
        "-k",
        "--kopii",
        help="Kopii #xxxxxxxx de la modifita eniro al tondujo.",
    ),
    semantika_kopii: bool = typer.Option(
        False,
        "-sk",
        "--semantika-kopii",
        help="Kopii [teksto](#xxxxxxxx) de la modifita eniro al tondujo.",
    ),
) -> None:
    """Modify a wordbank entry. Pass at least one option to update."""
    if kopii_uuid and semantika_kopii:
        typer.echo("Uzu nur unu el --kopii aŭ --semantika-kopii.", err=True)
        raise typer.Exit(code=1)
    opts = (
        teksto, lingvo, tipo, temo, tono, nivelo, difino, etikedo, ligilo,
        autoro, verko,
    )
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
        difinoj, uzoj = _normalize_difinoj_uzoj(difino, entry.get("uzoj") or [])
        entry["difinoj"] = difinoj
        entry["uzoj"] = uzoj
    if etikedo is not None:
        entry["etikedoj"] = _parse_etikedo(etikedo)
    if ligilo is not None:
        entry["ligiloj"] = ligilo
    if autoro is not None:
        entry["autoro"] = autoro
    if verko is not None:
        entry["verko"] = verko
    entry["modifita_je"] = _now_iso()

    # Apply French ligature normalization using the effective language
    effective_lingvo = (entry.get("lingvo") or "").lower()
    if effective_lingvo == "fr":
        entry["teksto"] = _apply_french_ligatures(entry["teksto"])
        entry["difinoj"] = [
            _apply_french_ligatures(d) for d in entry.get("difinoj") or []
        ]
    entry["ligiloj"] = _merge_links_with_inline_refs(
        entry.get("ligiloj") or [],
        entry.get("difinoj") or [],
        entry.get("uzoj") or [],
        entries,
        extra_payload=entry,
    )

    if not _show_diff_confirmation("modifi", entry, old_entry, all_entries=entries):
        typer.echo("Nuligita. (Cancelled.)")
        return

    idx = next(i for i, e in enumerate(entries) if e["uuid"] == entry["uuid"])
    entries[idx] = entry
    _sync_bidirectional_links(
        entries,
        entry["uuid"],
        entry.get("ligiloj") or [],
        previous_links=old_entry.get("ligiloj") or [],
    )
    _save_entries(entries)
    _push_undo({"op": "modifi", "old": old_entry})
    typer.echo(f"Modifis #{entry['uuid'][:8]}  \"{entry['teksto']}\"")
    if kopii_uuid or semantika_kopii:
        _copy_entry_reference(entry, semantika=semantika_kopii)


def _search_entries_optimized(
    *,
    lingvo: str | None = None,
    tipo: str | None = None,
    temo: str | None = None,
    tono: str | None = None,
    autoro: str | None = None,
    verko: str | None = None,
    nivelo_min: float | None = None,
    nivelo_max: float | None = None,
    dato_de: str | None = None,
    dato_gis: str | None = None,
    limo: int = 1000,
) -> list[dict]:
    """Load entries using SQL filters for efficiency."""
    conn = _get_db()
    try:
        where_clauses = []
        params = []
        
        if lingvo is not None:
            where_clauses.append("lingvo = ?")
            params.append(lingvo)
        if tono is not None:
            where_clauses.append("tono = ?")
            params.append(_normalize_tono(tono))
        if nivelo_min is not None:
            where_clauses.append("(nivelo >= ? OR nivelo IS NULL)")
            params.append(nivelo_min)
        if nivelo_max is not None:
            where_clauses.append("(nivelo <= ? OR nivelo IS NULL)")
            params.append(nivelo_max)
        if dato_de is not None:
            where_clauses.append("kreita_je >= ?")
            params.append(dato_de)
        if dato_gis is not None:
            end = dato_gis + "T23:59:59"
            where_clauses.append("kreita_je <= ?")
            params.append(end)
        
        where_sql = ""
        if where_clauses:
            where_sql = " WHERE " + " AND ".join(where_clauses)
        
        sql = f"SELECT * FROM vorto{where_sql} LIMIT ?"
        params.append(limo)
        
        rows = conn.execute(sql, params).fetchall()
        entries = [_row_to_dict(row) for row in rows]
        
        if temo is not None:
            low_temo = temo.lower()
            entries = [e for e in entries if low_temo in (e.get("temo") or "").lower()]
        
        if autoro is not None:
            low_autoro = autoro.lower()
            entries = [e for e in entries if low_autoro in (e.get("autoro") or "").lower()]
        
        if verko is not None:
            low_verko = verko.lower()
            entries = [e for e in entries if low_verko in (e.get("verko") or "").lower()]
        
        if tipo is not None:
            norm = _normalize_tipo(tipo)
            if norm:
                entries = [
                    e
                    for e in entries
                    if (
                        (
                            isinstance(e.get("tipo"), list)
                            and any(t in e.get("tipo") for t in norm)
                        )
                        or e.get("kategorio") in norm
                    )
                ]
        
        return entries
    finally:
        conn.close()


@app.command(
    "serci",
    help=tr(
        "Serĉi en la vortaro. Sen filtriloj → listigi enirojn ĝis --limo.",
        "Search the wordbank. No filters → list all entries up to --limo.",
        "Rechercher dans le lexique. Sans filtres → lister les entrées jusqu'à --limo.",
    ),
)
def serci(
    teksto: str | None = typer.Argument(
        None,
        help=tr(
            "Teksto por serĉi (defaŭlte: montri ĉion).",
            "Text to search for (default: show all).",
            "Texte à rechercher (par défaut : tout afficher).",
        ),
    ),
    ligilo_ref: str | None = typer.Option(
        None,
        "-L",
        "--ligilo",
        help=tr(
            "Serĉi rilatajn enirojn el donita UUID/titolo per ligiloj.",
            "Search related entries from a UUID/title via links.",
            "Rechercher des entrées liées depuis un UUID/titre via des liens.",
        ),
    ),
    lingvo: str | None = typer.Option(
        None,
        "-l",
        "--lingvo",
        help=tr(
            "Filtri laŭ lingvokodo.",
            "Filter by language code.",
            "Filtrer par code de langue.",
        ),
    ),
    tipo: str | None = typer.Option(
        None,
        "-t",
        "--tipo",
        help=tr("Filtri laŭ subtipo.", "Filter by subtype.", "Filtrer par sous-type."),
    ),
    temo: str | None = typer.Option(
        None,
        "--temo",
        help=tr("Filtri laŭ temo.", "Filter by theme.", "Filtrer par thème."),
    ),
    tono: str | None = typer.Option(
        None,
        "--tono",
        help=tr(
            "Filtri laŭ tonalo.",
            "Filter by tonality.",
            "Filtrer par tonalité.",
        ),
    ),
    autoro: str | None = typer.Option(
        None,
        "-a",
        "--autoro",
        help=tr("Filtri laŭ aŭtoro.", "Filter by author.", "Filtrer par auteur."),
    ),
    verko: str | None = typer.Option(
        None,
        "-v",
        "--verko",
        help=tr(
            "Filtri laŭ verko (formato: 'Titolo:Jaro').",
            "Filter by work (format: 'Title:Year').",
            "Filtrer par œuvre (format : 'Titre:Année').",
        ),
    ),
    nivelo_min: float | None = typer.Option(
        None,
        "--nivelo-min",
        help=tr(
            "Minimuma leksika nivelo.",
            "Minimum lexical level.",
            "Niveau lexical minimum.",
        ),
    ),
    nivelo_max: float | None = typer.Option(
        None,
        "--nivelo-max",
        help=tr(
            "Maksimuma leksika nivelo.",
            "Maximum lexical level.",
            "Niveau lexical maximum.",
        ),
    ),
    dato_de: str | None = typer.Option(
        None,
        "--dato-de",
        help=tr(
            "Komenca dato YYYY-MM-DD.",
            "Start date YYYY-MM-DD.",
            "Date de début AAAA-MM-JJ.",
        ),
    ),
    dato_gis: str | None = typer.Option(
        None,
        "--dato-gis",
        help=tr(
            "Fina dato YYYY-MM-DD.",
            "End date YYYY-MM-DD.",
            "Date de fin AAAA-MM-JJ.",
        ),
    ),
    regex: bool = typer.Option(
        False,
        "-r",
        "--regex",
        help=tr(
            "Trakti tekston kiel POSIX-regulesprimon.",
            "Interpret teksto as a POSIX regex.",
            "Interpréter le texte comme regex POSIX.",
        ),
    ),
    preciza: bool = typer.Option(
        False,
        "-p",
        "--preciza",
        help=tr(
            "Malŝalti malklaran rezervan kongruigon.",
            "Disable fuzzy fallback matching.",
            "Désactiver la correspondance approximative de secours.",
        ),
    ),
    limo: int = typer.Option(
        10,
        "-lo",
        "--limo",
        help=tr(
            "Maksimuma nombro da rezultoj (defaŭlte 10).",
            "Max number of results (default 10).",
            "Nombre maximum de résultats (10 par défaut).",
        ),
    ),
    ordo: str = typer.Option(
        "graveco",
        "-o",
        "--ordo",
        help=tr(
            "Ordo: graveco/g, dato/d (plej novaj), inversa-dato/id (plej malnovaj).",
            "Order: graveco/g (relevance), dato/d (newest), inversa-dato/id (oldest).",
            "Ordre : graveco/g (pertinence), dato/d (plus récent), "
            "inversa-dato/id (plus ancien).",
        ),
    ),
    nur_uuid: bool = typer.Option(
        False,
        "-u",
        "--uuid",
        help="Eligi nur UUID-liston kiel JSON (8-signaj prefiksoj).",
    ),
    kopii_uuid: bool = typer.Option(
        False,
        "-k",
        "--kopii",
        help=(
            "Kopii #xxxxxxxx de la trovita eniro al tondujo "
            "(ĉe pluraj rezultoj: la interage elektita)."
        ),
    ),
    semantika_kopii: bool = typer.Option(
        False,
        "-sk",
        "--semantika-kopii",
        help=(
            "Kopii [teksto](#xxxxxxxx) de la trovita eniro al tondujo "
            "(ĉe pluraj rezultoj: la interage elektita)."
        ),
    ),
) -> None:
    """Serĉi en la vortaro."""
    if kopii_uuid and semantika_kopii:
        typer.echo("Uzu nur unu el --kopii aŭ --semantika-kopii.", err=True)
        raise typer.Exit(code=1)
    if (kopii_uuid or semantika_kopii) and teksto is None:
        typer.echo("--kopii/--semantika-kopii postulas serĉan demandon.", err=True)
        raise typer.Exit(code=1)
    if (kopii_uuid or semantika_kopii) and ligilo_ref is not None:
        typer.echo("--kopii/--semantika-kopii ne kongruas kun --ligilo.", err=True)
        raise typer.Exit(code=1)

    entries = _load_entries()
    results = list(entries)
    fuzzy_used = False

    if ligilo_ref is not None:
        root = _find_entry(ligilo_ref, entries)
        if root is None:
            typer.echo(f"Eniro ne trovita por --ligilo: {ligilo_ref!r}", err=True)
            raise typer.Exit(code=1)
        # Keep existing --limo default for regular search, but default to 1 hop here.
        depth = 1 if limo == 10 else abs(limo)
        results = _ligilo_hops_of(str(root.get("uuid") or ""), entries, max_depth=depth)
        if norm_ordo := ordo.lower():
            if norm_ordo in ("dato", "d"):
                results.sort(key=lambda e: e.get("kreita_je") or "", reverse=True)
            elif norm_ordo in ("inversa-dato", "id"):
                results.sort(key=lambda e: e.get("kreita_je") or "")
        if nur_uuid:
            uuid_list = [str(e["uuid"])[:8] for e in results]
            typer.echo(json.dumps(uuid_list, ensure_ascii=False))
            return
        typer.echo(
            f"{len(results)} ligita(j) rezulto(j) trovita(j) "
            f"por #{str(root.get('uuid') or '')[:8]} (limo={depth})."
        )
        _display_results(results, all_entries=entries)
        return

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
            low = _fold_search_text(teksto)
            results = [
                e for e in results if low in _fold_search_text(e.get("teksto") or "")
            ]
            if not results and not preciza:
                fuzzy_used = True
                results = _fuzzy_text_matches(entries=entries, query=teksto, limit=limo)

    # Property filters
    if lingvo:
        results = [e for e in results if e.get("lingvo") == lingvo]
    if tipo:
        norm = _normalize_tipo(tipo)  # Returns list[str] or None
        if norm:
            results = [
                e
                for e in results
                if (
                    # Match if any normalized tipo matches any entry tipo
                    (
                        isinstance(e.get("tipo"), list)
                        and any(t in e.get("tipo") for t in norm)
                    )
                    # Or match kategorio (for backward compat)
                    or e.get("kategorio") in norm
                )
            ]
    if temo:
        low_temo = temo.lower()
        results = [e for e in results if low_temo in (e.get("temo") or "").lower()]
    if tono:
        norm_tono = _normalize_tono(tono)
        results = [e for e in results if e.get("tono") == norm_tono]
    if autoro:
        low_autoro = autoro.lower()
        results = [
            e for e in results if low_autoro in (e.get("autoro") or "").lower()
        ]
    if verko:
        low_verko = verko.lower()
        results = [e for e in results if low_verko in (e.get("verko") or "").lower()]
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

    if nur_uuid:
        uuid_list = [str(e["uuid"])[:8] for e in results]
        typer.echo(json.dumps(uuid_list, ensure_ascii=False))
        return

    if fuzzy_used:
        typer.echo("Neniu preciza rezulto; montrante similajn kongruojn.")
    if len(results) == 1:
        if kopii_uuid or semantika_kopii:
            _copy_entry_reference(results[0], semantika=semantika_kopii)
        _display_entry(results[0], entries, montri_cxion=False)
        return
    typer.echo(f"{len(results)} rezulto(j) trovita(j).")
    _display_results(
        results,
        all_entries=entries,
        numerate=bool(kopii_uuid or semantika_kopii),
    )
    if not results:
        return
    if not (kopii_uuid or semantika_kopii):
        return
    raw = typer.prompt("Elektu numeron por kopii (aŭ Enter por nuligi)", default="")
    if not raw.strip():
        typer.echo("Nuligita.")
        return
    try:
        idx = int(raw.strip()) - 1
    except ValueError:
        typer.echo("Nevalida elekto.", err=True)
        raise typer.Exit(code=1) from None
    if idx < 0 or idx >= len(results):
        typer.echo("Nevalida elekto.", err=True)
        raise typer.Exit(code=1)
    _copy_entry_reference(results[idx], semantika=semantika_kopii)
    _display_entry(results[idx], entries, montri_cxion=False)


@app.command("forigi")
def forigi(
    uid_or_teksto: list[str] = typer.Argument(
        ...,
        help=(
            "Unu aŭ pluraj UUID/teksto-celoj por forigi; aŭ unu JSON-listo "
            'kiel ["568b1385","3dfce5f3"].'
        ),
    ),
) -> None:
    """Move a wordbank entry to the recycle bin (with confirmation).

    Entries in the recycle bin are permanently deleted after 30 days.
    Use  vorto rubujo reakiri <uuid>  to restore.
    """
    if not uid_or_teksto:
        typer.echo("Mankas celo por forigi.", err=True)
        raise typer.Exit(code=2)
    entries = _load_entries()
    try:
        targets = _parse_forigi_targets(uid_or_teksto)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    if not targets:
        typer.echo("Mankas valida celo por forigi.", err=True)
        raise typer.Exit(code=1)

    to_delete: list[dict] = []
    seen: set[str] = set()
    for target in targets:
        entry = _find_entry(target, entries)
        if entry is None:
            typer.echo(f"Eniro ne trovita: {target!r}", err=True)
            raise typer.Exit(code=1)
        if entry["uuid"] in seen:
            continue
        seen.add(entry["uuid"])
        to_delete.append(entry)

    refs = _collect_vorto_incoming_refs(entries, {e["uuid"] for e in to_delete})
    if refs:
        typer.echo("[!] Averto: forigo rompos referencojn en aliaj vorto-eroj:")
        for line in refs:
            typer.echo(f"  {line}")

    typer.echo("Forigontaj eniroj:")
    _display_results(to_delete, all_entries=entries)
    confirm = typer.prompt("Ĉu daŭrigi? (j/N)", default="n")
    if confirm.strip().lower() not in ("j", "jes", "y", "yes"):
        typer.echo("Nuligita.")
        return

    for entry in to_delete:
        _move_to_rubujo(entry)
        _push_undo({"op": "forigi", "uuid": entry["uuid"]})
    typer.echo(
        f"Sendis al rubujo: {len(to_delete)} eniro(j) "
        f"(aŭtomate forigita post {_RUBUJO_DAYS} tagoj)"
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
# Export / Import
# ──────────────────────────────────────────────────────────────────────────────


def _safe_export_basename(raw: str, fallback: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(raw or "").strip())
    ascii_ready = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    candidate = re.sub(r"[^A-Za-z0-9._-]+", "-", ascii_ready).lower()
    candidate = re.sub(r"-{2,}", "-", candidate).strip("-._")
    return candidate or fallback


def _resolve_export_path(
    raw_path: str,
    *,
    default_filename: str,
    suffix: str | None = None,
) -> Path:
    path = Path(raw_path).expanduser()
    raw_text = str(raw_path or "").strip()
    if (path.exists() and path.is_dir()) or raw_text.endswith(("/", "\\")):
        path = path / default_filename
    if suffix and path.suffix.lower() != suffix.lower():
        path = path.with_suffix(suffix)
    return path.resolve()


def _entry_to_toml_text(entry: dict) -> str:
    def _json_string(value: object) -> str:
        return json.dumps(str(value or ""), ensure_ascii=False)

    def _json_list(items: list[object]) -> str:
        return json.dumps([str(item) for item in items], ensure_ascii=False)

    lines: list[str] = [
        f"uuid = {_json_string(entry.get('uuid'))}",
        f"teksto = {_json_string(entry.get('teksto'))}",
        f"lingvo = {_json_string(entry.get('lingvo'))}",
        f"kategorio = {_json_string(entry.get('kategorio'))}",
    ]

    tipo = entry.get("tipo")
    if isinstance(tipo, list):
        lines.append(f"tipo = {_json_list(tipo)}")
    else:
        lines.append(f"tipo = {_json_string(tipo)}")

    lines.extend(
        [
            f"temo = {_json_string(entry.get('temo'))}",
            f"tono = {_json_string(entry.get('tono'))}",
        ]
    )
    nivelo = entry.get("nivelo")
    if isinstance(nivelo, (int, float)):
        lines.append(f"nivelo = {float(nivelo)}")
    lines.extend(
        [
            f"difinoj = {_json_list(entry.get('difinoj') or [])}",
            f"uzoj = {_json_list(entry.get('uzoj') or [])}",
            f"ligiloj = {_json_list(entry.get('ligiloj') or [])}",
            f"autoro = {_json_string(entry.get('autoro'))}",
            f"verko = {_json_string(entry.get('verko'))}",
            f"kreita_je = {_json_string(entry.get('kreita_je'))}",
            f"modifita_je = {_json_string(entry.get('modifita_je'))}",
        ]
    )
    etikedoj = entry.get("etikedoj") or {}
    if isinstance(etikedoj, dict) and etikedoj:
        lines.append("")
        lines.append("[etikedoj]")
        for key, value in sorted(etikedoj.items()):
            key_text = json.dumps(str(key), ensure_ascii=False)
            lines.append(f"{key_text} = {_json_string(value)}")
    return "\n".join(lines) + "\n"


def _select_entry_for_export(reference: str, entries: list[dict]) -> dict | None:
    raw_ref = str(reference or "").strip()
    if not raw_ref:
        return None
    if raw_ref.lower().startswith("vt#"):
        raw_ref = "#" + raw_ref[3:]
    lookup = raw_ref[1:] if raw_ref.startswith("#") else raw_ref

    def _dedupe(candidates: list[dict]) -> list[dict]:
        seen: set[str] = set()
        ordered: list[dict] = []
        for candidate in candidates:
            uid = str(candidate.get("uuid") or "")
            if not uid or uid in seen:
                continue
            seen.add(uid)
            ordered.append(candidate)
        return ordered

    def _prompt_pick(candidates: list[dict], message: str) -> dict | None:
        if not candidates:
            return None
        typer.echo(message)
        _display_results(candidates, all_entries=entries, numerate=True)
        raw = typer.prompt(
            "Elektu numeron por eksporti (aŭ Enter por nuligi)",
            default="",
        )
        if not raw.strip():
            typer.echo("Nuligita.")
            raise typer.Exit(code=0)
        try:
            idx = int(raw.strip()) - 1
        except ValueError:
            typer.echo("Nevalida elekto.", err=True)
            raise typer.Exit(code=1) from None
        if idx < 0 or idx >= len(candidates):
            typer.echo("Nevalida elekto.", err=True)
            raise typer.Exit(code=1)
        return candidates[idx]

    by_uuid_exact = [e for e in entries if str(e.get("uuid") or "") == lookup]
    if len(by_uuid_exact) == 1:
        return by_uuid_exact[0]

    by_uuid_prefix = [
        e for e in entries if lookup and str(e.get("uuid") or "").startswith(lookup)
    ]
    by_text_exact = [
        e
        for e in entries
        if str(e.get("teksto") or "").strip().lower() == lookup.lower()
    ]
    exact_candidates = _dedupe([*by_uuid_exact, *by_uuid_prefix, *by_text_exact])
    if exact_candidates:
        if len(exact_candidates) == 1:
            return exact_candidates[0]
        return _prompt_pick(exact_candidates, f"Pluraj kandidatoj por {reference!r}:")

    folded_lookup = _fold_search_text(lookup)
    contains_candidates = _dedupe(
        [
            e
            for e in entries
            if folded_lookup
            and folded_lookup in _fold_search_text(str(e.get("teksto") or ""))
        ]
    )[:20]
    fuzzy_candidates = _fuzzy_text_matches(entries, lookup, limit=20)
    candidates = (
        contains_candidates if contains_candidates else _dedupe(fuzzy_candidates)
    )
    if not candidates:
        return None
    return _prompt_pick(
        candidates,
        f"Ekzakta kongruo ne trovita por {reference!r}. Proksimaj rezultoj:",
    )


@app.command("eksporti")
def eksporti(
    celo_aux_ref: str = typer.Argument(
        ...,
        help=(
            "Cel dosiero por plena eksporto (ekz: vorto.json), aŭ referenco por unuopa "
            "eksporto (ekz: #952f2079 aŭ saluton)."
        ),
    ),
    celvojo: str | None = typer.Argument(
        None,
        help=(
            "Nedeviga celvojo por unuopa eksporto al TOML. "
            "Ekzemplo: vorto eksporti #952f2079 ~/eliro/mia_vorto.toml"
        ),
    ),
    pasvorto: str | None = typer.Option(
        None,
        "-p",
        "--pasvorto",
        help="Optional password to encrypt the export.",
    ),
) -> None:
    """Eksporti ĉiujn enirojn (JSON) aŭ unu eniron (TOML)."""
    from autish.commands._crypto import encrypt  # noqa: PLC0415

    # One-entry export mode: vorto eksporti <UUID|TEKSTO> <celvojo>
    if celvojo is not None:
        if pasvorto:
            typer.echo(
                "--pasvorto estas disponebla nur por plena JSON-eksporto.",
                err=True,
            )
            raise typer.Exit(1)
        entries = _load_entries()
        entry = _select_entry_for_export(celo_aux_ref, entries)
        if entry is None:
            typer.echo(f"Eniro ne trovita: {celo_aux_ref!r}", err=True)
            raise typer.Exit(1)
        short_uuid = str(entry.get("uuid") or "")[:8]
        text_label = str(entry.get("teksto") or "").strip()
        default_base = _safe_export_basename(text_label, short_uuid or "vorto")
        default_name = f"{default_base}.toml"
        out_path = _resolve_export_path(
            celvojo,
            default_filename=default_name,
            suffix=".toml",
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(_entry_to_toml_text(entry), encoding="utf-8")
        typer.echo(f'Eksportis #{short_uuid}  "{text_label}" al {out_path}.')
        return

    # Full export mode (backward compatible): vorto eksporti <dosiero>
    entries = _load_entries()
    payload = json.dumps(entries, ensure_ascii=False, indent=2).encode("utf-8")
    out_path = _resolve_export_path(
        celo_aux_ref,
        default_filename="vorto_export.json",
        suffix=None,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if pasvorto:
        data = encrypt(payload, pasvorto)
        out_path.write_bytes(data)
        typer.echo(
            f"[✓] Eksportis {len(entries)} eniro(j)n al {out_path} (ĉifrita)."
        )
    else:
        out_path.write_bytes(payload)
        typer.echo(f"[✓] Eksportis {len(entries)} eniro(j)n al {out_path}.")


@app.command("importi")
def importi(
    dosiero: str = typer.Argument(..., help="Input file path (e.g. vorto.json)."),
    pasvorto: str | None = typer.Option(
        None,
        "-p",
        "--pasvorto",
        help="Password to decrypt the import (if encrypted).",
    ),
    anstatauigi: bool = typer.Option(
        False,
        "-A",
        "--anstatauigi",
        help="Overwrite existing entries instead of merging.",
    ),
) -> None:
    """Import wordbook entries from a JSON file (optionally encrypted)."""
    from autish.commands._crypto import decrypt, is_encrypted  # noqa: PLC0415

    in_path = Path(dosiero)
    if not in_path.exists():
        typer.echo(f"[!] Dosiero ne trovita: {in_path}", err=True)
        raise typer.Exit(1)

    raw = in_path.read_bytes()

    if is_encrypted(raw):
        if not pasvorto:
            pasvorto = typer.prompt("Pasvorto", hide_input=True)
        try:
            raw = decrypt(raw, pasvorto)
        except ValueError as exc:
            typer.echo(f"[!] Malĉifrad-eraro: {exc}", err=True)
            raise typer.Exit(1) from exc

    try:
        new_entries: list[dict] = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        typer.echo(f"[!] Malvalida dosierformato: {exc}", err=True)
        raise typer.Exit(1) from exc

    if not isinstance(new_entries, list):
        typer.echo("[!] Malvalida dosierformato: atendita listo de eniroj.", err=True)
        raise typer.Exit(1)

    if anstatauigi:
        if not _confirm_esperante(
            f"Ĉu anstataŭigi ĈIUJN ekzistantajn eniro(j)n per {len(new_entries)} "
            "importitajn?",
            default_yes=False,
        ):
            typer.echo("Nuligita.")
            return
        with _get_db() as con:
            con.execute("DELETE FROM vorto")
            con.commit()
        _save_entries(new_entries)
        typer.echo(
            f"[✓] Anstataŭigis ĉiujn eniro(j)n per {len(new_entries)} importitajn."
        )
    else:
        existing = _load_entries()
        existing_uuids = {e["uuid"] for e in existing}
        added = 0
        for entry in new_entries:
            if entry.get("uuid") not in existing_uuids:
                existing.append(entry)
                added += 1
        _save_entries(existing)
        typer.echo(f"[✓] Importis {added} nova(j)n eniro(j)n (ignoris duplikatojn).")


# ──────────────────────────────────────────────────────────────────────────────
# Interactive mode — full-screen curses TUI
# ──────────────────────────────────────────────────────────────────────────────


def _entry_to_lines(
    entry: dict,
    all_entries: list[dict] | None = None,
    *,
    montri_cxion: bool = True,
) -> list[str]:
    """Convert an entry dict to plain-text lines for the TUI pager."""
    link_context = all_entries or [entry]
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
    tipos = entry.get("tipo") or []
    tipo_value = (
        ", ".join(str(t) for t in tipos if str(t))
        if isinstance(tipos, list)
        else str(tipos) if tipos else ""
    )
    tipo_str = kategorio + ("/" + tipo_value if tipo_value else "")
    _row("tipo:", tipo_str)
    _row(
        "aŭtoro:",
        _render_internal_plain_links(
            str(entry.get("autoro") or ""), link_context, show_ref=False
        ),
    )
    _row(
        "verko:",
        _render_internal_plain_links(
            str(entry.get("verko") or ""), link_context, show_ref=False
        ),
    )
    if montri_cxion:
        _row(
            "temo:",
            _render_internal_plain_links(
                str(entry.get("temo") or ""), link_context, show_ref=False
            ),
        )
        _row(
            "tono:",
            _render_internal_plain_links(
                str(entry.get("tono") or ""), link_context, show_ref=False
            ),
        )
        nivelo = entry.get("nivelo")
        _row("nivelo:", f"{nivelo:.1f}" if nivelo is not None else "")

    difinoj: list[str] = entry.get("difinoj") or []
    uzoj: list[str] = entry.get("uzoj") or []
    if difinoj:
        lines.append(f"  {'difinoj:':<14}")
        if len(difinoj) == 1:
            rendered_difino = _render_internal_plain_links(
                difinoj[0], link_context, show_ref=False
            )
            lines.append(f"    {rendered_difino}")
            if uzoj and uzoj[0]:
                rendered_uzo = _render_internal_plain_links(
                    uzoj[0], link_context, show_ref=False
                )
                lines.append(f"       /{rendered_uzo}/")
        else:
            for i, d in enumerate(difinoj, 1):
                rendered_difino = _render_internal_plain_links(
                    d, link_context, show_ref=False
                )
                lines.append(f"    {i}. {rendered_difino}")
                if i - 1 < len(uzoj) and uzoj[i - 1]:
                    rendered_uzo = _render_internal_plain_links(
                        uzoj[i - 1], link_context, show_ref=False
                    )
                    lines.append(f"       /{rendered_uzo}/")

    etikedoj: dict[str, str] = entry.get("etikedoj") or {}
    if montri_cxion and etikedoj:
        lines.append(f"  {'etikedoj:':<14}")
        for k, v in etikedoj.items():
            lines.append(f"    {k}: {v}")

    ligiloj: list[str] = entry.get("ligiloj") or []
    if ligiloj:
        rendered_links: list[str] = []
        for item in ligiloj:
            raw_ref = str(item or "").strip()
            if not raw_ref:
                continue
            rendered_links.append(
                _render_ligilo_plain_text(raw_ref, link_context, show_ref=True)
            )
        _row("ligiloj:", ", ".join(rendered_links))

    if montri_cxion:
        lines.append("")
        _row("kreita:", (entry.get("kreita_je") or "")[:19])
        modifita = entry.get("modifita_je") or ""
        kreita = entry.get("kreita_je") or ""
        if modifita and modifita != kreita:
            _row("modifita:", modifita[:19])

    return lines


def _entries_to_lines(
    entries: list[dict], all_entries: list[dict] | None = None
) -> list[str]:
    """Convert entries to pager-ready plain-text lines."""
    if not entries:
        return ["Neniu rezulto trovita. (No results found.)"]
    link_context = all_entries or entries
    show_ligiloj = any(bool(e.get("ligiloj")) for e in entries)
    col_uuid = 10
    col_teksto = 28
    col_lingvo = 8
    col_tipo = 18
    col_niv = 5
    col_dato = 12
    col_ligiloj = 28
    header = (
        f"{'UUID':<{col_uuid}} {'Teksto':<{col_teksto}} "
        f"{'Lingvo':<{col_lingvo}} {'Tipo':<{col_tipo}} "
        f"{'Niv.':<{col_niv}} {'Dato':<{col_dato}}"
    )
    if show_ligiloj:
        header += f" {'Ligiloj':<{col_ligiloj}}"
    sep = "─" * len(header)
    lines = [header, sep]
    for e in entries:
        uid_short = e["uuid"][:col_uuid]
        kategorio = e.get("kategorio") or ""
        tipos = e.get("tipo") or []
        tipo_value = (
            ", ".join(str(t) for t in tipos if str(t))
            if isinstance(tipos, list)
            else str(tipos) if tipos else ""
        )
        tipo_str = (kategorio + ("/" + tipo_value if tipo_value else ""))[:col_tipo]
        date_str = (e.get("kreita_je") or "")[:10]
        nivelo = e.get("nivelo")
        niv_str = f"{nivelo:.1f}" if nivelo is not None else ""
        teksto = _render_internal_plain_links(
            str(e.get("teksto") or ""), link_context, show_ref=False
        )[:col_teksto]
        row = (
            f"{uid_short:<{col_uuid}} {teksto:<{col_teksto}} "
            f"{(e.get('lingvo') or ''):<{col_lingvo}} {tipo_str:<{col_tipo}} "
            f"{niv_str:<{col_niv}} {date_str:<{col_dato}}"
        )
        if show_ligiloj:
            ligiloj = e.get("ligiloj") or []
            rendered_links = "-"
            if ligiloj:
                rendered_links = " | ".join(
                    _render_ligilo_plain_text(
                        str(item or ""), link_context, show_ref=False
                    )
                    for item in ligiloj
                    if str(item or "").strip()
                )
            row += f" {rendered_links[:col_ligiloj]:<{col_ligiloj}}"
        lines.append(row)
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
    entry["difinoj"], entry["uzoj"] = _normalize_difinoj_uzoj(
        entry.get("difinoj") or [], entry.get("uzoj") or []
    )
    all_entries = _load_entries()
    entry["ligiloj"] = _merge_links_with_inline_refs(
        entry.get("ligiloj") or [],
        entry.get("difinoj") or [],
        entry.get("uzoj") or [],
        all_entries,
        extra_payload=entry,
    )
    all_entries.append(entry)
    _sync_bidirectional_links(
        all_entries,
        entry["uuid"],
        entry.get("ligiloj") or [],
        previous_links=[],
    )
    _save_entries(all_entries)
    _push_undo({"op": "aldoni", "uuid": entry["uuid"]})


def _tui_save_modified(entry: dict, old_entry: dict) -> None:
    entry["difinoj"], entry["uzoj"] = _normalize_difinoj_uzoj(
        entry.get("difinoj") or [], entry.get("uzoj") or []
    )
    all_entries = _load_entries()
    entry["ligiloj"] = _merge_links_with_inline_refs(
        entry.get("ligiloj") or [],
        entry.get("difinoj") or [],
        entry.get("uzoj") or [],
        all_entries,
        extra_payload=entry,
    )
    idx = next(
        (i for i, e in enumerate(all_entries) if e["uuid"] == entry["uuid"]), None
    )
    if idx is not None:
        all_entries[idx] = entry
    _sync_bidirectional_links(
        all_entries,
        entry["uuid"],
        entry.get("ligiloj") or [],
        previous_links=old_entry.get("ligiloj") or [],
    )
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
        tipos = e.get("tipo") or []
        tipo_value = (
            ", ".join(str(t) for t in tipos if str(t))
            if isinstance(tipos, list)
            else str(tipos) if tipos else ""
        )
        tipo_str = (kategorio + ("/" + tipo_value if tipo_value else ""))[:col_tipo]
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
        if not _confirm_esperante(
            f"Ĉu definitive forigi #{entry['uuid'][:8]}  \"{entry['teksto']}\"?",
            default_yes=False,
        ):
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
        if not _confirm_esperante(
            f"Ĉu definitive forigi ĈIUJN {len(entries)} eniro(j)n?",
            default_yes=False,
        ):
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
        render_entry=lambda entry: _entry_to_lines(
            entry, _load_entries(), montri_cxion=True
        ),
        render_entry_default=lambda entry: _entry_to_lines(
            entry, _load_entries(), montri_cxion=False
        ),
        render_results=lambda entries: _entries_to_lines(
            entries, all_entries=_load_entries()
        ),
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
