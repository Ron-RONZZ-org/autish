"""Shared helpers for etikedo/todo/taglibro microapps."""

from __future__ import annotations

import re
import sqlite3
import uuid as _uuid_mod
from collections.abc import Callable
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

import typer

from autish.utils import fold_search_text, now_iso

_DATA_DIR: Path = Path.home() / ".local" / "share" / "autish"
_DB_FILE: Path = _DATA_DIR / "tasklibro.db"
_ENCIK_DB_FILE: Path = _DATA_DIR / "encik.db"
_VORTO_DB_FILE: Path = _DATA_DIR / "vorto.db"

_CREATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS etikedo (
    uuid        TEXT PRIMARY KEY,
    teksto      TEXT NOT NULL,
    teksto_norm TEXT NOT NULL UNIQUE,
    kreita_je   TEXT NOT NULL,
    modifita_je TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS todo (
    uuid            TEXT PRIMARY KEY,
    titolo          TEXT NOT NULL,
    titolo_norm     TEXT NOT NULL,
    priskribo       TEXT NOT NULL DEFAULT '',
    priskribo_norm  TEXT NOT NULL DEFAULT '',
    prioritato      TEXT NOT NULL DEFAULT '0',
    stato           TEXT NOT NULL DEFAULT 'malfermita',
    kreita_je       TEXT NOT NULL,
    modifita_je     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS taglibro (
    uuid            TEXT PRIMARY KEY,
    titolo          TEXT NOT NULL,
    titolo_norm     TEXT NOT NULL,
    priskribo       TEXT NOT NULL DEFAULT '',
    priskribo_norm  TEXT NOT NULL DEFAULT '',
    tempo           TEXT NOT NULL,
    kreita_je       TEXT NOT NULL,
    modifita_je     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS todo_etikedo (
    todo_uuid       TEXT NOT NULL,
    etikedo_uuid    TEXT NOT NULL,
    PRIMARY KEY (todo_uuid, etikedo_uuid),
    FOREIGN KEY (todo_uuid) REFERENCES todo(uuid) ON DELETE CASCADE,
    FOREIGN KEY (etikedo_uuid) REFERENCES etikedo(uuid) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS taglibro_etikedo (
    taglibro_uuid   TEXT NOT NULL,
    etikedo_uuid    TEXT NOT NULL,
    PRIMARY KEY (taglibro_uuid, etikedo_uuid),
    FOREIGN KEY (taglibro_uuid) REFERENCES taglibro(uuid) ON DELETE CASCADE,
    FOREIGN KEY (etikedo_uuid) REFERENCES etikedo(uuid) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_etikedo_teksto_norm ON etikedo(teksto_norm);
CREATE INDEX IF NOT EXISTS idx_todo_titolo_norm ON todo(titolo_norm);
CREATE INDEX IF NOT EXISTS idx_todo_priskribo_norm ON todo(priskribo_norm);
CREATE INDEX IF NOT EXISTS idx_taglibro_titolo_norm ON taglibro(titolo_norm);
CREATE INDEX IF NOT EXISTS idx_taglibro_priskribo_norm ON taglibro(priskribo_norm);
"""

_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")


def connect() -> sqlite3.Connection:
    """Open and initialize the shared SQLite database."""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(_DB_FILE), timeout=5.0)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA foreign_keys=ON;")
    con.executescript(_CREATE_SCHEMA)
    return con


def new_uuid() -> str:
    return str(_uuid_mod.uuid4())


def is_uuid_prefix(ref: str) -> bool:
    token = str(ref or "").strip().lstrip("#")
    if not token:
        return False
    return bool(re.fullmatch(r"[0-9a-f]{8}(?:[0-9a-f-]{0,28})", token.casefold()))


def _fetch_one_by_uuid_prefix(
    *,
    db_file: Path,
    table: str,
    fields: str,
    ref: str,
) -> dict | None:
    if not db_file.exists():
        return None
    token = str(ref or "").strip().lstrip("#")
    if not token:
        return None
    con = sqlite3.connect(str(db_file), timeout=3.0)
    con.row_factory = sqlite3.Row
    try:
        row = con.execute(
            f"SELECT {fields} FROM {table} WHERE uuid = ?",
            (token,),
        ).fetchone()
        if row:
            return dict(row)
        rows = con.execute(
            f"SELECT {fields} FROM {table} WHERE uuid LIKE ? "
            "ORDER BY uuid COLLATE NOCASE LIMIT 2",
            (f"{token}%",),
        ).fetchall()
        if len(rows) == 1:
            return dict(rows[0])
        return None
    except sqlite3.Error:
        return None
    finally:
        con.close()


def find_encik_by_ref(ref: str) -> dict | None:
    return _fetch_one_by_uuid_prefix(
        db_file=_ENCIK_DB_FILE,
        table="encik",
        fields="uuid, titolo, difinio",
        ref=ref,
    )


def find_vorto_by_ref(ref: str) -> dict | None:
    return _fetch_one_by_uuid_prefix(
        db_file=_VORTO_DB_FILE,
        table="vorto",
        fields="uuid, teksto",
        ref=ref,
    )


def _canonicalize_internal_ref(token: str) -> str:
    raw = str(token or "").strip()
    lower = raw.casefold()
    if lower.startswith("ec#"):
        encik_ref = raw[3:].lstrip("#").strip()
        if not encik_ref:
            return raw
        target = find_encik_by_ref(encik_ref)
        resolved = str(target.get("uuid") or encik_ref) if target else encik_ref
        return f"ec#{resolved}"
    if lower.startswith("vt#"):
        vorto_ref = raw[3:].lstrip("#").strip()
        if not vorto_ref:
            return raw
        target = find_vorto_by_ref(vorto_ref)
        resolved = str(target.get("uuid") or vorto_ref) if target else vorto_ref
        return f"vt#{resolved}"
    return raw


def normalize_markdown_links(text: str) -> str:
    """Normalize markdown ec#/vt# targets to canonical full UUID refs."""
    raw_text = str(text or "")
    if not raw_text:
        return ""

    def _replace(match: re.Match[str]) -> str:
        label = match.group(1)
        target = match.group(2)
        canonical = _canonicalize_internal_ref(target)
        return f"[{label}]({canonical})"

    return _MARKDOWN_LINK_RE.sub(_replace, raw_text)


def auto_create_semantic_link_etikedoj(text: str) -> None:
    """Auto-create etikedo entries for semantic links [label](ec#uuid)."""
    raw_text = str(text or "")
    if not raw_text:
        return
    
    matches = _MARKDOWN_LINK_RE.finditer(raw_text)
    con = connect()
    try:
        for match in matches:
            label = match.group(1).strip()
            target = match.group(2).strip()
            lower_target = target.casefold()
            
            if not (lower_target.startswith("ec#") or lower_target.startswith("vt#")):
                continue
            
            canonical = _canonicalize_internal_ref(target)
            etikedo_text = (
                f"[{label}]({canonical})" if label else canonical
            )
            folded = fold_search_text(etikedo_text)
            
            existing = con.execute(
                "SELECT uuid FROM etikedo WHERE teksto_norm = ?",
                (folded,),
            ).fetchone()
            if not existing:
                uid = new_uuid()
                now = now_iso()
                con.execute(
                    "INSERT INTO etikedo "
                    "(uuid, teksto, teksto_norm, kreita_je, modifita_je) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (uid, etikedo_text, folded, now, now),
                )
        con.commit()
    finally:
        con.close()


def _render_internal_link_plain(label: str, target: str, *, show_ref: bool) -> str:
    token = _canonicalize_internal_ref(target)
    lower = token.casefold()
    if lower.startswith("ec#"):
        ref = token[3:]
        target_entry = find_encik_by_ref(ref)
        if target_entry is None:
            fallback = f"ec#{ref[:8]}"
            return fallback if not label else label
        shown = str(target_entry.get("titolo") or "").strip() or f"ec#{ref[:8]}"
        if label:
            shown = label
        if not show_ref:
            return shown
        return f"{shown} (ec#{str(target_entry.get('uuid') or '')[:8]})"
    if lower.startswith("vt#"):
        ref = token[3:]
        target_entry = find_vorto_by_ref(ref)
        if target_entry is None:
            fallback = f"vt#{ref[:8]}"
            return fallback if not label else label
        shown = str(target_entry.get("teksto") or "").strip() or f"vt#{ref[:8]}"
        if label:
            shown = label
        if not show_ref:
            return shown
        return f"{shown} (vt#{str(target_entry.get('uuid') or '')[:8]})"
    return label or target


def render_markdown_links_plain(text: str, *, show_ref: bool = False) -> str:
    """Render markdown text with ec#/vt# links as human-readable plain text."""
    raw_text = str(text or "")
    if not raw_text:
        return ""

    def _replace(match: re.Match[str]) -> str:
        return _render_internal_link_plain(
            match.group(1).strip(),
            match.group(2).strip(),
            show_ref=show_ref,
        )

    return _MARKDOWN_LINK_RE.sub(_replace, raw_text)


def fuzzy_matches(
    items: list[dict],
    query: str,
    *,
    text_getter: Callable[[dict], str],
    limit: int = 20,
    threshold: float = 0.62,
) -> list[dict]:
    needle = fold_search_text(query)
    if not needle:
        return []
    scored: list[tuple[float, dict]] = []
    for item in items:
        candidate = fold_search_text(text_getter(item))
        if not candidate:
            continue
        ratio = SequenceMatcher(None, needle, candidate).ratio()
        if ratio >= threshold:
            scored.append((ratio, item))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:limit]]


def search_items(
    items: list[dict],
    query: str | None,
    *,
    text_getter: Callable[[dict], str],
    limit: int = 50,
) -> tuple[list[dict], bool]:
    if not query:
        return list(items), False
    needle = fold_search_text(query)
    contains = [
        item
        for item in items
        if needle and needle in fold_search_text(text_getter(item))
    ]
    if contains:
        return contains[:limit], False
    fuzzy = fuzzy_matches(items, query, text_getter=text_getter, limit=limit)
    return fuzzy, bool(fuzzy)


def prompt_pick(
    candidates: list[dict],
    *,
    title: str,
    text_getter: Callable[[dict], str],
) -> dict | None:
    if not candidates:
        return None
    typer.echo(title)
    for index, item in enumerate(candidates, start=1):
        uid = str(item.get("uuid") or "")
        label = text_getter(item)
        typer.echo(f"{index}. {label} (#{uid[:8]})")
    raw = typer.prompt("Elektu numeron (aŭ Enter por nuligi)", default="")
    if not raw.strip():
        return None
    try:
        idx = int(raw.strip()) - 1
    except ValueError:
        typer.echo("Nevalida elekto.", err=True)
        raise typer.Exit(1) from None
    if idx < 0 or idx >= len(candidates):
        typer.echo("Nevalida elekto.", err=True)
        raise typer.Exit(1)
    return candidates[idx]


def resolve_reference(
    items: list[dict],
    reference: str,
    *,
    text_getter: Callable[[dict], str],
    kind_label: str,
    allow_fuzzy: bool = True,
    interactive: bool = True,
) -> dict | None:
    raw_ref = str(reference or "").strip()
    if not raw_ref:
        return None
    token = raw_ref.lstrip("#")
    folded_ref = fold_search_text(token)

    exact_uuid = [item for item in items if str(item.get("uuid") or "") == token]
    if len(exact_uuid) == 1:
        return exact_uuid[0]
    prefix = [item for item in items if str(item.get("uuid") or "").startswith(token)]
    exact_text = [
        item for item in items if fold_search_text(text_getter(item)) == folded_ref
    ]

    exact_candidates: list[dict] = []
    seen: set[str] = set()
    for item in [*exact_uuid, *prefix, *exact_text]:
        uid = str(item.get("uuid") or "")
        if uid in seen:
            continue
        seen.add(uid)
        exact_candidates.append(item)
    if len(exact_candidates) == 1:
        return exact_candidates[0]
    if len(exact_candidates) > 1:
        if not interactive:
            return None
        return prompt_pick(
            exact_candidates,
            title=f"Pluraj {kind_label}-kandidatoj por {reference!r}:",
            text_getter=text_getter,
        )

    if not allow_fuzzy:
        return None
    contains = [
        item
        for item in items
        if folded_ref and folded_ref in fold_search_text(text_getter(item))
    ][:20]
    fuzzy = fuzzy_matches(items, token, text_getter=text_getter, limit=20)
    candidates = contains if contains else fuzzy
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1 and interactive:
        return prompt_pick(
            candidates,
            title=f"Neniu ekzakta kongruo por {reference!r}. Proksimaj rezultoj:",
            text_getter=text_getter,
        )
    return None


def list_etikedoj(con: sqlite3.Connection) -> list[dict]:
    rows = con.execute(
        "SELECT uuid, teksto, teksto_norm, kreita_je, modifita_je "
        "FROM etikedo ORDER BY teksto COLLATE NOCASE"
    ).fetchall()
    return [dict(row) for row in rows]


def resolve_etikedo_refs(
    references: list[str] | None,
    *,
    interactive: bool = True,
    prompt_on_missing: bool = False,
) -> list[str]:
    refs = [
        str(ref or "").strip() for ref in (references or []) if str(ref or "").strip()
    ]
    if not refs:
        return []
    resolved: list[str] = []
    seen: set[str] = set()
    for ref in refs:
        with connect() as con:
            labels = list_etikedoj(con)
            target = resolve_reference(
                labels,
                ref,
                text_getter=lambda item: str(item.get("teksto") or ""),
                kind_label="etikedo",
                allow_fuzzy=True,
                interactive=interactive,
            )
            if target is None:
                if prompt_on_missing and interactive:
                    answer = typer.prompt(
                        f"Etikedo ne trovita: {ref!r}. Ĉu aldoni novan? (j/N)",
                        default="N",
                    )
                    if answer.strip().lower() == "j":
                        normalized = normalize_markdown_links(ref).strip()
                        if not normalized:
                            typer.echo("Malplena etikedo ne permesata.", err=True)
                            raise typer.Exit(1)
                        folded = fold_search_text(normalized)
                        existing = con.execute(
                            "SELECT uuid FROM etikedo WHERE teksto_norm = ?",
                            (folded,),
                        ).fetchone()
                        if existing:
                            uid = str(existing["uuid"])
                        else:
                            uid = new_uuid()
                            now = now_iso()
                            con.execute(
                                "INSERT INTO etikedo "
                                "(uuid, teksto, teksto_norm, kreita_je, modifita_je) "
                                "VALUES (?, ?, ?, ?, ?)",
                                (uid, normalized, folded, now, now),
                            )
                            con.commit()
                            rendered = render_markdown_links_plain(
                                normalized, show_ref=True
                            )
                            typer.echo(f"Aldonis etikedon: {rendered}")
                        if uid not in seen:
                            seen.add(uid)
                            resolved.append(uid)
                    else:
                        typer.echo(f"Etikedo ne trovita: {ref!r}", err=True)
                        raise typer.Exit(1)
                else:
                    typer.echo(f"Etikedo ne trovita: {ref!r}", err=True)
                    raise typer.Exit(1)
            else:
                uid = str(target.get("uuid") or "")
                if uid and uid not in seen:
                    seen.add(uid)
                    resolved.append(uid)
    return resolved


def etikedo_text_map(con: sqlite3.Connection) -> dict[str, str]:
    rows = con.execute("SELECT uuid, teksto FROM etikedo").fetchall()
    return {
        str(row["uuid"]): render_markdown_links_plain(str(row["teksto"] or ""))
        for row in rows
    }


def format_iso_short(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw
    return dt.astimezone().strftime("%Y-%m-%d %H:%M")
