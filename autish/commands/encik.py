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
from functools import lru_cache
from html import escape
from pathlib import Path

import typer
from rich.panel import Panel
from rich.table import Table

from autish.commands.uzanto import _load_profile
from autish.console import console
from autish.services.ai_common import build_verki_service, load_ai_context
from autish.services import encik_repo
from autish.services.verki import VerkiRequest, VerkiServiceError
from autish.utils import now_iso, open_path_in_browser

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
# DB schema (moved to autish/services/encik_repo.py)
# ──────────────────────────────────────────────────────────────────────────────

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


@lru_cache(maxsize=1)
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


@lru_cache(maxsize=1)
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


@lru_cache(maxsize=1)
def _runtime_known_semantika_ligiloj() -> set[str]:
    return set(_runtime_semantika_alias_map().values())


def _terminal_has_light_background() -> bool:
    """Check if terminal has a light background for contrast calculations."""
    colorfgbg = os.environ.get("COLORFGBG", "")
    if not colorfgbg:
        return False
    parts = colorfgbg.split(";")
    if len(parts) >= 2:
        try:
            bg_color = int(parts[-1].strip())
            return bg_color in {7, 15}
        except ValueError:
            return False
    return False


def _contrast_accent_style() -> str:
    """Return an accent color with improved contrast against terminal background."""
    return "blue" if _terminal_has_light_background() else "bright_cyan"


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
    """Initialize the database (delegated to encik_repo)."""
    encik_repo.init_db()


def _get_conn() -> sqlite3.Connection:
    """Get a database connection (delegated to encik_repo)."""
    return encik_repo.get_conn()


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
    """Convert a row to dict (delegated to encik_repo)."""
    return encik_repo.row_to_dict(row)
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
    """Load all entries without sorting (delegated to encik_repo)."""
    return encik_repo.load_all_unsorted()


def _load_all() -> list[dict]:
    """Load all entries sorted by title (delegated to encik_repo)."""
    return encik_repo.load_all()


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
    
    # Also try compact matching (ignoring all spaces and punctuation)
    # This allows "AI," to match "AI"
    from autish.utils import fold_search_compact
    compact_needle = fold_search_compact(needle)
    compact_text = fold_search_compact(text)
    if compact_needle and compact_text:
        compact_matches = len(re.findall(re.escape(compact_needle), compact_text))
        return max(direct, stripped, compact_matches)
    
    return max(direct, stripped)


def _fold_search_text(text: str) -> str:
    raw = str(text or "")
    raw = raw.replace("œ", "oe").replace("Œ", "OE")
    normalized = unicodedata.normalize("NFKD", raw)
    stripped = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return stripped.casefold()


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
    """Search using FTS5 if available, falls back to Python search.
    
    FTS significantly improves performance on large databases by:
    - Using inverted indexes for O(log n) text lookups
    - Filtering at database level before loading into memory
    - Ranking by relevance with minimal Python-side scoring
    """
    needle = _fold_search_text(query.strip())
    if not needle:
        return []
    
    conn = _get_conn()
    try:
        # Try FTS search for full_text queries
        if full_text:
            # Build FTS query: search all indexed columns
            # FTS5 supports: column:query, AND, OR, NOT operators
            fts_query = " OR ".join(needle.split())
            try:
                rows = conn.execute(
                    """
                    SELECT uuid FROM encik_fts
                    WHERE encik_fts MATCH ?
                    LIMIT ?
                    """,
                    (fts_query, max_results * 2),  # Get extra for filtering
                ).fetchall()
                
                fts_uuids = {row[0] for row in rows}
                # Load matched entries from main table
                placeholders = ",".join("?" * len(fts_uuids))
                entries = []
                if fts_uuids:
                    rows = conn.execute(
                        f"SELECT * FROM encik WHERE uuid IN ({placeholders})",
                        list(fts_uuids),
                    ).fetchall()
                    entries = [_row_to_dict(row) for row in rows]
            except (sqlite3.OperationalError, sqlite3.DatabaseError):
                # FTS not available or query malformed, fall back to Python search
                entries = _load_all()
        else:
            # For non-full_text, still use Python search (simpler logic)
            entries = _load_all()
    finally:
        conn.close()
    
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
        "semantika": semantika,
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
    recovered = _repair_latex_controls_in_math(text)
    lines = recovered.replace("\r\n", "\n").replace("\r", "\n").split("\n")
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


def _repair_latex_controls_in_math(text: str) -> str:
    """Recover LaTeX control sequences in math spans.

    This is robust against TOML-consumed escapes (e.g. \\text -> tab + 'ext').
    It is applied both at parse-time and render-time so legacy stored entries are
    also displayed correctly without requiring data migration.
    """
    if not text:
        return ""

    tokens = (
        "theta",
        "varepsilon",
        "epsilon",
        "alpha",
        "beta",
        "gamma",
        "delta",
        "lambda",
        "mu",
        "pi",
        "sigma",
        "phi",
        "psi",
        "omega",
        "frac",
        "sqrt",
        "sum",
        "int",
        "widehat",
        "overrightarrow",
        "rightarrow",
        "to",
        "text",
        "Longleftrightarrow",
        "exists",
        "mathbb",
        "lim",
        "in",
    )

    def _repair_chunk(chunk: str) -> str:
        repaired = chunk
        for token in tokens:
            repaired = re.sub(
                rf"(?<!\\)(?<![A-Za-z]){token}(\b|_)",
                rf"\\{token}\1",
                repaired,
            )
        # Recover consumed escapes (\t, \f, \r, \v, \b, \a) inside math chunks.
        for token in tokens:
            tail = token[1:]
            repaired = re.sub(
                rf"[\t\f\r\v\x08\x07]{tail}(\b|_)",
                rf"\\{token}\1",
                repaired,
            )
        return repaired

    recovered = re.sub(
        r"\$\$.*?\$\$",
        lambda m: _repair_chunk(m.group(0)),
        text,
        flags=re.DOTALL,
    )
    return re.sub(
        r"(?<!\\)\$(?!\$)[^\n$]*(?<!\\)\$",
        lambda m: _repair_chunk(m.group(0)),
        recovered,
    )


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
        "Kontrolu kampnomojn: terminologio.xx, difino.xx, superklaso, "
        "ligilo, fonto, semantika.",
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
    if line.strip().endswith("=") and "invalid value" in lowered and dotted_key_like:
        hints.append(
            'Por plurlinia teksto (`"""`), metu la malferman `"""` sur la '
            'sama linio kiel `=` (ekz. difino.fr = """...).'
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
            raise ValueError(f"Nevalida .enc: nekonata kampo '{key}'.{suggestion}")


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
                difinoj[str(lang).strip().lower()] = (
                    str(value).strip().replace("\\n", "\n")
                )
    difino_obj = data.get("difino")
    if not difinoj and isinstance(difino_obj, dict):
        for lang, value in difino_obj.items():
            if str(value).strip():
                difinoj[str(lang).strip().lower()] = (
                    str(value).strip().replace("\\n", "\n")
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
    runtime_map = _runtime_semantika_alias_map()
    return runtime_map.get(value.lower(), value)


def _is_known_semantika_ligilo(raw: str | None) -> bool:
    normalized = _normalize_semantika_ligilo(raw)
    return bool(normalized and normalized in _runtime_known_semantika_ligiloj())


def _reverse_semantika_ligilo(raw: str | None) -> str | None:
    raw_lower = str(raw or "").strip().lower()
    if raw_lower == "rdfs:superclassof":
        return "rdfs:subClassOf"
    rel = _normalize_semantika_ligilo(raw)
    reverse_map: dict[str, str | None] = {
        "rdfs:subClassOf": "rdfs:hasSubClass",
        "rdfs:superClassOf": "rdfs:subClassOf",
        "rdfs:hasSubClass": "rdfs:subClassOf",
        "rdf:type": "rdf:hasInstance",
        "rdf:hasInstance": "rdf:type",
        "wdt:P361": "wdt:P527",
        "wdt:P527": "wdt:P361",
        # Symmetric relations keep the same semantic arc both directions.
        "owl:disjointWith": "owl:disjointWith",
        "owl:inverseOf": "owl:inverseOf",
        "wdt:P26": "wdt:P26",
    }
    if rel in reverse_map:
        return reverse_map[rel]
    if rel in _runtime_known_semantika_ligiloj():
        # Known directional properties without an explicit inverse in our
        # supported set should not self-reverse semantically.
        return None
    return rel


def _directional_semantic_family(rel: str | None) -> set[str]:
    normalized = _normalize_semantika_ligilo(rel)
    if normalized in {"rdf:type", "rdf:hasInstance"}:
        return {"rdf:type", "rdf:hasInstance"}
    if normalized in {"rdfs:subClassOf", "rdfs:superClassOf", "rdfs:hasSubClass"}:
        return {"rdfs:subClassOf", "rdfs:superClassOf", "rdfs:hasSubClass"}
    if normalized in {"wdt:P361", "wdt:P527"}:
        return {"wdt:P361", "wdt:P527"}
    return {normalized} if normalized else set()


def _load_auto_reverse_pairs(entry: dict) -> set[tuple[str, str | None]]:
    datumo = entry.get("datumo") if isinstance(entry.get("datumo"), dict) else {}
    raw = datumo.get(_AUTO_REVERSE_DATUMO_KEY) if isinstance(datumo, dict) else None
    items = _normalize_ligilo_items(raw or [])
    return {
        (str(item.get("uuid") or ""), _normalize_semantika_ligilo(item.get("tipo")))
        for item in items
        if str(item.get("uuid") or "")
    }


def _save_auto_reverse_pairs(entry: dict, pairs: set[tuple[str, str | None]]) -> None:
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


def _reconcile_all_semantic_reverse_links() -> None:
    all_entries = _load_all_unsorted()
    changed: dict[str, dict] = {}
    expected_by_target: dict[str, set[tuple[str, str | None]]] = {}

    for source in all_entries:
        source_uuid = str(source.get("uuid") or "")
        if not source_uuid:
            continue
        for item in _normalize_ligilo_items(source.get("ligilo") or []):
            target = _find_by_uuid(str(item.get("uuid") or ""))
            if target is None:
                continue
            target_uuid = str(target.get("uuid") or "")
            reverse_sem = _reverse_semantika_ligilo(item.get("tipo"))
            expected_by_target.setdefault(target_uuid, set()).add(
                (source_uuid, reverse_sem)
            )

    for target in all_entries:
        target_uuid = str(target.get("uuid") or "")
        if not target_uuid:
            continue
        expected_pairs = expected_by_target.get(target_uuid, set())
        auto_pairs = _load_auto_reverse_pairs(target)
        target_items_original = _normalize_ligilo_items(target.get("ligilo") or [])
        manual_pairs = {
            (
                str(item.get("uuid") or ""),
                _normalize_semantika_ligilo(item.get("tipo")),
            )
            for item in target_items_original
            if (
                str(item.get("uuid") or ""),
                _normalize_semantika_ligilo(item.get("tipo")),
            )
            not in auto_pairs
        }
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
            cleaned_items: list[dict[str, str | None]] = []
            for item in target_items:
                item_uuid = str(item.get("uuid") or "")
                item_sem = _normalize_semantika_ligilo(item.get("tipo"))
                if item_uuid != source_uuid:
                    cleaned_items.append(item)
                    continue
                if family and item_sem not in family:
                    cleaned_items.append(item)
                    continue
                if not family and item_sem != reverse_sem:
                    cleaned_items.append(item)
                    continue
            target_items = cleaned_items
            target_items.append({"uuid": source_uuid, "tipo": reverse_sem})

        original_serialized = _serialize_ligilo_items(target_items_original)
        reconciled_serialized = _serialize_ligilo_items(target_items)
        final_auto_pairs = {pair for pair in expected_pairs if pair not in manual_pairs}
        if (
            original_serialized != reconciled_serialized
            or auto_pairs != final_auto_pairs
        ):
            target["ligilo"] = reconciled_serialized
            _save_auto_reverse_pairs(target, final_auto_pairs)
            target["modifita_je"] = now_iso()
            changed[target_uuid] = target

    for updated in changed.values():
        _update_entry(updated)


def _public_datumo(entry: dict) -> dict:
    data = entry.get("datumo")
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if k != _AUTO_REVERSE_DATUMO_KEY}


def _public_ligilo_items(entry: dict) -> list[dict[str, str | None]]:
    ligilo_items = _display_ligilo_items(entry)
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
        if sem in {"rdfs:subClassOf", "rdfs:superClassOf", "rdfs:hasSubClass"} and (
            (target_uuid, "rdfs:subClassOf") in source_pairs
            and (
                (target_uuid, "rdfs:superClassOf") in source_pairs
                or (target_uuid, "rdfs:hasSubClass") in source_pairs
            )
        ):
            title = _resolve_uuid_to_title(target_uuid)
            conflicts.append(
                "- Kontraŭdiro inter rdfs:subClassOf kaj rdfs:hasSubClass "
                f"al {title} "
                f"(#{target_uuid[:8]}). Sugesto: konservu nur unu direkton."
            )

        target_entry = by_uuid.get(target_uuid)
        if target_entry is None:
            continue
        reverse_links = _normalize_ligilo_items(target_entry.get("ligilo") or [])
        has_same_back = False
        for item in reverse_links:
            raw_back_ref = str(item.get("uuid") or "")
            resolved_back = _find_by_uuid(raw_back_ref)
            back_uuid = (
                str(resolved_back.get("uuid") or "") if resolved_back else raw_back_ref
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
                "rdfs:hasSubClass."
            )
        elif sem in {"rdfs:superClassOf", "rdfs:hasSubClass"}:
            conflicts.append(
                f"- Logika konflikto: #{source_uuid[:8]} kaj #{target_uuid[:8]} ambaŭ "
                "uzas rdfs:hasSubClass. Sugesto: en la kontraŭa direkto uzu "
                "rdfs:subClassOf."
            )
    return sorted(set(conflicts))


def _raise_if_malformed_entry(entry: dict) -> None:
    """Reject entries that look corrupted or malformed.
    
    Detects incomplete or corrupted entries from failed AI generation
    that have suspicious patterns with no meaningful definition.
    """
    titolo = str(entry.get("titolo") or "").strip()
    difino = str(entry.get("difino") or {}).strip()

    # Pattern: "Fonto-<hash> [<something>](#<fragment>)" with NO definition
    # indicates incomplete or corrupted generation (AI reasoning leakage)
    if (
        re.match(r"^Fonto-[a-f0-9]{8}\s+\[[^\]]+\]\(#[a-f0-9]+\)$", titolo)
        and not difino
    ):
        raise ValueError(
            "Nevalida nodo-titolo: aspektas kiel ne-kompleta aŭ ĉena-pensado eligo. "
            "Certigu ke la .enc dosiero estas valida."
        )


def _raise_if_semantic_conflicts(entry: dict, *, strict: bool = True) -> None:
    if not strict:
        _reconcile_all_semantic_reverse_links()
    conflicts = _semantic_conflicts_for_entry(entry, _load_all())
    if not conflicts:
        return
    typer.echo("Semantika logika konflikto trovita en ligilo:", err=True)
    for line in conflicts:
        typer.echo(line, err=True)
    typer.echo(_semantika_help_hint(), err=True)
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
        cleaned = _canonicalize_superklaso_ref(raw)
        return [cleaned] if cleaned else []
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        if isinstance(item, str):
            cleaned = _canonicalize_superklaso_ref(item)
            if cleaned:
                out.append(cleaned)
            continue
        if isinstance(item, list):
            first_raw = str(item[0]) if item else ""
            second_raw = str(item[1]) if len(item) >= 2 else ""
            first_clean = _canonicalize_superklaso_ref(first_raw)
            second_clean = _canonicalize_superklaso_ref(second_raw)
            first_sem = _is_known_semantika_ligilo(
                _normalize_semantika_ligilo(first_raw)
            )
            second_sem = _is_known_semantika_ligilo(
                _normalize_semantika_ligilo(second_raw)
            )

            candidate = ""
            if second_sem and first_clean:
                candidate = first_clean
            elif first_sem and second_clean:
                candidate = second_clean
            elif first_clean and second_clean:
                first_resolved = _find_by_uuid(first_clean) is not None
                second_resolved = _find_by_uuid(second_clean) is not None
                if first_resolved and not second_resolved:
                    candidate = first_clean
                elif second_resolved and not first_resolved:
                    candidate = second_clean
                elif _looks_like_uuid_ref(second_raw):
                    candidate = second_clean
                elif _looks_like_uuid_ref(first_raw):
                    candidate = first_clean
                else:
                    # Legacy .enc exported this pair as [Titolo, UUID].
                    candidate = second_clean
            else:
                if second_clean:
                    candidate = second_clean
                elif first_clean:
                    candidate = first_clean
                else:
                    for raw_part in item[2:]:
                        normalized_part = _canonicalize_superklaso_ref(str(raw_part))
                        if normalized_part:
                            candidate = normalized_part
                            break
            if candidate:
                out.append(candidate)
    return _normalize_uuid_list(out)


def _merge_superklaso_into_ligilo(superklaso: list[str], ligilo: list) -> list:
    items = _normalize_ligilo_items(ligilo)
    for parent_ref in _normalise_superklaso_refs(superklaso):
        has_pair = any(
            str(item.get("uuid") or "") == parent_ref
            and _normalize_semantika_ligilo(item.get("tipo")) == "rdfs:subClassOf"
            for item in items
        )
        if not has_pair:
            items.append({"uuid": parent_ref, "tipo": "rdfs:subClassOf"})
    return _serialize_ligilo_items(items)


def _canonicalize_class_alias_fields(entry: dict) -> dict:
    superklaso = _normalise_superklaso_refs(entry.get("superklaso") or [])
    ligilo = _serialize_ligilo_items(_normalize_ligilo_items(entry.get("ligilo") or []))
    entry["ligilo"] = _merge_superklaso_into_ligilo(superklaso, ligilo)
    entry["superklaso"] = []
    return entry


def _build_class_relation_maps(
    all_entries: list[dict],
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    by_uuid = {str(e.get("uuid") or ""): e for e in all_entries if e.get("uuid")}

    def _resolve_ref(ref: str) -> str:
        token = _clean_uuid_ref(ref)
        if not token:
            return ""
        if token in by_uuid:
            return token
        matches = [uid for uid in by_uuid if uid.startswith(token)]
        if len(matches) == 1:
            return matches[0]
        return ""

    parents_of: dict[str, set[str]] = {uid: set() for uid in by_uuid}
    children_of: dict[str, set[str]] = {uid: set() for uid in by_uuid}

    for entry in all_entries:
        uid = str(entry.get("uuid") or "")
        if not uid:
            continue

        for parent_ref in _normalise_superklaso_refs(entry.get("superklaso") or []):
            parent_uuid = _resolve_ref(parent_ref)
            if not parent_uuid:
                continue
            parents_of.setdefault(uid, set()).add(parent_uuid)
            children_of.setdefault(parent_uuid, set()).add(uid)

        for item in _normalize_ligilo_items(entry.get("ligilo") or []):
            sem = _normalize_semantika_ligilo(item.get("tipo"))
            target_uuid = _resolve_ref(str(item.get("uuid") or ""))
            if not target_uuid:
                continue
            if sem == "rdfs:subClassOf":
                parents_of.setdefault(uid, set()).add(target_uuid)
                children_of.setdefault(target_uuid, set()).add(uid)
            elif sem in {"rdfs:hasSubClass", "rdfs:superClassOf"}:
                parents_of.setdefault(target_uuid, set()).add(uid)
                children_of.setdefault(uid, set()).add(target_uuid)
    return parents_of, children_of


def _normalize_ligilo_items(raw: list | str) -> list[dict[str, str | None]]:
    normalized = _normalise_uuids(raw)
    items: list[dict[str, str | None]] = []
    for item in normalized:
        if isinstance(item, str):
            canonical_ref = _canonicalize_ligilo_ref(item)
            if canonical_ref:
                items.append({"uuid": canonical_ref, "tipo": None})
        elif isinstance(item, list) and item:
            uuid_ref = _canonicalize_ligilo_ref(str(item[0]))
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


def _display_ligilo_items(
    entry_or_ligilo: dict | list | str,
) -> list[dict[str, str | None]]:
    if isinstance(entry_or_ligilo, dict):
        raw_ligilo = _merge_superklaso_into_ligilo(
            _normalise_superklaso_refs(entry_or_ligilo.get("superklaso") or []),
            _serialize_ligilo_items(
                _normalize_ligilo_items(entry_or_ligilo.get("ligilo") or [])
            ),
        )
    else:
        raw_ligilo = entry_or_ligilo
    raw_items = _normalize_ligilo_items(raw_ligilo)
    deduped: list[dict[str, str | None]] = []
    seen: set[tuple[str, str | None]] = set()
    for item in raw_items:
        raw_uuid = str(item.get("uuid") or "")
        resolved = _find_by_uuid(raw_uuid)
        canonical_uuid = str(resolved.get("uuid") or "") if resolved else raw_uuid
        sem = _normalize_semantika_ligilo(item.get("tipo"))
        key = (canonical_uuid, sem)
        if key in seen:
            continue
        seen.add(key)
        deduped.append({"uuid": canonical_uuid, "tipo": sem})
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
    raw_ref = str(uuid or "").strip()
    if raw_ref.lower().startswith("vt#"):
        vorto_ref = raw_ref[3:].lstrip("#")
        target = _find_vorto_by_uuid(vorto_ref)
        if target:
            return str(target.get("teksto") or f"vt#{vorto_ref[:8]}")
        return f"vt#{vorto_ref[:8]}"
    if raw_ref.lower().startswith("ec#"):
        raw_ref = raw_ref[3:]
    normalized_uuid = raw_ref.lstrip("#")
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
            uuid_part = _canonicalize_ligilo_ref(uuid_part)
            tipo_norm = _normalize_semantika_ligilo(tipo_part)
            if tipo_part.strip() and not _is_known_semantika_ligilo(tipo_norm):
                raise ValueError(
                    f"Nevalida semantika ligilo: {tipo_part.strip()!r}. "
                    f"{_semantika_help_hint()}"
                )
            if uuid_part:
                items.append({"uuid": uuid_part, "tipo": tipo_norm})
        else:
            uuid_part = _canonicalize_ligilo_ref(token)
            if uuid_part:
                items.append({"uuid": uuid_part, "tipo": None})
    return _serialize_ligilo_items(items)


def _extract_markdown_ligilo_refs(text: str) -> list[dict[str, str | None]]:
    refs: list[dict[str, str | None]] = []
    for match in re.finditer(
        r"\[[^\]]+\]\(((?:#|[eE][cC]#|[vV][tT]#)[^)]+)\)",
        text or "",
    ):
        raw = match.group(1).strip()
        if not raw:
            continue
        first, sep, second = raw.partition(",")
        uuid_raw = first.strip()
        if not uuid_raw:
            continue
        sem = _normalize_semantika_ligilo(second.strip()) if sep else None
        resolved_ref = _canonicalize_ligilo_ref(uuid_raw)
        if not resolved_ref:
            continue
        if not resolved_ref.lower().startswith("vt#"):
            target = _find_by_uuid(resolved_ref)
            if target is not None:
                resolved_ref = str(target.get("uuid") or resolved_ref)
        refs.append({"uuid": resolved_ref, "tipo": sem})
    return refs


def _extract_markdown_ligilo_refs_from_payload(
    payload: object,
) -> list[dict[str, str | None]]:
    refs: list[dict[str, str | None]] = []
    if isinstance(payload, str):
        refs.extend(_extract_markdown_ligilo_refs(payload))
        return refs
    if isinstance(payload, list):
        for item in payload:
            refs.extend(_extract_markdown_ligilo_refs_from_payload(item))
        return refs
    if isinstance(payload, dict):
        for value in payload.values():
            refs.extend(_extract_markdown_ligilo_refs_from_payload(value))
    return refs


def _extract_auto_ligilo_refs(parsed: dict) -> list[dict[str, str | None]]:
    refs: list[dict[str, str | None]] = []
    for key, value in parsed.items():
        if key in {"ligilo", "superklaso"}:
            continue
        refs.extend(_extract_markdown_ligilo_refs_from_payload(value))
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


def _validate_semantic_links(parsed: dict) -> list[str]:
    """Validate all semantic links in parsed entry.
    
    Returns list of unresolved link UUIDs that failed to resolve.
    Only validates ligilo fields, not display fields like terminologio/difinio.
    """
    unresolved = []
    # Only validate ligilo field which contains actual semantic links
    ligilo_items = _normalize_ligilo_items(parsed.get("ligilo") or [])
    for item in ligilo_items:
        uuid_str = item.get("uuid") or ""
        if not uuid_str:
            continue
        # Check if this is a vorto reference
        if str(uuid_str).lower().startswith("vt#"):
            # For vorto, we skip validation (external reference)
            continue
        # For encik references, validate they exist
        clean_uuid = _clean_uuid_ref(str(uuid_str))
        if not clean_uuid:
            unresolved.append(str(uuid_str))
            continue
        target = _find_by_uuid(clean_uuid)
        if target is None:
            unresolved.append(clean_uuid)
    return unresolved


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
        for parent_ref in _normalise_superklaso_refs(source.get("superklaso") or []):
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


def _sync_bidirectional_relations_for_entry(
    entry: dict, *, previous_ligilo: list | None = None
) -> None:
    """Keep ligilo/superklaso relationships consistent in both directions.

    - A.ligilo contains B  => B.ligilo contains A
    - B.superklaso contains A => A has B as subklaso (derived in display/search)
      and we ensure parent references are normalized.
    """
    all_entries = _load_all_unsorted()
    by_uuid = {e["uuid"]: e for e in all_entries}
    current = by_uuid.get(entry["uuid"])
    if current is None:
        return

    def _resolve_ref(raw_ref: str) -> str:
        token = _clean_uuid_ref(raw_ref)
        if not token:
            return ""
        if token in by_uuid:
            return token
        matches = [uid for uid in by_uuid if uid.startswith(token)]
        if len(matches) == 1:
            return matches[0]
        return token

    changed: list[dict] = []
    current_lig_items = [
        {"uuid": _resolve_ref(str(item.get("uuid") or "")), "tipo": item.get("tipo")}
        for item in _normalize_ligilo_items(current.get("ligilo") or [])
        if _resolve_ref(str(item.get("uuid") or ""))
    ]
    current_lig_items = _normalize_ligilo_items(
        _serialize_ligilo_items(current_lig_items)
    )
    current_sup = [
        resolved
        for raw in _normalise_superklaso_refs(current.get("superklaso") or [])
        if (resolved := _resolve_ref(raw))
    ]
    current["ligilo"] = _serialize_ligilo_items(current_lig_items)
    current["superklaso"] = current_sup
    current["modifita_je"] = now_iso()
    changed.append(current)
    current_pairs = {
        (
            str(item.get("uuid") or ""),
            _normalize_semantika_ligilo(item.get("tipo")),
        )
        for item in current_lig_items
        if str(item.get("uuid") or "")
    }
    removed_pairs: set[tuple[str, str | None]] = set()
    if previous_ligilo is not None:
        previous_items = [
            {
                "uuid": _resolve_ref(str(item.get("uuid") or "")),
                "tipo": item.get("tipo"),
            }
            for item in _normalize_ligilo_items(previous_ligilo)
            if _resolve_ref(str(item.get("uuid") or ""))
        ]
        for item in previous_items:
            key = (
                str(item.get("uuid") or ""),
                _normalize_semantika_ligilo(item.get("tipo")),
            )
            if key[0] and key not in current_pairs:
                removed_pairs.add(key)

    # Bidirectional ligilo with semantic inverse mapping where needed
    for item in current_lig_items:
        other_ref = _resolve_ref(str(item.get("uuid") or ""))
        sem = _normalize_semantika_ligilo(item.get("tipo"))
        reverse_sem = _reverse_semantika_ligilo(sem)
        other = by_uuid.get(other_ref) or _find_by_uuid(other_ref)
        if other is None:
            continue
        other_lig_items = _normalize_ligilo_items(other.get("ligilo") or [])
        if not any(
            str(x.get("uuid") or "") == current["uuid"]
            and _normalize_semantika_ligilo(x.get("tipo")) == reverse_sem
            for x in other_lig_items
        ):
            other_lig_items.append({"uuid": current["uuid"], "tipo": reverse_sem})
            auto_pairs = _load_auto_reverse_pairs(other)
            auto_pairs.add((current["uuid"], reverse_sem))
            _save_auto_reverse_pairs(other, auto_pairs)
            other["ligilo"] = _serialize_ligilo_items(other_lig_items)
            other["modifita_je"] = now_iso()
            changed.append(other)

    # Remove stale auto-managed reverse links for relations removed from current.
    for other_uuid, sem in removed_pairs:
        reverse_sem = _reverse_semantika_ligilo(sem)
        other = by_uuid.get(other_uuid) or _find_by_uuid(other_uuid)
        if other is None:
            continue
        auto_pairs = _load_auto_reverse_pairs(other)
        auto_key = (current["uuid"], reverse_sem)
        if auto_key not in auto_pairs:
            continue
        other_lig_items = _normalize_ligilo_items(other.get("ligilo") or [])
        filtered_items = [
            item
            for item in other_lig_items
            if not (
                str(item.get("uuid") or "") == current["uuid"]
                and _normalize_semantika_ligilo(item.get("tipo")) == reverse_sem
            )
        ]
        if len(filtered_items) == len(other_lig_items):
            auto_pairs.discard(auto_key)
            _save_auto_reverse_pairs(other, auto_pairs)
            continue
        auto_pairs.discard(auto_key)
        _save_auto_reverse_pairs(other, auto_pairs)
        other["ligilo"] = _serialize_ligilo_items(filtered_items)
        other["modifita_je"] = now_iso()
        changed.append(other)

    # Normalize parent links (superklaso only stores UUID refs)
    for parent_ref in current_sup:
        parent = _find_by_uuid(parent_ref)
        if parent is None:
            continue
        # touch parent timestamp only when relation exists for visibility freshness
        parent["modifita_je"] = now_iso()
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
    all_entries = _load_all()
    class_parents_map, class_children_map = _build_class_relation_maps(all_entries)

    if montri_cxion and terminologio:
        panel_lines.append(f"  [dim]{'terminologio:':<14}[/dim]")
        for lang, term in sorted(terminologio.items()):
            panel_lines.append(f"    {lang}: {_render_markdown_text(term)}")

    difinio = (
        difinoj.get(selected_lang)
        or entry.get("difinio", "")
        or next(iter(difinoj.values()), "")
    ).strip()
    needs_browser_for_difino = _has_non_cli_renderable_markup(difinio)
    needs_browser_for_enhavo = _has_non_cli_renderable_markup(
        (entry.get("enhavo") or "").strip()
    )
    fallback_path: str | None = None

    def _browser_fallback_link() -> str:
        nonlocal fallback_path
        if fallback_path is None:
            fallback_html = _render_entry_html(
                entry, lingvo=selected_lang, link_depth=1
            )
            fallback_path = _write_html_document(fallback_html)
        return (
            f"[link=file://{fallback_path}]Malfermu en retumilo por KaTeX/bildoj[/link]"
        )

    if montri_cxion and difinoj:
        panel_lines.append(f"  [dim]{'difino:':<14}[/dim]")
        for lang, term_def in sorted(difinoj.items()):
            if _has_non_cli_renderable_markup(term_def):
                panel_lines.append(f"    {lang}: {_browser_fallback_link()}")
            else:
                panel_lines.append(f"    {lang}: {_render_markdown_text(term_def)}")
    elif difinio:
        panel_lines.append(f"  [dim]{'difino:':<14}[/dim]")
        if needs_browser_for_difino:
            panel_lines.append(f"    {_browser_fallback_link()}")
        else:
            for ln in difinio.splitlines():
                panel_lines.append(f"    {_render_markdown_text(ln)}")

    enhavo = (entry.get("enhavo") or "").strip()
    if enhavo and montri_cxion:
        panel_lines.append(f"  [dim]{'enhavo:':<14}[/dim]")
        if needs_browser_for_enhavo:
            panel_lines.append(f"    {_browser_fallback_link()}")
        else:
            for ln in enhavo.splitlines():
                panel_lines.append(f"    {_render_markdown_text(ln)}")

    if montri_cxion:
        sub = _subklasoj_of(entry["uuid"], max_depth=1)
        if sub:
            panel_lines.append(f"  [dim]{'subklaso:':<14}[/dim]")
            for child in sub:
                panel_lines.append(
                    f"    {child['titolo']}  [dim]#{child['uuid'][:8]}[/dim]"
                )

    ligilo_items = _display_ligilo_items(entry)
    if ligilo_items:
        grouped_ligilo: dict[str, dict[str, object]] = {}
        for item in ligilo_items:
            uuid = str(item.get("uuid") or "")
            if not uuid:
                continue
            sem = _normalize_semantika_ligilo(item.get("tipo"))
            group = grouped_ligilo.setdefault(
                uuid,
                {"sems": set(), "has_plain": False},
            )
            if sem:
                sems = group["sems"]
                if isinstance(sems, set):
                    sems.add(sem)
            else:
                group["has_plain"] = True

        rank_map = {
            "rdf:type": 0,
            "rdfs:subClassOf": 1,
            "owl:inverseOf": 2,
            "owl:disjointWith": 3,
        }

        def _sem_display_value(sem_value: str, target_uuid: str) -> str:
            sem_norm = _normalize_semantika_ligilo(sem_value)
            if sem_norm in {"rdfs:subClassOf", "rdfs:superClassOf", "rdfs:hasSubClass"}:
                current_uid = str(entry.get("uuid") or "")
                parents = class_parents_map.get(current_uid, set())
                children = class_children_map.get(current_uid, set())
                if target_uuid in children and target_uuid not in parents:
                    sem_norm = "rdfs:hasSubClass"
                elif target_uuid in parents:
                    sem_norm = "rdfs:subClassOf"
            return sem_norm or sem_value

        def _group_sort_key(target_uuid: str) -> tuple[int, tuple[str, str]]:
            group = grouped_ligilo[target_uuid]
            sems = group["sems"]
            sem_values = sorted(sems) if isinstance(sems, set) else []
            rank = min((rank_map.get(sem, 4) for sem in sem_values), default=4)
            title = _resolve_uuid_to_title(target_uuid)
            return (rank, _proper_noun_sort_key(title))

        sorted_uuids = sorted(grouped_ligilo, key=_group_sort_key)
        panel_lines.append(f"  [dim]{'ligilo:':<14}[/dim]")
        for uuid in sorted_uuids:
            group = grouped_ligilo[uuid]
            linked_title = _resolve_uuid_to_title(uuid)
            line = _render_relation_cli_link(linked_title, uuid)
            sems = group["sems"]
            sem_values = sorted(sems) if isinstance(sems, set) else []
            sem_display = [_sem_display_value(sem, uuid) for sem in sem_values]
            sem_display_sorted = sorted(
                sem_display,
                key=lambda sem: (rank_map.get(sem, 4), sem),
            )
            if sem_display_sorted:
                sem_prefix = ", ".join(sem_display_sorted)
                line = f"[dim]{sem_prefix}[/dim] {line}"
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
                parts.append(f"noto={json.dumps(note_text, ensure_ascii=False)}")
            if s.get("ligilo"):
                parts.append(f"ligilo={_render_markdown_text(str(s['ligilo']))}")
            title_lang_items = sorted(
                (k, v) for k, v in s.items() if k.startswith("titolo.")
            )
            for k, v in title_lang_items:
                val_text = _render_markdown_text(str(v))
                parts.append(f"{k}={json.dumps(val_text, ensure_ascii=False)}")
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
            panel_lines.append(f'    "{text}"{suffix}')
        if should_show_hint and not montri_cxion:
            panel_lines.append(f"    [dim]{_language_preference_hint()}[/dim]")

    semantika = _normalize_semantika_valoroj(entry.get("semantika"))
    if semantika:
        panel_lines.append(f"  [dim]{'semantika:':<14}[/dim]")
        semantika_priskriboj = _runtime_semantika_description_map()
        for item in semantika:
            tipo = str(item.get("tipo") or "")
            arko = str(item.get("arko") or "").strip()
            canonical_arko = _normalize_semantika_ligilo(arko) or arko
            priskribo = semantika_priskriboj.get(canonical_arko, canonical_arko)
            rendered_value = _format_semantika_valoro(
                item.get("valoro"), tipo=tipo, markdown=True
            )
            rendered_unuo = _format_semantika_unuo_cli(item)
            rendered_priskribo = _render_markdown_text(priskribo)
            if rendered_unuo:
                panel_lines.append(
                    f"    {rendered_priskribo} {rendered_value} {rendered_unuo}"
                )
            else:
                panel_lines.append(f"    {rendered_priskribo} {rendered_value}")

    datumo = entry.get("datumo") or {}
    datumo = _public_datumo(entry)
    if datumo:
        panel_lines.append(f"  [dim]{'datumo:':<14}[/dim]")
        for ds_name, payload in sorted(datumo.items()):
            rows = payload.get("datumo") if isinstance(payload, dict) else None
            row_count = len(rows) if isinstance(rows, list) else 0
            panel_lines.append(f"    {ds_name}: {row_count} vico(j)")

    # Display linked manuals (manlibro(j))
    manuals = get_manuals_for_encik(entry["uuid"])
    if manuals:
        manlibro_label = "manlibro(j):" if len(manuals) == 1 else "manlibro(j):"
        panel_lines.append(f"  [dim]{manlibro_label:<14}[/dim]")
        for manual in manuals:
            manual_uuid = str(manual.get("uuid", ""))[:8]
            manual_title = str(manual.get("titolo", ""))
            panel_lines.append(f"    {manual_title}  [dim]#{manual_uuid}[/dim]")

    if montri_cxion:
        kj = entry.get("kreita_je", "")[:10]
        mj = entry.get("modifita_je", "")[:10]
        panel_lines.append(f"  [dim]{'kreita_je:':<14}[/dim] {kj}")
        panel_lines.append(f"  [dim]{'modifita_je:':<14}[/dim] {mj}")

    display_title = _render_markdown_text(title)
    spacing = max(0, int(_load_encik_montrado_settings().get("spaco", 0)))
    if spacing > 0:
        spaced_lines: list[str] = []
        seen_section = False
        for line in panel_lines:
            is_section = line.strip().startswith("[dim]") and ":" in line
            if is_section and seen_section:
                spaced_lines.extend([""] * spacing)
            if is_section:
                seen_section = True
            spaced_lines.append(line)
        panel_body = "\n".join(spaced_lines)
    else:
        panel_body = "\n".join(panel_lines)
    console.print(
        Panel(
            panel_body,
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
        ref_token = raw_ref.split(",", 1)[0].strip()
        if ref_token.lower().startswith("vt#"):
            vorto_ref = ref_token[3:].lstrip("#")
            target = _find_vorto_by_uuid(vorto_ref)
            if not target:
                return f"{label} (vt#{vorto_ref[:8]})"
            short_uuid = str(target.get("uuid") or "")[:8]
            return f"{label} (vt#{short_uuid})"
        if ref_token.lower().startswith("ec#"):
            ref_token = ref_token[3:]
        ref = ref_token.lstrip("#")
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

    rendered = re.sub(
        r"\[([^\]]+)\]\(((?:#|[eE][cC]#|[vV][tT]#)[^)]+)\)",
        _replace_internal,
        text,
    )
    rendered = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", _replace_external, rendered)
    rendered = re.sub(r"(\*\*|__|\*|_|`)", "", rendered)
    return rendered


def _has_non_cli_renderable_markup(text: str) -> bool:
    content = str(text or "")
    if not content.strip():
        return False
    if re.search(r"\$\$.*?\$\$", content, flags=re.DOTALL):
        return True
    if re.search(r"(?<!\\)\$(?!\$)[^\n$]*(?<!\\)\$", content):
        return True
    if re.search(r"!\[[^\]]*\]\([^)]+\)", content):
        return True
    if "<img" in content.lower():
        return True
    return False


def _strip_markdown_links(text: str) -> str:
    stripped = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", str(text or ""))
    return re.sub(r"(\*\*|__|\*|_|`)", "", stripped)


def _render_relation_cli_link(label: str, ref: str) -> str:
    """Render a clickable CLI relation link for an encik UUID reference."""
    raw_ref = str(ref or "").strip()
    is_vorto_ref = raw_ref.lower().startswith("vt#")
    if raw_ref.lower().startswith("ec#"):
        raw_ref = raw_ref[3:]
    normalized_ref = raw_ref[3:].lstrip("#") if is_vorto_ref else raw_ref.lstrip("#")
    target = (
        _find_vorto_by_uuid(normalized_ref)
        if is_vorto_ref
        else _find_by_uuid(normalized_ref)
    )
    short_ref = normalized_ref[:8]
    clean_label = _strip_markdown_links(str(label or "")).strip()
    if clean_label.startswith("##"):
        clean_label = "#" + clean_label.lstrip("#")
    if not is_vorto_ref and re.fullmatch(r"#?[0-9a-fA-F]{1,8}\*?", clean_label):
        clean_label = f"#{short_ref}"
    if is_vorto_ref:
        shown_label = clean_label or (str(target.get("teksto") or "") if target else "")
        if shown_label:
            return f"{shown_label} [dim]vt#{short_ref}[/dim]"
        return f"[dim]vt#{short_ref}[/dim]"
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
    return f"[link=file://{target_path}]{shown_label}[/link] [dim]#{short_target}[/dim]"


def _render_relation_html_link(label: str, ref: str, *, link_depth: int = 0) -> str:
    """Render an HTML relation link for an encik UUID reference."""
    raw_ref = str(ref or "").strip()
    is_vorto_ref = raw_ref.lower().startswith("vt#")
    if raw_ref.lower().startswith("ec#"):
        raw_ref = raw_ref[3:]
    normalized_ref = raw_ref[3:].lstrip("#") if is_vorto_ref else raw_ref.lstrip("#")
    target = (
        _find_vorto_by_uuid(normalized_ref)
        if is_vorto_ref
        else _find_by_uuid(normalized_ref)
    )
    short_ref = normalized_ref[:8]
    clean_label = _strip_markdown_links(str(label or "")).strip()
    if clean_label.startswith("##"):
        clean_label = "#" + clean_label.lstrip("#")
    if not is_vorto_ref and re.fullmatch(r"#?[0-9a-fA-F]{1,8}\*?", clean_label):
        clean_label = f"#{short_ref}"
    if is_vorto_ref:
        shown_label = clean_label or (str(target.get("teksto") or "") if target else "")
        if shown_label:
            return f"{escape(shown_label)} vt#{escape(short_ref)}"
        return f"vt#{escape(short_ref)}"
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
        f'<a href="file://{escape(target_path)}">#{escape(short_target)}</a>'
    )


def _markdown_to_html_fragment_with_links(md_text: str, *, link_depth: int = 0) -> str:
    if link_depth <= 0:
        md_text = _replace_internal_markdown_links_with_file_urls(md_text)
    md_text = _repair_latex_controls_in_math(md_text)
    try:
        import markdown  # type: ignore[import-untyped]
    except ImportError:
        return f"<pre>{escape(md_text)}</pre>"
    safe_text, math_chunks = _protect_math_segments(md_text)
    extensions = ["extra", "toc", "tables", "fenced_code", "codehilite"]
    try:
        html = markdown.markdown(safe_text, extensions=extensions)
    except Exception:
        html = markdown.markdown(safe_text)
    return _restore_math_segments(html, math_chunks)


def _protect_math_segments(text: str) -> tuple[str, list[str]]:
    chunks: list[str] = []

    def _reserve(match: re.Match[str]) -> str:
        chunks.append(match.group(0))
        return f"{_MATH_TOKEN_PREFIX}{len(chunks) - 1}END"

    protected = text
    for pattern in (
        re.compile(r"\$\$.*?\$\$", re.DOTALL),
        re.compile(r"\\\\\[.*?\\\\\]", re.DOTALL),
        re.compile(r"\\\\\(.*?\\\\\)", re.DOTALL),
        re.compile(r"(?<!\\)\$(?!\$)[^\n$]*(?<!\\)\$", re.DOTALL),
    ):
        protected = pattern.sub(_reserve, protected)
    return protected, chunks


def _restore_math_segments(html: str, chunks: list[str]) -> str:
    restored = html
    for idx, raw in enumerate(chunks):
        restored = restored.replace(f"{_MATH_TOKEN_PREFIX}{idx}END", raw)
    return restored


def _replace_internal_markdown_links_with_file_urls(md_text: str) -> str:
    if not md_text:
        return ""

    def _replace(match: re.Match[str]) -> str:
        label = match.group(1).strip()
        ref_token = match.group(2).strip().split(",", 1)[0].strip()
        if ref_token.lower().startswith("vt#"):
            vorto_ref = ref_token[3:].lstrip("#")
            target = _find_vorto_by_uuid(vorto_ref)
            if not target:
                return f"{label} (vt#{vorto_ref[:8]})"
            short_uuid = str(target.get("uuid") or "")[:8]
            return f"{label} (vt#{short_uuid})"
        if ref_token.lower().startswith("ec#"):
            ref_token = ref_token[3:]
        ref = ref_token.lstrip("#")
        target = _find_by_uuid(ref)
        if not target:
            return f"{label} (#{ref[:8]})"
        target_html = _render_entry_html(target, link_depth=1)
        target_path = _write_html_document(target_html)
        return f"[{label}](file://{target_path})"

    return re.sub(
        r"\[([^\]]+)\]\(((?:#|[eE][cC]#|[vV][tT]#)[^)]+)\)",
        _replace,
        md_text,
    )


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

    if montri_cxion:
        sub = _subklasoj_of(entry["uuid"], max_depth=1)
        if sub:
            sub_rows = "<br>".join(
                f"{escape(e['titolo'])} #{escape(e['uuid'][:8])}" for e in sub
            )
            rows.append(("subklaso", sub_rows))

    ligilo_items = _normalize_ligilo_items(entry.get("ligilo") or [])
    ligilo_items = sorted(ligilo_items, key=_ligilo_rank)
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
                parts.append(f'"{title_html}"')
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
                parts.append(f"{escape(k)}={val_html}")
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

    semantika = _normalize_semantika_valoroj(entry.get("semantika"))
    if semantika:
        sem_lines: list[str] = []
        for item in semantika:
            tipo = str(item.get("tipo") or "")
            arko = str(item.get("arko") or "")
            rendered = _format_semantika_valoro(item.get("valoro"), tipo=tipo)
            rendered_unuo = _format_semantika_unuo_html(item, link_depth=link_depth)
            if rendered_unuo:
                sem_lines.append(
                    f"{escape(tipo)} {escape(arko)} {escape(rendered)} {rendered_unuo}"
                )
            else:
                sem_lines.append(f"{escape(tipo)} {escape(arko)} {escape(rendered)}")
        rows.append(("semantika", "<br>".join(sem_lines)))

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
        "delimiters:[{left:'$$',right:'$$',display:true},{left:'$',right:'$',display:false},"
        "{left:'\\\\[',right:'\\\\]',display:true},{left:'\\\\(',right:'\\\\)',display:false}],"
        "throwOnError:false,strict:'ignore'"
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
        profile = _load_profile(quiet=True)
    except Exception:
        return [], True
    raw_langs = profile.get("lingvoj")
    if raw_langs is None:
        raw_langs = profile.get("lingvo")
    if isinstance(raw_langs, str):
        raw_items: list[object] = [part.strip() for part in raw_langs.split(",")]
    elif isinstance(raw_langs, list):
        raw_items = raw_langs
    else:
        return [], True
    valid: list[str] = []
    invalid_found = False
    for item in raw_items:
        code = str(item).strip().lower()
        if not code:
            continue
        if re.fullmatch(r"[a-z]{2}", code):
            if code not in valid:
                valid.append(code)
            continue
        invalid_found = True
    if not valid:
        return [], True
    return valid, invalid_found


def _terminal_has_light_background() -> bool:
    colorfgbg = str(os.environ.get("COLORFGBG") or "").strip()
    if not colorfgbg:
        return False
    parts = [part for part in re.split(r"[;:]", colorfgbg) if part]
    if not parts:
        return False
    try:
        bg = int(parts[-1])
    except ValueError:
        return False
    return bg in {7, 15} or bg >= 10


def _contrast_accent_style() -> str:
    """Return an accent color with improved contrast against terminal background."""
    return "blue" if _terminal_has_light_background() else "bright_cyan"


def _language_preference_hint() -> str:
    langs, _ = _load_user_language_preferences()
    ui_lang = langs[0] if langs and langs[0] in {"eo", "en", "fr"} else "eo"
    messages = {
        "eo": (
            "Konsilo: agordu lingvojn per "
            "uzanto profilo modifi -l eo,en,fr por personecigi citaĵojn."
        ),
        "en": (
            "Hint: set languages with "
            "uzanto profilo modifi -l eo,en,fr to personalize quote display."
        ),
        "fr": (
            "Astuce : définissez vos langues avec "
            "uzanto profilo modifi -l eo,en,fr pour personnaliser les citations."
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
    open_path_in_browser(tmp_path)
    return tmp_path


def _entry_user_locale_title(
    entry: dict, *, preferred_langs: list[str] | None = None
) -> str:
    language_order: list[str] = []
    if preferred_langs:
        for raw_code in preferred_langs:
            code = str(raw_code or "").strip().lower()
            if re.fullmatch(r"[a-z]{2}", code) and code not in language_order:
                language_order.append(code)
    else:
        profile_langs, _ = _load_user_language_preferences()
        for code in profile_langs:
            if code not in language_order:
                language_order.append(code)
        env_lang = (os.environ.get("LC_ALL") or os.environ.get("LANG") or "").split(
            "."
        )[0]
        env_lang = env_lang.split("_")[0].lower()
        if re.fullmatch(r"[a-z]{2}", env_lang) and env_lang not in language_order:
            language_order.append(env_lang)
    terms_obj = entry.get("terminologio")
    terms = terms_obj if isinstance(terms_obj, dict) else {}
    for code in language_order:
        candidate = str(terms.get(code) or "").strip()
        if candidate:
            return candidate
    eo_term = str(terms.get("eo") or "").strip()
    if eo_term:
        return eo_term
    en_term = str(terms.get("en") or "").strip()
    if en_term:
        return en_term
    title = str(entry.get("titolo") or "").strip()
    if title:
        return title
    for value in terms.values():
        text = str(value or "").strip()
        if text:
            return text
    return ""


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


def _print_candidates(
    candidates: list[dict], *, preferred_langs: list[str] | None = None
) -> None:
    table = Table(show_header=True, header_style="dim", box=None)
    table.add_column("#", style="dim", width=3)
    table.add_column("UUID", style="dim", width=10)
    table.add_column("Titolo")
    for i, e in enumerate(candidates, 1):
        display_title = _entry_user_locale_title(e, preferred_langs=preferred_langs)
        table.add_row(str(i), e["uuid"][:8], display_title)
    console.print(table)


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


def _copy_entry_reference(
    entry: dict,
    *,
    semantika: bool = False,
    preferred_langs: list[str] | None = None,
) -> None:
    entry_uuid = str(entry.get("uuid") or "")
    if not entry_uuid:
        typer.echo("Nevalida nodo: mankas UUID por kopii.", err=True)
        raise typer.Exit(code=1)
    short_ref = f"#{entry_uuid[:8]}"
    if semantika:
        display_title = _entry_user_locale_title(entry, preferred_langs=preferred_langs)
        display_title = _strip_title_disambiguation(display_title)
        payload = f"[{display_title}]({short_ref})"
        _copy_to_clipboard(payload, "Kopiis semantikan referencon al tondujo.")
        return
    _copy_to_clipboard(short_ref, f"Kopiis UUID al tondujo: {short_ref}")


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


def _resolve_entry(
    ref: str, *, interactive: bool = True, precise: bool = False
) -> dict | None:
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

    if precise:
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

    _, children_map = _build_class_relation_maps(all_entries)
    by_uuid = {str(e.get("uuid") or ""): e for e in all_entries if e.get("uuid")}

    visited: set[str] = {root_full_uuid}
    results: list[dict] = []
    queue: deque[tuple[str, int]] = deque([(root_full_uuid, 0)])

    while queue:
        current_uuid, depth = queue.popleft()
        if max_depth > 0 and depth >= max_depth:
            continue
        for child_uuid in sorted(children_map.get(current_uuid, set())):
            child = by_uuid.get(child_uuid)
            if child is None:
                continue
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

    all_entries = _load_all()
    parents_map, _ = _build_class_relation_maps(all_entries)
    by_uuid = {str(e.get("uuid") or ""): e for e in all_entries if e.get("uuid")}

    while queue:
        current_uuid, depth = queue.popleft()
        if max_depth > 0 and depth >= max_depth:
            continue
        for parent_uuid in sorted(parents_map.get(current_uuid, set())):
            parent = by_uuid.get(parent_uuid)
            if parent is None:
                continue
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
    parents_map, children_map = _build_class_relation_maps(all_entries)
    children_of: dict[str, list[str]] = {
        uid: sorted(children) for uid, children in children_map.items()
    }
    parents_of: dict[str, list[str]] = {
        uid: sorted(parents) for uid, parents in parents_map.items()
    }
    links_of: dict[str, list[str]] = {}
    for entry in all_entries:
        uid = str(entry.get("uuid") or "")
        if not uid:
            continue
        links = []
        for link_item in _normalize_ligilo_items(entry.get("ligilo") or []):
            if _normalize_semantika_ligilo(link_item.get("tipo")):
                continue
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
    semantic_pairs: set[tuple[str, str]] = {
        tuple(sorted((src, dst)))
        for src, dst, rel, sem in edges
        if rel == "ligilo" and _normalize_semantika_ligilo(sem)
    }
    if semantic_pairs:
        filtered_edges: list[tuple[str, str, str, str | None]] = []
        for src, dst, rel, sem in edges:
            if rel == "ligilo" and not _normalize_semantika_ligilo(sem):
                if tuple(sorted((src, dst))) in semantic_pairs:
                    continue
            filtered_edges.append((src, dst, rel, sem))
        edges = filtered_edges
    nodes = [by_uuid[uid] for uid in visited if uid in by_uuid]
    nodes.sort(key=lambda e: str(e.get("titolo") or "").lower())
    return nodes, edges


def _render_linked_graph_html(
    root: dict, nodes: list[dict], edges: list[tuple[str, str, str, str | None]]
) -> str:
    try:
        from pyvis.network import Network  # type: ignore[import-untyped]
    except ImportError:
        typer.echo(
            "Eraro: pako 'pyvis' ne instalita. Rulu: poetry add pyvis",
            err=True,
        )
        raise typer.Exit(code=1) from None

    env_lang = (os.environ.get("LC_ALL") or os.environ.get("LANG") or "").split(".")[0]
    env_lang = env_lang.split("_")[0].lower()

    def _graph_title(entry: dict) -> str:
        terms = entry.get("terminologio") or {}
        return (
            str(terms.get(env_lang) or "")
            or str(terms.get("eo") or "")
            or str(entry.get("titolo") or "")
            or str(entry.get("uuid") or "")[:8]
        )

    root_uuid = str(root.get("uuid") or "")
    net = Network(
        height="85vh",
        width="100%",
        directed=True,
        bgcolor="#111111",
        font_color="#e5e7eb",
        cdn_resources="remote",
    )
    net.barnes_hut(
        gravity=-14000,
        central_gravity=0.18,
        spring_length=95,
        spring_strength=0.06,
        damping=0.88,
    )
    net.toggle_physics(True)

    for entry in nodes:
        uid = str(entry.get("uuid") or "")
        title = _graph_title(entry)
        is_root = uid == root_uuid
        net.add_node(
            uid,
            label=title,
            title=f"{escape(title)}<br>#{uid[:8]}",
            color="#f5a524" if is_root else "#5dade2",
            size=24 if is_root else 16,
            shape="dot",
            group=0 if is_root else 1,
        )

    seen_edges: set[tuple[str, str, str, str | None]] = set()
    for src, dst, rel, sem in edges:
        key = (src, dst, rel, sem)
        if key in seen_edges:
            continue
        seen_edges.add(key)
        if rel == "ligilo":
            annotation = sem or "ligilo"
            net.add_edge(
                src,
                dst,
                color="#27ae60",
                label=annotation,
                title=escape(annotation),
                arrows="to",
                width=1.6,
                font={"size": 18, "color": "#d1fae5", "strokeWidth": 2},
            )
            continue
        if rel == "subklaso":
            net.add_edge(
                src,
                dst,
                color="#8e44ad",
                label="sub",
                title="subklaso",
                arrows="to",
                width=1.6,
                font={"size": 15, "color": "#e9d5ff", "strokeWidth": 2},
            )
            continue
        net.add_edge(
            src,
            dst,
            color="#e67e22",
            label="sup",
            title="superklaso",
            arrows="to",
            width=1.6,
            font={"size": 15, "color": "#fed7aa", "strokeWidth": 2},
        )

    root_label = escape(str(root.get("titolo") or root.get("uuid") or "nodo"))
    net.set_options(
        json.dumps(
            {
                "interaction": {
                    "hover": True,
                    "navigationButtons": True,
                    "keyboard": {"enabled": True, "bindToWindow": False},
                    "multiselect": True,
                },
                "edges": {
                    "smooth": {"enabled": True, "type": "dynamic"},
                    "selectionWidth": 2,
                },
                "nodes": {
                    "font": {
                        "size": 28,
                        "face": "system-ui",
                        "color": "#e5e7eb",
                        "strokeWidth": 3,
                    },
                    "scaling": {"label": {"enabled": True, "min": 16, "max": 36}},
                },
                "layout": {"improvedLayout": True},
                "physics": {
                    "enabled": True,
                    "barnesHut": {
                        "gravitationalConstant": -14000,
                        "centralGravity": 0.18,
                        "springLength": 95,
                        "springConstant": 0.06,
                        "damping": 0.88,
                    },
                },
                "configure": {
                    "enabled": True,
                    "filter": ["physics", "layout", "interaction"],
                    "showButton": True,
                },
            },
            ensure_ascii=False,
        )
    )

    intro = (
        f"<h1>Rilata mapo por {root_label}</h1>"
        "<details open><summary>Helpo pri navigado</summary>"
        "<ul>"
        "<li>Rulumilo: zomi/malzomi</li>"
        "<li>Treni fonon: movi (pan)</li>"
        "<li>Treni nodon: ŝanĝi aranĝon</li>"
        "<li>Dekstre: agordoj por fiziko/interago (fold/unfold paneloj)</li>"
        "</ul></details>"
    )
    html = net.generate_html(notebook=False)
    style_inject = (
        "<style>"
        "body{font-family:system-ui,sans-serif;background:#111;color:#e5e7eb;}"
        "#mynetwork{border:1px solid #333;border-radius:8px;}"
        "details{margin:.6rem 0;color:#d1d5db;} summary{cursor:pointer;}"
        "h1{font-size:1.25rem;margin:.4rem 0 .7rem 0;}"
        "</style>"
    )
    html = html.replace("</head>", f"{style_inject}</head>", 1)
    zoom_shortcuts = (
        "<script>"
        "document.addEventListener('keydown', function(ev){"
        "if(!ev.ctrlKey) return;"
        "const k=(ev.key||'').toLowerCase();"
        "if(!['+','-','=','_'].includes(k)) return;"
        "if(typeof network==='undefined' || !network.getScale) return;"
        "ev.preventDefault();"
        "const scale=network.getScale();"
        "const factor=(k==='-'||k==='_')?0.9:1.1;"
        "network.moveTo({"
        "scale: Math.max(0.1, Math.min(4, scale*factor)),"
        "animation:true"
        "});"
        "});"
        "</script>"
    )
    html = html.replace("<body>", f"<body>{intro}{zoom_shortcuts}", 1)
    return html


def _render_semantika_matches_html(
    rel: str, matches: list[tuple[dict, str]]
) -> tuple[dict, list[dict], list[tuple[str, str, str, str | None]]]:
    all_entries = _load_all()
    by_uuid = {str(e.get("uuid") or ""): e for e in all_entries}
    nodes_by_uuid: dict[str, dict] = {}
    edges: list[tuple[str, str, str, str | None]] = []
    seen_edges: set[tuple[str, str, str, str | None]] = set()
    root: dict | None = None
    for source, target_uuid in matches:
        source_uuid = str(source.get("uuid") or "")
        if not source_uuid:
            continue
        if root is None:
            root = source
        nodes_by_uuid[source_uuid] = source
        target = by_uuid.get(target_uuid) or _find_by_uuid(target_uuid)
        if target:
            nodes_by_uuid[str(target.get("uuid") or target_uuid)] = target
        edge = (source_uuid, target_uuid, "ligilo", rel)
        if edge not in seen_edges:
            seen_edges.add(edge)
            edges.append(edge)
    root_entry = root or next(iter(nodes_by_uuid.values()))
    nodes = sorted(
        nodes_by_uuid.values(), key=lambda e: str(e.get("titolo") or "").casefold()
    )
    return root_entry, nodes, edges


def _search_graph_of(
    candidates: list[dict], max_depth: int
) -> tuple[dict, list[dict], list[tuple[str, str, str, str | None]]]:
    all_nodes: dict[str, dict] = {}
    all_edges: list[tuple[str, str, str, str | None]] = []
    seen_edges: set[tuple[str, str, str, str | None]] = set()
    for entry in candidates:
        nodes, edges = _linked_graph_of(
            str(entry.get("uuid") or ""), max_depth=max_depth
        )
        for node in nodes:
            uid = str(node.get("uuid") or "")
            if uid:
                all_nodes[uid] = node
        for edge in edges:
            if edge in seen_edges:
                continue
            seen_edges.add(edge)
            all_edges.append(edge)
    if not all_nodes:
        seed = candidates[0]
        all_nodes[str(seed.get("uuid") or "")] = seed
    root = candidates[0]
    nodes = sorted(
        all_nodes.values(), key=lambda e: str(e.get("titolo") or "").casefold()
    )
    return root, nodes, all_edges


def _paralela_of(root_uuid: str, max_results: int) -> list[dict]:
    """Find sister classes: entries that share at least one parent with *root_uuid*."""
    root = _find_by_uuid(root_uuid)
    if root is None:
        return []
    all_entries = _load_all()
    parents_map, _children_map = _build_class_relation_maps(all_entries)
    by_uuid = {str(e.get("uuid") or ""): e for e in all_entries if e.get("uuid")}

    root_parents = set(parents_map.get(str(root.get("uuid") or ""), set()))
    if not root_parents:
        return []

    sisters: list[dict] = []
    for entry in by_uuid.values():
        uid = str(entry.get("uuid") or "")
        if uid == str(root.get("uuid") or ""):
            continue
        entry_parents = set(parents_map.get(uid, set()))
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


def _print_encik_montrado_settings(settings: dict[str, object]) -> None:
    table = Table(
        title="encik agordo — montrado",
        show_header=True,
        header_style="bold",
        expand=False,
    )
    table.add_column("KAMPO", style="cyan", no_wrap=True)
    table.add_column("VALORO", style="white", no_wrap=True)
    table.add_column("PRISKRIBO", style="dim")
    table.add_row(
        "html",
        "1" if bool(settings.get("html")) else "0",
        "Defaŭlte malfermi `encik vidi` kiel HTML.",
    )
    table.add_row(
        "scienca_nombro",
        str(int(settings.get("scienca_nombro", 4))),
        "Scienca noto kiam |x| >= 10^n aŭ |x| <= 1/10^n.",
    )
    table.add_row(
        "spaco",
        str(int(settings.get("spaco", 0))),
        "Nombro de malplenaj linioj inter kampoj en `encik vidi`.",
    )
    console.print(table)
    typer.echo(f"Dosiero: {_ENCIK_CONFIG_FILE}")


@app.command("agordi")
def agordi(
    html: str | None = typer.Option(
        None,
        "--html",
        help="Defaŭlta HTML-montrado por `encik vidi` (0/1, false/true).",
    ),
    scienca_nombro: int | None = typer.Option(
        None,
        "-sn",
        "--scienca-nombro",
        help="n por limoj 10^n kaj 1/10^n en nombro-montrado (ekz: -sn 4).",
    ),
    spaco: int | None = typer.Option(
        None,
        "--spaco",
        help="Malplenaj linioj inter kampoj en `encik vidi` (ekz: --spaco 1).",
    ),
) -> None:
    """Montri aŭ ŝanĝi encik montrado-agordon en ~/.config/autish/encik.toml."""
    settings = _load_encik_montrado_settings()
    if html is None and scienca_nombro is None and spaco is None:
        _print_encik_montrado_settings(settings)
        return
    if html is not None:
        try:
            settings["html"] = _parse_semantika_bool(html, field="--html")
        except ValueError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc
    if scienca_nombro is not None:
        if scienca_nombro < 0:
            typer.echo("--scienca-nombro devas esti >= 0.", err=True)
            raise typer.Exit(code=1)
        settings["scienca_nombro"] = scienca_nombro
    if spaco is not None:
        if spaco < 0:
            typer.echo("--spaco devas esti >= 0.", err=True)
            raise typer.Exit(code=1)
        settings["spaco"] = spaco
    _save_encik_montrado_settings(settings)
    typer.echo("Konservis encik montrado-agordon.")
    _print_encik_montrado_settings(settings)


@app.command("aldoni")
def aldoni(
    dosiero: str = typer.Argument(
        ...,
        help=(
            "Vojo al .enc dosiero.\n"
            "Ekzemplo: encik aldoni ./fiziko/suno.enc\n"
            "\n"
            "Formato (ĉiu elemento sur nova linio):\n"
            '  terminologio.xx = "..."\n'
            '  difino.xx = "..."\n'
            '  """laŭvola libera teksto"""\n'
            '  superklaso = ["uuid1", "uuid2"]\n'
            '  ligilo = ["uuid1", ["uuid2", "rdf:type"],\n'
            '            ["uuid3", "owl:inverseOf"], "vt#8bf534dc"]\n'
            '  fonto = [{titolo="...", autoro="...", jaro=2020, tipo="libroj", '
            'noto="...", ligilo="https://...", lingvo="eo,en"}]\n'
            '  citajo = [{teksto="...", autoro="...", verko="...", '
            'jaro="...", lingvo="eo,fr"}]\n'
            '  datumo.<nomo> = """{...json...}"""  # nomo devas esti unika\n'
            '  semantika = """\n'
            "  int wdt:P1082 890\n"
            "  int wdt:P2046 1E6 #abcde\n"
            "  float wdt:P1082 2,8E8\n"
            "  str wdt:P5191 philosophia\n"
            "  bool wdt:P31 true\n"
            '  """\n'
            "\n"
            "Komentoj en .enc dosiero:\n"
            "  # tiu ĉi estas komento\n"
            "\n"
            'JSON-datumo: datumo.<nomo> = """{...}""".\n'
            "Datumo-kampoj:\n"
            "  - metriko (laŭvola): ĉeno aŭ plurlingva objekto.\n"
            "  - meta (laŭvola): objekto kun identigaj metadatumoj; valoroj povas esti "
            "unuopaj aŭ plurlingvaj objektoj.\n"
            "  - datumo (deviga): listo de vicoj; "
            "unua vico povas esti kolumnetikedoj.\n"
            "  - etikedo (laŭvola): plurlingvaj kolumnaj etikedoj.\n"
            "Semantika valoro: subtenas '.'/',' decimalajn apartigilojn "
            "kaj E-notacion; "
            "laŭvola #UUID unuo, defaŭlte SI.\n"
            "\n"
            "Semantikaj ligiloj (laŭvolaj en ligilo):\n"
            "  rdf:type         # estas tipo de\n"
            "  rdfs:subClassOf  # subklaso de\n"
            "  owl:disjointWith # malkongrua kun\n"
            "  owl:inverseOf    # inversa de\n"
            "  wdt:P50          # aŭtoro / kreinto\n"
            "  wdt:P361         # parto de\n"
            "  wdt:P527         # havas parton\n"
            "  ...\n"
            "Plena listo: encik semantika\n"
            "\n"
            "Validaj fonto.tipo:\n"
            "  libroj, artikoloj, retejoj, filmoj, tezoj, raportoj, podkastoj, "
            "prelegoj\n"
            "Aliasoj:\n"
            "  lib, art, ret, fil, tez, rap, pod, pre"
        ),
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
    vidi_poste: bool = typer.Option(
        False,
        "-v",
        "--vidi",
        help="Montri la aldonitan/modifitan nodon post konservado.",
    ),
    html: bool = typer.Option(
        False,
        "-H",
        "--html",
        help=(
            "Kun --vidi: montri la aldonitan/modifitan nodon kiel HTML en "
            "la defaŭlta retumilo."
        ),
    ),
) -> None:
    """Aldoni novan nodon el .enc dosiero."""
    if kopii_uuid and semantika_kopii:
        typer.echo("Uzu nur unu el --kopii aŭ --semantika-kopii.", err=True)
        raise typer.Exit(code=1)
    if html and not vidi_poste:
        vidi_poste = True
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
    parsed = _canonicalize_class_alias_fields(parsed)
    
    # Validate semantic links
    unresolved_links = _validate_semantic_links(parsed)
    if unresolved_links:
        typer.echo(
            "[!] Eraro: Kelkaj semantikaj ligiloj ne troviĝas:",
            err=True,
        )
        for link_uuid in unresolved_links:
            typer.echo(f"    - {link_uuid}", err=True)
        raise typer.Exit(code=1)

    # Duplicate title check
    existing = _find_by_title_exact(parsed["titolo"])
    if existing is not None:
        previous_ligilo = _serialize_ligilo_items(
            _normalize_ligilo_items(existing.get("ligilo") or [])
        )
        typer.echo(
            f'Nodo kun titolo "{existing["titolo"]}" jam ekzistas '
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
            semantika=parsed["semantika"],
            modifita_je=now_iso(),
        )
        _update_entry(existing)
        _sync_bidirectional_relations_for_entry(
            existing,
            previous_ligilo=previous_ligilo,
        )
        typer.echo(f'Modifis #{existing["uuid"][:8]}  "{existing["titolo"]}"')
        if kopii_uuid or semantika_kopii:
            _copy_entry_reference(existing, semantika=semantika_kopii)
        if vidi_poste:
            if html:
                html_doc = _render_entry_html(existing)
                out_path = _open_html_document(html_doc)
                typer.echo(f"Malfermas en retumilo: {out_path}")
            else:
                _display_entry(existing)
        return

    now = now_iso()
    entry: dict = {
        "uuid": str(_uuid_mod.uuid4()),
        "kreita_je": now,
        "modifita_je": now,
        **parsed,
    }
    try:
        _raise_if_malformed_entry(entry)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    _raise_if_semantic_conflicts(entry)
    _insert_entry(entry)
    _sync_bidirectional_relations_for_entry(entry)
    typer.echo(f'Aldonis #{entry["uuid"][:8]}  "{entry["titolo"]}"')
    if kopii_uuid or semantika_kopii:
        _copy_entry_reference(entry, semantika=semantika_kopii)
    if vidi_poste:
        if html:
            html_doc = _render_entry_html(entry)
            out_path = _open_html_document(html_doc)
            typer.echo(f"Malfermas en retumilo: {out_path}")
        else:
            _display_entry(entry)


@app.command("modifi")
def modifi(
    ref: str | None = typer.Argument(
        None,
        help=(
            "Terminologio (parta aŭ ekzakta) aŭ UUID de redaktota nodo. "
            'Ekzemplo: encik modifi "#e0a5d3b7"'
        ),
    ),
    dosiero: Path | None = typer.Argument(
        None,
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help=(
            "Nova .enc dosiero por rekta anstataŭigo (sen redaktilo). "
            "Ekzemplo: encik modifi Fiziko ./nova.enc"
        ),
    ),
    titolo: str | None = typer.Option(
        None, "--titolo", help='Nova ĉefa titolo. Ekzemplo: --titolo "Nova nodo"'
    ),
    difinio: str | None = typer.Option(
        None,
        "--difinio",
        help='Nova ĉefa difino. Ekzemplo: --difinio "Mallonga priskribo."',
    ),
    termino: list[str] | None = typer.Option(
        None,
        "-t",
        "--terminologio",
        help=(
            "Anstataŭigi/aldoni terminon laŭ lingvo: xx:teksto (ripetebla). "
            "Ekzemplo: -t eo:Suno -t en:Sun"
        ),
    ),
    termino_difino: list[str] | None = typer.Option(
        None,
        "-d",
        "--difino",
        help=(
            "Anstataŭigi/aldoni difinon laŭ lingvo: xx:teksto (ripetebla). "
            'Ekzemplo: -d eo:"Stelo..." -d en:"A star..."'
        ),
    ),
    enhavo: str | None = typer.Option(
        None, "--enhavo", help='Nova enhavo. Ekzemplo: --enhavo "Plia teksto."'
    ),
    superklaso: list[str] | None = typer.Option(
        None,
        "--superklaso",
        help=(
            "Anstataŭigi superklaso-liston (ripetebla). "
            "Ekzemplo: --superklaso #abcd1234"
        ),
    ),
    ligilo: list[str] | None = typer.Option(
        None,
        "-L",
        "--ligilo",
        help=(
            "Anstataŭigi ligilo-liston (ripetebla). Formoj: UUID aŭ UUID:semantiko "
            "(ekz. --ligilo #abc12345:rdf:type)."
        ),
    ),
    kopii_uuid: bool = typer.Option(
        False,
        "-k",
        "--kopii",
        help="Kopii #xxxxxxxx de la modifita nodo al tondujo.",
    ),
    semantika_kopii: bool = typer.Option(
        False,
        "-sk",
        "--semantika-kopii",
        help="Kopii [titolo](#xxxxxxxx) de la modifita nodo al tondujo.",
    ),
) -> None:
    """Modifi ekzistantan nodon per redaktilo, .enc dosiero, aŭ CLI-opcioj."""
    if kopii_uuid and semantika_kopii:
        typer.echo("Uzu nur unu el --kopii aŭ --semantika-kopii.", err=True)
        raise typer.Exit(code=1)
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
    previous_ligilo = _serialize_ligilo_items(
        _normalize_ligilo_items(entry.get("ligilo") or [])
    )

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
                typer.echo(f"Redaktilo eliris kun kodo {result.returncode}.", err=True)
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
        parsed = _canonicalize_class_alias_fields(parsed)
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
            semantika=parsed["semantika"],
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
        merged_from_super = _merge_superklaso_into_ligilo(
            _normalise_superklaso_refs(superklaso),
            _serialize_ligilo_items(_normalize_ligilo_items(entry.get("ligilo") or [])),
        )
        entry["ligilo"] = merged_from_super
        entry["superklaso"] = []
    if ligilo is not None:
        try:
            entry["ligilo"] = _parse_ligilo_cli_values(ligilo)
        except ValueError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc

    entry = _canonicalize_class_alias_fields(entry)

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
    entry["difinio"] = (
        defs.get(primary_lang, "").strip() or next(iter(defs.values())).strip()
    )

    existing = _find_by_title_exact(entry["titolo"])
    if existing is not None and existing["uuid"] != entry["uuid"]:
        typer.echo(
            f'Nodo kun titolo "{entry["titolo"]}" jam ekzistas '
            f"(#{existing['uuid'][:8]}).",
            err=True,
        )
        raise typer.Exit(code=1)

    try:
        _raise_if_malformed_entry(entry)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    _raise_if_semantic_conflicts(entry, strict=False)
    entry["modifita_je"] = now_iso()
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
