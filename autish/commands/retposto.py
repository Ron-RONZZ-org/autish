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
import uuid as _uuid_mod
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

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
    help="Retpoŝto — TUI email microapp.",
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

# Allowed column names for _update_message_field to prevent SQL injection
_MSG_UPDATABLE_COLS: frozenset[str] = frozenset({
    "dosierujo_id", "legita", "stelo", "spamo", "forigita",
    "prioritato", "etikedoj",
})
# ──────────────────────────────────────────────────────────────────────────────

_CREATE_KONTO = """
CREATE TABLE IF NOT EXISTS konto (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
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
    if "subskribo" not in existing_cols:
        con.execute("ALTER TABLE konto ADD COLUMN subskribo TEXT")
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
        rows = con.execute("SELECT * FROM konto ORDER BY id ASC").fetchall()
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
        cur = con.execute(
            """INSERT INTO konto
               (nomo, retposto, imap_servilo, imap_haveno, imap_ssl,
                smtp_servilo, smtp_haveno, smtp_tls, uzantonomo, kreita_je)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
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
    with _get_db() as con:
        con.execute(f"UPDATE konto SET {set_clause} WHERE id = ?", values)


def _delete_account(account_id: int) -> None:
    with _get_db() as con:
        con.execute("DELETE FROM konto WHERE id = ?", (account_id,))
    try:
        keyring.delete_password(_KEYRING_SERVICE, str(account_id))
    except keyring.errors.PasswordDeleteError:
        pass  # password was never stored — that's fine


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
    return result


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
               (uuid, konto_id, dosierujo_id, message_id, uid, de, al, cc, bcc,
                subjekto, korpo, html_korpo, prioritato, legita, stelo, spamo,
                forigita, aldonajoj, etikedoj, ricevita_je, kreita_je)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                msg.get("uuid") or _make_uuid(),
                msg["konto_id"],
                msg.get("dosierujo_id"),
                msg.get("message_id"),
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
            con.execute(
                "UPDATE mesago SET forigita = 1 WHERE id = ?", (msg_id,)
            )


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
    if cc:
        mime["Cc"] = ", ".join(cc)
    mime.attach(MIMEText(korpo, "plain", "utf-8"))

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
    if not imap_servilo:
        imap_servilo = typer.prompt("IMAP server")
    if not smtp_servilo:
        smtp_servilo = typer.prompt("SMTP server")
    password = typer.prompt("Password", hide_input=True)

    acc = {
        "nomo": nomo,
        "retposto": retposto.lower().strip(),
        "imap_servilo": imap_servilo,
        "imap_haveno": imap_haveno,
        "imap_ssl": imap_ssl,
        "smtp_servilo": smtp_servilo,
        "smtp_haveno": smtp_haveno,
        "smtp_tls": smtp_tls,
        "uzantonomo": retposto.lower().strip(),
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
    if not typer.confirm(f"Forigi konton '{acc['retposto']}'?", default=False):
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
    konto: str | None = typer.Option(
        None, "-k", "--konto", help="Account id or email (default: all)."
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
        acc = _find_account(konto)
        if not acc:
            typer.echo(f"[!] Account not found: {konto}", err=True)
            raise typer.Exit(1)
        accounts = [acc]

    total_f = total_s = 0
    for acc in accounts:
        typer.echo(f"Prenante de {acc['retposto']}…")
        f, s = _fetch_account_mail(acc, max_msgs)
        typer.echo(f"  [✓] {f} nova(j), {s} preterpasita(j)")
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
    if not korpo:
        korpo = typer.prompt("Body")

    al_list = [a.strip() for a in al.split(",") if a.strip()]
    cc_list = [a.strip() for a in cc.split(",") if a.strip()] if cc else []
    bcc_list = [a.strip() for a in bcc.split(",") if a.strip()] if bcc else []

    ok = _send_message(acc, al_list, subjekto, korpo, cc_list, bcc_list)
    if ok:
        typer.echo(f"[✓] Sendita al: {', '.join(al_list)}")
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
    if typer.confirm(f"Forigi '{row['retposto']}'?", default=False):
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

    folder_id = _ensure_folder(acc_id, dosierujo, dosierujo)
    _update_message_field(mesago_id, dosierujo_id=folder_id)
    typer.echo(f"[✓] Mesaĝo {mesago_id} movita al: {dosierujo} (id={folder_id})")
