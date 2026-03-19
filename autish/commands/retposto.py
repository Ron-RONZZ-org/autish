"""retposto — TUI email microapp (Retpoŝto).

Usage:
    retposto                         — interactive TUI
    retposto aldoni-konton           — add an email account
    retposto forigi-konton <id>      — remove an email account
    retposto listigi-kontojn         — list configured accounts
    retposto sendi                   — compose & send from CLI
    retposto preni                   — fetch mail from all accounts
    retposto kontakto listigi        — list contacts
    retposto kontakto importi <vcf>  — import contacts from a VCF file
    retposto kontakto eksporti <vcf> — export contacts to a VCF file

Data is stored in ~/.local/share/autish/retposto.db (SQLite, WAL mode).
Passwords are stored in the system keyring (keyring library).
"""

from __future__ import annotations

import email as _email_mod
import email.header
import email.message
import email.policy
import imaplib
import json
import re
import smtplib
import sqlite3
import ssl
import urllib.request
import uuid as _uuid_mod
import webbrowser
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import make_msgid
from pathlib import Path
from tempfile import NamedTemporaryFile

import keyring
import typer
import vobject
from rich.console import Console
from rich.table import Table

# ──────────────────────────────────────────────────────────────────────────────
# Typer apps
# ──────────────────────────────────────────────────────────────────────────────

app = typer.Typer(
    name="retposto",
    help=(
        "Retpoŝto — TUI email microapp.\n\n"
        "Altnivela CLI-agordo:\n"
        "  - subskribo  (retposto subskribo ...)\n"
        "  - filtro     (retposto filtro agordi/montri ...)"
    ),
    no_args_is_help=False,
    invoke_without_command=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)

kontakto_app = typer.Typer(
    name="kontakto",
    help="Manage contacts (koresponda listo).",
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)
app.add_typer(kontakto_app, name="kontakto")

filtro_app = typer.Typer(
    name="filtro",
    help="Manage Sieve-style message filters.",
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)
app.add_typer(filtro_app, name="filtro")

console = Console()

# ──────────────────────────────────────────────────────────────────────────────
# Storage paths
# ──────────────────────────────────────────────────────────────────────────────

_DATA_DIR: Path = Path.home() / ".local" / "share" / "autish"
_DB_FILE: Path = _DATA_DIR / "retposto.db"
_KEYRING_SERVICE: str = "autish-retposto"

_MAX_FOLDERS_PER_ACCOUNT: int = 20

_EMAIL_DOMAIN_CONFIGS: dict[str, dict[str, object]] = {
    "gmail.com": {
        "imap_servilo": "imap.gmail.com",
        "imap_haveno": 993,
        "imap_ssl": True,
        "smtp_servilo": "smtp.gmail.com",
        "smtp_haveno": 587,
        "smtp_tls": True,
    },
    "googlemail.com": {
        "imap_servilo": "imap.gmail.com",
        "imap_haveno": 993,
        "imap_ssl": True,
        "smtp_servilo": "smtp.gmail.com",
        "smtp_haveno": 587,
        "smtp_tls": True,
    },
    "outlook.com": {
        "imap_servilo": "outlook.office365.com",
        "imap_haveno": 993,
        "imap_ssl": True,
        "smtp_servilo": "smtp.office365.com",
        "smtp_haveno": 587,
        "smtp_tls": True,
    },
    "hotmail.com": {
        "imap_servilo": "outlook.office365.com",
        "imap_haveno": 993,
        "imap_ssl": True,
        "smtp_servilo": "smtp.office365.com",
        "smtp_haveno": 587,
        "smtp_tls": True,
    },
    "live.com": {
        "imap_servilo": "outlook.office365.com",
        "imap_haveno": 993,
        "imap_ssl": True,
        "smtp_servilo": "smtp.office365.com",
        "smtp_haveno": 587,
        "smtp_tls": True,
    },
    "office365.com": {
        "imap_servilo": "outlook.office365.com",
        "imap_haveno": 993,
        "imap_ssl": True,
        "smtp_servilo": "smtp.office365.com",
        "smtp_haveno": 587,
        "smtp_tls": True,
    },
    "yahoo.com": {
        "imap_servilo": "imap.mail.yahoo.com",
        "imap_haveno": 993,
        "imap_ssl": True,
        "smtp_servilo": "smtp.mail.yahoo.com",
        "smtp_haveno": 465,
        "smtp_tls": False,
    },
    "yahoo.co.jp": {
        "imap_servilo": "imap.mail.yahoo.co.jp",
        "imap_haveno": 993,
        "imap_ssl": True,
        "smtp_servilo": "smtp.mail.yahoo.co.jp",
        "smtp_haveno": 465,
        "smtp_tls": False,
    },
    "icloud.com": {
        "imap_servilo": "imap.mail.me.com",
        "imap_haveno": 993,
        "imap_ssl": True,
        "smtp_servilo": "smtp.mail.me.com",
        "smtp_haveno": 587,
        "smtp_tls": True,
    },
    "me.com": {
        "imap_servilo": "imap.mail.me.com",
        "imap_haveno": 993,
        "imap_ssl": True,
        "smtp_servilo": "smtp.mail.me.com",
        "smtp_haveno": 587,
        "smtp_tls": True,
    },
    "mac.com": {
        "imap_servilo": "imap.mail.me.com",
        "imap_haveno": 993,
        "imap_ssl": True,
        "smtp_servilo": "smtp.mail.me.com",
        "smtp_haveno": 587,
        "smtp_tls": True,
    },
    "proton.me": {
        "imap_servilo": "127.0.0.1",
        "imap_haveno": 1143,
        "imap_ssl": False,
        "smtp_servilo": "127.0.0.1",
        "smtp_haveno": 1025,
        "smtp_tls": False,
    },
    "protonmail.com": {
        "imap_servilo": "127.0.0.1",
        "imap_haveno": 1143,
        "imap_ssl": False,
        "smtp_servilo": "127.0.0.1",
        "smtp_haveno": 1025,
        "smtp_tls": False,
    },
}

# Allowed column names for _update_message_field to prevent SQL injection
_MSG_UPDATABLE_COLS: frozenset[str] = frozenset({
    "konto_id", "dosierujo_id", "legita", "stelo", "spamo", "forigita",
    "prioritato", "etikedoj",
})
# ──────────────────────────────────────────────────────────────────────────────

_CREATE_KONTO = """
CREATE TABLE IF NOT EXISTS konto (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ordo         INTEGER NOT NULL DEFAULT 0,
    nomo         TEXT NOT NULL,
    retposto     TEXT NOT NULL UNIQUE,
    imap_servilo TEXT NOT NULL,
    imap_haveno  INTEGER NOT NULL DEFAULT 993,
    imap_ssl     INTEGER NOT NULL DEFAULT 1,
    smtp_servilo TEXT NOT NULL,
    smtp_haveno  INTEGER NOT NULL DEFAULT 587,
    smtp_tls     INTEGER NOT NULL DEFAULT 1,
    uzantonomo   TEXT,
    subskribo    TEXT,
    kreita_je    TEXT NOT NULL
);
"""

_CREATE_DOSIERUJO = """
CREATE TABLE IF NOT EXISTS dosierujo (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    konto_id    INTEGER NOT NULL REFERENCES konto(id) ON DELETE CASCADE,
    nomo        TEXT NOT NULL,
    patro_id    INTEGER REFERENCES dosierujo(id) ON DELETE CASCADE,
    server_nomo TEXT,
    UNIQUE(konto_id, nomo, patro_id)
);
"""

_CREATE_MESAGO = """
CREATE TABLE IF NOT EXISTS mesago (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid         TEXT NOT NULL UNIQUE,
    konto_id     INTEGER NOT NULL REFERENCES konto(id) ON DELETE CASCADE,
    dosierujo_id INTEGER REFERENCES dosierujo(id),
    message_id   TEXT,
    in_reply_to  TEXT,
    references_hdr TEXT,
    uid          TEXT,
    de           TEXT,
    al           TEXT NOT NULL DEFAULT '[]',
    cc           TEXT NOT NULL DEFAULT '[]',
    bcc          TEXT NOT NULL DEFAULT '[]',
    subjekto     TEXT,
    korpo        TEXT,
    html_korpo   TEXT,
    prioritato   INTEGER DEFAULT 5,
    legita       INTEGER NOT NULL DEFAULT 0,
    stelo        INTEGER NOT NULL DEFAULT 0,
    spamo        INTEGER NOT NULL DEFAULT 0,
    forigita     INTEGER NOT NULL DEFAULT 0,
    aldonajoj    TEXT NOT NULL DEFAULT '[]',
    etikedoj     TEXT NOT NULL DEFAULT '[]',
    ricevita_je  TEXT,
    kreita_je    TEXT NOT NULL
);
"""

_CREATE_KONTAKTO = """
CREATE TABLE IF NOT EXISTS kontakto (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid        TEXT NOT NULL UNIQUE,
    nomo        TEXT,
    retposto    TEXT NOT NULL UNIQUE,
    organizo    TEXT,
    telefono    TEXT,
    noto        TEXT,
    kreita_je   TEXT NOT NULL,
    modifita_je TEXT NOT NULL
);
"""

_CREATE_SPAMO_BLOKO = """
CREATE TABLE IF NOT EXISTS spamo_bloko (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    regulo    TEXT NOT NULL UNIQUE,
    kreita_je TEXT NOT NULL
);
"""

_CREATE_FILTRO = """
CREATE TABLE IF NOT EXISTS filtro (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    nomo       TEXT NOT NULL UNIQUE,
    sieve_kodo TEXT NOT NULL,
    aktiva     INTEGER NOT NULL DEFAULT 1,
    ordo       INTEGER NOT NULL DEFAULT 0,
    kreita_je  TEXT NOT NULL
);
"""

# ──────────────────────────────────────────────────────────────────────────────
# DB helpers
# ──────────────────────────────────────────────────────────────────────────────


def _get_db() -> sqlite3.Connection:
    """Open (and initialise) the SQLite database, returning a connection."""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(_DB_FILE), timeout=5.0)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA foreign_keys=ON;")
    con.executescript(
        _CREATE_KONTO
        + _CREATE_DOSIERUJO
        + _CREATE_MESAGO
        + _CREATE_KONTAKTO
        + _CREATE_SPAMO_BLOKO
        + _CREATE_FILTRO
    )
    # Migrations for existing databases
    _migrate_db(con)
    return con


def _migrate_db(con: sqlite3.Connection) -> None:
    """Apply forward-only schema migrations to existing databases."""
    existing_cols = {
        row[1]
        for row in con.execute("PRAGMA table_info(konto)").fetchall()
    }
    if "ordo" not in existing_cols:
        con.execute("ALTER TABLE konto ADD COLUMN ordo INTEGER NOT NULL DEFAULT 0")
        rows = con.execute("SELECT id FROM konto ORDER BY id ASC").fetchall()
        for idx, row in enumerate(rows, 1):
            con.execute("UPDATE konto SET ordo = ? WHERE id = ?", (idx, row["id"]))
        con.commit()
    if "subskribo" not in existing_cols:
        con.execute("ALTER TABLE konto ADD COLUMN subskribo TEXT")
        con.commit()

    mesago_cols = {
        row[1] for row in con.execute("PRAGMA table_info(mesago)").fetchall()
    }
    if "in_reply_to" not in mesago_cols:
        con.execute("ALTER TABLE mesago ADD COLUMN in_reply_to TEXT")
        con.commit()
    if "references_hdr" not in mesago_cols:
        con.execute("ALTER TABLE mesago ADD COLUMN references_hdr TEXT")
        con.commit()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_uuid() -> str:
    return str(_uuid_mod.uuid4())


# ──────────────────────────────────────────────────────────────────────────────
# Account helpers
# ──────────────────────────────────────────────────────────────────────────────


def _load_accounts() -> list[dict]:
    with _get_db() as con:
        rows = con.execute("SELECT * FROM konto ORDER BY ordo ASC, id ASC").fetchall()
    return [dict(r) for r in rows]


def _find_account(id_or_addr: str) -> dict | None:
    """Find account by integer id or email address (partial match)."""
    with _get_db() as con:
        if id_or_addr.isdigit():
            row = con.execute(
                "SELECT * FROM konto WHERE id = ?", (int(id_or_addr),)
            ).fetchone()
        else:
            row = con.execute(
                "SELECT * FROM konto WHERE retposto LIKE ?",
                (f"%{id_or_addr}%",),
            ).fetchone()
    return dict(row) if row else None


def _save_account(acc: dict) -> int:
    with _get_db() as con:
        max_order_row = con.execute(
            "SELECT MAX(ordo) AS max_ordo FROM konto"
        ).fetchone()
        next_order = int(max_order_row["max_ordo"] or 0) + 1
        cur = con.execute(
            """INSERT INTO konto
               (ordo, nomo, retposto, imap_servilo, imap_haveno, imap_ssl,
                smtp_servilo, smtp_haveno, smtp_tls, uzantonomo, kreita_je)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                next_order,
                acc["nomo"],
                acc["retposto"].strip(),
                acc["imap_servilo"].strip(),
                acc.get("imap_haveno", 993),
                int(acc.get("imap_ssl", True)),
                acc["smtp_servilo"].strip(),
                acc.get("smtp_haveno", 587),
                int(acc.get("smtp_tls", True)),
                (acc.get("uzantonomo") or acc["retposto"]).strip(),
                acc.get("kreita_je") or _now_iso(),
            ),
        )
        return cur.lastrowid  # type: ignore[return-value]


_KONTO_UPDATABLE_COLS: frozenset[str] = frozenset({
    "nomo", "imap_servilo", "imap_haveno", "imap_ssl",
    "smtp_servilo", "smtp_haveno", "smtp_tls", "uzantonomo", "subskribo",
})


def _update_account(account_id: int, fields: dict) -> None:
    """Update selected fields of an existing account."""
    if not fields:
        return
    invalid = set(fields) - _KONTO_UPDATABLE_COLS
    if invalid:
        raise ValueError(f"Disallowed column(s) in _update_account: {invalid}")
    # Coerce port values to int when present
    for port_col in ("imap_haveno", "smtp_haveno"):
        if port_col in fields:
            try:
                fields[port_col] = int(fields[port_col])
            except (ValueError, TypeError):
                pass
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [account_id]
    # Column names come exclusively from _KONTO_UPDATABLE_COLS (checked above),
    # so the f-string interpolation is safe from SQL injection.
    with _get_db() as con:
        con.execute(f"UPDATE konto SET {set_clause} WHERE id = ?", values)


def _delete_account(account_id: int) -> None:
    with _get_db() as con:
        con.execute("DELETE FROM konto WHERE id = ?", (account_id,))
    try:
        keyring.delete_password(_KEYRING_SERVICE, str(account_id))
    except keyring.errors.PasswordDeleteError:
        pass  # password was never stored — that's fine


def _move_account_order(account_id: int, direction: int) -> bool:
    """Move account ordering up/down by one step. Returns True if moved."""
    if direction not in (-1, 1):
        raise ValueError("direction must be -1 or 1")
    with _get_db() as con:
        rows = con.execute(
            "SELECT id, ordo FROM konto ORDER BY ordo ASC, id ASC"
        ).fetchall()
        ordered = [dict(r) for r in rows]
        idx = next(
            (i for i, row in enumerate(ordered) if row["id"] == account_id),
            None,
        )
        if idx is None:
            return False
        swap_idx = idx + direction
        if swap_idx < 0 or swap_idx >= len(ordered):
            return False
        cur = ordered[idx]
        other = ordered[swap_idx]
        con.execute(
            "UPDATE konto SET ordo = ? WHERE id = ?",
            (other["ordo"], cur["id"]),
        )
        con.execute(
            "UPDATE konto SET ordo = ? WHERE id = ?",
            (cur["ordo"], other["id"]),
        )
    return True


def _get_password(account_id: int) -> str:
    pw = keyring.get_password(_KEYRING_SERVICE, str(account_id))
    return pw or ""


def _set_password(account_id: int, password: str) -> None:
    keyring.set_password(_KEYRING_SERVICE, str(account_id), password)


# ──────────────────────────────────────────────────────────────────────────────
# Folder helpers
# ──────────────────────────────────────────────────────────────────────────────


def _load_folders(account_id: int) -> list[dict]:
    with _get_db() as con:
        rows = con.execute(
            "SELECT * FROM dosierujo WHERE konto_id = ? ORDER BY id ASC",
            (account_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def _ensure_folder(account_id: int, nomo: str, server_nomo: str | None = None,
                   patro_id: int | None = None) -> int:
    """Return folder id, creating if absent."""
    with _get_db() as con:
        row = con.execute(
            "SELECT id FROM dosierujo WHERE konto_id=? AND nomo=? AND patro_id IS ?",
            (account_id, nomo, patro_id),
        ).fetchone()
        if row:
            return int(row["id"])
        cur = con.execute(
            "INSERT INTO dosierujo"
            " (konto_id, nomo, patro_id, server_nomo) VALUES (?,?,?,?)",
            (account_id, nomo, patro_id, server_nomo or nomo),
        )
        return cur.lastrowid  # type: ignore[return-value]


def _find_folder_by_name(account_id: int, nomo: str) -> dict | None:
    with _get_db() as con:
        row = con.execute(
            "SELECT * FROM dosierujo WHERE konto_id = ? AND nomo = ? ORDER BY id ASC",
            (account_id, nomo),
        ).fetchone()
    return dict(row) if row else None


def _rename_folder(folder_id: int, nova_nomo: str) -> None:
    with _get_db() as con:
        con.execute(
            "UPDATE dosierujo SET nomo = ? WHERE id = ?",
            (nova_nomo, folder_id),
        )


def _move_folder(folder_id: int, nova_patro_id: int | None) -> None:
    if nova_patro_id == folder_id:
        raise ValueError("Folder cannot be moved under itself.")
    with _get_db() as con:
        con.execute(
            "UPDATE dosierujo SET patro_id = ? WHERE id = ?",
            (nova_patro_id, folder_id),
        )


# ──────────────────────────────────────────────────────────────────────────────
# Message helpers
# ──────────────────────────────────────────────────────────────────────────────


def _load_messages(
    konto_id: int | None = None,
    dosierujo_id: int | None = None,
    spamo: bool = False,
    forigita: bool = False,
    legita: int | None = None,
    limit: int = 200,
    coalesce_threads: bool = False,
) -> list[dict]:
    clauses = ["forigita = ?", "spamo = ?"]
    params: list = [int(forigita), int(spamo)]
    if konto_id is not None:
        clauses.append("konto_id = ?")
        params.append(konto_id)
    if dosierujo_id is not None:
        clauses.append("dosierujo_id = ?")
        params.append(dosierujo_id)
    if legita is not None:
        clauses.append("legita = ?")
        params.append(legita)
    where = " AND ".join(clauses)
    params.append(limit)
    with _get_db() as con:
        rows = con.execute(
            f"SELECT * FROM mesago WHERE {where} ORDER BY ricevita_je DESC LIMIT ?",
            params,
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        for col in ("al", "cc", "bcc", "aldonajoj", "etikedoj"):
            try:
                d[col] = json.loads(d[col] or "[]")
            except (json.JSONDecodeError, TypeError):
                d[col] = []
        result.append(d)
    if coalesce_threads:
        return _coalesce_messages(result)
    return result


def _coalesce_messages(messages: list[dict]) -> list[dict]:
    """Return one representative (latest) message per conversation."""
    def _thread_root(msg: dict) -> str:
        refs = (msg.get("references_hdr") or "").strip().split()
        if refs:
            return refs[0]
        if msg.get("in_reply_to"):
            return str(msg["in_reply_to"])
        if msg.get("message_id"):
            return str(msg["message_id"])
        subject_key = _normalize_subject_for_thread(msg.get("subjekto"))
        if subject_key:
            return f"subj:{subject_key}"
        return f"id:{msg.get('id')}"

    groups: dict[str, list[dict]] = {}
    for msg in messages:
        key = _thread_root(msg)
        groups.setdefault(key, []).append(msg)
    merged: list[dict] = []
    for grouped in groups.values():
        grouped.sort(
            key=lambda item: item.get("ricevita_je") or item.get("kreita_je") or "",
            reverse=True,
        )
        rep = dict(grouped[0])
        rep["_thread_count"] = len(grouped)
        rep["_thread_ids"] = [int(m["id"]) for m in grouped if m.get("id") is not None]
        merged.append(rep)
    merged.sort(
        key=lambda item: item.get("ricevita_je") or item.get("kreita_je") or "",
        reverse=True,
    )
    return merged


def _save_message(msg: dict) -> int:
    with _get_db() as con:
        # Check for duplicate by message_id
        if msg.get("message_id"):
            existing = con.execute(
                "SELECT id FROM mesago WHERE message_id = ? AND konto_id = ?",
                (msg["message_id"], msg["konto_id"]),
            ).fetchone()
            if existing:
                return int(existing["id"])
        cur = con.execute(
            """INSERT OR IGNORE INTO mesago
               (uuid, konto_id, dosierujo_id, message_id, in_reply_to,
                references_hdr, uid, de, al, cc, bcc,
                 subjekto, korpo, html_korpo, prioritato, legita, stelo, spamo,
                 forigita, aldonajoj, etikedoj, ricevita_je, kreita_je)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                msg.get("uuid") or _make_uuid(),
                msg["konto_id"],
                msg.get("dosierujo_id"),
                msg.get("message_id"),
                msg.get("in_reply_to"),
                msg.get("references_hdr"),
                msg.get("uid"),
                msg.get("de"),
                json.dumps(msg.get("al") or [], ensure_ascii=False),
                json.dumps(msg.get("cc") or [], ensure_ascii=False),
                json.dumps(msg.get("bcc") or [], ensure_ascii=False),
                msg.get("subjekto"),
                msg.get("korpo"),
                msg.get("html_korpo"),
                msg.get("prioritato", 5),
                int(msg.get("legita", False)),
                int(msg.get("stelo", False)),
                int(msg.get("spamo", False)),
                int(msg.get("forigita", False)),
                json.dumps(msg.get("aldonajoj") or [], ensure_ascii=False),
                json.dumps(msg.get("etikedoj") or [], ensure_ascii=False),
                msg.get("ricevita_je"),
                msg.get("kreita_je") or _now_iso(),
            ),
        )
        return cur.lastrowid  # type: ignore[return-value]


def _update_message_field(msg_id: int, **fields: object) -> None:
    if not fields:
        return
    invalid = set(fields) - _MSG_UPDATABLE_COLS
    if invalid:
        raise ValueError(f"Disallowed column(s) in _update_message_field: {invalid}")
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [msg_id]
    with _get_db() as con:
        con.execute(f"UPDATE mesago SET {set_clause} WHERE id = ?", values)


def _delete_message(msg_id: int, permanent: bool = False) -> None:
    with _get_db() as con:
        if permanent:
            con.execute("DELETE FROM mesago WHERE id = ?", (msg_id,))
        else:
            row = con.execute(
                "SELECT konto_id FROM mesago WHERE id = ?", (msg_id,)
            ).fetchone()
            if row is None:
                return
            trash_folder_id = _ensure_folder(int(row["konto_id"]), "Trash", "Trash")
            con.execute(
                "UPDATE mesago SET dosierujo_id = ?, forigita = 0 WHERE id = ?",
                (trash_folder_id, msg_id),
            )


def _copy_message(msg_id: int, konto_id: int, dosierujo_id: int) -> int | None:
    """Copy a message to another folder/account and return new message id."""
    with _get_db() as con:
        row = con.execute("SELECT * FROM mesago WHERE id = ?", (msg_id,)).fetchone()
        if row is None:
            return None
        cur = con.execute(
            """INSERT INTO mesago
               (uuid, konto_id, dosierujo_id, message_id, in_reply_to,
                references_hdr, uid, de, al, cc, bcc,
                subjekto, korpo, html_korpo, prioritato, legita, stelo, spamo,
                forigita, aldonajoj, etikedoj, ricevita_je, kreita_je)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                _make_uuid(),
                konto_id,
                dosierujo_id,
                None,
                row["in_reply_to"],
                row["references_hdr"],
                None,
                row["de"],
                row["al"],
                row["cc"],
                row["bcc"],
                row["subjekto"],
                row["korpo"],
                row["html_korpo"],
                row["prioritato"],
                row["legita"],
                row["stelo"],
                row["spamo"],
                0,
                row["aldonajoj"],
                row["etikedoj"],
                row["ricevita_je"],
                _now_iso(),
            ),
        )
        return int(cur.lastrowid)


# ──────────────────────────────────────────────────────────────────────────────
# Contact helpers
# ──────────────────────────────────────────────────────────────────────────────


def _load_contacts() -> list[dict]:
    with _get_db() as con:
        rows = con.execute(
            "SELECT * FROM kontakto ORDER BY nomo ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def _find_contact(query: str) -> list[dict]:
    """Search contacts by name or email (partial match)."""
    pat = f"%{query}%"
    with _get_db() as con:
        rows = con.execute(
            "SELECT * FROM kontakto"
            " WHERE nomo LIKE ? OR retposto LIKE ? ORDER BY nomo ASC",
            (pat, pat),
        ).fetchall()
    return [dict(r) for r in rows]


_KONTAKTO_UPDATABLE_COLS: frozenset[str] = frozenset(
    {"nomo", "organizo", "telefono", "noto", "modifita_je"}
)


def _upsert_contact(retposto: str, nomo: str | None = None,
                    organizo: str | None = None,
                    telefono: str | None = None,
                    noto: str | None = None) -> None:
    """Insert or update a contact by email address."""
    now = _now_iso()
    with _get_db() as con:
        existing = con.execute(
            "SELECT id FROM kontakto WHERE retposto = ?", (retposto,)
        ).fetchone()
        if existing:
            # Only include fields explicitly provided by the caller.
            # Keys are drawn from _KONTAKTO_UPDATABLE_COLS (literal strings),
            # never from untrusted input — but we validate anyway.
            update_fields: dict[str, object] = {"modifita_je": now}
            if nomo is not None:
                update_fields["nomo"] = nomo
            if organizo is not None:
                update_fields["organizo"] = organizo
            if telefono is not None:
                update_fields["telefono"] = telefono
            if noto is not None:
                update_fields["noto"] = noto
            invalid = set(update_fields) - _KONTAKTO_UPDATABLE_COLS
            if invalid:
                raise ValueError(
                    f"Disallowed column(s) in _upsert_contact: {invalid}"
                )
            set_clause = ", ".join(f"{k} = ?" for k in update_fields)
            con.execute(
                f"UPDATE kontakto SET {set_clause} WHERE retposto = ?",
                [*update_fields.values(), retposto],
            )
        else:
            con.execute(
                """INSERT INTO kontakto
                   (uuid, nomo, retposto, organizo, telefono, noto,
                    kreita_je, modifita_je)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (_make_uuid(), nomo, retposto, organizo, telefono, noto,
                 now, now),
            )


def _delete_contact(contact_id: int) -> None:
    with _get_db() as con:
        con.execute("DELETE FROM kontakto WHERE id = ?", (contact_id,))


# ──────────────────────────────────────────────────────────────────────────────
# Spam / block helpers
# ──────────────────────────────────────────────────────────────────────────────


def _load_spam_blocks() -> list[dict]:
    with _get_db() as con:
        rows = con.execute(
            "SELECT * FROM spamo_bloko ORDER BY kreita_je ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def _add_spam_block(rule: str) -> None:
    with _get_db() as con:
        con.execute(
            "INSERT OR IGNORE INTO spamo_bloko (regulo, kreita_je) VALUES (?,?)",
            (rule.lower().strip(), _now_iso()),
        )


def _remove_spam_block(rule: str) -> None:
    with _get_db() as con:
        con.execute(
            "DELETE FROM spamo_bloko WHERE regulo = ?", (rule.lower().strip(),)
        )


def _is_spam(sender: str) -> bool:
    """Check if sender matches any spam block rule."""
    sender_lower = sender.lower()
    blocks = _load_spam_blocks()
    for b in blocks:
        rule = b["regulo"]
        if rule in sender_lower:
            return True
    return False


# ──────────────────────────────────────────────────────────────────────────────
# Filter (Sieve-style) helpers
# ──────────────────────────────────────────────────────────────────────────────

_SIEVE_COND_RE = re.compile(
    r'(?P<field>from|to|subject|body)\s+'
    r'(?P<neg>not\s+)?'
    r'(?P<op>contains|is)\s+'
    r'"(?P<value>[^"]*)"',
    re.IGNORECASE,
)

_SIEVE_ACTION_RE = re.compile(
    r'(?P<action>fileinto|discard|mark-spam|mark-read|set-priority)\s*'
    r'(?:"(?P<arg>[^"]*)")?',
    re.IGNORECASE,
)


def _load_filters() -> list[dict]:
    with _get_db() as con:
        rows = con.execute(
            "SELECT * FROM filtro WHERE aktiva = 1 ORDER BY ordo ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def _save_filter(nomo: str, sieve_kodo: str, ordo: int = 0) -> None:
    with _get_db() as con:
        con.execute(
            """INSERT INTO filtro (nomo, sieve_kodo, aktiva, ordo, kreita_je)
               VALUES (?,?,1,?,?)
               ON CONFLICT(nomo) DO UPDATE SET sieve_kodo=excluded.sieve_kodo,
               ordo=excluded.ordo""",
            (nomo, sieve_kodo, ordo, _now_iso()),
        )


def _delete_filter(nomo: str) -> None:
    with _get_db() as con:
        con.execute("DELETE FROM filtro WHERE nomo = ?", (nomo,))


def _apply_filters(msg: dict, filters: list[dict]) -> dict:
    """Apply local Sieve-style filters to a message dict in place."""
    body_text = (msg.get("korpo") or "").lower()
    subj = (msg.get("subjekto") or "").lower()
    sender = (msg.get("de") or "").lower()
    recipients = " ".join(msg.get("al") or []).lower()

    for f in filters:
        try:
            cond, action_part = f["sieve_kodo"].split("=>", 1)
        except ValueError:
            continue
        cond = cond.strip()
        action_part = action_part.strip()

        if not _eval_sieve_condition(cond, sender, recipients, subj, body_text):
            continue

        am = _SIEVE_ACTION_RE.match(action_part)
        if not am:
            continue
        action = am.group("action").lower()
        arg = am.group("arg") or ""

        if action == "fileinto":
            msg["_filter_folder"] = arg
        elif action == "discard":
            msg["forigita"] = 1
        elif action == "mark-spam":
            msg["spamo"] = 1
        elif action == "mark-read":
            msg["legita"] = 1
        elif action == "set-priority":
            try:
                msg["prioritato"] = max(1, min(10, int(arg)))
            except ValueError:
                pass

    return msg


def _eval_sieve_condition(cond: str, sender: str, recipients: str,
                          subject: str, body: str) -> bool:
    """Evaluate a simple Sieve-like condition string."""
    field_map = {
        "from": sender,
        "to": recipients,
        "subject": subject,
        "body": body,
    }
    for m in _SIEVE_COND_RE.finditer(cond):
        field_val = field_map.get(m.group("field").lower(), "")
        negate = bool(m.group("neg"))
        op = m.group("op").lower()
        value = m.group("value").lower()
        if op == "contains":
            match = value in field_val
        else:  # "is"
            match = field_val == value
        if negate:
            match = not match
        if not match:
            return False
    return True


# ──────────────────────────────────────────────────────────────────────────────
# Email parsing helpers
# ──────────────────────────────────────────────────────────────────────────────


def _decode_header(value: str | None) -> str:
    """Decode an RFC 2047-encoded header value to a plain string."""
    if not value:
        return ""
    parts = email.header.decode_header(value)
    decoded: list[str] = []
    for bpart, charset in parts:
        if isinstance(bpart, bytes):
            try:
                decoded.append(bpart.decode(charset or "utf-8", errors="replace"))
            except (LookupError, UnicodeDecodeError):
                decoded.append(bpart.decode("utf-8", errors="replace"))
        else:
            decoded.append(bpart)
    return "".join(decoded)


def _extract_address(raw: str | None) -> str:
    """Return just the email address from a From/To header value."""
    if not raw:
        return ""
    m = re.search(r"<([^>]+)>", raw)
    if m:
        return m.group(1).strip().lower()
    return raw.strip().strip("<>").lower()


def _extract_address_list(raw: str | None) -> list[str]:
    """Parse a comma-separated address list header."""
    if not raw:
        return []
    # Split on commas not inside angle brackets
    parts = re.split(r",\s*(?![^<]*>)", raw)
    return [_extract_address(p) for p in parts if p.strip()]


def _parse_imap_message(raw_bytes: bytes, konto_id: int,
                        dosierujo_id: int | None,
                        uid: str | None = None) -> dict:
    """Parse a raw RFC 5322 message into a retposto message dict."""
    msg = _email_mod.message_from_bytes(
        raw_bytes, policy=_email_mod.policy.compat32
    )

    sender = _decode_header(msg.get("From"))
    al_raw = _decode_header(msg.get("To", ""))
    cc_raw = _decode_header(msg.get("Cc", ""))
    subject = _decode_header(msg.get("Subject"))
    date_str = msg.get("Date", "")
    message_id = (msg.get("Message-ID") or "").strip()
    in_reply_to = (msg.get("In-Reply-To") or "").strip()
    references_hdr = (msg.get("References") or "").strip()

    # Parse date
    ricevita_je: str | None = None
    try:
        from email.utils import parsedate_to_datetime
        ricevita_je = parsedate_to_datetime(date_str).isoformat()
    except Exception:
        pass

    # Extract body
    korpo: str | None = None
    html_korpo: str | None = None
    aldonajoj: list[str] = []

    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            disp = str(part.get("Content-Disposition") or "")
            if "attachment" in disp:
                filename = part.get_filename() or "attachment"
                aldonajoj.append(_decode_header(filename))
            elif ct == "text/plain" and korpo is None:
                payload = part.get_payload(decode=True)
                if isinstance(payload, bytes):
                    charset = part.get_content_charset() or "utf-8"
                    korpo = payload.decode(charset, errors="replace")
            elif ct == "text/html" and html_korpo is None:
                payload = part.get_payload(decode=True)
                if isinstance(payload, bytes):
                    charset = part.get_content_charset() or "utf-8"
                    html_korpo = payload.decode(charset, errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        if isinstance(payload, bytes):
            charset = msg.get_content_charset() or "utf-8"
            korpo = payload.decode(charset, errors="replace")

    return {
        "uuid": _make_uuid(),
        "konto_id": konto_id,
        "dosierujo_id": dosierujo_id,
        "message_id": message_id or None,
        "in_reply_to": in_reply_to or None,
        "references_hdr": references_hdr or None,
        "uid": uid,
        "de": _extract_address(sender),
        "al": _extract_address_list(al_raw),
        "cc": _extract_address_list(cc_raw),
        "bcc": [],
        "subjekto": subject,
        "korpo": korpo,
        "html_korpo": html_korpo,
        "prioritato": 5,
        "legita": 0,
        "stelo": 0,
        "spamo": 0,
        "forigita": 0,
        "aldonajoj": aldonajoj,
        "etikedoj": [],
        "ricevita_je": ricevita_je,
        "kreita_je": _now_iso(),
    }


# ──────────────────────────────────────────────────────────────────────────────
# IMAP fetch
# ──────────────────────────────────────────────────────────────────────────────


def _fetch_account_mail(acc: dict, max_msgs: int = 100) -> tuple[int, int]:
    """Fetch unseen mail for one account. Returns (fetched, skipped)."""
    password = _get_password(acc["id"])
    if not password:
        typer.echo(
            f"[!] No password stored for {acc['retposto']}. "
            "Use: retposto aldoni-konton",
            err=True,
        )
        return 0, 0

    login = acc.get("uzantonomo") or acc["retposto"]
    host = acc["imap_servilo"]
    port = acc.get("imap_haveno", 993)
    use_ssl = bool(acc.get("imap_ssl", True))

    filters = _load_filters()

    try:
        if use_ssl:
            ctx = ssl.create_default_context()
            imap = imaplib.IMAP4_SSL(host, port, ssl_context=ctx)
        else:
            imap = imaplib.IMAP4(host, port)

        imap.login(login, password)

        # Enumerate server folders and sync INBOX + others
        status, folder_list = imap.list()
        server_folders: list[str] = ["INBOX"]
        if status == "OK":
            for item in folder_list or []:
                if isinstance(item, bytes):
                    m = re.search(rb'"/" "?([^"]+)"?$', item)
                    if m:
                        fname = m.group(1).decode("utf-8", errors="replace").strip()
                        if fname not in server_folders:
                            server_folders.append(fname)

        fetched = skipped = 0
        for sfolder in server_folders[:_MAX_FOLDERS_PER_ACCOUNT]:
            try:
                status, _data = imap.select(sfolder, readonly=True)
            except imaplib.IMAP4.error:
                continue
            if status != "OK":
                continue

            folder_id = _ensure_folder(acc["id"], sfolder, sfolder)

            _, data = imap.search(None, "ALL")
            uids_raw = (data[0] or b"").split()
            # take the most recent max_msgs
            recent_uids = uids_raw[-max_msgs:]
            for uid_bytes in recent_uids:
                uid = uid_bytes.decode()
                _, msg_data = imap.fetch(uid, "(RFC822)")
                if not msg_data or not msg_data[0]:
                    skipped += 1
                    continue
                raw = msg_data[0][1] if isinstance(msg_data[0], tuple) else None
                if not isinstance(raw, bytes):
                    skipped += 1
                    continue
                parsed = _parse_imap_message(raw, acc["id"], folder_id, uid)

                # Spam check
                if _is_spam(parsed.get("de") or ""):
                    parsed["spamo"] = 1

                # Auto-save contact from sender
                sender_addr = parsed.get("de") or ""
                if sender_addr and "@" in sender_addr:
                    _upsert_contact(sender_addr)

                # Apply local filters
                parsed = _apply_filters(parsed, filters)

                # Handle filter folder redirect
                if "_filter_folder" in parsed:
                    ff = parsed.pop("_filter_folder")
                    parsed["dosierujo_id"] = _ensure_folder(acc["id"], ff, ff)

                _save_message(parsed)
                fetched += 1

        imap.logout()
        return fetched, skipped

    except (imaplib.IMAP4.error, OSError, ssl.SSLError) as exc:
        typer.echo(f"[!] IMAP error for {acc['retposto']}: {exc}", err=True)
        return 0, 0


# ──────────────────────────────────────────────────────────────────────────────
# SMTP send
# ──────────────────────────────────────────────────────────────────────────────


def _send_message(
    acc: dict,
    al: list[str],
    subjekto: str,
    korpo: str,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    html_korpo: str | None = None,
    in_reply_to: str | None = None,
    references_hdr: str | None = None,
) -> bool:
    """Send an email via SMTP. Returns True on success."""
    password = _get_password(acc["id"])
    if not password:
        typer.echo(
            f"[!] No password stored for {acc['retposto']}.", err=True
        )
        return False

    login = acc.get("uzantonomo") or acc["retposto"]
    host = acc["smtp_servilo"]
    port = acc.get("smtp_haveno", 587)
    use_tls = bool(acc.get("smtp_tls", True))

    mime = MIMEMultipart("alternative")
    mime["From"] = f"{acc['nomo']} <{acc['retposto']}>"
    mime["To"] = ", ".join(al)
    mime["Subject"] = subjekto
    msg_id = make_msgid(domain=(acc.get("retposto", "").split("@")[-1] or None))
    mime["Message-ID"] = msg_id
    if in_reply_to:
        mime["In-Reply-To"] = in_reply_to
    if references_hdr:
        mime["References"] = references_hdr
    if cc:
        mime["Cc"] = ", ".join(cc)
    mime.attach(MIMEText(korpo, "plain", "utf-8"))
    if html_korpo:
        mime.attach(MIMEText(html_korpo, "html", "utf-8"))

    recipients = al + (cc or []) + (bcc or [])

    try:
        ctx = ssl.create_default_context()
        if use_tls:
            with smtplib.SMTP(host, port, timeout=30) as smtp:
                smtp.ehlo()
                smtp.starttls(context=ctx)
                smtp.login(login, password)
                smtp.sendmail(acc["retposto"], recipients, mime.as_string())
        else:
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=30) as smtp:
                smtp.login(login, password)
                smtp.sendmail(acc["retposto"], recipients, mime.as_string())

        # Save to Sent folder
        sent_folder_id = _ensure_folder(acc["id"], "Sent", "Sent")
        _save_message({
            "konto_id": acc["id"],
            "dosierujo_id": sent_folder_id,
            "message_id": msg_id,
            "in_reply_to": in_reply_to,
            "references_hdr": references_hdr,
            "de": acc["retposto"],
            "al": al,
            "cc": cc or [],
            "bcc": bcc or [],
            "subjekto": subjekto,
            "korpo": korpo,
            "legita": 1,
            "ricevita_je": _now_iso(),
        })
        # Auto-save recipients as contacts
        for addr in recipients:
            if "@" in addr:
                _upsert_contact(addr)

        return True

    except (smtplib.SMTPException, OSError, ssl.SSLError) as exc:
        typer.echo(f"[!] SMTP error: {exc}", err=True)
        return False


def _load_text_from_path_or_url(source: str) -> str:
    src = source.strip()
    if src.startswith(("http://", "https://")):
        with urllib.request.urlopen(src, timeout=10) as resp:  # noqa: S310
            return resp.read().decode("utf-8", errors="replace")
    return Path(src).expanduser().read_text(encoding="utf-8", errors="replace")


def _strip_html_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html)


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


def _infer_mail_config(email_addr: str) -> dict[str, object] | None:
    if "@" not in email_addr:
        return None
    domain = email_addr.rsplit("@", 1)[1].strip().lower()
    if not domain:
        return None
    return _EMAIL_DOMAIN_CONFIGS.get(domain)


def _normalize_subject_for_thread(subject: str | None) -> str:
    text = (subject or "").strip().lower()
    while True:
        updated = re.sub(r"^(re|fwd|fw)\s*:\s*", "", text, flags=re.IGNORECASE)
        if updated == text:
            break
        text = updated.strip()
    return text


def _thread_tokens(msg: dict) -> set[str]:
    tokens: set[str] = set()
    for key in ("message_id", "in_reply_to", "references_hdr"):
        raw = (msg.get(key) or "").strip()
        if not raw:
            continue
        for token in raw.split():
            clean = token.strip()
            if clean:
                tokens.add(clean)
    return tokens


def _load_conversation_messages(msg: dict) -> list[dict]:
    konto_id = msg.get("konto_id")
    if konto_id is None:
        return [msg]
    with _get_db() as con:
        rows = con.execute(
            (
                "SELECT * FROM mesago WHERE konto_id = ? "
                "ORDER BY COALESCE(ricevita_je, kreita_je) ASC"
            ),
            (konto_id,),
        ).fetchall()
    messages = [dict(r) for r in rows]
    for item in messages:
        for col in ("al", "cc", "bcc", "aldonajoj", "etikedoj"):
            try:
                item[col] = json.loads(item[col] or "[]")
            except (json.JSONDecodeError, TypeError):
                item[col] = []

    tokens_by_id: dict[int, set[str]] = {
        int(item["id"]): _thread_tokens(item)
        for item in messages
        if item.get("id") is not None
    }
    seed_id = int(msg.get("id", -1))
    seed_tokens = tokens_by_id.get(seed_id, _thread_tokens(msg))
    if seed_tokens:
        conversation_ids: set[int] = set()
        token_frontier = set(seed_tokens)
        changed = True
        while changed:
            changed = False
            for item in messages:
                item_id = int(item.get("id", -1))
                item_tokens = tokens_by_id.get(item_id, set())
                if not item_tokens or item_id in conversation_ids:
                    continue
                if item_tokens & token_frontier:
                    conversation_ids.add(item_id)
                    token_frontier |= item_tokens
                    changed = True
        if conversation_ids:
            conv = [
                item
                for item in messages
                if int(item.get("id", -1)) in conversation_ids
            ]
            if conv:
                return conv

    base_subject = _normalize_subject_for_thread(msg.get("subjekto"))
    if not base_subject:
        return [msg]
    conv = [
        item
        for item in messages
        if _normalize_subject_for_thread(item.get("subjekto")) == base_subject
    ]
    return conv or [msg]


def _reply_targets(
    account_email: str, msg: dict, *, reply_all: bool = False
) -> tuple[list[str], list[str]]:
    me = (account_email or "").strip().lower()
    sender = (msg.get("de") or "").strip().lower()
    to_list = [(x or "").strip().lower() for x in (msg.get("al") or []) if x]
    cc_list = [(x or "").strip().lower() for x in (msg.get("cc") or []) if x]

    if sender and sender != me:
        primary = sender
    else:
        primary = next((addr for addr in to_list if addr and addr != me), "")

    if not primary:
        return ([], [])

    if not reply_all:
        return ([primary], [])

    to_targets: list[str] = [primary]
    for addr in to_list:
        if addr and addr != me and addr not in to_targets:
            to_targets.append(addr)

    cc_targets: list[str] = []
    for addr in cc_list:
        if addr and addr != me and addr not in to_targets and addr not in cc_targets:
            cc_targets.append(addr)

    return (to_targets, cc_targets)


def _parse_cli_uid(uid_text: str, accounts: list[dict]) -> tuple[int, str]:
    compact = uid_text.strip()
    if not compact.isdigit():
        raise ValueError("UID devas esti ciferoj.")
    for idx in range(len(accounts), 0, -1):
        prefix = str(idx)
        if compact.startswith(prefix) and len(compact) > len(prefix):
            return int(accounts[idx - 1]["id"]), compact[len(prefix):]
    raise ValueError("Nevalida UID formo.")


# ──────────────────────────────────────────────────────────────────────────────
# ManageSieve upload
# ──────────────────────────────────────────────────────────────────────────────


def _build_sieve_script(filters: list[dict]) -> str:
    """Build a Sieve script from local filter definitions."""
    lines = ['require ["fileinto", "imap4flags"];', ""]
    for f in filters:
        try:
            cond_str, action_str = f["sieve_kodo"].split("=>", 1)
        except ValueError:
            continue
        cond_str = cond_str.strip()
        action_str = action_str.strip()

        # Build Sieve condition
        sieve_conds: list[str] = []
        for m in _SIEVE_COND_RE.finditer(cond_str):
            field = m.group("field").lower()
            negate = bool(m.group("neg"))
            op = m.group("op").lower()
            val = m.group("value")
            sieve_field = {
                "from": "from", "to": "to",
                "subject": "subject", "body": "body",
            }.get(field, field)
            sieve_op = ":contains" if op == "contains" else ":is"
            test = f'header {sieve_op} "{sieve_field}" "{val}"'
            if negate:
                test = f"not {test}"
            sieve_conds.append(test)

        if not sieve_conds:
            continue
        cond_part = (
            sieve_conds[0]
            if len(sieve_conds) == 1
            else "allof(" + ", ".join(sieve_conds) + ")"
        )

        # Build Sieve action
        am = _SIEVE_ACTION_RE.match(action_str)
        if not am:
            continue
        action = am.group("action").lower()
        arg = am.group("arg") or ""
        if action == "fileinto":
            sieve_action = f'fileinto "{arg}";'
        elif action == "discard":
            sieve_action = "discard;"
        elif action == "mark-spam":
            sieve_action = 'addflag "\\\\Junk";'
        elif action == "mark-read":
            sieve_action = 'addflag "\\\\Seen";'
        else:
            continue

        lines.append(f"if {cond_part} {{")
        lines.append(f"  {sieve_action}")
        lines.append("}")

    return "\n".join(lines)


def _upload_sieve(acc: dict, sieve_script: str,
                  sieve_host: str | None = None,
                  sieve_port: int = 4190) -> bool:
    """Upload a Sieve script via ManageSieve protocol. Returns True on success."""
    try:
        import managesieve  # type: ignore[import-untyped]
    except ImportError:
        typer.echo(
            "[!] managesieve package not installed. "
            "Add it to pyproject.toml: managesieve = \"*\"",
            err=True,
        )
        return False

    password = _get_password(acc["id"])
    host = sieve_host or acc["imap_servilo"]
    login = acc.get("uzantonomo") or acc["retposto"]
    try:
        sieve = managesieve.MANAGESIEVE(host, sieve_port)
        sieve.authenticate("PLAIN", login, password)
        sieve.putscript("autish-retposto", sieve_script)
        sieve.setactive("autish-retposto")
        sieve.logout()
        return True
    except Exception as exc:
        typer.echo(f"[!] ManageSieve error: {exc}", err=True)
        return False


# ──────────────────────────────────────────────────────────────────────────────
# VCF import / export
# ──────────────────────────────────────────────────────────────────────────────


def _import_vcf(vcf_path: Path) -> int:
    """Import contacts from a VCF file. Returns count imported."""
    text = vcf_path.read_text(encoding="utf-8", errors="replace")
    count = 0
    for vcard in vobject.readComponents(text):
        try:
            email_addr = ""
            if hasattr(vcard, "email"):
                email_addr = str(vcard.email.value).lower().strip()
            if not email_addr or "@" not in email_addr:
                continue
            nomo = ""
            if hasattr(vcard, "fn"):
                nomo = str(vcard.fn.value).strip()
            organizo = ""
            if hasattr(vcard, "org"):
                org_val = vcard.org.value
                if isinstance(org_val, list):
                    organizo = ";".join(str(x) for x in org_val)
                else:
                    organizo = str(org_val)
            telefono = ""
            if hasattr(vcard, "tel"):
                telefono = str(vcard.tel.value).strip()
            _upsert_contact(email_addr, nomo or None, organizo or None,
                            telefono or None)
            count += 1
        except Exception:
            continue
    return count


def _export_vcf(vcf_path: Path) -> int:
    """Export all contacts to a VCF file. Returns count exported."""
    contacts = _load_contacts()
    cards: list[str] = []
    for c in contacts:
        vc = vobject.vCard()
        vc.add("fn").value = c.get("nomo") or c["retposto"]
        vc.add("email").value = c["retposto"]
        if c.get("organizo"):
            vc.add("org").value = [c["organizo"]]
        if c.get("telefono"):
            vc.add("tel").value = c["telefono"]
        cards.append(vc.serialize())
    vcf_path.write_text("".join(cards), encoding="utf-8")
    return len(contacts)


# ──────────────────────────────────────────────────────────────────────────────
# CLI subcommands
# ──────────────────────────────────────────────────────────────────────────────


@app.callback(invoke_without_command=True)
def retposto_main(ctx: typer.Context) -> None:
    """Retpoŝto — TUI email microapp. Launch interactive TUI if no subcommand."""
    if ctx.invoked_subcommand is None:
        _launch_tui()


def _launch_tui() -> None:
    """Launch the curses TUI."""
    import curses

    from autish.commands._retposto_tui import RetpostoTUI

    def _run(stdscr: object) -> None:
        tui = RetpostoTUI(
            stdscr,  # type: ignore[arg-type]
            load_accounts=_load_accounts,
            load_messages=_load_messages,
            load_folders=_load_folders,
            fetch_account_mail=_fetch_account_mail,
            send_message=_send_message,
            save_message=_save_message,
            update_message_field=_update_message_field,
            delete_message=_delete_message,
            load_contacts=_load_contacts,
            find_contact=_find_contact,
            upsert_contact=_upsert_contact,
            load_filters=_load_filters,
            add_spam_block=_add_spam_block,
            is_spam=_is_spam,
            ensure_folder=_ensure_folder,
            save_account=_save_account,
            set_password=_set_password,
            load_spam_blocks=_load_spam_blocks,
            remove_spam_block=_remove_spam_block,
            update_account=_update_account,
            load_messages_spam=_load_messages,
            copy_message=_copy_message,
            move_account_order=_move_account_order,
            rename_folder=_rename_folder,
            move_folder=_move_folder,
            load_conversation=_load_conversation_messages,
        )
        tui.run()

    curses.wrapper(_run)


@app.command("aldoni-konton")
def aldoni_konton(
    ctx: typer.Context,
    nomo: str | None = typer.Option(
        None, "-n", "--nomo", help="Display name for this account."
    ),
    retposto: str | None = typer.Option(
        None, "-r", "--retposto", help="Email address."
    ),
    imap_servilo: str | None = typer.Option(
        None, "--imap", help="IMAP server hostname."
    ),
    smtp_servilo: str | None = typer.Option(
        None, "--smtp", help="SMTP server hostname."
    ),
    imap_haveno: int = typer.Option(993, "--imap-haveno", help="IMAP port."),
    smtp_haveno: int = typer.Option(587, "--smtp-haveno", help="SMTP port."),
    imap_ssl: bool = typer.Option(True, "--imap-ssl/--no-imap-ssl"),
    smtp_tls: bool = typer.Option(True, "--smtp-tls/--no-smtp-tls"),
) -> None:
    """Add a new email account (interactive if options omitted)."""
    if not nomo:
        nomo = typer.prompt("Display name")
    if not retposto:
        retposto = typer.prompt("Email address")
    retposto = retposto.lower().strip()

    inferred = _infer_mail_config(retposto)
    if inferred and not imap_servilo and not smtp_servilo:
        imap_servilo = str(inferred["imap_servilo"])
        imap_haveno = int(inferred["imap_haveno"])
        imap_ssl = bool(inferred["imap_ssl"])
        smtp_servilo = str(inferred["smtp_servilo"])
        smtp_haveno = int(inferred["smtp_haveno"])
        smtp_tls = bool(inferred["smtp_tls"])
        typer.echo(
            "[i] Aŭtomate deduktis servilojn por ĉi tiu retpoŝta domajno. "
            "Uzu --imap/--smtp por mane ŝanĝi."
        )

    if not imap_servilo:
        imap_servilo = typer.prompt("IMAP server")
    if not smtp_servilo:
        smtp_servilo = typer.prompt("SMTP server")
    password = typer.prompt("Password", hide_input=True)

    acc = {
        "nomo": nomo,
        "retposto": retposto,
        "imap_servilo": imap_servilo,
        "imap_haveno": imap_haveno,
        "imap_ssl": imap_ssl,
        "smtp_servilo": smtp_servilo,
        "smtp_haveno": smtp_haveno,
        "smtp_tls": smtp_tls,
        "uzantonomo": retposto,
    }
    acc_id = _save_account(acc)
    _set_password(acc_id, password)
    typer.echo(f"[✓] Konto aldonis (id={acc_id}): {retposto}")


@app.command("forigi-konton")
def forigi_konton(
    id_adr: str = typer.Argument(..., help="Account id or email address.")
) -> None:
    """Remove an email account."""
    acc = _find_account(id_adr)
    if not acc:
        typer.echo(f"[!] Konto ne trovita: {id_adr}", err=True)
        raise typer.Exit(1)
    if not _confirm_esperante(
        f"Forigi konton '{acc['retposto']}'?", default_yes=False
    ):
        typer.echo("Nuligita.")
        return
    _delete_account(acc["id"])
    typer.echo(f"[✓] Konto forigita: {acc['retposto']}")


@app.command("listigi-kontojn")
def listigi_kontojn() -> None:
    """List configured email accounts."""
    accounts = _load_accounts()
    if not accounts:
        typer.echo("Neniuj kontoj konfiguritaj. Uzu: retposto aldoni-konton")
        return
    table = Table(title="Kontoj")
    table.add_column("ID", style="dim")
    table.add_column("Nomo")
    table.add_column("Retpoŝto")
    table.add_column("IMAP")
    table.add_column("SMTP")
    for a in accounts:
        table.add_row(
            str(a["id"]),
            a["nomo"],
            a["retposto"],
            f"{a['imap_servilo']}:{a['imap_haveno']}",
            f"{a['smtp_servilo']}:{a['smtp_haveno']}",
        )
    console.print(table)


@app.command("preni")
def preni(
    konto: list[str] | None = typer.Option(
        None,
        "-k",
        "--konto",
        help="Account id/email (repeat flag for multiple accounts).",
    ),
    max_msgs: int = typer.Option(
        100, "-m", "--max", help="Max messages per folder."
    ),
) -> None:
    """Fetch new mail from server(s)."""
    accounts = _load_accounts()
    if not accounts:
        typer.echo("[!] No accounts configured. Use: retposto aldoni-konton", err=True)
        raise typer.Exit(1)

    if konto:
        selected: list[dict] = []
        for ident in konto:
            acc = _find_account(ident)
            if not acc:
                typer.echo(f"[!] Account not found: {ident}", err=True)
                raise typer.Exit(1)
            selected.append(acc)
        accounts = selected

    total_f = total_s = 0
    for idx, acc in enumerate(accounts, 1):
        typer.echo(f"Por **{acc['retposto']}**")
        f, s = _fetch_account_mail(acc, max_msgs)
        typer.echo(f"  [✓] {f} nova(j), {s} preterpasita(j)")
        with _get_db() as con:
            rows = con.execute(
                "SELECT subjekto, uid FROM mesago WHERE konto_id = ? AND legita = 0 "
                "AND uid IS NOT NULL ORDER BY ricevita_je DESC LIMIT 20",
                (acc["id"],),
            ).fetchall()
        typer.echo(f"---nelegitaj retpoŝtoj por {acc['retposto']}---")
        typer.echo("**Subjekto**\t**UID**")
        for row in rows:
            subject = row["subjekto"] or "(sen subjekto)"
            uid_val = str(row["uid"])
            typer.echo(f"{subject}\t{idx}{uid_val}")
        typer.echo("---------------------------------------")
        total_f += f
        total_s += s
    typer.echo(f"\nSume: {total_f} nova(j) mesaĝo(j).")


@app.command("sendi")
def sendi(
    al: str | None = typer.Option(
        None, "-a", "--al", help="Recipient(s), comma-separated."
    ),
    subjekto: str | None = typer.Option(None, "-s", "--subjekto", help="Subject."),
    korpo: str | None = typer.Option(None, "--korpo", help="Body text."),
    html: bool = typer.Option(
        False, "--html", help="Interpret --korpo as HTML file/URL source."
    ),
    md: bool = typer.Option(
        False, "--md", help="Interpret --korpo as Markdown file/URL source."
    ),
    cc: str | None = typer.Option(None, "--cc", help="CC address(es)."),
    bcc: str | None = typer.Option(None, "--bcc", help="BCC address(es)."),
    konto: str | None = typer.Option(
        None, "-k", "--konto", help="Account id or email."
    ),
) -> None:
    """Send an email from the command line."""
    accounts = _load_accounts()
    if not accounts:
        typer.echo("[!] No accounts configured.", err=True)
        raise typer.Exit(1)

    if konto:
        acc = _find_account(konto)
        if not acc:
            typer.echo(f"[!] Account not found: {konto}", err=True)
            raise typer.Exit(1)
    else:
        if len(accounts) == 1:
            acc = accounts[0]
        else:
            for i, a in enumerate(accounts):
                typer.echo(f"  {i + 1}. {a['retposto']}")
            idx = typer.prompt("Select account (number)", type=int) - 1
            if not 0 <= idx < len(accounts):
                typer.echo("[!] Invalid selection.", err=True)
                raise typer.Exit(1)
            acc = accounts[idx]

    if not al:
        al = typer.prompt("To")
    if not subjekto:
        subjekto = typer.prompt("Subject")
    if html and md:
        typer.echo("[!] Uzu nur unu el --html aŭ --md.", err=True)
        raise typer.Exit(1)
    if not korpo:
        korpo = typer.prompt("Body")
    body_plain = korpo
    body_html: str | None = None
    if html:
        try:
            body_html = _load_text_from_path_or_url(korpo)
            body_plain = _strip_html_tags(body_html)
        except OSError as exc:
            typer.echo(f"[!] Ne povis legi HTML-fonton: {exc}", err=True)
            raise typer.Exit(1) from exc
    elif md:
        try:
            md_text = _load_text_from_path_or_url(korpo)
            import mistune

            body_html = mistune.html(md_text)
            body_plain = md_text
        except (ImportError, OSError) as exc:
            typer.echo(f"[!] Ne povis prilabori Markdown: {exc}", err=True)
            raise typer.Exit(1) from exc

    al_list = [a.strip() for a in al.split(",") if a.strip()]
    cc_list = [a.strip() for a in cc.split(",") if a.strip()] if cc else []
    bcc_list = [a.strip() for a in bcc.split(",") if a.strip()] if bcc else []

    ok = _send_message(
        acc,
        al_list,
        subjekto,
        body_plain,
        cc_list,
        bcc_list,
        html_korpo=body_html,
    )
    if ok:
        typer.echo(f"[✓] Sendita al: {', '.join(al_list)}")
    else:
        raise typer.Exit(1)


@app.command("vidi")
def vidi_mesagon(
    uid: str = typer.Argument(..., help="Composite UID from `preni` output."),
    html: bool = typer.Option(False, "--html", help="Render HTML in browser."),
) -> None:
    """View one fetched message in CLI by composite UID."""
    accounts = _load_accounts()
    if not accounts:
        typer.echo("[!] Neniuj kontoj konfiguritaj.", err=True)
        raise typer.Exit(1)
    try:
        acc_id, msg_uid = _parse_cli_uid(uid, accounts)
    except ValueError as exc:
        typer.echo(f"[!] {exc}", err=True)
        raise typer.Exit(1) from exc
    with _get_db() as con:
        row = con.execute(
            (
                "SELECT * FROM mesago WHERE konto_id = ? AND uid = ? "
                "ORDER BY id DESC LIMIT 1"
            ),
            (acc_id, msg_uid),
        ).fetchone()
    if not row:
        typer.echo(f"[!] Mesaĝo ne trovita por UID: {uid}", err=True)
        raise typer.Exit(1)
    msg = dict(row)
    if html and msg.get("html_korpo"):
        with NamedTemporaryFile(
            "w", encoding="utf-8", suffix=".html", delete=False
        ) as f:
            f.write(msg["html_korpo"])
            tmp = f.name
        webbrowser.open(f"file://{tmp}")
        typer.echo(f"[✓] Malfermis HTML en retumilo: {tmp}")
        return
    typer.echo(f"De: {msg.get('de') or ''}")
    typer.echo(f"Subjekto: {msg.get('subjekto') or ''}")
    typer.echo(f"Dato: {(msg.get('ricevita_je') or '')[:19]}")
    typer.echo("")
    typer.echo(msg.get("korpo") or _strip_html_tags(msg.get("html_korpo") or ""))


@app.command("respondi")
def respondi_mesagon(
    uid: str = typer.Argument(..., help="Composite UID from `preni` output."),
    korpo: str | None = typer.Option(None, "--korpo", help="Body text."),
    konto: str | None = typer.Option(None, "-k", "--konto", help="From account."),
) -> None:
    """Reply to one message from CLI."""
    accounts = _load_accounts()
    if not accounts:
        typer.echo("[!] Neniuj kontoj konfiguritaj.", err=True)
        raise typer.Exit(1)
    try:
        acc_id, msg_uid = _parse_cli_uid(uid, accounts)
    except ValueError as exc:
        typer.echo(f"[!] {exc}", err=True)
        raise typer.Exit(1) from exc
    with _get_db() as con:
        row = con.execute(
            (
                "SELECT * FROM mesago WHERE konto_id = ? AND uid = ? "
                "ORDER BY id DESC LIMIT 1"
            ),
            (acc_id, msg_uid),
        ).fetchone()
    if not row:
        typer.echo(f"[!] Mesaĝo ne trovita por UID: {uid}", err=True)
        raise typer.Exit(1)
    src = dict(row)
    acc = (
        _find_account(konto)
        if konto
        else next((a for a in accounts if a["id"] == acc_id), accounts[0])
    )
    if acc is None:
        typer.echo("[!] Konto ne trovita.", err=True)
        raise typer.Exit(1)
    to_targets, cc_targets = _reply_targets(acc.get("retposto", ""), src)
    if not to_targets:
        typer.echo("[!] Ne eblas determini ricevonton por respondo.", err=True)
        raise typer.Exit(1)
    body = korpo if korpo is not None else typer.prompt("Body")
    sub = "Re: " + (src.get("subjekto") or "")
    base_refs = " ".join(
        x for x in [src.get("references_hdr"), src.get("message_id")] if x
    ).strip() or None
    ok = _send_message(
        acc,
        to_targets,
        sub,
        body,
        cc_targets,
        [],
        in_reply_to=src.get("message_id"),
        references_hdr=base_refs,
    )
    if ok:
        typer.echo(f"[✓] Respondo sendita al: {', '.join(to_targets)}")
    else:
        raise typer.Exit(1)


@app.command("respondi-ciujn")
def respondi_ciujn_mesagon(
    uid: str = typer.Argument(..., help="Composite UID from `preni` output."),
    korpo: str | None = typer.Option(None, "--korpo", help="Body text."),
    konto: str | None = typer.Option(None, "-k", "--konto", help="From account."),
) -> None:
    """Reply-all to one message from CLI."""
    accounts = _load_accounts()
    if not accounts:
        typer.echo("[!] Neniuj kontoj konfiguritaj.", err=True)
        raise typer.Exit(1)
    try:
        acc_id, msg_uid = _parse_cli_uid(uid, accounts)
    except ValueError as exc:
        typer.echo(f"[!] {exc}", err=True)
        raise typer.Exit(1) from exc
    with _get_db() as con:
        row = con.execute(
            (
                "SELECT * FROM mesago WHERE konto_id = ? AND uid = ? "
                "ORDER BY id DESC LIMIT 1"
            ),
            (acc_id, msg_uid),
        ).fetchone()
    if not row:
        typer.echo(f"[!] Mesaĝo ne trovita por UID: {uid}", err=True)
        raise typer.Exit(1)
    src = dict(row)
    acc = (
        _find_account(konto)
        if konto
        else next((a for a in accounts if a["id"] == acc_id), accounts[0])
    )
    if acc is None:
        typer.echo("[!] Konto ne trovita.", err=True)
        raise typer.Exit(1)
    to_targets, cc_targets = _reply_targets(
        acc.get("retposto", ""), src, reply_all=True
    )
    if not to_targets:
        typer.echo("[!] Ne eblas determini ricevontojn por respondi-ciujn.", err=True)
        raise typer.Exit(1)
    body = korpo if korpo is not None else typer.prompt("Body")
    sub = "Re: " + (src.get("subjekto") or "")
    base_refs = " ".join(
        x for x in [src.get("references_hdr"), src.get("message_id")] if x
    ).strip() or None
    ok = _send_message(
        acc,
        to_targets,
        sub,
        body,
        cc_targets,
        [],
        in_reply_to=src.get("message_id"),
        references_hdr=base_refs,
    )
    if ok:
        typer.echo(
            f"[✓] Respondo-ciujn sendita al: {', '.join(to_targets + cc_targets)}"
        )
    else:
        raise typer.Exit(1)


@app.command("plusendi")
def plusendi_mesagon(
    uid: str = typer.Argument(..., help="Composite UID from `preni` output."),
    al: str = typer.Option(
        ..., "-a", "--al", help="Forward recipient(s), comma-separated."
    ),
    korpo: str | None = typer.Option(None, "--korpo", help="Optional preface body."),
    konto: str | None = typer.Option(None, "-k", "--konto", help="From account."),
) -> None:
    """Forward one message from CLI."""
    accounts = _load_accounts()
    if not accounts:
        typer.echo("[!] Neniuj kontoj konfiguritaj.", err=True)
        raise typer.Exit(1)
    try:
        acc_id, msg_uid = _parse_cli_uid(uid, accounts)
    except ValueError as exc:
        typer.echo(f"[!] {exc}", err=True)
        raise typer.Exit(1) from exc
    with _get_db() as con:
        row = con.execute(
            (
                "SELECT * FROM mesago WHERE konto_id = ? AND uid = ? "
                "ORDER BY id DESC LIMIT 1"
            ),
            (acc_id, msg_uid),
        ).fetchone()
    if not row:
        typer.echo(f"[!] Mesaĝo ne trovita por UID: {uid}", err=True)
        raise typer.Exit(1)
    src = dict(row)
    acc = (
        _find_account(konto)
        if konto
        else next((a for a in accounts if a["id"] == acc_id), accounts[0])
    )
    if acc is None:
        typer.echo("[!] Konto ne trovita.", err=True)
        raise typer.Exit(1)
    pref = korpo or ""
    forwarded = src.get("korpo") or _strip_html_tags(src.get("html_korpo") or "")
    body = f"{pref}\n\n--- Plusendita mesaĝo ---\n{forwarded}".strip()
    sub = "Fwd: " + (src.get("subjekto") or "")
    to = [a.strip() for a in al.split(",") if a.strip()]
    ok = _send_message(acc, to, sub, body)
    if ok:
        typer.echo(f"[✓] Plusendita al: {', '.join(to)}")
    else:
        raise typer.Exit(1)


# ──────────────────────────────────────────────────────────────────────────────
# Contact subcommands
# ──────────────────────────────────────────────────────────────────────────────


@kontakto_app.command("listigi")
def kontakto_listigi(
    serci: str | None = typer.Option(
        None, "-s", "--serci", help="Search term."
    )
) -> None:
    """List contacts (koresponda listo)."""
    contacts = _find_contact(serci) if serci else _load_contacts()
    if not contacts:
        typer.echo("Neniuj kontaktoj trovitaj.")
        return
    table = Table(title="Koresponda Listo")
    table.add_column("ID", style="dim")
    table.add_column("Nomo")
    table.add_column("Retpoŝto")
    table.add_column("Organizo")
    for c in contacts:
        table.add_row(
            str(c["id"]),
            c.get("nomo") or "",
            c["retposto"],
            c.get("organizo") or "",
        )
    console.print(table)


@kontakto_app.command("aldoni")
def kontakto_aldoni(
    retposto: str = typer.Argument(..., help="Email address."),
    nomo: str | None = typer.Option(None, "-n", "--nomo"),
    organizo: str | None = typer.Option(None, "-o", "--organizo"),
    telefono: str | None = typer.Option(None, "-t", "--telefono"),
) -> None:
    """Add or update a contact."""
    _upsert_contact(retposto.lower().strip(), nomo, organizo, telefono)
    typer.echo(f"[✓] Kontakto savis: {retposto}")


@kontakto_app.command("forigi")
def kontakto_forigi(
    contact_id: int = typer.Argument(..., help="Contact ID.")
) -> None:
    """Remove a contact."""
    with _get_db() as con:
        row = con.execute(
            "SELECT * FROM kontakto WHERE id = ?", (contact_id,)
        ).fetchone()
    if not row:
        typer.echo(f"[!] Kontakto ne trovita: {contact_id}", err=True)
        raise typer.Exit(1)
    if _confirm_esperante(f"Forigi '{row['retposto']}'?", default_yes=False):
        _delete_contact(contact_id)
        typer.echo("[✓] Forigita.")
    else:
        typer.echo("Nuligita.")


@kontakto_app.command("importi")
def kontakto_importi(
    vcf_dosiero: str = typer.Argument(..., help="Path to VCF file.")
) -> None:
    """Import contacts from a VCF file."""
    path = Path(vcf_dosiero)
    if not path.exists():
        typer.echo(f"[!] Dosiero ne trovita: {vcf_dosiero}", err=True)
        raise typer.Exit(1)
    count = _import_vcf(path)
    typer.echo(f"[✓] Importis {count} kontakto(j)n.")


@kontakto_app.command("eksporti")
def kontakto_eksporti(
    vcf_dosiero: str = typer.Argument(..., help="Path for output VCF file.")
) -> None:
    """Export contacts to a VCF file."""
    path = Path(vcf_dosiero)
    count = _export_vcf(path)
    typer.echo(f"[✓] Eksportis {count} kontakto(j)n al {vcf_dosiero}.")


# ──────────────────────────────────────────────────────────────────────────────
# Filter subcommands
# ──────────────────────────────────────────────────────────────────────────────


@filtro_app.command("agordi")
def filtro_agordi(
    fonto: str = typer.Argument(
        ...,
        help="Path/URL to .siv/.sieve/.txt file containing complete rules.",
    ),
    nomo: str = typer.Option(
        "ĉefa", "-n", "--nomo", help="Stored filter profile name."
    ),
) -> None:
    """Set the full sieve/filter script from one source file/URL."""
    try:
        sieve_kodo = _load_text_from_path_or_url(fonto)
    except OSError as exc:
        typer.echo(f"[!] Ne povis legi filter-fonton: {exc}", err=True)
        raise typer.Exit(1) from exc
    _save_filter(nomo, sieve_kodo, 0)
    typer.echo(f"[✓] Filtro agordita el: {fonto}")


@filtro_app.command("montri")
def filtro_montri(
    nomo: str = typer.Option("ĉefa", "-n", "--nomo", help="Filter profile name.")
) -> None:
    """Show stored full filter script."""
    with _get_db() as con:
        row = con.execute(
            "SELECT sieve_kodo FROM filtro WHERE nomo = ?",
            (nomo,),
        ).fetchone()
    if not row:
        typer.echo(f"[!] Filtro ne trovita: {nomo}", err=True)
        raise typer.Exit(1)
    typer.echo(row["sieve_kodo"])


@filtro_app.command("aldoni")
def filtro_aldoni(
    nomo: str = typer.Argument(..., help="Filter name."),
    sieve_kodo: str = typer.Argument(
        ...,
        help=(
            'Sieve-style rule: "from contains \\"spam\\"" => fileinto "Spam"'
        ),
    ),
    ordo: int = typer.Option(0, "-o", "--ordo", help="Execution order."),
) -> None:
    """Add or update a Sieve-style filter.

    Condition syntax (before =>):
      from/to/subject/body [not] contains/is "value"
    Multiple conditions are ANDed.

    Action syntax (after =>):
      fileinto "FolderName" | discard | mark-spam | mark-read | set-priority "N"
    """
    _save_filter(nomo, sieve_kodo, ordo)
    typer.echo(f"[✓] Filtro savis: {nomo}")


@filtro_app.command("listigi")
def filtro_listigi() -> None:
    """List active filters."""
    filters = _load_filters()
    if not filters:
        typer.echo("Neniuj filtroj.")
        return
    table = Table(title="Filtroj")
    table.add_column("ID", style="dim")
    table.add_column("Nomo")
    table.add_column("Ordo")
    table.add_column("Sieve-kodo")
    for f in filters:
        table.add_row(
            str(f["id"]), f["nomo"], str(f["ordo"]), f["sieve_kodo"]
        )
    console.print(table)


@filtro_app.command("forigi")
def filtro_forigi(
    nomo: str = typer.Argument(..., help="Filter name to delete.")
) -> None:
    """Delete a filter by name."""
    _delete_filter(nomo)
    typer.echo(f"[✓] Filtro forigita: {nomo}")


@filtro_app.command("alŝuti")
def filtro_alsuti(
    konto: str = typer.Argument(..., help="Account id or email."),
    sieve_host: str | None = typer.Option(
        None, "--sieve-host", help="ManageSieve host (default: IMAP host)."
    ),
    sieve_port: int = typer.Option(4190, "--sieve-port"),
) -> None:
    """Upload filters to server via ManageSieve (if available)."""
    acc = _find_account(konto)
    if not acc:
        typer.echo(f"[!] Account not found: {konto}", err=True)
        raise typer.Exit(1)
    filters = _load_filters()
    script = _build_sieve_script(filters)
    ok = _upload_sieve(acc, script, sieve_host, sieve_port)
    if ok:
        typer.echo("[✓] Sieve-skripto alŝutita.")
    else:
        raise typer.Exit(1)


# ──────────────────────────────────────────────────────────────────────────────
# Spam block subcommands
# ──────────────────────────────────────────────────────────────────────────────


@app.command("bloki")
def bloki(
    regulo: str = typer.Argument(
        ..., help="Email address or domain to block (e.g. spam@evil.com or evil.com)."
    )
) -> None:
    """Block a sender or domain from appearing in inbox."""
    _add_spam_block(regulo)
    typer.echo(f"[✓] Blokita: {regulo}")


@app.command("malbloki")
def malbloki(
    regulo: str = typer.Argument(..., help="Rule to remove from block list.")
) -> None:
    """Remove a sender/domain from the block list."""
    _remove_spam_block(regulo)
    typer.echo(f"[✓] Malblokita: {regulo}")


@app.command("blok-listo")
def blok_listo() -> None:
    """Show all blocked senders/domains."""
    blocks = _load_spam_blocks()
    if not blocks:
        typer.echo("Neniuj blokitaj adresoj.")
        return
    table = Table(title="Blok-Listo")
    table.add_column("ID", style="dim")
    table.add_column("Regulo")
    table.add_column("Kreita je", style="dim")
    for b in blocks:
        table.add_row(str(b["id"]), b["regulo"], (b["kreita_je"] or "")[:19])
    console.print(table)


# ──────────────────────────────────────────────────────────────────────────────
# Account update and signature CLI subcommands
# ──────────────────────────────────────────────────────────────────────────────


@app.command("ĝisdatigi-konton")
def gisdatigi_konton(
    id_adr: str = typer.Argument(..., help="Account id or email address."),
    nomo: str | None = typer.Option(None, "-n", "--nomo", help="Display name."),
    imap_servilo: str | None = typer.Option(None, "--imap", help="IMAP server."),
    imap_haveno: int | None = typer.Option(None, "--imap-haveno"),
    smtp_servilo: str | None = typer.Option(None, "--smtp", help="SMTP server."),
    smtp_haveno: int | None = typer.Option(None, "--smtp-haveno"),
    pasvorto: bool = typer.Option(
        False, "-p", "--pasvorto", help="Prompt for new password."
    ),
) -> None:
    """Update IMAP/SMTP credentials for an existing account."""
    acc = _find_account(id_adr)
    if not acc:
        typer.echo(f"[!] Konto ne trovita: {id_adr}", err=True)
        raise typer.Exit(1)

    updates: dict[str, object] = {}
    if nomo is not None:
        updates["nomo"] = nomo
    if imap_servilo is not None:
        updates["imap_servilo"] = imap_servilo
    if imap_haveno is not None:
        updates["imap_haveno"] = imap_haveno
    if smtp_servilo is not None:
        updates["smtp_servilo"] = smtp_servilo
    if smtp_haveno is not None:
        updates["smtp_haveno"] = smtp_haveno

    if updates:
        _update_account(acc["id"], updates)
        typer.echo(f"[✓] Konto ĝisdatigita (id={acc['id']}).")

    if pasvorto:
        new_pw = typer.prompt(
            "Nova pasvorto", hide_input=True, confirmation_prompt=True
        )
        _set_password(acc["id"], new_pw)
        typer.echo("[✓] Pasvorto ĝisdatigita.")

    if not updates and not pasvorto:
        typer.echo("Neniu ŝanĝo specifita. Uzu --help por vidi la eblojn.")


@app.command("subskribo")
def subskribo_cmd(
    id_adr: str = typer.Argument(..., help="Account id or email address."),
    agordi: str | None = typer.Option(
        None, "-a", "--agordi",
        help="Set signature: local file path or URL (http/https).",
    ),
    forigi: bool = typer.Option(
        False, "-f", "--forigi", help="Remove the signature."
    ),
) -> None:
    """View or set the email signature for an account.

    The signature can be a local plain-text/HTML file path or an http(s) URL.
    It is automatically appended to new messages and replies in the TUI.
    """
    acc = _find_account(id_adr)
    if not acc:
        typer.echo(f"[!] Konto ne trovita: {id_adr}", err=True)
        raise typer.Exit(1)

    if forigi:
        _update_account(acc["id"], {"subskribo": None})
        typer.echo("[✓] Subskribo forigita.")
        return

    if agordi is not None:
        _update_account(acc["id"], {"subskribo": agordi.strip()})
        typer.echo(f"[✓] Subskribo agordita: {agordi.strip()}")
        return

    # Display current signature setting
    current = acc.get("subskribo") or ""
    if current:
        typer.echo(f"Subskribo: {current}")
    else:
        typer.echo("Neniu subskribo agordita.")


# ──────────────────────────────────────────────────────────────────────────────
# Folder management CLI subcommands
# ──────────────────────────────────────────────────────────────────────────────


@app.command("novdos")
def novdos(
    nomo: str = typer.Argument(..., help="Folder name to create."),
    konto: str | None = typer.Option(
        None, "-k", "--konto", help="Account id or email (default: first account)."
    ),
    patro: str | None = typer.Option(
        None, "-p", "--patro", help="Parent folder name (for sub-folders)."
    ),
) -> None:
    """Create a new folder (or sub-folder) under an account."""
    accounts = _load_accounts()
    if not accounts:
        typer.echo("[!] Neniuj kontoj konfiguritaj.", err=True)
        raise typer.Exit(1)

    if konto:
        acc = _find_account(konto)
        if not acc:
            typer.echo(f"[!] Konto ne trovita: {konto}", err=True)
            raise typer.Exit(1)
    else:
        acc = accounts[0]

    patro_id: int | None = None
    if patro:
        folders = _load_folders(acc["id"])
        match = next((f for f in folders if f["nomo"] == patro), None)
        if not match:
            typer.echo(f"[!] Patra dosierujo ne trovita: {patro}", err=True)
            raise typer.Exit(1)
        patro_id = match["id"]

    folder_id = _ensure_folder(acc["id"], nomo, nomo, patro_id)
    parent_info = f" (patro: {patro})" if patro else ""
    typer.echo(
        f"[✓] Dosierujo kreita{parent_info}: {nomo} "
        f"(id={folder_id}) por {acc['retposto']}"
    )


@app.command("listigi-dosierujojn")
def listigi_dosierujojn(
    konto: str | None = typer.Option(
        None, "-k", "--konto", help="Account id or email (default: all)."
    )
) -> None:
    """List folders for one or all accounts."""
    accounts = _load_accounts()
    if not accounts:
        typer.echo("Neniuj kontoj konfiguritaj.")
        return

    if konto:
        acc = _find_account(konto)
        if not acc:
            typer.echo(f"[!] Konto ne trovita: {konto}", err=True)
            raise typer.Exit(1)
        accounts = [acc]

    for acc in accounts:
        typer.echo(f"\n{acc['retposto']}:")
        folders = _load_folders(acc["id"])
        if not folders:
            typer.echo("  (neniuj dosierujoj)")
            continue
        for f in folders:
            indent = "  "
            if f.get("patro_id") is not None:
                indent = "    "
            typer.echo(f"{indent}{f['nomo']}  (id={f['id']})")


@app.command("movi-mesagon")
def movi_mesagon(
    mesago_id: int = typer.Argument(..., help="Message id."),
    dosierujo: str = typer.Argument(..., help="Destination folder name."),
    konto: str | None = typer.Option(
        None, "-k", "--konto", help="Account id or email."
    ),
) -> None:
    """Move a message to a different folder."""
    with _get_db() as con:
        row = con.execute(
            "SELECT * FROM mesago WHERE id = ?", (mesago_id,)
        ).fetchone()
    if not row:
        typer.echo(f"[!] Mesaĝo ne trovita: {mesago_id}", err=True)
        raise typer.Exit(1)
    msg = dict(row)
    acc_id = msg["konto_id"]

    if konto:
        acc = _find_account(konto)
        if acc:
            acc_id = acc["id"]

    target = _find_folder_by_name(acc_id, dosierujo)
    if not target:
        typer.echo(f"[!] Dosierujo ne trovita: {dosierujo}", err=True)
        raise typer.Exit(1)
    folder_id = int(target["id"])
    _update_message_field(mesago_id, dosierujo_id=folder_id)
    typer.echo(f"[✓] Mesaĝo {mesago_id} movita al: {dosierujo} (id={folder_id})")


@app.command("kopii-mesagon")
def kopii_mesagon(
    mesago_id: int = typer.Argument(..., help="Message id."),
    dosierujo: str = typer.Argument(..., help="Destination folder name."),
    konto: str | None = typer.Option(
        None, "-k", "--konto", help="Account id or email."
    ),
) -> None:
    """Copy a message to a different folder."""
    with _get_db() as con:
        row = con.execute(
            "SELECT * FROM mesago WHERE id = ?", (mesago_id,)
        ).fetchone()
    if not row:
        typer.echo(f"[!] Mesaĝo ne trovita: {mesago_id}", err=True)
        raise typer.Exit(1)
    msg = dict(row)
    acc_id = int(msg["konto_id"])
    if konto:
        acc = _find_account(konto)
        if not acc:
            typer.echo(f"[!] Konto ne trovita: {konto}", err=True)
            raise typer.Exit(1)
        acc_id = int(acc["id"])
    target = _find_folder_by_name(acc_id, dosierujo)
    if not target:
        typer.echo(f"[!] Dosierujo ne trovita: {dosierujo}", err=True)
        raise typer.Exit(1)
    new_id = _copy_message(mesago_id, acc_id, int(target["id"]))
    if new_id is None:
        typer.echo(f"[!] Mesaĝo ne trovita: {mesago_id}", err=True)
        raise typer.Exit(1)
    typer.echo(
        f"[✓] Mesaĝo {mesago_id} kopiita al: {dosierujo} "
        f"(id={target['id']}), nova id={new_id}"
    )


@app.command("renomi-dosierujon")
def renomi_dosierujon(
    dosierujo_id: int = typer.Argument(..., help="Folder id."),
    nova_nomo: str = typer.Argument(..., help="New folder name."),
) -> None:
    """Rename a folder."""
    with _get_db() as con:
        row = con.execute(
            "SELECT id FROM dosierujo WHERE id = ?",
            (dosierujo_id,),
        ).fetchone()
    if not row:
        typer.echo(f"[!] Dosierujo ne trovita: {dosierujo_id}", err=True)
        raise typer.Exit(1)
    _rename_folder(dosierujo_id, nova_nomo)
    typer.echo(f"[✓] Dosierujo renomita: {dosierujo_id} → {nova_nomo}")


@app.command("movi-dosierujon")
def movi_dosierujon(
    dosierujo_id: int = typer.Argument(..., help="Folder id to move."),
    nova_patro_id: int = typer.Argument(..., help="New parent folder id."),
) -> None:
    """Move a folder under another folder (as sub-folder)."""
    with _get_db() as con:
        row = con.execute(
            "SELECT id FROM dosierujo WHERE id = ?",
            (dosierujo_id,),
        ).fetchone()
        patro = con.execute(
            "SELECT id FROM dosierujo WHERE id = ?",
            (nova_patro_id,),
        ).fetchone()
    if not row:
        typer.echo(f"[!] Dosierujo ne trovita: {dosierujo_id}", err=True)
        raise typer.Exit(1)
    if not patro:
        typer.echo(f"[!] Patra dosierujo ne trovita: {nova_patro_id}", err=True)
        raise typer.Exit(1)
    try:
        _move_folder(dosierujo_id, nova_patro_id)
    except ValueError as exc:
        typer.echo(f"[!] Eraro: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"[✓] Dosierujo {dosierujo_id} movita sub {nova_patro_id}")


@app.command("reordigi-konton")
def reordigi_konton(
    konto: str = typer.Argument(..., help="Account id or email."),
    direkto: str = typer.Argument(..., help="'supren' or 'suben'."),
) -> None:
    """Move account display order up/down by one."""
    acc = _find_account(konto)
    if not acc:
        typer.echo(f"[!] Konto ne trovita: {konto}", err=True)
        raise typer.Exit(1)
    if direkto not in ("supren", "suben"):
        typer.echo("[!] Direkto devas esti 'supren' aŭ 'suben'.", err=True)
        raise typer.Exit(1)
    moved = _move_account_order(int(acc["id"]), -1 if direkto == "supren" else 1)
    if not moved:
        typer.echo("[!] Konto jam ĉe limo; ne movita.", err=True)
        raise typer.Exit(1)
    typer.echo(f"[✓] Konto reordigita: {acc['retposto']} ({direkto}).")


# ──────────────────────────────────────────────────────────────────────────────
# Export / Import (account configurations)
# ──────────────────────────────────────────────────────────────────────────────

_7Z_MAGIC = b"7z\xbc\xaf\x27\x1c"


def _is_7z_bytes(data: bytes) -> bool:
    """Return True if *data* starts with the 7z magic bytes."""
    return len(data) >= 6 and data[:6] == _7Z_MAGIC


def _accounts_to_toml(accounts: list[dict], passwords: dict[int, str]) -> bytes:
    """Serialise account configs + passwords to TOML bytes."""
    import tomli_w  # noqa: PLC0415

    records: list[dict] = []
    for acc in accounts:
        record: dict = {
            "nomo": acc.get("nomo") or "",
            "retposto": acc.get("retposto") or "",
            "imap_servilo": acc.get("imap_servilo") or "",
            "imap_haveno": int(acc.get("imap_haveno") or 993),
            "imap_ssl": bool(acc.get("imap_ssl", True)),
            "smtp_servilo": acc.get("smtp_servilo") or "",
            "smtp_haveno": int(acc.get("smtp_haveno") or 587),
            "smtp_tls": bool(acc.get("smtp_tls", True)),
            "uzantonomo": acc.get("uzantonomo") or "",
            "subskribo": acc.get("subskribo") or "",
        }
        pw = passwords.get(int(acc["id"]))
        if pw:
            record["pasvorto"] = pw
        records.append(record)
    return tomli_w.dumps({"kontoj": records}).encode("utf-8")


def _toml_to_accounts(toml_bytes: bytes) -> list[dict]:
    """Deserialise account configs from TOML bytes."""
    try:
        import tomllib  # type: ignore[import-untyped]  # noqa: PLC0415
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef,import-untyped]  # noqa: PLC0415
    data = tomllib.loads(toml_bytes.decode("utf-8"))
    kontoj = data.get("kontoj")
    if not isinstance(kontoj, list):
        raise ValueError("Malvalida eksportita dosiero: 'kontoj' ne trovita.")
    return kontoj


@app.command("eksporti")
def eksporti(
    dosiero: str = typer.Argument(
        ..., help="Output file path (e.g. retposto.7z or retposto.zip)."
    ),
    pasvorto: str | None = typer.Option(
        None,
        "-p",
        "--pasvorto",
        help="Encryption password (required; asked interactively if omitted).",
    ),
    formato: str = typer.Option(
        "7z",
        "-f",
        "--formato",
        help="Archive format: '7z' (default) or 'zip'.",
    ),
) -> None:
    """Export all retposto user data as an encrypted archive.

    Includes account configs (with passwords), sieve filter script,
    contacts (VCF), and any local signature files.
    """
    import io  # noqa: PLC0415
    import tempfile  # noqa: PLC0415
    import zipfile  # noqa: PLC0415

    import py7zr  # noqa: PLC0415

    from autish.commands._crypto import (  # noqa: PLC0415
        encrypt,
        validate_strong_password,
    )

    if formato not in ("7z", "zip"):
        typer.echo("[!] Formato devas esti '7z' au 'zip'.", err=True)
        raise typer.Exit(1)

    if not pasvorto:
        pasvorto = typer.prompt("Pasvorto", hide_input=True, confirmation_prompt=True)

    err = validate_strong_password(pasvorto)
    if err:
        typer.echo(f"[!] {err}", err=True)
        raise typer.Exit(1)

    accounts = _load_accounts()
    if not accounts:
        typer.echo("[!] Neniuj kontoj por eksporti.", err=True)
        raise typer.Exit(1)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        # 1. Account configs + passwords
        passwords_map: dict[int, str] = {}
        for acc in accounts:
            pw = keyring.get_password(_KEYRING_SERVICE, str(acc["id"]))
            if pw:
                passwords_map[int(acc["id"])] = pw
        toml_bytes = _accounts_to_toml(accounts, passwords_map)
        (tmp_path / "kontoj.toml").write_bytes(toml_bytes)

        # 2. Sieve filter script
        filters = _load_filters()
        if filters:
            sieve_script = _build_sieve_script(filters)
            (tmp_path / "filtro.sieve").write_text(sieve_script, encoding="utf-8")

        # 3. Contacts VCF
        contacts = _load_contacts()
        if contacts:
            _export_vcf(tmp_path / "kontaktoj.vcf")

        # 4. Local signature files — copy them into the archive
        for acc in accounts:
            subskribo = acc.get("subskribo") or ""
            if subskribo and not subskribo.startswith(("http://", "https://")):
                sig_path = Path(subskribo)
                if sig_path.exists():
                    dest = tmp_path / f"subskribo_{acc['id']}{sig_path.suffix}"
                    dest.write_bytes(sig_path.read_bytes())

        # Build archive
        out_path = Path(dosiero)
        bundle_files = list(tmp_path.iterdir())

        if formato == "7z":
            with py7zr.SevenZipFile(str(out_path), "w", password=pasvorto) as szf:
                for fp in bundle_files:
                    szf.write(fp, fp.name)
        else:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for fp in bundle_files:
                    zf.write(fp, fp.name)
            encrypted = encrypt(buf.getvalue(), pasvorto)
            out_path.write_bytes(encrypted)

    typer.echo(
        f"[v] Eksportis retpostan datumaron ({len(accounts)} konto(j)n) "
        f"al {out_path} (formato={formato}, cifrita)."
    )


@app.command("importi")
def importi(
    dosiero: str = typer.Argument(
        ..., help="Input file path (encrypted archive or legacy encrypted TOML)."
    ),
    pasvorto: str | None = typer.Option(
        None,
        "-p",
        "--pasvorto",
        help="Decryption password (asked interactively if omitted).",
    ),
    anstatauigi: bool = typer.Option(
        False,
        "-A",
        "--anstatauigi",
        help="Overwrite existing accounts instead of merging.",
    ),
) -> None:
    """Import email account configs from an encrypted archive or legacy export."""
    import io  # noqa: PLC0415
    import tempfile  # noqa: PLC0415
    import zipfile  # noqa: PLC0415

    import py7zr  # noqa: PLC0415

    from autish.commands._crypto import decrypt, is_encrypted  # noqa: PLC0415

    in_path = Path(dosiero)
    if not in_path.exists():
        typer.echo(f"[!] Dosiero ne trovita: {in_path}", err=True)
        raise typer.Exit(1)

    raw = in_path.read_bytes()

    # Determine format: 7z archive, AUTX-encrypted zip/blob
    if _is_7z_bytes(raw):
        # New 7z archive format
        if not pasvorto:
            pasvorto = typer.prompt("Pasvorto", hide_input=True)
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                with py7zr.SevenZipFile(str(in_path), "r", password=pasvorto) as szf:
                    szf.extractall(path=tmp_dir)
                toml_path = Path(tmp_dir) / "kontoj.toml"
                if not toml_path.exists():
                    typer.echo(
                        "[!] Arkivo ne enhavas 'kontoj.toml'.", err=True
                    )
                    raise typer.Exit(1)
                kontoj_bytes = toml_path.read_bytes()
        except typer.Exit:
            raise
        except Exception as exc:
            typer.echo(f"[!] Arkiv-eraro: {exc}", err=True)
            raise typer.Exit(1) from exc
    elif is_encrypted(raw):
        # AUTX-encrypted blob (zip inside AUTX, or legacy TOML inside AUTX)
        if not pasvorto:
            pasvorto = typer.prompt("Pasvorto", hide_input=True)
        try:
            decrypted = decrypt(raw, pasvorto)
        except ValueError as exc:
            typer.echo(f"[!] Malcifrad-eraro: {exc}", err=True)
            raise typer.Exit(1) from exc
        # Check if decrypted content is a zip archive
        if decrypted[:2] == b"PK":
            buf = io.BytesIO(decrypted)
            with zipfile.ZipFile(buf, "r") as zf:
                if "kontoj.toml" in zf.namelist():
                    kontoj_bytes = zf.read("kontoj.toml")
                else:
                    # Treat decrypted content as raw TOML (legacy format)
                    kontoj_bytes = decrypted
        else:
            kontoj_bytes = decrypted
    else:
        typer.echo(
            "[!] Dosiero ne estas cifrita. Retposto-eksportoj ciam estas cifritaj.",
            err=True,
        )
        raise typer.Exit(1)

    try:
        kontoj = _toml_to_accounts(kontoj_bytes)
    except (ValueError, Exception) as exc:
        typer.echo(f"[!] Malvalida dosierformato: {exc}", err=True)
        raise typer.Exit(1) from exc

    if anstatauigi:
        if not _confirm_esperante(
            f"Cu anstatauigi CIUJN ekzistantajn kontojn per {len(kontoj)} importitajn?",
            default_yes=False,
        ):
            typer.echo("Nuligita.")
            return
        existing = _load_accounts()
        for acc in existing:
            _delete_account(int(acc["id"]))

    added = 0
    for rec in kontoj:
        if not rec.get("retposto"):
            continue
        pw = rec.pop("pasvorto", None)
        acc_id = _save_account(rec)
        if pw:
            _set_password(acc_id, pw)
        added += 1

    typer.echo(f"[v] Importis {added} konto(j)n.")



# ──────────────────────────────────────────────────────────────────────────────
# Account editor (konton)
# ──────────────────────────────────────────────────────────────────────────────


@app.command("konton")
def konton() -> None:
    """Open all email accounts in the system terminal editor for direct editing.

    Serialises all account configurations (without passwords) to a temporary
    TOML file, opens it with $EDITOR / $VISUAL / sensible-editor / nano / vi,
    and re-imports any changes on save.  Passwords remain in the system keyring
    and are not written to the temporary file.
    """
    import os  # noqa: PLC0415
    import subprocess  # noqa: PLC0415
    import tempfile  # noqa: PLC0415

    accounts = _load_accounts()
    if not accounts:
        typer.echo(
            "[!] Neniuj kontoj konfiguritaj. Uzu: retposto aldoni-konton",
            err=True,
        )
        raise typer.Exit(1)

    # Build editable TOML (no passwords)
    import tomli_w  # noqa: PLC0415

    records: list[dict] = []
    for acc in accounts:
        records.append({
            "id": int(acc["id"]),
            "nomo": acc.get("nomo") or "",
            "retposto": acc.get("retposto") or "",
            "imap_servilo": acc.get("imap_servilo") or "",
            "imap_haveno": int(acc.get("imap_haveno") or 993),
            "imap_ssl": bool(acc.get("imap_ssl", True)),
            "smtp_servilo": acc.get("smtp_servilo") or "",
            "smtp_haveno": int(acc.get("smtp_haveno") or 587),
            "smtp_tls": bool(acc.get("smtp_tls", True)),
            "uzantonomo": acc.get("uzantonomo") or "",
            "subskribo": acc.get("subskribo") or "",
        })
    toml_text = tomli_w.dumps({"kontoj": records})

    # Choose editor
    editor = (
        os.environ.get("VISUAL")
        or os.environ.get("EDITOR")
        or _find_terminal_editor()
    )

    with tempfile.NamedTemporaryFile(
        suffix=".toml", mode="w", encoding="utf-8", delete=False
    ) as tf:
        tf.write(toml_text)
        tmp_file = tf.name

    try:
        result = subprocess.run([editor, tmp_file], check=False)
        if result.returncode != 0:
            typer.echo(f"[!] Redaktoro finis kun kodo {result.returncode}.", err=True)
            return

        # Read back
        try:
            import tomllib  # type: ignore[import-untyped]  # noqa: PLC0415
        except ImportError:
            import tomli as tomllib  # type: ignore[no-redef,import-untyped]  # noqa: PLC0415

        with open(tmp_file, encoding="utf-8") as f:
            edited_data = tomllib.loads(f.read())
    finally:
        try:
            Path(tmp_file).unlink(missing_ok=True)
        except OSError:
            pass

    edited_kontoj = edited_data.get("kontoj")
    if not isinstance(edited_kontoj, list):
        typer.echo("[!] Malvalida TOML: 'kontoj' listo ne trovita.", err=True)
        raise typer.Exit(1)

    updated = 0
    for rec in edited_kontoj:
        acc_id = rec.get("id")
        if acc_id is None:
            continue
        acc_id = int(acc_id)
        existing = _find_account(str(acc_id))
        if not existing:
            continue
        fields: dict[str, object] = {}
        for col in _KONTO_UPDATABLE_COLS:
            if col in rec:
                fields[col] = rec[col]
        if fields:
            _update_account(acc_id, fields)
            updated += 1

    typer.echo(f"[v] Aktualigis {updated} konto(j)n.")


def _find_terminal_editor() -> str:
    """Return a terminal text editor available on the system."""
    import shutil  # noqa: PLC0415

    for candidate in ("sensible-editor", "nano", "vi", "vim"):
        if shutil.which(candidate):
            return candidate
    return "vi"
