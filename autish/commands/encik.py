"""encik — personal knowledge management microapp.

Usage:
    encik                       — interactive welcome screen
    encik aldoni <file.enc>     — add a new knowledge node from an .enc file
    encik vidi <titolo|UUID>    — view an existing node
    encik modifi <title|UUID>   — edit an existing node in $EDITOR as a temp .enc file
    encik eksporti <title|UUID> <celvojo> — export one node to .enc
    encik agordi                — manage display settings in ~/.config/autish/encik.toml
    encik serci <demando>       — search nodes (title by default)
    encik semantika-serci "<kondiĉoj>" — search by typed semantic value conditions
      -t/--teksto               — search full entry text instead of title only
      -s/--subklasoj <term>     — recursive subclass search
      -S/--superklasoj <term>   — recursive superclass search
      -P/--paralela             — sister-class search (same parent)
      -L/--limo <int>           — depth limit for -s/-S (default 5),
                                  max results for -p (default 100)

Data is stored in an SQLite database at ~/.local/share/autish/encik.db.
"""

from __future__ import annotations

import csv
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid as _uuid_mod
from collections import deque
from datetime import datetime, timezone
from difflib import get_close_matches
from html import escape
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from autish.commands.uzanto import _load_profile
from autish.services.ai_common import build_verki_service, load_ai_context
from autish.services.verki import VerkiRequest, VerkiServiceError
from autish.utils import (
    fold_search_compact,
    fold_search_text,
    fuzzy_match_ignore_whitespace,
    open_path_in_browser,
)

# Import doc helper for displaying manlibro(j) in encik vidi
try:
    from autish.commands.doc import get_manuals_for_encik
except ImportError:
    def get_manuals_for_encik(encik_uuid: str) -> list[dict[str, str]]:  # type: ignore[no-redef]
        return []

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
    help="Encik — persona sci-mastruma mikroapo.",
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
_VORTO_DB_FILE: Path = _DATA_DIR / "vorto.db"
_CONFIG_DIR: Path = Path.home() / ".config" / "autish"
_ENCIK_CONFIG_FILE: Path = _CONFIG_DIR / "encik.toml"
_SEMANTIKA_CONFIG_DIR: Path = _CONFIG_DIR / "semantika"

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
    semantika   TEXT NOT NULL DEFAULT '[]',
    kreita_je   TEXT NOT NULL,
    modifita_je TEXT NOT NULL
);
"""

_CREATE_ENCIK_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_encik_titolo_lower ON encik(LOWER(titolo));
CREATE INDEX IF NOT EXISTS idx_encik_uuid_prefix ON encik(substr(uuid, 1, 8));
CREATE INDEX IF NOT EXISTS idx_encik_kreita_je ON encik(kreita_je);
"""

_CREATE_ENCIK_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS encik_fts USING fts5(
    uuid UNINDEXED,
    titolo,
    terminologio,
    difinio,
    difinoj,
    enhavo,
    content=encik,
    content_rowid=rowid
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

_SEMANTIKA_LIGILO_DEFINOJ: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "rdf:type",
        "estas tipo de (klasigo; inkl. aliaso wdt:P31)",
        (
            "rdf:type",
            "type",
            "estas tipo de",
            "wdt:p31",
            "p31",
            "instance of",
            "instanco de",
        ),
    ),
    (
        "rdf:hasInstance",
        "havas instancon (inversa de rdf:type)",
        ("rdf:hasinstance",),
    ),
    (
        "rdfs:subClassOf",
        "subklaso de (kanona direkto; inkl. aliaso wdt:P279)",
        ("rdfs:subclassof", "subklaso de", "wdt:p279", "p279", "subclass of"),
    ),
    (
        "rdfs:hasSubClass",
        "havas subklason (inversa de rdfs:subClassOf)",
        ("rdfs:superclassof", "superklaso de"),
    ),
    (
        "owl:disjointWith",
        "malkongrua kun",
        ("owl:disjointwith", "malkongrua kun"),
    ),
    ("owl:inverseOf", "inversa de", ("owl:inverseof", "inversa de")),
    ("wdt:P50", "aŭtoro / kreinto", ("p50", "author", "creator", "aŭtoro", "kreinto")),
    ("wdt:P361", "parto de", ("p361", "part of", "parto de")),
    ("wdt:P527", "havas parton", ("p527", "has part", "havas parton")),
    ("wdt:P276", "loko / situas en", ("p276", "located in", "location", "loko")),
    ("wdt:P463", "membro de", ("p463", "member of", "membro de")),
    (
        "wdt:P106",
        "okupo / profesio",
        ("p106", "occupation", "profession", "okupo", "profesio"),
    ),
    ("wdt:P26", "geedzo / partnero", ("p26", "spouse", "partner", "geedzo")),
    (
        "wdt:P123",
        "eldonisto / publikigita de",
        ("p123", "publisher", "published by", "eldonisto"),
    ),
    ("wdt:P69", "edukita ĉe", ("p69", "educated at", "edukita ĉe")),
    (
        "wdt:P569",
        "dato de naskiĝo",
        ("p569", "date of birth", "naskigxdato", "naskiĝo"),
    ),
    ("wdt:P570", "dato de morto", ("p570", "date of death", "morto")),
    ("wdt:P17", "lando", ("p17", "country", "lando")),
    ("wdt:P131", "situas en administra unuo", ("p131", "located in admin unit")),
    ("wdt:P571", "fondita / komenco", ("p571", "inception", "fondita")),
    (
        "wdt:P5191",
        "devenas de leksiko (etimologia/abstrakta rilato)",
        ("p5191", "derived from lexeme", "etimologio", "devenas de"),
    ),
    (
        "wdt:P2046",
        "areo (geografia kvanto)",
        ("p2046", "area", "surface area", "areo"),
    ),
    (
        "wdt:P1082",
        "loĝantaro / populacio",
        ("p1082", "population", "loĝantaro", "populacio"),
    ),
)


def _build_semantika_ligilo_map() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for canonical, _, aliases in _SEMANTIKA_LIGILO_DEFINOJ:
        mapping[canonical.lower()] = canonical
        for alias in aliases:
            mapping[alias.lower()] = canonical
    return mapping


_SEMANTIKAJ_LIGILOJ: dict[str, str] = _build_semantika_ligilo_map()
_KANONAJ_SEMANTIKAJ_LIGILOJ: set[str] = {
    canonical for canonical, _, _ in _SEMANTIKA_LIGILO_DEFINOJ
}
_SEMANTIKA_DEFINOJ_MAP: dict[str, tuple[str, tuple[str, ...]]] = {
    canonical: (description, aliases)
    for canonical, description, aliases in _SEMANTIKA_LIGILO_DEFINOJ
}
_SEMANTIKA_KATEGORIOJ: dict[str, tuple[str, ...]] = {
    "generala": (
        "rdf:type",
        "rdf:hasInstance",
        "rdfs:subClassOf",
        "rdfs:hasSubClass",
        "owl:disjointWith",
        "owl:inverseOf",
        "wdt:P361",
        "wdt:P527",
    ),
    "persono": (
        "rdf:type",
        "rdfs:subClassOf",
        "wdt:P50",
        "wdt:P106",
        "wdt:P69",
        "wdt:P26",
        "wdt:P463",
        "wdt:P569",
        "wdt:P570",
    ),
    "geografio": (
        "rdf:type",
        "rdfs:subClassOf",
        "wdt:P17",
        "wdt:P131",
        "wdt:P276",
        "wdt:P361",
        "wdt:P527",
        "wdt:P2046",
        "wdt:P1082",
    ),
    "abstrakta": (
        "rdf:type",
        "rdfs:subClassOf",
        "owl:disjointWith",
        "owl:inverseOf",
        "wdt:P5191",
        "wdt:P571",
        "wdt:P123",
    ),
}
_SEMANTIKA_HELPO_TEKSTO = (
    "Semantic link types for Encik knowledge graph.\n"
    "Organized by group in ~/.config/autish/semantika/*.csv "
    "(LIGILO, PRISKRIBO, ALIAZOJ columns).\n"
    "\n"
    "Common semantic link types:\n"
    "  RDF/RDFS: rdf:type (instance of), rdfs:subClassOf "
    "(is subclass of), owl:inverseOf\n"
    "  Wikidata: wdt:P50 (author), wdt:P361 (part of), "
    "wdt:P527 (has part), wdt:P276 (location),\n"
    "            wdt:P106 (occupation), wdt:P26 (spouse), "
    "wdt:P123 (publisher), wdt:P69 (educated at)\n"
    "\n"
    "Subcommands:\n"
    "- encik semantika <grupo>          Show semantic links in category\n"
    "- encik semantika serci <query>    Search Wikidata for semantic links\n"
    "- encik semantika aldoni <id> <grupo>   Add semantic link to category\n"
    "\n"
    "Usage:\n"
    "- encik serci --semantiko rdf:type [--al <target-node>]\n"
    "- encik modifi <uuid> --ligilo <uuid>:rdf:type\n"
    "\n"
    "Groups: generala, abstrakta, persono, geografio, agento, "
    "invento, komputiko, komerco"
)




def _semantika_help_hint() -> str:
    return (
        "Vidu `encik semantika -h` por grupoj/subkomandoj, aŭ "
        "`encik semantika serci <demando>` por trovi semantikan arkon."
    )


_AUTO_REVERSE_DATUMO_KEY = "__autish_auto_reverse_ligilo__"
_MATH_TOKEN_PREFIX = "AUTISHMATHSEGMENT"
_SEMANTIKA_VALORO_TIPOJ: frozenset[str] = frozenset({"int", "bool", "float", "str"})
_SEMANTIKA_BOOL_TRUE: frozenset[str] = frozenset({"true", "vero", "jes", "j", "1"})
_SEMANTIKA_BOOL_FALSE: frozenset[str] = frozenset({"false", "malvero", "ne", "n", "0"})
_SEMANTIKA_RANGE_RE = re.compile(r"^\(\s*([^,]+?)\s*,\s*([^)]+?)\s*\)$")

_ALLOWED_ENC_PLAIN_KEYS: frozenset[str] = frozenset(
    {
        "terminologio",
        "difinio",
        "difino",
        "titolo",
        "superklaso",
        "ligilo",
        "fonto",
        "citajo",
        "datumo",
        "semantika",
        "source",
    }
)
_ALLOWED_ENC_PLAIN_KEYS_SORTED: tuple[str, ...] = tuple(sorted(_ALLOWED_ENC_PLAIN_KEYS))
_ENCIK_MONTRADO_DEF: dict[str, object] = {
    "html": False,
    "scienca_nombro": 4,
    "spaco": 0,
}
_SEMANTIKA_CSV_HEADERS: tuple[str, str, str] = ("LIGILO", "PRISKRIBO", "ALIAZOJ")
_SEMANTIKA_RESERVED_SUBCOMMANDS: frozenset[str] = frozenset({"serci", "aldoni"})
_SEMANTIKA_CONFIG_CACHE: dict[str, object] = {"signature": None, "groups": None}
_REGISTERED_SEMANTIKA_GROUP_COMMANDS: set[str] = set()

# ──────────────────────────────────────────────────────────────────────────────
# DB helpers
# ──────────────────────────────────────────────────────────────────────────────


def _default_semantika_group_rows() -> dict[str, list[tuple[str, str, str]]]:
    rows_by_group: dict[str, list[tuple[str, str, str]]] = {}
    for group_name, canonicals in _SEMANTIKA_KATEGORIOJ.items():
        rows: list[tuple[str, str, str]] = []
        for canonical in canonicals:
            description, aliases = _SEMANTIKA_DEFINOJ_MAP.get(canonical, ("", ()))
            alias_text = ",".join(dict.fromkeys(aliases))
            rows.append((canonical, description, alias_text))
        rows_by_group[group_name] = rows
    return rows_by_group


def _semantika_group_file(group_name: str) -> Path:
    return _SEMANTIKA_CONFIG_DIR / f"{group_name}.csv"


def _normalize_semantika_group_name(raw: str) -> str:
    normalized = str(raw or "").strip().lower().replace(" ", "-")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", normalized):
        raise ValueError("Nevalida grupo: uzu nur minusklojn, ciferojn, '-' aŭ '_'.")
    return normalized


def _write_semantika_group_rows(
    group_name: str,
    rows: list[dict[str, object]],
) -> None:
    _SEMANTIKA_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    target = _semantika_group_file(group_name)
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(_SEMANTIKA_CSV_HEADERS)
        for row in rows:
            ligilo = str(row.get("ligilo") or "").strip()
            priskribo = str(row.get("priskribo") or "").strip()
            aliases = row.get("aliasoj")
            if isinstance(aliases, list):
                alias_text = ",".join(
                    str(alias).strip() for alias in aliases if str(alias).strip()
                )
            else:
                alias_text = str(aliases or "").strip()
            if ligilo:
                writer.writerow([ligilo, priskribo, alias_text])


def _parse_alias_list(raw: str) -> list[str]:
    return [token.strip() for token in str(raw or "").split(",") if token.strip()]


def _read_semantika_group_rows(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            return rows
        field_lookup = {name.strip().upper(): name for name in reader.fieldnames}
        ligilo_col = field_lookup.get("LIGILO")
        priskribo_col = field_lookup.get("PRISKRIBO")
        alias_col = field_lookup.get("ALIAZOJ")
        if not ligilo_col:
            return rows
        for raw_row in reader:
            ligilo_raw = str(raw_row.get(ligilo_col) or "").strip()
            if not ligilo_raw:
                continue
            canonical = _SEMANTIKAJ_LIGILOJ.get(ligilo_raw.lower(), ligilo_raw)
            priskribo = (
                str(raw_row.get(priskribo_col) or "").strip() if priskribo_col else ""
            )
            aliases = _parse_alias_list(raw_row.get(alias_col) if alias_col else "")
            rows.append(
                {
                    "ligilo": canonical,
                    "priskribo": priskribo,
                    "aliasoj": aliases,
                }
            )
    return rows


def _semantika_config_signature() -> tuple[tuple[str, int, int], ...]:
    if not _SEMANTIKA_CONFIG_DIR.exists():
        return ()
    signature: list[tuple[str, int, int]] = []
    for path in sorted(_SEMANTIKA_CONFIG_DIR.glob("*.csv")):
        stat = path.stat()
        signature.append((path.name, stat.st_mtime_ns, stat.st_size))
    return tuple(signature)


def _ensure_semantika_group_files() -> None:
    _SEMANTIKA_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    default_rows = _default_semantika_group_rows()
    for group_name, canonical_rows in default_rows.items():
        path = _semantika_group_file(group_name)
        if path.exists():
            continue
        rows = [
            {
                "ligilo": ligilo,
                "priskribo": priskribo,
                "aliasoj": _parse_alias_list(aliases),
            }
            for ligilo, priskribo, aliases in canonical_rows
        ]
        _write_semantika_group_rows(group_name, rows)


def _invalidate_semantika_config_cache() -> None:
    _SEMANTIKA_CONFIG_CACHE["signature"] = None
    _SEMANTIKA_CONFIG_CACHE["groups"] = None


def _load_semantika_groups() -> dict[str, list[dict[str, object]]]:
    _ensure_semantika_group_files()
    signature = _semantika_config_signature()
    cached_signature = _SEMANTIKA_CONFIG_CACHE.get("signature")
    cached_groups = _SEMANTIKA_CONFIG_CACHE.get("groups")
    if signature == cached_signature and isinstance(cached_groups, dict):
        return {
            name: [dict(row) for row in rows] for name, rows in cached_groups.items()
        }
    groups: dict[str, list[dict[str, object]]] = {}
    for path in sorted(_SEMANTIKA_CONFIG_DIR.glob("*.csv")):
        group_name = path.stem.strip().lower()
        if not group_name:
            continue
        rows = _read_semantika_group_rows(path)
        if rows:
            groups[group_name] = rows
    _SEMANTIKA_CONFIG_CACHE["signature"] = signature
    _SEMANTIKA_CONFIG_CACHE["groups"] = groups
    return {name: [dict(row) for row in rows] for name, rows in groups.items()}


def _runtime_semantika_alias_map() -> dict[str, str]:
    mapping = dict(_SEMANTIKAJ_LIGILOJ)
    for rows in _load_semantika_groups().values():
        for row in rows:
            ligilo = str(row.get("ligilo") or "").strip()
            if not ligilo:
                continue
            canonical = _SEMANTIKAJ_LIGILOJ.get(ligilo.lower(), ligilo)
            mapping[canonical.lower()] = canonical
            for alias in row.get("aliasoj") or []:
                alias_text = str(alias).strip()
                if alias_text:
                    mapping[alias_text.lower()] = canonical
    return mapping


def _runtime_semantika_description_map() -> dict[str, str]:
    descriptions: dict[str, str] = {}
    for canonical, (description, _aliases) in _SEMANTIKA_DEFINOJ_MAP.items():
        text = str(description or "").strip()
        if text:
            descriptions[canonical] = text
    for rows in _load_semantika_groups().values():
        for row in rows:
            ligilo = str(row.get("ligilo") or "").strip()
            if not ligilo:
                continue
            canonical = _SEMANTIKAJ_LIGILOJ.get(ligilo.lower(), ligilo)
            priskribo = str(row.get("priskribo") or "").strip()
            if priskribo:
                descriptions[canonical] = priskribo
    return descriptions


def _runtime_known_semantika_ligiloj() -> set[str]:
    return set(_runtime_semantika_alias_map().values())


def _load_encik_montrado_settings() -> dict[str, object]:
    settings: dict[str, object] = dict(_ENCIK_MONTRADO_DEF)
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not _ENCIK_CONFIG_FILE.exists():
        _save_encik_montrado_settings(settings)
        return settings
    try:
        data = tomllib.loads(_ENCIK_CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return settings
    montrado = data.get("montrado")
    if not isinstance(montrado, dict):
        return settings
    if "html" in montrado:
        raw_html = montrado.get("html")
        if isinstance(raw_html, bool):
            settings["html"] = raw_html
        else:
            try:
                settings["html"] = _parse_semantika_bool(
                    str(raw_html), field="montrado.html"
                )
            except ValueError:
                pass
    if "scienca_nombro" in montrado:
        try:
            settings["scienca_nombro"] = max(0, int(montrado.get("scienca_nombro")))
        except (TypeError, ValueError):
            pass
    if "spaco" in montrado:
        try:
            settings["spaco"] = max(0, int(montrado.get("spaco")))
        except (TypeError, ValueError):
            pass
    return settings


def _save_encik_montrado_settings(settings: dict[str, object]) -> None:
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    html_value = bool(settings.get("html"))
    scienca_nombro = max(0, int(settings.get("scienca_nombro", 4)))
    spaco = max(0, int(settings.get("spaco", 0)))
    text = (
        "[montrado]\n"
        f"html = {'true' if html_value else 'false'}\n"
        f"scienca_nombro = {scienca_nombro}\n"
        f"spaco = {spaco}\n"
    )
    _ENCIK_CONFIG_FILE.write_text(text, encoding="utf-8")


def _format_number_for_display(
    value: float,
    *,
    integer_like: bool,
) -> str:
    settings = _load_encik_montrado_settings()
    n = max(0, int(settings.get("scienca_nombro", 4)))
    if value == 0:
        return "0"
    threshold = 10**n
    abs_value = abs(value)
    if abs_value >= threshold or abs_value <= (1 / threshold):
        return f"{value:.6e}"
    if integer_like:
        return str(int(value))
    return f"{value:g}"


def _init_db() -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_FILE)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(_CREATE_ENCIK)
        conn.executescript(_CREATE_ENCIK_INDEXES)
        conn.execute(_CREATE_ENCIK_FTS)
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
    if "semantika" not in cols:
        conn.execute(
            "ALTER TABLE encik ADD COLUMN semantika TEXT NOT NULL DEFAULT '[]'"
        )


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    for field in ("superklaso", "ligilo", "fonto", "citajo", "source"):
        if isinstance(d.get(field), str):
            d[field] = json.loads(d[field])
    for field in ("terminologio", "difinoj", "datumo", "semantika"):
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
    if "semantika" not in d:
        d["semantika"] = []
    if not d.get("titolo"):
        d["titolo"] = next(iter(d.get("terminologio", {}).values()), "")
    if not d.get("difinio") and d.get("difino"):
        d["difinio"] = str(d.get("difino") or "")
    if not d.get("difinio"):
        d["difinio"] = next(iter(d.get("difinoj", {}).values()), "")
    return d


def _load_all_unsorted() -> list[dict]:
    """Load all entries without sorting (faster for internal operations)."""
    conn = _get_conn()
    try:
        rows = conn.execute("SELECT * FROM encik").fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def _load_all() -> list[dict]:
    """Load all entries sorted by title (for display/UI)."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM encik ORDER BY titolo COLLATE NOCASE"
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def _find_by_uuid(uid: str) -> dict | None:
    raw = str(uid or "").strip()
    if raw.lower().startswith("vt#"):
        return None
    if raw.lower().startswith("ec#"):
        raw = raw[3:]
    normalized = raw.lstrip("#")
    if not normalized:
        return None
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM encik WHERE uuid = ?", (normalized,)
        ).fetchone()
        if row:
            return _row_to_dict(row)
        rows = conn.execute(
            "SELECT * FROM encik WHERE uuid LIKE ? ORDER BY uuid COLLATE NOCASE",
            (f"{normalized}%",),
        ).fetchall()
        if len(rows) == 1:
            return _row_to_dict(rows[0])
        return None
    finally:
        conn.close()


def _find_vorto_by_uuid(uid: str) -> dict | None:
    normalized = str(uid or "").strip().lstrip("#")
    if not normalized or not _VORTO_DB_FILE.exists():
        return None
    conn = sqlite3.connect(str(_VORTO_DB_FILE), timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT uuid, teksto FROM vorto WHERE uuid = ?",
            (normalized,),
        ).fetchone()
        if row:
            return dict(row)
        rows = conn.execute(
            "SELECT uuid, teksto FROM vorto "
            "WHERE uuid LIKE ? ORDER BY uuid COLLATE NOCASE LIMIT 2",
            (f"{normalized}%",),
        ).fetchall()
        if len(rows) == 1:
            return dict(rows[0])
        return None
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def _canonicalize_ligilo_ref(ref: str | None) -> str:
    token = _clean_uuid_ref(ref)
    if not token:
        return ""
    lower = token.lower()
    if lower.startswith("vt#"):
        vorto_ref = token[3:].lstrip("#").strip()
        if not vorto_ref:
            return ""
        target = _find_vorto_by_uuid(vorto_ref)
        resolved = str(target.get("uuid") or vorto_ref) if target else vorto_ref
        return f"vt#{resolved}"
    if lower.startswith("ec#"):
        encik_ref = token[3:].lstrip("#").strip()
        if not encik_ref:
            return ""
        target = _find_by_uuid(encik_ref)
        return str(target.get("uuid") or encik_ref) if target else encik_ref
    return token


def _looks_like_uuid_ref(token: str) -> bool:
    raw = str(token or "").strip()
    if raw.startswith("#"):
        return True
    if raw.lower().startswith(("ec#", "vt#")):
        return True
    candidate = _clean_uuid_ref(raw)
    if not candidate:
        return False
    lowered = candidate.lower()
    if re.fullmatch(r"[0-9a-f]{8}", lowered):
        return True
    if re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", lowered):
        return True
    return False


def _canonicalize_superklaso_ref(ref: str | None) -> str:
    candidate = _canonicalize_ligilo_ref(ref)
    if not candidate:
        return ""
    lowered = candidate.lower()
    if lowered.startswith("vt#"):
        return ""
    sem = _normalize_semantika_ligilo(candidate)
    if _is_known_semantika_ligilo(sem):
        return ""
    return _clean_uuid_ref(candidate)


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
    folded_text = _fold_search_text(text)
    folded_needle = _fold_search_text(needle)
    if not folded_text or not folded_needle:
        return 0

    def _collapse_spaces(value: str) -> str:
        return " ".join(str(value or "").split())

    def _strip_parenthesized(value: str) -> str:
        return _collapse_spaces(re.sub(r"\([^)]*\)", " ", value))

    folded_needle_compact = _collapse_spaces(folded_needle)
    folded_text_compact = _collapse_spaces(folded_text)
    direct = len(re.findall(re.escape(folded_needle_compact), folded_text_compact))
    stripped = len(
        re.findall(
            re.escape(_collapse_spaces(folded_needle)),
            _strip_parenthesized(folded_text),
        )
    )
    compact_text = fold_search_compact(text)
    compact_needle = fold_search_compact(needle)
    compact = 0
    if compact_text and compact_needle:
        compact = len(re.findall(re.escape(compact_needle), compact_text))
    fuzzy = 1 if fuzzy_match_ignore_whitespace(needle, text, threshold=0.86) else 0
    return max(direct, stripped, compact, fuzzy)


def _fold_search_text(text: str) -> str:
    return fold_search_text(text)


def _build_subklaso_count_map(entries: list[dict]) -> dict[str, int]:
    uuids = {str(e.get("uuid") or "") for e in entries}
    out: dict[str, int] = {uid: 0 for uid in uuids if uid}
    for entry in entries:
        for parent_ref in _normalise_superklaso_refs(entry.get("superklaso") or []):
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


def _search_entries_with_fts(
    query: str,
    *,
    full_text: bool,
    max_results: int,
    prefer_newest: bool = True,
    prefer_high_level: bool = True,
) -> list[dict]:
    """Search entries with Python-side ranking.
    
    **Performance Note for Large Databases (10k+ entries):**
    Current implementation loads all entries then filters with Python.
    For optimal scaling to 100k+ entries, we recommend:
    
    1. Normalize terminologio multilingual fields to searchable columns
    2. Create FTS5 triggers to keep encik_fts in sync with inserts/updates
    3. Switch to FTS-based filtering for better performance
    
    **Current Performance (with Python filtering):**
    - 100 entries: ~5ms
    - 10k entries: ~50ms
    - 100k entries: ~500ms (memory intensive, not recommended)
    
    For production with 100k+ entries:
    - Use dedicated search service (Elasticsearch, Meilisearch)
    - Or implement FTS5 with proper trigger maintenance
    """
    needle = _fold_search_text(query.strip())
    compact_needle = fold_search_compact(query.strip())
    if not needle and not compact_needle:
        return []
    
    # Load all entries (optimization pending - see docstring)
    entries = _load_all()
    
    # Apply Python-side ranking and filtering
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
        
        compactness_candidates: list[int] = []
        for part in pool:
            folded_part = _fold_search_text(part)
            if not folded_part:
                continue
            folded_part_compact = " ".join(folded_part.split())
            folded_part_no_paren = " ".join(
                re.sub(r"\([^)]*\)", " ", folded_part).split()
            )
            needle_compact = " ".join(needle.split())
            if needle_compact in folded_part_compact:
                compactness_candidates.append(
                    max(0, len(folded_part_compact) - len(needle_compact))
                )
            if needle_compact in folded_part_no_paren:
                compactness_candidates.append(
                    max(0, len(folded_part_no_paren) - len(needle_compact))
                )
        
        e_copy = dict(e)
        e_copy["_match_count"] = match_count
        e_copy["_compactness"] = (
            min(compactness_candidates) if compactness_candidates else 10**9
        )
        e_copy["_subklaso_count"] = int(sub_count_map.get(str(e.get("uuid") or ""), 0))
        e_copy["_time"] = str(e.get("modifita_je") or e.get("kreita_je") or "")
        scored.append(e_copy)
    
    def _sort_key(item: dict) -> tuple:
        match_key = -int(item.get("_match_count", 0))
        compactness_key = int(item.get("_compactness", 10**9))
        level_val = int(item.get("_subklaso_count", 0))
        level_key = -level_val if prefer_high_level else level_val
        time_val = str(item.get("_time") or "")
        time_key = (
            "".join(chr(255 - ord(c)) for c in time_val) if prefer_newest else time_val
        )
        return (match_key, compactness_key, level_key, time_key)
    
    scored.sort(key=_sort_key)
    return scored[:max_results]


def _search_entries(
    query: str,
    *,
    full_text: bool,
    max_results: int,
    prefer_newest: bool = True,
    prefer_high_level: bool = True,
) -> list[dict]:
    needle = _fold_search_text(query.strip())
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
        compactness_candidates: list[int] = []
        for part in pool:
            folded_part = _fold_search_text(part)
            if not folded_part:
                continue
            folded_part_compact = " ".join(folded_part.split())
            folded_part_no_paren = " ".join(
                re.sub(r"\([^)]*\)", " ", folded_part).split()
            )
            needle_compact = " ".join(needle.split())
            if needle_compact in folded_part_compact:
                compactness_candidates.append(
                    max(0, len(folded_part_compact) - len(needle_compact))
                )
            if needle_compact in folded_part_no_paren:
                compactness_candidates.append(
                    max(0, len(folded_part_no_paren) - len(needle_compact))
                )
        e_copy = dict(e)
        e_copy["_match_count"] = match_count
        e_copy["_compactness"] = (
            min(compactness_candidates) if compactness_candidates else 10**9
        )
        e_copy["_subklaso_count"] = int(sub_count_map.get(str(e.get("uuid") or ""), 0))
        e_copy["_time"] = str(e.get("modifita_je") or e.get("kreita_je") or "")
        scored.append(e_copy)

    def _sort_key(item: dict) -> tuple:
        match_key = -int(item.get("_match_count", 0))
        compactness_key = int(item.get("_compactness", 10**9))
        level_val = int(item.get("_subklaso_count", 0))
        level_key = -level_val if prefer_high_level else level_val
        time_val = str(item.get("_time") or "")
        time_key = (
            "".join(chr(255 - ord(c)) for c in time_val) if prefer_newest else time_val
        )
        return (match_key, compactness_key, level_key, time_key)

    scored.sort(key=_sort_key)
    return scored[:max_results]


def _fuzzy_title_matches(partial: str, max_results: int = 5) -> list[dict]:
    return _search_entries(
        partial, full_text=False, max_results=max_results, prefer_newest=True
    )


def _compile_semantika_text_pattern(pattern: str, *, field: str) -> re.Pattern[str]:
    if "\n" in pattern:
        raise ValueError(f"Nevalida {field}: tekst-kondiĉo ne povas enhavi novliniojn.")
    regex_src = "^" + re.escape(pattern).replace(r"\*", r"[^\n]*") + "$"
    return re.compile(regex_src, re.IGNORECASE)


def _parse_semantika_serci_conditions(raw_query: str) -> list[dict[str, object]]:
    clauses = [part.strip() for part in str(raw_query or "").split(";") if part.strip()]
    if not clauses:
        raise ValueError(
            "Nevalida semantika-serci: mankas kondiĉoj. "
            "Ekzemplo: `wdt:P5191 *philosophia*; wdt:P1082 (0,1000)`."
        )

    conditions: list[dict[str, object]] = []
    for idx, clause in enumerate(clauses, start=1):
        arc_token, sep, expression = clause.partition(" ")
        if not sep or not expression.strip():
            raise ValueError(
                f"Nevalida semantika-serci kondiĉo {idx}: "
                "uzu `ARKO valoro` (ekz. `wdt:P31 true`)."
            )
        arko = _normalize_semantika_ligilo(arc_token.strip())
        if not arko:
            raise ValueError(f"Nevalida semantika-serci kondiĉo {idx}: arko mankas.")
        expression = expression.strip()
        range_match = _SEMANTIKA_RANGE_RE.fullmatch(expression)
        field_name = f"semantika-serci kondiĉo {idx}"
        if range_match:
            lower = _parse_semantika_float(range_match.group(1), field=field_name)
            upper = _parse_semantika_float(range_match.group(2), field=field_name)
            if lower > upper:
                raise ValueError(
                    "Nevalida "
                    f"{field_name}: minimumo ne povas esti pli granda ol maksimumo."
                )
            conditions.append(
                {"kind": "range", "arko": arko, "minimumo": lower, "maksimumo": upper}
            )
            continue
        lowered = expression.lower()
        if lowered in _SEMANTIKA_BOOL_TRUE or lowered in _SEMANTIKA_BOOL_FALSE:
            conditions.append(
                {
                    "kind": "bool",
                    "arko": arko,
                    "valoro": _parse_semantika_bool(expression, field=field_name),
                }
            )
            continue
        text_pattern = _parse_semantika_str(expression)
        conditions.append(
            {
                "kind": "text",
                "arko": arko,
                "regex": _compile_semantika_text_pattern(
                    text_pattern, field=field_name
                ),
            }
        )
    return conditions


def _matches_semantika_condition(
    semantikaj_valoroj: list[dict[str, object]],
    condition: dict[str, object],
) -> bool:
    kind = str(condition.get("kind") or "")
    arko = str(condition.get("arko") or "")
    if not kind or not arko:
        return False
    for item in semantikaj_valoroj:
        if str(item.get("arko") or "") != arko:
            continue
        tipo = str(item.get("tipo") or "")
        valoro = item.get("valoro")
        if kind == "text":
            if tipo != "str":
                continue
            regex = condition.get("regex")
            if isinstance(regex, re.Pattern) and regex.fullmatch(str(valoro or "")):
                return True
        elif kind == "bool":
            if tipo != "bool":
                continue
            expected = bool(condition.get("valoro"))
            if bool(valoro) == expected:
                return True
        elif kind == "range":
            if tipo not in {"int", "float"}:
                continue
            current = _parse_semantika_float(valoro, field="semantika-serci")
            minimumo = float(condition.get("minimumo") or 0.0)
            maksimumo = float(condition.get("maksimumo") or 0.0)
            if minimumo <= current <= maksimumo:
                return True
    return False


def _entry_matches_semantika_conditions(
    entry: dict,
    conditions: list[dict[str, object]],
) -> bool:
    semantikaj_valoroj = _normalize_semantika_valoroj(entry.get("semantika"))
    if not semantikaj_valoroj:
        return False
    return all(
        _matches_semantika_condition(semantikaj_valoroj, condition)
        for condition in conditions
    )


def _insert_entry(entry: dict) -> None:
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO encik"
            " (uuid, titolo, difinio, terminologio, difinoj, enhavo,"
            " superklaso, ligilo, fonto, citajo, datumo, semantika,"
            " kreita_je, modifita_je)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                json.dumps(entry.get("semantika", []), ensure_ascii=False),
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
               superklaso=?, ligilo=?, fonto=?, citajo=?, datumo=?, semantika=?,
               modifita_je=?
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
                json.dumps(entry.get("semantika", []), ensure_ascii=False),
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

# Superklasoj (retro-kongrue): UUID-oj aŭ [Terminologio, UUID] paroj
superklaso = {superklaso}

# Ligiloj: listo de UUID-oj aŭ [UUID, semantika_tipo]
# Ekzemploj:
#   ligilo = "uuid1"
#   ligilo = ["vt#8bf534dc"]          # ligo al vorto
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

# Semantikaj valoroj: semantika = \"\"\"tipo arko valoro [#unuo_uuid]\"\"\"
{semantika}
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
    semantika = _normalize_semantika_valoroj(entry.get("semantika"))
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
                    items.append(f"{k} = {json.dumps(v, ensure_ascii=False)}")
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
                    items.append(
                        f"{k} = {json.dumps(str(c.get(k)), ensure_ascii=False)}"
                    )
            parts.append(f"{{{', '.join(items)}}}")
        return "[" + ", ".join(parts) + "]"

    def _datumo_block(datasets: dict) -> str:
        if not datasets:
            return ""
        lines: list[str] = []
        for name in sorted(datasets):
            payload = json.dumps(datasets[name], ensure_ascii=False, indent=2)
            lines.append(f'datumo.{name} = """\n{payload}\n"""')
        return "\n\n".join(lines)

    def _semantika_block(items: list[dict[str, object]]) -> str:
        if not items:
            return ""
        lines: list[str] = []
        for item in items:
            tipo = str(item.get("tipo") or "").strip().lower()
            arko = str(item.get("arko") or "").strip()
            valoro = _format_semantika_valoro(
                item.get("valoro"), tipo=tipo, for_enc=True
            )
            unuo = _normalize_semantika_unuo(item.get("unuo"), field="semantika.unuo")
            if not tipo or not arko:
                continue
            if unuo:
                lines.append(f"{tipo} {arko} {valoro} #{unuo}")
            else:
                lines.append(f"{tipo} {arko} {valoro}")
        if not lines:
            return ""
        return 'semantika = """\n' + "\n".join(lines) + '\n"""'

    def _lang_map_lines(prefix: str, mapping: dict[str, str]) -> str:
        lines = []
        for lang in sorted(mapping):
            value = _decode_visible_newlines(str(mapping[lang] or ""))
            if "\n" in value:
                safe = value.replace('"""', '\\"""')
                lines.append(f'{prefix}.{lang} = """\n{safe}\n"""')
            else:
                lines.append(
                    f"{prefix}.{lang} = {json.dumps(value, ensure_ascii=False)}"
                )
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
        semantika=_semantika_block(semantika),
    )


def _invalid_edit_dir() -> Path:
    return _DATA_DIR / "encik-invalidaj"


def _invalid_edit_path(uuid: str) -> Path:
    return _invalid_edit_dir() / f"{uuid}.enc"


def _safe_export_basename(raw: str, fallback: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(raw or "").strip())
    ascii_ready = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    candidate = re.sub(r"[^A-Za-z0-9._-]+", "-", ascii_ready).lower()
    candidate = re.sub(r"-{2,}", "-", candidate).strip("-._")
    return candidate or fallback


def _resolve_export_path(raw_path: str, *, default_filename: str, suffix: str) -> Path:
    path = Path(raw_path).expanduser()
    raw_text = str(raw_path or "").strip()
    if (path.exists() and path.is_dir()) or raw_text.endswith(("/", "\\")):
        path = path / default_filename
    if path.suffix.lower() != suffix.lower():
        path = path.with_suffix(suffix)
    return path.resolve()


def _parse_required_lingvo_codes(raw: str, *, field: str) -> list[str]:
    parsed = _normalize_lingvo_codes(raw, field=field)
    if not parsed:
        raise ValueError(
            f"Mankas valoro por {field}. Uzu 2-literajn kodojn (ekz: eo,fr,en)."
        )
    return parsed


def _validate_generated_enc_output(
    raw_text: str,
    *,
    term_lingvoj: list[str],
    difino_lingvoj: list[str],
) -> None:
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            suffix=".enc",
            delete=False,
        ) as temp:
            temp.write(raw_text)
            temp_path = Path(temp.name)
        parsed = _parse_enc_file(temp_path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()

    terminologio = parsed.get("terminologio") or {}
    difinoj = parsed.get("difinoj") or {}
    missing_terms = [
        lang for lang in term_lingvoj if not str(terminologio.get(lang) or "").strip()
    ]
    missing_defs = [
        lang for lang in difino_lingvoj if not str(difinoj.get(lang) or "").strip()
    ]
    if missing_terms or missing_defs:
        problems: list[str] = []
        if missing_terms:
            problems.append(f"mankas terminologio por: {', '.join(missing_terms)}")
        if missing_defs:
            problems.append(f"mankas difino por: {', '.join(missing_defs)}")
        raise ValueError("Nevalida AI-.enc eligo: " + "; ".join(problems))

    expanded = _expand_multi_locale_assignments(
        _normalize_multiline_value_spacing(raw_text)
    )
    expanded = _escape_latex_style_backslashes(expanded)
    parsed_raw = tomllib.loads(expanded)
    allowed = {"terminologio", "difino"}
    extra = sorted(str(key) for key in parsed_raw.keys() if str(key) not in allowed)
    if extra:
        raise ValueError(
            "Nevalida AI-.enc eligo: nur `terminologio` kaj `difino` "
            "kampoj estas permesitaj."
        )


def _build_encik_generi_instrukcio(
    termino: str,
    *,
    term_lingvoj: list[str],
    difino_lingvoj: list[str],
    papildona_instrukcio: str | None,
) -> str:
    term_line = ",".join(term_lingvoj)
    def_line = ",".join(difino_lingvoj)
    lines = [
        f'Generu validan .enc dosieron pri "{termino}".',
        "Redonu nur la .enc tekston, sen klarigoj.",
        "Generu nur kampojn `terminologio.xx` kaj `difino.xx`.",
        f"Terminologio-lingvoj: {term_line}.",
        f"Difino-lingvoj: {def_line}.",
        "Ĉiu petita lingvo devas havi ne-malplenan valoron.",
        "Ne uzu kodbarilojn.",
    ]
    if (papildona_instrukcio or "").strip():
        lines.append(f"Plia instrukcio: {papildona_instrukcio.strip()}")
    return "\n".join(lines)


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
        if re.match(r"^\s*fonto\s*=", line):
            # First, fix bracket syntax: [[ -> [ and ]] -> ]
            # This converts array-of-arrays notation to array-of-inline-tables
            fixed = re.sub(r"=\s*\[\[", "=[{", line)  # [[ -> [{
            fixed = re.sub(r"\]\]", "}]", fixed)  # ]] -> }]

            # Then add missing commas between fields in inline tables
            # Pattern: Look for " followed by space and a letter/underscore (next field)
            # This matches: year="2021" author="..."
            # Replace with: year="2021", author="..."
            fixed = re.sub(
                r'"\s+([a-zA-Z_])',  # " followed by whitespace and letter
                r'", \1',  # Replace with ", followed by letter
                fixed,
            )
            lines.append(fixed)
        else:
            lines.append(line)
    return "\n".join(lines)


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
        if re.match(r"^\s*(ligilo|superklaso)\s*=\s*\[", line, re.IGNORECASE):
            # Quote unquoted tokens in arrays, including #uuid and rdf/owl tags.
            fixed = re.sub(
                r"(?<=[\[,])\s*([#a-zA-Z0-9_:\-\.]+)\s*(?=[,\]])",
                lambda m: f'"{m.group(1).strip()}"',
                line,
            )
            lines.append(fixed)
            continue

        lines.append(line)
    return "\n".join(lines)


def _expand_multi_locale_assignments(text: str) -> str:
    """Expand keys like terminologio.(en,fr)=... into one assignment per locale."""
    lines: list[str] = []
    pattern = re.compile(
        r"^(?P<indent>\s*)(?P<field>terminologio|difino|difinio)\.\((?P<langs>[^)]+)\)\s*=\s*(?P<rhs>.+?)\s*$",
        re.IGNORECASE,
    )
    for line in text.splitlines():
        match = pattern.match(line)
        if not match:
            lines.append(line)
            continue
        field = match.group("field")
        lang_raw = match.group("langs")
        rhs = match.group("rhs").strip()
        parsed_langs = _normalize_lingvo_codes(
            lang_raw.replace(" ", ""), field=f"{field}.lingvo"
        )
        if not parsed_langs:
            raise ValueError(f"Nevalida {field}.lingvo listo: {lang_raw!r}.")
        # Be permissive for this shorthand: treat bare tokens as strings.
        if rhs and rhs[0] not in ('"', "'", "[", "{"):
            rhs = json.dumps(rhs, ensure_ascii=False)
        indent = match.group("indent")
        for lang in parsed_langs:
            lines.append(f"{indent}{field}.{lang} = {rhs}")
    return "\n".join(lines)


def _parse_semantika_bool(raw: object, *, field: str) -> bool:
    if isinstance(raw, bool):
        return raw
    value = str(raw).strip().lower()
    if value in _SEMANTIKA_BOOL_TRUE:
        return True
    if value in _SEMANTIKA_BOOL_FALSE:
        return False
    raise ValueError(f"Nevalida {field}: bool devas esti true/false (aŭ jes/ne).")


def _parse_semantika_int(raw: object, *, field: str) -> int:
    if isinstance(raw, bool):
        raise ValueError(f"Nevalida {field}: int ne povas esti bool-valoro.")
    if isinstance(raw, int):
        return raw
    value = str(raw).strip().replace(" ", "").replace("_", "")
    if re.fullmatch(r"[+-]?\d+", value):
        return int(value)
    if "," in value and "." not in value:
        normalized = value.replace(",", ".")
    else:
        normalized = value.replace(",", "")
    try:
        numeric = float(normalized)
    except ValueError as exc:
        raise ValueError(f"Nevalida {field}: int-valoro atendata.") from exc
    if not numeric.is_integer():
        raise ValueError(f"Nevalida {field}: int-valoro atendata.")
    return int(numeric)


def _parse_semantika_float(raw: object, *, field: str) -> float:
    if isinstance(raw, bool):
        raise ValueError(f"Nevalida {field}: float ne povas esti bool-valoro.")
    if isinstance(raw, (int, float)):
        return float(raw)
    value = str(raw).strip().replace(" ", "").replace("_", "")
    if "," in value and "." not in value:
        value = value.replace(",", ".")
    else:
        value = value.replace(",", "")
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"Nevalida {field}: float-valoro atendata.") from exc


def _parse_semantika_str(raw: object) -> str:
    if isinstance(raw, str):
        value = raw.strip()
    else:
        value = str(raw).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        if value[0] == '"':
            try:
                decoded = json.loads(value)
                if isinstance(decoded, str):
                    return decoded
            except json.JSONDecodeError:
                pass
        return value[1:-1]
    return value


def _normalize_semantika_unuo(raw: object, *, field: str) -> str | None:
    if raw is None:
        return None
    unuo = str(raw).strip()
    if not unuo:
        return None
    if unuo.lower() in {"si", "si-unuo"}:
        return None
    if unuo.startswith("#"):
        unuo = unuo[1:]
    if not unuo or any(ch.isspace() for ch in unuo):
        raise ValueError(f"Nevalida {field}: unuo devas esti #UUID.")
    return unuo


def _extract_inline_semantika_unuo(
    raw_valoro: object, *, tipo: str, field: str
) -> tuple[object, str | None]:
    if tipo not in {"int", "float", "bool"} or not isinstance(raw_valoro, str):
        return raw_valoro, None
    text = raw_valoro.strip()
    if not text:
        return text, None
    value_part, sep, maybe_unuo = text.rpartition(" ")
    if not sep or not value_part.strip():
        return text, None
    if not maybe_unuo.startswith("#"):
        return text, None
    normalized_unuo = _normalize_semantika_unuo(maybe_unuo, field=field)
    return value_part.strip(), normalized_unuo


def _parse_semantika_typed_value(raw: object, *, tipo: str, field: str) -> object:
    if tipo == "bool":
        return _parse_semantika_bool(raw, field=field)
    if tipo == "int":
        return _parse_semantika_int(raw, field=field)
    if tipo == "float":
        return _parse_semantika_float(raw, field=field)
    if tipo == "str":
        return _parse_semantika_str(raw)
    raise ValueError(f"Nevalida {field}: nekonata tipo {tipo!r}.")


def _coerce_semantika_item(item: object, *, field: str) -> dict[str, object]:
    if not isinstance(item, dict):
        raise ValueError(f"Nevalida {field}: devas esti objekto kun tipo/arko/valoro.")
    raw_tipo = item.get("tipo", item.get("type"))
    raw_arko = item.get("arko", item.get("arc"))
    if raw_tipo is None or raw_arko is None:
        raise ValueError(f"Nevalida {field}: mankas tipo aŭ arko.")
    tipo = str(raw_tipo).strip().lower()
    if tipo not in _SEMANTIKA_VALORO_TIPOJ:
        allowed = ", ".join(sorted(_SEMANTIKA_VALORO_TIPOJ))
        raise ValueError(f"Nevalida {field}: tipo devas esti unu el {allowed}.")
    arko = _normalize_semantika_ligilo(str(raw_arko).strip())
    if not arko:
        raise ValueError(f"Nevalida {field}: arko mankas.")
    if "valoro" in item:
        raw_valoro = item.get("valoro")
    elif "value" in item:
        raw_valoro = item.get("value")
    else:
        raise ValueError(f"Nevalida {field}: mankas valoro.")
    inline_valoro, inline_unuo = _extract_inline_semantika_unuo(
        raw_valoro, tipo=tipo, field=field
    )
    valoro = _parse_semantika_typed_value(inline_valoro, tipo=tipo, field=field)
    explicit_unuo = item.get("unuo", item.get("unit"))
    normalized_unuo = _normalize_semantika_unuo(
        explicit_unuo if explicit_unuo is not None else inline_unuo, field=field
    )
    coerced: dict[str, object] = {"tipo": tipo, "arko": arko, "valoro": valoro}
    if normalized_unuo:
        coerced["unuo"] = normalized_unuo
    return coerced


def _parse_semantika_field(raw_value: object) -> list[dict[str, object]]:
    if raw_value is None:
        return []
    if isinstance(raw_value, list):
        return [
            _coerce_semantika_item(item, field=f"semantika[{idx}]")
            for idx, item in enumerate(raw_value)
        ]
    if not isinstance(raw_value, str):
        raise ValueError("Nevalida semantika: devas esti teksto aŭ listo.")
    items: list[dict[str, object]] = []
    for line_no, raw_line in enumerate(raw_value.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(maxsplit=2)
        if len(parts) < 3:
            raise ValueError(
                "Nevalida semantika linio "
                f"{line_no}: atendata formato `tipo arko valoro`."
            )
        tipo, arko, valoro = parts
        item = _coerce_semantika_item(
            {"tipo": tipo, "arko": arko, "valoro": valoro},
            field=f"semantika linio {line_no}",
        )
        items.append(item)
    return items


def _normalize_semantika_valoroj(raw_value: object) -> list[dict[str, object]]:
    if raw_value is None:
        return []
    if isinstance(raw_value, str):
        try:
            decoded = json.loads(raw_value)
        except json.JSONDecodeError:
            return []
        raw_value = decoded
    if not isinstance(raw_value, list):
        return []
    normalized: list[dict[str, object]] = []
    for idx, item in enumerate(raw_value):
        try:
            normalized.append(_coerce_semantika_item(item, field=f"semantika[{idx}]"))
        except ValueError:
            continue
    return normalized


def _format_semantika_valoro(
    value: object, *, tipo: str, for_enc: bool = False, markdown: bool = False
) -> str:
    if tipo == "bool":
        rendered = "true" if bool(value) else "false"
    elif tipo == "int":
        parsed_int = _parse_semantika_int(value, field="semantika.valoro")
        rendered = (
            str(parsed_int)
            if for_enc
            else _format_number_for_display(float(parsed_int), integer_like=True)
        )
    elif tipo == "float":
        parsed_float = _parse_semantika_float(value, field="semantika.valoro")
        rendered = (
            f"{parsed_float:g}"
            if for_enc
            else _format_number_for_display(parsed_float, integer_like=False)
        )
    else:
        rendered = str(value)
    if for_enc and tipo == "str":
        return json.dumps(rendered, ensure_ascii=False)
    if markdown and tipo == "str":
        return _render_markdown_text(rendered)
    return rendered


def _format_semantika_unuo_cli(item: dict[str, object]) -> str:
    tipo = str(item.get("tipo") or "").strip().lower()
    unuo = _normalize_semantika_unuo(item.get("unuo"), field="semantika.unuo")
    if tipo not in {"int", "float"}:
        if not unuo:
            return ""
        return f"[dim](#{unuo})[/dim]"
    if not unuo:
        return "[dim](SI)[/dim]"
    return f"[dim](#{unuo})[/dim]"


def _format_semantika_unuo_html(item: dict[str, object], *, link_depth: int) -> str:
    tipo = str(item.get("tipo") or "").strip().lower()
    unuo = _normalize_semantika_unuo(item.get("unuo"), field="semantika.unuo")
    if tipo not in {"int", "float"}:
        if not unuo:
            return ""
    if tipo in {"int", "float"} and not unuo:
        return "<em>SI</em>"
    if not unuo:
        return ""
    resolved = _find_by_uuid(unuo)
    if not resolved:
        return f"#{escape(unuo)}"
    target_uuid = str(resolved.get("uuid") or unuo)
    target_title = _resolve_uuid_to_title(target_uuid)
    return _render_relation_html_link(target_title, target_uuid, link_depth=link_depth)


def _parse_enc_file(path: Path) -> dict:
    """Parse an .enc file and return a dict with the entry fields.

    The .enc format is TOML with an optional leading comment ``# title``.
    If the TOML itself contains a ``titolo`` key that takes precedence;
    otherwise the first ``# …`` comment is used as the title.
    """
    raw = _normalize_multiline_value_spacing(path.read_text(encoding="utf-8"))
    raw = _expand_multi_locale_assignments(raw)
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
    semantika = _parse_semantika_field(data.get("semantika"))

    entry = {
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
        "semantika": semantika,
    }
    # Validate ligilo references
    try:
        _raise_if_malformed_entry(entry)
        _validate_ligilo_references(entry)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    _raise_if_semantic_conflicts(entry, strict=False)
    entry["modifita_je"] = _now_iso()
    _update_entry(entry)
    _sync_bidirectional_relations_for_entry(entry, previous_ligilo=previous_ligilo)
    invalid_path.unlink(missing_ok=True)
    typer.echo(f'Modifis #{entry["uuid"][:8]}  "{entry["titolo"]}"')
    if kopii_uuid or semantika_kopii:
        _copy_entry_reference(entry, semantika=semantika_kopii)


@app.command("vidi")
def vidi(
    ref: str | None = typer.Argument(
        None,
        help=(
            "UUID, #UUID, aŭ terminologio (aproksimativa serĉo subtenata). "
            'Ekzemplo: encik vidi "#e0a5d3b7"'
        ),
    ),
    lingvo: str | None = typer.Option(
        None,
        "-l",
        "--lingvo",
        help="Montri en difinita lingvo (ekz. eo, en, id). Ekzemplo: -l en",
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
    kopii_uuid: bool = typer.Option(
        False,
        "-k",
        "--kopii",
        help="Kopii #xxxxxxxx de la montrita nodo al tondujo.",
    ),
    semantika_kopii: bool = typer.Option(
        False,
        "-sk",
        "--semantika-kopii",
        help="Kopii [titolo](#xxxxxxxx) de la montrita nodo al tondujo.",
    ),
) -> None:
    """Montri unu nodon laŭ UUID aŭ terminologio."""
    if kopii_uuid and semantika_kopii:
        typer.echo("Uzu nur unu el --kopii aŭ --semantika-kopii.", err=True)
        raise typer.Exit(code=1)
    if (kopii_uuid or semantika_kopii) and html:
        typer.echo("--kopii/--semantika-kopii ne kongruas kun --html.", err=True)
        raise typer.Exit(code=1)
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
    montrado_settings = _load_encik_montrado_settings()
    if not html and bool(montrado_settings.get("html")):
        html = True
    if html:
        html_doc = _render_entry_html(entry, lingvo=lingvo, montri_cxion=montri_cxion)
        out_path = _open_html_document(html_doc)
        typer.echo(f"Malfermas en retumilo: {out_path}")
        return
    if kopii_uuid or semantika_kopii:
        _copy_entry_reference(entry, semantika=semantika_kopii)
    _display_entry(entry, lingvo=lingvo, montri_cxion=montri_cxion)


@app.command("eksporti")
def eksporti(
    ref: str = typer.Argument(
        ...,
        help=(
            "UUID, #UUID, aŭ titolo por eksporti unu nodon. "
            'Ekzemplo: encik eksporti "#e0a5d3b7" ~/eliro/nodo.enc'
        ),
    ),
    celvojo: str = typer.Argument(
        ...,
        help=("Cel dosiero aŭ dosierujo por .enc eligo. Ekzemplo: ~/eliro/fiziko.enc"),
    ),
) -> None:
    """Eksporti unu encik-nodon al .enc dosiero."""
    entry = _resolve_entry(ref, interactive=True, precise=False)
    if entry is None:
        typer.echo(f"Nodo ne trovita: {ref!r}", err=True)
        raise typer.Exit(code=1)
    short_uuid = str(entry.get("uuid") or "")[:8]
    title = str(entry.get("titolo") or "").strip()
    default_name = f"{_safe_export_basename(title, short_uuid or 'encik')}.enc"
    out_path = _resolve_export_path(
        celvojo,
        default_filename=default_name,
        suffix=".enc",
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(_entry_to_enc(entry), encoding="utf-8")
    typer.echo(f'Eksportis #{short_uuid}  "{title}" al {out_path}.')


@app.command("generi")
def generi(
    terminologio: str = typer.Argument(
        ...,
        help='Terminologio por AI-generado (ekz: encik generi "macOS").',
    ),
    terminologio_lingvo: str = typer.Option(
        ...,
        "-tl",
        "--terminologio-lingvo",
        help="Lingvoj por `terminologio` (ekz: -tl eo,fr,en).",
    ),
    difino_lingvo: str = typer.Option(
        ...,
        "-dl",
        "--difino-lingvo",
        help="Lingvoj por `difino` (ekz: -dl eo,fr,en).",
    ),
    instrukcio: str | None = typer.Option(
        None,
        "-i",
        "--instrukcio",
        help="Plia instrukcio por la AI-modelo.",
    ),
    kunteksto_dosiero: Path | None = typer.Option(
        None,
        "-K",
        "--kunteksto-dosiero",
        help=(
            "Propra kunteksto-dosiero "
            "(ekz: -K ~/.config/autish/verki/encik-generi-kunteksto.md)."
        ),
    ),
    eksporti_vojo: str | None = typer.Option(
        None,
        "-E",
        "--eksporti",
        help="Skribi rezulton al .enc dosiero aŭ dosierujo (ekz: -E ./eliro/).",
    ),
    modelo: str = typer.Option(
        "MiniMaxAI/MiniMax-M2.7:novita",
        "-m",
        "--modelo",
        help="AI-modelo (ekz: -m MiniMaxAI/MiniMax-M2.7:novita).",
    ),
    provizanto: str = typer.Option(
        "huggingface",
        "-p",
        "--provizanto",
        help="AI-provizanto (ekz: -p huggingface).",
    ),
    api_slosilo: str | None = typer.Option(
        None,
        "-as",
        "--api-slosilo",
        help="API-slosilo por la AI-provizanto.",
    ),
    maksimumaj_tokenoj: int = typer.Option(
        1200,
        "-mt",
        "--maksimumaj-tokenoj",
        help="Maksimumaj novaj tokenoj (ekz: -mt 1500).",
    ),
    temperaturo: float = typer.Option(
        0.3,
        "-tm",
        "--temperaturo",
        help="Modela temperaturo inter 0 kaj 2 (ekz: -tm 0.3).",
    ),
) -> None:
    """Generi .enc tekston per AI por terminologio + difino kampoj."""
    try:
        term_lingvoj = _parse_required_lingvo_codes(
            terminologio_lingvo, field="--terminologio-lingvo"
        )
        difino_lingvoj = _parse_required_lingvo_codes(
            difino_lingvo, field="--difino-lingvo"
        )
        context = load_ai_context(
            "encik-generi",
            override_path=kunteksto_dosiero,
        )
        profile: dict | None = None
        try:
            profile = _load_profile(quiet=True)
        except Exception:
            profile = None
        service = build_verki_service(
            provizanto=provizanto,
            modelo=modelo,
            api_slosilo=api_slosilo,
            profile=profile,
        )
        generated = service.verki(
            VerkiRequest(
                instrukcio=_build_encik_generi_instrukcio(
                    terminologio,
                    term_lingvoj=term_lingvoj,
                    difino_lingvoj=difino_lingvoj,
                    papildona_instrukcio=instrukcio,
                ),
                kunteksto=context,
                maksimumaj_tokenoj=maksimumaj_tokenoj,
                temperaturo=temperaturo,
            )
        )
        _validate_generated_enc_output(
            generated,
            term_lingvoj=term_lingvoj,
            difino_lingvoj=difino_lingvoj,
        )
    except (ValueError, VerkiServiceError) as exc:
        typer.echo(f"Eraro: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if eksporti_vojo:
        default_name = f"{_safe_export_basename(terminologio, 'encik')}.enc"
        out_path = _resolve_export_path(
            eksporti_vojo,
            default_filename=default_name,
            suffix=".enc",
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(generated, encoding="utf-8")
        typer.echo(f"Skribis al {out_path}.")
    typer.echo(generated)


def _semantika_language_priority(languages: list[str]) -> list[str]:
    ordered: list[str] = []
    for raw_code in [*languages, "eo", "en"]:
        code = str(raw_code or "").strip().lower()
        if not re.fullmatch(r"[a-z]{2}", code):
            continue
        if code not in ordered:
            ordered.append(code)
    return ordered or ["eo", "en"]


def _semantika_serci_languages(lingvo: str | None) -> list[str]:
    if lingvo:
        parsed = _normalize_lingvo_codes(lingvo, field="--lingvo")
        if parsed:
            return _semantika_language_priority(parsed)
        raise ValueError("Nevalida --lingvo. Uzu 2-litera(j)n kodojn (ekz: eo,en).")
    preferred, _ = _load_user_language_preferences()
    if preferred:
        return _semantika_language_priority(preferred)
    env_lang = (os.environ.get("LC_ALL") or os.environ.get("LANG") or "").split(".")[0]
    env_code = env_lang.split("_")[0].strip().lower()
    if re.fullmatch(r"[a-z]{2}", env_code):
        return _semantika_language_priority([env_code])
    return ["eo", "en"]


def _wikidata_api_get(params: dict[str, str], *, timeout: float = 5.0) -> dict:
    query = urllib.parse.urlencode(params)
    url = f"https://www.wikidata.org/w/api.php?{query}"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "autish-encik/0.0.1 (Wikidata semantika integration)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            payload = response.read().decode(charset, errors="replace")
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError("Wikidata API neatingebla") from exc
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Wikidata API respondo nevalida") from exc
    if not isinstance(data, dict):
        raise RuntimeError("Wikidata API respondo nevalida")
    return data


def _wikidata_search_properties(
    query: str, languages: list[str]
) -> list[dict[str, object]]:
    dedup: dict[str, dict[str, object]] = {}
    for lang in languages:
        data = _wikidata_api_get(
            {
                "action": "wbsearchentities",
                "format": "json",
                "language": lang,
                "uselang": lang,
                "type": "property",
                "limit": "15",
                "search": query,
            }
        )
        results = data.get("search")
        if not isinstance(results, list):
            continue
        for item in results:
            if not isinstance(item, dict):
                continue
            prop_id = str(item.get("id") or "").strip()
            if not re.fullmatch(r"P\d+", prop_id):
                continue
            ligilo = f"wdt:{prop_id}"
            label = str(item.get("label") or "").strip()
            description = str(item.get("description") or "").strip()
            aliases: list[str] = []
            match_obj = item.get("match")
            if isinstance(match_obj, dict):
                text = str(match_obj.get("text") or "").strip()
                if text and text.lower() != label.lower():
                    aliases.append(text)
            if prop_id.lower() not in {alias.lower() for alias in aliases}:
                aliases.append(prop_id.lower())
            existing = dedup.get(ligilo)
            if existing is None:
                dedup[ligilo] = {
                    "ligilo": ligilo,
                    "priskribo": description,
                    "aliasoj": aliases,
                    "etikedo": label,
                    "fonto": "wikidata",
                }
                continue
            if not str(existing.get("priskribo") or "") and description:
                existing["priskribo"] = description
            combined_aliases = [str(a) for a in existing.get("aliasoj") or []]
            for alias in aliases:
                if alias.lower() not in {a.lower() for a in combined_aliases}:
                    combined_aliases.append(alias)
            existing["aliasoj"] = combined_aliases
    if dedup:
        prop_ids = [ligilo.split(":", 1)[1] for ligilo in dedup]
        try:
            metadata = _wikidata_properties_metadata(prop_ids, languages)
        except RuntimeError:
            metadata = {}
        for ligilo, item in dedup.items():
            prop_id = ligilo.split(":", 1)[1]
            localized = metadata.get(prop_id)
            if not localized:
                continue
            localized_label = str(localized.get("etikedo") or "").strip()
            localized_description = str(localized.get("priskribo") or "").strip()
            if localized_label:
                item["etikedo"] = localized_label
            if localized_description:
                item["priskribo"] = localized_description
            merged_aliases: list[str] = []
            for alias in [
                *[str(a) for a in (localized.get("aliasoj") or [])],
                *[str(a) for a in (item.get("aliasoj") or [])],
            ]:
                cleaned = alias.strip()
                if cleaned and cleaned.lower() not in {
                    a.lower() for a in merged_aliases
                }:
                    merged_aliases.append(cleaned)
            if merged_aliases:
                item["aliasoj"] = merged_aliases
    return list(dedup.values())


def _extract_wikidata_entity_metadata(
    entity: dict[str, object], *, prop_id: str, lang_list: list[str]
) -> dict[str, object]:
    labels = entity.get("labels")
    descriptions = entity.get("descriptions")
    aliases_obj = entity.get("aliases")
    label = ""
    description = ""
    if isinstance(labels, dict):
        for lang in lang_list:
            payload = labels.get(lang)
            if isinstance(payload, dict) and str(payload.get("value") or "").strip():
                label = str(payload.get("value") or "").strip()
                break
    if isinstance(descriptions, dict):
        for lang in lang_list:
            payload = descriptions.get(lang)
            if isinstance(payload, dict) and str(payload.get("value") or "").strip():
                description = str(payload.get("value") or "").strip()
                break
    alias_values: list[str] = []
    if isinstance(aliases_obj, dict):
        for lang in lang_list:
            payload = aliases_obj.get(lang)
            if not isinstance(payload, list):
                continue
            for alias_entry in payload:
                if not isinstance(alias_entry, dict):
                    continue
                value = str(alias_entry.get("value") or "").strip()
                if value and value.lower() not in {a.lower() for a in alias_values}:
                    alias_values.append(value)
    if prop_id.lower() not in {alias.lower() for alias in alias_values}:
        alias_values.append(prop_id.lower())
    return {
        "etikedo": label,
        "priskribo": description,
        "aliasoj": alias_values,
    }


def _wikidata_properties_metadata(
    prop_ids: list[str], languages: list[str]
) -> dict[str, dict[str, object]]:
    normalized_ids: list[str] = []
    for raw_id in prop_ids:
        candidate = str(raw_id or "").strip().upper()
        if not re.fullmatch(r"P\d+", candidate):
            continue
        if candidate not in normalized_ids:
            normalized_ids.append(candidate)
    if not normalized_ids:
        return {}
    lang_list = _semantika_language_priority(languages)
    data = _wikidata_api_get(
        {
            "action": "wbgetentities",
            "format": "json",
            "ids": "|".join(normalized_ids),
            "props": "labels|descriptions|aliases",
            "languages": "|".join(lang_list),
        }
    )
    entities = data.get("entities")
    if not isinstance(entities, dict):
        raise RuntimeError("Wikidata API respondo ne enhavas 'entities'")
    extracted: dict[str, dict[str, object]] = {}
    for prop_id in normalized_ids:
        entity = entities.get(prop_id)
        if not isinstance(entity, dict):
            continue
        extracted[prop_id] = _extract_wikidata_entity_metadata(
            entity,
            prop_id=prop_id,
            lang_list=lang_list,
        )
    return extracted


def _wikidata_property_metadata(
    prop_id: str, languages: list[str]
) -> dict[str, object]:
    lang_list = _semantika_language_priority(languages)
    data = _wikidata_api_get(
        {
            "action": "wbgetentities",
            "format": "json",
            "ids": prop_id,
            "props": "labels|descriptions|aliases",
            "languages": "|".join(lang_list),
        }
    )
    entities = data.get("entities")
    if not isinstance(entities, dict):
        raise RuntimeError("Wikidata API respondo ne enhavas 'entities'")
    entity = entities.get(prop_id)
    if not isinstance(entity, dict):
        raise RuntimeError("Wikidata API respondo ne enhavas la petitan ID")
    return _extract_wikidata_entity_metadata(
        entity,
        prop_id=prop_id,
        lang_list=lang_list,
    )


semantika_app = typer.Typer(
    help=_SEMANTIKA_HELPO_TEKSTO,
    no_args_is_help=False,
    invoke_without_command=True,
    context_settings={"help_option_names": ["-h", "--help", "--helpo"]},
)


@semantika_app.callback(invoke_without_command=True)
def _semantika_root(ctx: typer.Context) -> None:
    _register_semantika_group_commands()
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


def _print_semantika_kategorio(kategorio: str) -> None:
    groups = _load_semantika_groups()
    rows = groups.get(kategorio)
    if not rows:
        typer.echo(f"Nekonata semantika grupo: {kategorio!r}", err=True)
        raise typer.Exit(code=1)
    table = Table(
        title=f"Semantikaj ligiloj — {kategorio}",
        show_header=True,
        header_style="bold",
        expand=False,
    )
    table.add_column("LIGILO", style=_contrast_accent_style(), no_wrap=True)
    table.add_column("PRISKRIBO", style="white")
    table.add_column("ALIAZOJ", style="dim")
    for row in rows:
        canonical = str(row.get("ligilo") or "")
        description = str(row.get("priskribo") or "")
        aliases = [str(alias) for alias in (row.get("aliasoj") or []) if str(alias)]
        alias_text = ", ".join(aliases[:5]) if aliases else ""
        if len(aliases) > 5:
            alias_text += ", ..."
        table.add_row(canonical, description or "-", alias_text or "-")
    console.print(table)
    typer.echo(
        "Uzo: en `ligilo` uzu UUID:semantiko (ekz: "
        "1234abcd:rdf:type aŭ 1234abcd:wdt:P50)."
    )


def _register_semantika_group_commands() -> None:
    names = set(_SEMANTIKA_KATEGORIOJ.keys())
    if _SEMANTIKA_CONFIG_DIR.exists():
        names.update(
            path.stem.strip().lower() for path in _SEMANTIKA_CONFIG_DIR.glob("*.csv")
        )
    for group_name in sorted(name for name in names if name):
        if (
            group_name in _SEMANTIKA_RESERVED_SUBCOMMANDS
            or group_name in _REGISTERED_SEMANTIKA_GROUP_COMMANDS
        ):
            continue
        help_text = f"Montri semantikajn ligilojn de grupo '{group_name}'."

        def _group_command(group: str = group_name) -> None:
            _print_semantika_kategorio(group)

        semantika_app.command(group_name, help=help_text)(_group_command)
        _REGISTERED_SEMANTIKA_GROUP_COMMANDS.add(group_name)


@semantika_app.command(
    "serci",
    help=(
        "Serĉi semantikajn arkojn per Wikidata API kun loka fallback "
        "(~/.config/autish/semantika/*.csv)."
    ),
)
def semantika_ligilo_serci(
    demando: str = typer.Argument(
        ...,
        help='Serĉdemando por LIGILO/PRISKRIBO/ALIAZOJ (ekz: "P1082" aŭ "population").',
    ),
    lingvo: str | None = typer.Option(
        None,
        "-l",
        "--lingvo",
        help="Lingvo-kodo(j) por Wikidata serĉo (ekz: -l eo aŭ -l eo,en).",
    ),
) -> None:
    needle = demando.strip().lower()
    if not needle:
        typer.echo("Mankas serĉdemando.", err=True)
        raise typer.Exit(code=1)
    try:
        languages = _semantika_serci_languages(lingvo)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    local_matches: list[dict[str, object]] = []
    for group_name, rows in _load_semantika_groups().items():
        for row in rows:
            ligilo = str(row.get("ligilo") or "")
            priskribo = str(row.get("priskribo") or "")
            aliases = [str(alias) for alias in (row.get("aliasoj") or [])]
            haystack = [ligilo, priskribo, *aliases]
            if any(needle in value.lower() for value in haystack if value):
                local_matches.append(
                    {
                        "fonto": "loka",
                        "grupo": group_name,
                        "ligilo": ligilo,
                        "priskribo": priskribo,
                        "aliasoj": aliases,
                    }
                )

    wikidata_matches: list[dict[str, object]] = []
    wikidata_warning = ""
    try:
        wikidata_matches = _wikidata_search_properties(demando, languages)
    except RuntimeError as exc:
        wikidata_warning = (
            f"Averto: {exc}. Uzas lokan fallback-serĉon en semantika CSV."
        )
    if wikidata_warning:
        typer.echo(wikidata_warning, err=True)

    combined: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for row in wikidata_matches + local_matches:
        key = (str(row.get("fonto") or ""), str(row.get("ligilo") or "").lower())
        if key in seen:
            continue
        seen.add(key)
        combined.append(row)
    if not combined:
        typer.echo("Neniu semantika arko trovita (Wikidata nek loka).")
        return

    table = Table(show_header=True, header_style="bold", expand=False)
    table.add_column("FONTO", style="dim", no_wrap=True)
    table.add_column("GRUPO", style="dim", no_wrap=True)
    table.add_column("LIGILO", style=_contrast_accent_style(), no_wrap=True)
    table.add_column("PRISKRIBO")
    table.add_column("ALIAZOJ", style="dim")
    for row in combined:
        aliases = [str(alias) for alias in (row.get("aliasoj") or []) if str(alias)]
        table.add_row(
            str(row.get("fonto") or "-"),
            str(row.get("grupo") or "-"),
            str(row.get("ligilo") or ""),
            str(row.get("priskribo") or "-"),
            ", ".join(aliases) if aliases else "-",
        )
    console.print(table)


def _normalize_semantika_add_id(raw_id: str) -> tuple[str, str | None]:
    token = str(raw_id or "").strip()
    if not token:
        raise ValueError("Mankas semantika ID.")
    prop_match = re.fullmatch(r"[Pp](\d+)", token)
    if prop_match:
        prop_id = f"P{prop_match.group(1)}"
        return f"wdt:{prop_id}", prop_id
    wdt_match = re.fullmatch(r"wdt:[Pp](\d+)", token, flags=re.IGNORECASE)
    if wdt_match:
        prop_id = f"P{wdt_match.group(1)}"
        return f"wdt:{prop_id}", prop_id
    normalized = _normalize_semantika_ligilo(token) or token
    return normalized, None


@semantika_app.command(
    "aldoni",
    help=(
        "Aldoni semantikan arkon al grupo en ~/.config/autish/semantika. "
        "Normale validigas per Wikidata API; se neatingebla, loka fallback."
    ),
)
def semantika_ligilo_aldoni(
    identigilo: str = typer.Argument(
        ...,
        help="Arko aŭ Wikidata ID (ekz: P1082 aŭ wdt:P1082).",
    ),
    grupo: str = typer.Argument(
        ...,
        help='Cel-grupo (CSV dosiero). Ekzemplo: "geografio".',
    ),
    priskribo: str | None = typer.Option(
        None,
        "-p",
        "--priskribo",
        help='Mana PRISKRIBO por offline fallback (ekz: -p "Loĝantaro").',
    ),
    aliazoj: str | None = typer.Option(
        None,
        "-a",
        "--aliazoj",
        help="Manaj ALIAZOJ (CSV) por offline fallback (ekz: -a p1082,population).",
    ),
    lingvo: str | None = typer.Option(
        None,
        "-l",
        "--lingvo",
        help="Lingvo-kodo(j) por Wikidata metadatumoj (ekz: -l eo,en).",
    ),
) -> None:
    try:
        group_name = _normalize_semantika_group_name(grupo)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    ligilo, prop_id = _normalize_semantika_add_id(identigilo)
    groups = _load_semantika_groups()
    if group_name not in groups:
        answer = typer.prompt(
            f"Grupo '{group_name}' ne ekzistas. Ĉu krei ĝin? (j/N)",
            default="n",
        )
        if answer.strip().lower() not in {"j", "jes", "y", "yes"}:
            typer.echo("Nuligita.")
            return
        groups[group_name] = []

    rows = [dict(row) for row in groups.get(group_name, [])]
    existing_index = next(
        (
            index
            for index, row in enumerate(rows)
            if str(row.get("ligilo") or "").strip().lower() == ligilo.lower()
        ),
        None,
    )
    overwrite_existing = False
    if existing_index is not None:
        typer.echo(
            f"Averto: {ligilo} jam ekzistas en grupo '{group_name}'.",
            err=True,
        )
        answer = typer.prompt(
            "Ĉu anstataŭigi la ekzistantan eniron? (j/N)",
            default="n",
        )
        if answer.strip().lower() not in {"j", "jes", "y", "yes"}:
            typer.echo("Nuligita.")
            return
        overwrite_existing = True

    default_desc, default_aliases = _SEMANTIKA_DEFINOJ_MAP.get(ligilo, ("", ()))
    resolved_desc = default_desc
    resolved_aliases = list(default_aliases)
    if prop_id:
        try:
            languages = _semantika_serci_languages(lingvo)
        except ValueError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc
        try:
            meta = _wikidata_property_metadata(prop_id, languages)
            if str(meta.get("priskribo") or "").strip():
                resolved_desc = str(meta.get("priskribo") or "").strip()
            meta_aliases = [str(v) for v in (meta.get("aliasoj") or []) if str(v)]
            for alias in meta_aliases:
                if alias.lower() not in {a.lower() for a in resolved_aliases}:
                    resolved_aliases.append(alias)
        except RuntimeError as exc:
            typer.echo(
                f"Averto: {exc}. Aldono ne validigita kontraŭ Wikidata.",
                err=True,
            )
            if not priskribo:
                typer.echo(
                    "Offline fallback: uzu almenaŭ --priskribo por "
                    "konservi CSV-eniron.",
                    err=True,
                )
                raise typer.Exit(code=1) from exc
            resolved_desc = priskribo
            resolved_aliases = _parse_alias_list(aliazoj or "")
    if priskribo:
        resolved_desc = priskribo
    if aliazoj is not None:
        resolved_aliases = _parse_alias_list(aliazoj)
    if prop_id and prop_id.lower() not in {a.lower() for a in resolved_aliases}:
        resolved_aliases.append(prop_id.lower())
    new_row = {
        "ligilo": ligilo,
        "priskribo": resolved_desc,
        "aliasoj": resolved_aliases,
    }
    if overwrite_existing and existing_index is not None:
        rows[existing_index] = new_row
    else:
        rows.append(new_row)
    _write_semantika_group_rows(group_name, rows)
    _invalidate_semantika_config_cache()
    _register_semantika_group_commands()
    if overwrite_existing:
        typer.echo(
            f"Anstataŭigis {ligilo} en grupo '{group_name}'. "
            f"Dosiero: {_semantika_group_file(group_name)}"
        )
    else:
        typer.echo(
            f"Aldonis {ligilo} al grupo '{group_name}'. "
            f"Dosiero: {_semantika_group_file(group_name)}"
        )


app.add_typer(semantika_app, name="semantika")
_register_semantika_group_commands()


@app.command("semantika-serci")
def semantika_serci(
    ctx: typer.Context,
    esprimo: str | None = typer.Argument(
        None,
        help=(
            "Kondiĉoj apartigitaj per ';'.\n"
            "Ekzemploj:\n"
            '  encik semantika-serci "wdt:P5191 *philosophia*"\n'
            '  encik semantika-serci "wdt:P1082 (0,1000); wdt:P31 true"'
        ),
    ),
) -> None:
    """Serĉi nodojn laŭ semantikaj datum-valoroj (AND inter kondiĉoj)."""
    if esprimo is None:
        typer.echo(ctx.get_help())
        return
    try:
        conditions = _parse_semantika_serci_conditions(esprimo)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    matches = [
        entry
        for entry in _load_all()
        if _entry_matches_semantika_conditions(entry, conditions)
    ]
    if not matches:
        typer.echo("Neniu nodo trovita por semantika-serĉo.")
        return
    if len(matches) == 1:
        _display_entry(matches[0])
        return
    typer.echo(f"{len(matches)} nodo(j) trovitaj.")
    _print_candidates(matches)


def _parse_semantiko_link_filters(raw: str) -> list[tuple[str, str | None]]:
    clauses = [part.strip() for part in str(raw or "").split(";") if part.strip()]
    if not clauses:
        raise ValueError("Nevalida --semantiko valoro.")
    parsed: list[tuple[str, str | None]] = []
    for idx, clause in enumerate(clauses, start=1):
        rel_token, sep, raw_target = clause.partition(" ")
        rel = _normalize_semantika_ligilo(rel_token.strip())
        if not rel or not _is_known_semantika_ligilo(rel):
            raise ValueError(
                f"Nevalida --semantiko valoro en kondiĉo {idx}: {rel_token!r}."
            )
        target = raw_target.strip() if sep else None
        if sep and not target:
            raise ValueError(
                f"Nevalida --semantiko kondiĉo {idx}: mankas celnodo post ligilo."
            )
        parsed.append((rel, target or None))
    return parsed


@app.command("serci")
def serci(
    ctx: typer.Context,
    demando: str | None = typer.Argument(
        None,
        help="Demando por serĉo (titolo defaŭlte, aŭ plena teksto kun -t).",
    ),
    lingvo: str | None = typer.Option(
        None,
        "-l",
        "--lingvo",
        help=(
            "Preferataj lingvokodoj por montri rezultojn (komo-disigitaj). "
            "Ekzemplo: -l fr,en"
        ),
    ),
    teksto: bool = typer.Option(
        False,
        "-t",
        "--teksto",
        help="Serĉi tra plena enhavo de nodoj (ne nur titolo).",
    ),
    html: bool = typer.Option(
        False,
        "-H",
        "--html",
        help="Montri serĉrezultojn kiel semantikan retan diagramon en retumilo.",
    ),
    preciza: bool = typer.Option(
        False,
        "-p",
        "--preciza",
        help="Malŝalti malklaran rezervan kongruigon.",
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
        "-L",
        "--ligilo",
        help="Montri rilatan mapon (super/sub/ligilo) de nodo en HTML.",
    ),
    semantiko: str | None = typer.Option(
        None,
        "-sm",
        "--semantiko",
        help=(
            "Filter by semantic link type or condition (RDF/OWL/Wikidata). "
            "Examples: rdf:type, rdfs:subClassOf, wdt:P50 (author), "
            "wdt:P361 (part of), wdt:P276 (location), wdt:P106 (occupation). "
            "Complex: 'rdf:type #9be93895; wdt:P361 #1a2b3c4d'. "
            "Full reference: encik semantika"
        ),
    ),
    al_ref: str | None = typer.Option(
        None,
        "--al",
        help="Kun --semantiko: celi specifan nodon (UUID/titolo).",
    ),
    paralela: bool = typer.Option(
        False,
        "-P",
        "--paralela",
        help="Serĉi paralelajn klasojn (nodoj kun sama superklaso).",
    ),
    limo: int = typer.Option(
        20,
        "-lo",
        "--limo",
        help=(
            "Por -s/-S: maksimuma profundo (0 = senlima). Por -p: maksimumaj rezultoj."
        ),
    ),
    paralela_limo: int = typer.Option(
        100,
        "--paralela-limo",
        hidden=True,
        help="Maksimumaj rezultoj por --paralela (defaŭlte 100).",
    ),
    kopii_uuid: bool = typer.Option(
        False,
        "-k",
        "--kopii",
        help=(
            "Kopii mallongan UUID-referencon (#xxxxxxxx) de la trovita nodo al tondujo "
            "(ĉe pluraj rezultoj: la interage elektita)."
        ),
    ),
    semantika_kopii: bool = typer.Option(
        False,
        "-sk",
        "--semantika-kopii",
        help=(
            "Kopii semantikan referencon en formo [titolo](#xxxxxxxx) al tondujo "
            "(ĉe pluraj rezultoj: la interage elektita)."
        ),
    ),
) -> None:
    """Serĉi nodojn. Por semantikaj ligiloj, vidu ankaŭ: encik semantika."""
    relation_mode = (
        any(
            value is not None
            for value in (subklasoj, superklasoj, ligilo_ref, semantiko)
        )
        or paralela
    )
    if not relation_mode and not demando and not (kopii_uuid or semantika_kopii):
        typer.echo(ctx.get_help())
        return

    if nova_unue and malnova_unue:
        typer.echo("Uzu nur unu el --nova-unue aŭ --malnova-unue.", err=True)
        raise typer.Exit(code=1)
    if alta_unue and malalta_unue:
        typer.echo("Uzu nur unu el --alta-unue aŭ --malalta-unue.", err=True)
        raise typer.Exit(code=1)
    if kopii_uuid and semantika_kopii:
        typer.echo("Uzu nur unu el --kopii aŭ --semantika-kopii.", err=True)
        raise typer.Exit(code=1)
    if semantiko and ligilo_ref is not None:
        typer.echo("Uzu aŭ --ligilo aŭ --semantiko, ne ambaŭ samtempe.", err=True)
        raise typer.Exit(code=1)
    if al_ref and not semantiko:
        typer.echo("--al postulas --semantiko.", err=True)
        raise typer.Exit(code=1)
    if (kopii_uuid or semantika_kopii) and demando is None:
        typer.echo("--kopii/--semantika-kopii postulas serĉan demandon.", err=True)
        raise typer.Exit(code=1)
    if (kopii_uuid or semantika_kopii) and html:
        typer.echo("--kopii/--semantika-kopii ne kongruas kun --html.", err=True)
        raise typer.Exit(code=1)
    preferred_search_langs: list[str] = []
    if lingvo is not None:
        try:
            preferred_search_langs = _normalize_lingvo_codes(lingvo, field="--lingvo")
        except ValueError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc

    def _preferred_search_lang(entry: dict) -> str | None:
        if not preferred_search_langs:
            return None
        terms_obj = entry.get("terminologio")
        terms = terms_obj if isinstance(terms_obj, dict) else {}
        defs_obj = entry.get("difinoj")
        defs = defs_obj if isinstance(defs_obj, dict) else {}
        for code in preferred_search_langs:
            if str(terms.get(code) or "").strip() or str(defs.get(code) or "").strip():
                return code
        return None

    if semantiko:
        try:
            filters = _parse_semantiko_link_filters(semantiko)
        except ValueError as exc:
            typer.echo("Nevalida --semantiko valoro.", err=True)
            typer.echo(str(exc), err=True)
            typer.echo(_semantika_help_hint(), err=True)
            raise typer.Exit(code=1) from exc

        if al_ref:
            if len(filters) != 1:
                typer.echo(
                    "--al kongruas nur kun unu --semantiko ligilo-kondiĉo.",
                    err=True,
                )
                raise typer.Exit(code=1)
            rel, existing_target = filters[0]
            if existing_target is not None:
                typer.echo(
                    "Uzu aŭ --al aŭ celreferencon en --semantiko, ne ambaŭ.",
                    err=True,
                )
                raise typer.Exit(code=1)
            filters = [(rel, al_ref)]

        resolved_filters: list[tuple[str, str | None]] = []
        for rel, target_ref in filters:
            if target_ref is None:
                resolved_filters.append((rel, None))
                continue
            target_entry = _resolve_entry(
                target_ref, interactive=False, precise=preciza
            )
            if target_entry is None:
                typer.echo(
                    f"Cela nodo ne trovita por --semantiko: {target_ref!r}",
                    err=True,
                )
                raise typer.Exit(code=1)
            resolved_filters.append((rel, str(target_entry["uuid"])))

        matches: list[tuple[dict, list[tuple[str, str]]]] = []
        for entry in _load_all():
            links = _normalize_ligilo_items(entry.get("ligilo") or [])
            matched_links: list[tuple[str, str]] = []
            ok = True
            for rel, target_uuid in resolved_filters:
                rel_hits: list[str] = []
                for link in links:
                    if link.get("tipo") != rel:
                        continue
                    to_uuid = str(link.get("uuid") or "")
                    resolved = _find_by_uuid(to_uuid)
                    if not resolved:
                        continue
                    resolved_uuid = str(resolved["uuid"])
                    if target_uuid and resolved_uuid != target_uuid:
                        continue
                    rel_hits.append(resolved_uuid)
                if not rel_hits:
                    ok = False
                    break
                matched_links.append((rel, rel_hits[0]))
            if ok:
                matches.append((entry, matched_links))

        if not matches:
            typer.echo("Neniu semantika ligilo trovita.")
            return

        if html:
            if len(resolved_filters) != 1:
                typer.echo(
                    "--html por --semantiko subtenas nur unu ligilo-kondiĉon.",
                    err=True,
                )
                raise typer.Exit(code=1)
            only_rel = resolved_filters[0][0]
            html_matches = [(entry, links[0][1]) for entry, links in matches]
            root, graph_nodes, graph_edges = _render_semantika_matches_html(
                only_rel, html_matches
            )
            html_doc = _render_linked_graph_html(root, graph_nodes, graph_edges)
            out_path = _open_html_document(html_doc)
            typer.echo(f"Malfermas semantikan mapon en retumilo: {out_path}")
            return

        if len(resolved_filters) == 1:
            typer.echo(f"Semantikaj ligiloj ({resolved_filters[0][0]}):")
        else:
            typer.echo("Semantikaj ligiloj (AND-kondiĉoj):")
        for source, link_hits in matches:
            for rel, to_uuid in link_hits:
                target_title = _resolve_uuid_to_title(to_uuid)
                typer.echo(
                    f"  #{source['uuid'][:8]} {source['titolo']} -> "
                    f"{rel} -> {target_title} #{to_uuid[:8]}"
                )
        return

    # For -s/-S/-L/-p we need to resolve the root node.
    # `encik serci -p <ref>` uses positional `demando` as the root reference.
    root_ref = subklasoj or superklasoj or ligilo_ref
    if root_ref is None and paralela:
        root_ref = demando

    if paralela and root_ref is None:
        typer.echo("Mankas radika nodo por --paralela (uzu UUID aŭ titolon).", err=True)
        raise typer.Exit(code=1)

    if root_ref is not None:
        root = _resolve_entry(root_ref, precise=preciza)
        if root is None:
            typer.echo(f"Nodo ne trovita: {root_ref!r}", err=True)
            raise typer.Exit(code=1)
        depth = abs(limo)
        if html:
            graph_nodes, graph_edges = _linked_graph_of(root["uuid"], max_depth=depth)
            if not graph_nodes:
                typer.echo(f"Neniu rilata nodo trovita por '{root['titolo']}'.")
                return
            html_doc = _render_linked_graph_html(root, graph_nodes, graph_edges)
            out_path = _open_html_document(html_doc)
            typer.echo(f"Malfermas rilatan mapon en retumilo: {out_path}")
            return

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
            max_r = paralela_limo if limo == 20 else abs(limo)
            results = _paralela_of(root["uuid"], max_results=max_r)
            if not results:
                typer.echo(f"Neniu paralela nodo trovita por '{root['titolo']}'.")
                return
            typer.echo(f"Paralela ({root['titolo']}) — max {max_r}:")
            for e in results:
                typer.echo(f"  #{e['uuid'][:8]}  {e['titolo']}")
            return

        # ── -L / --ligilo ──────────────────────────────────────────────────
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

        def _copy_selected_entry(entry: dict) -> None:
            if not kopii_uuid and not semantika_kopii:
                return
            _copy_entry_reference(
                entry,
                semantika=semantika_kopii,
                preferred_langs=preferred_search_langs,
            )

        if preciza:
            needle = demando.strip().lower()
            candidates = [
                e
                for e in _load_all()
                if needle
                and (
                    str(e.get("titolo") or "").strip().lower() == needle
                    or needle
                    in {
                        str(v).strip().lower()
                        for v in (e.get("terminologio") or {}).values()
                        if str(v).strip()
                    }
                    or str(e.get("uuid") or "").startswith(needle.lstrip("#"))
                )
            ][: abs(limo)]
        else:
            candidates = _search_entries_with_fts(
                demando,
                full_text=teksto,
                max_results=abs(limo),
                prefer_newest=not malnova_unue,
                prefer_high_level=not malalta_unue,
            )
        if html and candidates:
            root, graph_nodes, graph_edges = _search_graph_of(candidates, max_depth=1)
            html_doc = _render_linked_graph_html(root, graph_nodes, graph_edges)
            out_path = _open_html_document(html_doc)
            typer.echo(f"Malfermas serĉan mapon en retumilo: {out_path}")
            return
        if not candidates:
            typer.echo(f"Neniu nodo trovita por '{demando}'.")
            return
        if len(candidates) == 1:
            _copy_selected_entry(candidates[0])
            _display_entry(candidates[0], lingvo=_preferred_search_lang(candidates[0]))
            return
        _print_candidates(candidates, preferred_langs=preferred_search_langs)
        raw = typer.prompt(
            "Elektu numeron por vidi detalojn/kopii (aŭ Enter por preteriri)",
            default="",
        )
        if raw.strip():
            try:
                idx = int(raw.strip()) - 1
                if 0 <= idx < len(candidates):
                    _copy_selected_entry(candidates[idx])
                    _display_entry(
                        candidates[idx], lingvo=_preferred_search_lang(candidates[idx])
                    )
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
            typer.echo(f"Paĝo {pagho} ne ekzistas (nur {max_pages} paĝo(j)).", err=True)
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
            'Mankas UUID. Se vi uzas UUID kun #, citu ĝin:\n  encik forigi "#e0a5d3b7"',
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
                        f"Pluredaj trovoj por {uuid_input}. Uzu pli longan UUID-on.",
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
