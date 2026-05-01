"""kalendaro — calendar microapp (local store + remote sync queue)."""

from __future__ import annotations

import base64
import json
import sqlite3
import threading
import time
import uuid as _uuid_mod
from datetime import date, datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request
from xml.etree import ElementTree as ET

import keyring
import typer
from rich.markup import escape
from rich.table import Table

from autish.console import console
from autish.i18n import tr
from autish.utils import now_iso

app = typer.Typer(
    name="kalendaro",
    help=tr(
        "Kalendaro — administri kalendarojn kaj eventojn.",
        "Kalendaro — manage calendars and events.",
        "Kalendaro — gérer calendriers et événements.",
    ),
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help", "--helpo"]},
)

_DATA_DIR: Path = Path.home() / ".local" / "share" / "autish"
_DB_FILE: Path = _DATA_DIR / "kalendaro.db"
_MAX_UNDO = 30
_sync_lock = threading.Lock()
_sync_worker_started = False
_KEYRING_SERVICE = "autish.kalendaro"


def _connect() -> sqlite3.Connection:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(_DB_FILE)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS calendars(
          uuid TEXT PRIMARY KEY,
          url TEXT NOT NULL,
          username TEXT NOT NULL DEFAULT '',
          remote INTEGER NOT NULL DEFAULT 1,
          kreita_je TEXT NOT NULL,
          modifita_je TEXT NOT NULL
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS events(
          uuid TEXT PRIMARY KEY,
          calendar_uuid TEXT NOT NULL,
          titolo TEXT NOT NULL DEFAULT '',
          komenco TEXT NOT NULL,
          fino TEXT NOT NULL,
          kategorio TEXT NOT NULL DEFAULT '',
          loko TEXT NOT NULL DEFAULT '',
          ripeto TEXT NOT NULL DEFAULT '',
          partoprenantoj TEXT NOT NULL DEFAULT '[]',
          priskribo TEXT NOT NULL DEFAULT '',
          kreita_je TEXT NOT NULL,
          modifita_je TEXT NOT NULL
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS undo_changes(
          id TEXT PRIMARY KEY,
          operacio TEXT NOT NULL,
          payload TEXT NOT NULL,
          kreita_je TEXT NOT NULL
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS sync_queue(
          id TEXT PRIMARY KEY,
          calendar_uuid TEXT NOT NULL,
          operacio TEXT NOT NULL,
          payload TEXT NOT NULL DEFAULT '{}',
          stato TEXT NOT NULL DEFAULT 'pending',
          eraro TEXT NOT NULL DEFAULT '',
          kreita_je TEXT NOT NULL,
          modifita_je TEXT NOT NULL
        )
        """
    )
    return con


def _parse_date_token(raw: str, *, ref: date | None = None) -> date:
    token = raw.strip()
    if not token.isdigit():
        raise ValueError(f"Nevalida dato: {raw!r}")
    today = ref or date.today()
    if len(token) == 8:
        return datetime.strptime(token, "%Y%m%d").date()
    if len(token) == 4:
        return datetime.strptime(f"{today.year}{token}", "%Y%m%d").date()
    if len(token) == 2:
        return datetime.strptime(
            f"{today.year}{today.month:02d}{token}", "%Y%m%d"
        ).date()
    raise ValueError(f"Nevalida dato-formo: {raw!r}")


def _parse_range(start_raw: str | None, end_raw: str | None) -> tuple[date, date]:
    today = date.today()
    if not start_raw:
        return today, today
    start = _parse_date_token(start_raw, ref=today)
    end = _parse_date_token(end_raw, ref=today) if end_raw else start
    if end < start:
        start, end = end, start
    return start, end


def _parse_dt(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def _to_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _set_password(calendar_uuid: str, password: str) -> None:
    if not password:
        return
    keyring.set_password(_KEYRING_SERVICE, calendar_uuid, password)


def _get_password(calendar_uuid: str) -> str:
    return keyring.get_password(_KEYRING_SERVICE, calendar_uuid) or ""


def _delete_password(calendar_uuid: str) -> None:
    try:
        keyring.delete_password(_KEYRING_SERVICE, calendar_uuid)
    except keyring.errors.PasswordDeleteError:
        return


def _fmt_hhmm(value: str) -> str:
    return _parse_dt(value).strftime("%H%M")


def _fmt_date(value: str) -> str:
    return _parse_dt(value).strftime("%Y-%m-%d")


def _short(text: str, limit: int = 40) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _render_calendar_url(url: str) -> str:
    full_url = str(url)
    rendered = f"[link={escape(full_url)}]{escape(full_url)}[/link]"
    if len(full_url) > 40:
        return (
            f"{rendered} "
            "[dim](se via terminalo vide mallongigas la ligilon, "
            "Ctrl+klako/kopio daŭre celas la plenan URL)[/dim]"
        )
    return rendered


def _resolve_calendar_uuid(con: sqlite3.Connection, ref: str) -> str | None:
    lookup = ref[1:] if ref.startswith("#") else ref
    row = con.execute("SELECT uuid FROM calendars WHERE uuid = ?", (lookup,)).fetchone()
    if row:
        return str(row["uuid"])
    matches = con.execute(
        "SELECT uuid FROM calendars WHERE uuid LIKE ? ORDER BY uuid",
        (lookup + "%",),
    ).fetchall()
    if len(matches) == 1:
        return str(matches[0]["uuid"])
    return None


def _resolve_event_uuid(con: sqlite3.Connection, ref: str) -> str | None:
    lookup = ref[1:] if ref.startswith("#") else ref
    row = con.execute("SELECT uuid FROM events WHERE uuid = ?", (lookup,)).fetchone()
    if row:
        return str(row["uuid"])
    matches = con.execute(
        "SELECT uuid FROM events WHERE uuid LIKE ? ORDER BY uuid", (lookup + "%",)
    ).fetchall()
    if len(matches) == 1:
        return str(matches[0]["uuid"])
    return None


def _warn_unsynced(con: sqlite3.Connection, calendar_uuids: list[str]) -> None:
    if not calendar_uuids:
        return
    placeholders = ",".join("?" for _ in calendar_uuids)
    rows = con.execute(
        f"""
        SELECT COUNT(*) AS c FROM sync_queue
        WHERE calendar_uuid IN ({placeholders}) AND stato IN ('pending','failed')
        """,
        tuple(calendar_uuids),
    ).fetchone()
    count = int(rows["c"]) if rows else 0
    if count > 0:
        warning = (
            f"[!] Averto: {count} nesinkronigita(j) ŝanĝo(j) "
            "ankoraŭ atendas sinkronigon."
        )
        typer.echo(
            warning,
            err=True,
        )


def _calendar_exists(con: sqlite3.Connection, url: str, username: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM calendars "
        "WHERE lower(url)=lower(?) AND lower(username)=lower(?)",
        (url.strip(), username.strip()),
    ).fetchone()
    return row is not None


def _probe_calendar_config(url: str, username: str, password: str) -> None:
    low = url.strip().lower()
    if low.startswith("file://"):
        # Local calendars may point to files that will be created later.
        return
    if low.startswith(("http://", "https://", "caldav://")):
        if not username.strip() or not password.strip():
            raise ValueError(
                "Ĉi tiu fora kalendaro bezonas --uzantnomo kaj --pasvorto."
            )
        return
    raise ValueError(
        "Nesubtenata kalendara URL-skemo. Uzu file://..., http(s)://... aŭ caldav://..."
    )


def _is_remote_calendar_url(url: str) -> bool:
    return url.strip().lower().startswith(("http://", "https://", "caldav://"))


def _remote_http_url(url: str) -> str:
    raw = url.strip()
    if raw.lower().startswith("caldav://"):
        return "https://" + raw[len("caldav://") :]
    return raw


def _http_fetch_text(
    url: str,
    *,
    username: str,
    password: str,
    method: str = "GET",
    body: str | None = None,
    headers: dict[str, str] | None = None,
) -> str:
    data = body.encode("utf-8") if body is not None else None
    req = urllib_request.Request(url, data=data, method=method)
    req.add_header("User-Agent", "autish-kalendaro/1.0")
    req.add_header("Accept", "text/calendar, application/xml;q=0.9, */*;q=0.1")
    if username or password:
        token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
        req.add_header("Authorization", f"Basic {token}")
    if body is not None:
        req.add_header("Content-Type", "application/xml; charset=utf-8")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib_request.urlopen(req, timeout=20) as response:
            payload = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
            return payload.decode(charset, errors="replace")
    except urllib_error.HTTPError as exc:
        body_bytes = exc.read()
        charset = exc.headers.get_content_charset() if exc.headers else None
        detail = body_bytes.decode(charset or "utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail[:240]}") from exc
    except urllib_error.URLError as exc:
        raise RuntimeError(f"Reta eraro: {exc.reason}") from exc


def _extract_calendar_data_chunks(text: str) -> list[str]:
    if "BEGIN:VEVENT" in text:
        return [text]
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    chunks: list[str] = []
    for node in root.iter():
        if node.tag.lower().endswith("calendar-data"):
            payload = (node.text or "").strip()
            if "BEGIN:VEVENT" in payload:
                chunks.append(payload)
    return chunks


def _fetch_remote_calendar_payloads(
    url: str, username: str, password: str
) -> list[str]:
    http_url = _remote_http_url(url)
    attempts: list[tuple[str, str | None, dict[str, str] | None]] = [
        (http_url, None, None),
    ]
    parsed = urllib_parse.urlparse(http_url)
    parsed_query = urllib_parse.parse_qsl(parsed.query, keep_blank_values=True)
    if "export" not in dict(parsed_query):
        query_pairs = list(parsed_query)
        query_pairs.append(("export", "1"))
        export_url = urllib_parse.urlunparse(
            parsed._replace(query=urllib_parse.urlencode(query_pairs))
        )
        attempts.append((export_url, None, None))
    report_body = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
        "<d:prop><d:getetag/><c:calendar-data/></d:prop>"
        "<c:filter><c:comp-filter name=\"VCALENDAR\">"
        "<c:comp-filter name=\"VEVENT\"/>"
        "</c:comp-filter></c:filter>"
        "</c:calendar-query>"
    )
    attempts.append((http_url, report_body, {"Depth": "1"}))

    errors: list[str] = []
    for attempt_url, body, headers in attempts:
        try:
            text = _http_fetch_text(
                attempt_url,
                username=username,
                password=password,
                method="REPORT" if body is not None else "GET",
                body=body,
                headers=headers,
            )
        except RuntimeError as exc:
            errors.append(str(exc))
            continue
        chunks = _extract_calendar_data_chunks(text)
        if chunks:
            return chunks
        errors.append("Respondo ne enhavis VEVENT-datumojn.")
    raise RuntimeError(
        "Ne povis alporti eventojn de fora kalendaro: " + " | ".join(errors[-2:])
    )


def _pull_calendar_events(
    con: sqlite3.Connection,
    calendar_uuid: str,
    *,
    now: str | None = None,
) -> int:
    row = con.execute(
        "SELECT url, username FROM calendars WHERE uuid = ?", (calendar_uuid,)
    ).fetchone()
    if row is None:
        raise RuntimeError("Kalendaro ne trovita por sinkronigo.")
    url = str(row["url"] or "").strip()
    username = str(row["username"] or "").strip()
    ts = now or now_iso()
    imported = 0
    if url.lower().startswith("file://"):
        file_path = Path(url[7:])
        if file_path.exists():
            imported_ids = _insert_ics_events(
                con, calendar_uuid, file_path.read_text(encoding="utf-8"), now=ts
            )
            imported += len(imported_ids)
        return imported
    if _is_remote_calendar_url(url):
        password = _get_password(calendar_uuid)
        chunks = _fetch_remote_calendar_payloads(url, username, password)
        for chunk in chunks:
            imported_ids = _insert_ics_events(con, calendar_uuid, chunk, now=ts)
            imported += len(imported_ids)
        return imported
    raise RuntimeError("Nesubtenata kalendara URL por sinkronigo.")


def _queue_sync(
    con: sqlite3.Connection, calendar_uuid: str, operation: str, payload: dict
) -> None:
    now = now_iso()
    con.execute(
        """
        INSERT INTO sync_queue(
          id, calendar_uuid, operacio, payload, stato, eraro, kreita_je, modifita_je
        )
        VALUES (?, ?, ?, ?, 'pending', '', ?, ?)
        """,
        (
            str(_uuid_mod.uuid4()),
            calendar_uuid,
            operation,
            json.dumps(payload, ensure_ascii=False),
            now,
            now,
        ),
    )
    _start_sync_worker()


def _sync_worker() -> None:
    while True:
        with _sync_lock:
            con = _connect()
            try:
                pending = con.execute(
                    """
                    SELECT q.id, q.calendar_uuid, q.operacio, c.url
                    FROM sync_queue q
                    JOIN calendars c ON c.uuid = q.calendar_uuid
                    WHERE q.stato = 'pending'
                    ORDER BY q.kreita_je
                    LIMIT 20
                    """
                ).fetchall()
                if not pending:
                    return
                now = now_iso()
                for row in pending:
                    queue_id = str(row["id"])
                    calendar_uuid = str(row["calendar_uuid"])
                    operation = str(row["operacio"] or "")
                    url = str(row["url"] or "")
                    if operation in {"komenca-sinkronigo", "tiri"}:
                        try:
                            _pull_calendar_events(con, calendar_uuid, now=now)
                        except RuntimeError as exc:
                            con.execute(
                                "UPDATE sync_queue "
                                "SET stato='failed', eraro=?, modifita_je=? "
                                "WHERE id=?",
                                (str(exc), now, queue_id),
                            )
                            continue
                        con.execute(
                            "UPDATE sync_queue "
                            "SET stato='synced', eraro='', modifita_je=? "
                            "WHERE id=?",
                            (now, queue_id),
                        )
                        continue
                    if _is_remote_calendar_url(url):
                        con.execute(
                            "UPDATE sync_queue "
                            "SET stato='failed', eraro=?, modifita_je=? "
                            "WHERE id=?",
                            (
                                "Fora skriba sinkronigo ankoraŭ ne subtenata.",
                                now,
                                queue_id,
                            ),
                        )
                    else:
                        con.execute(
                            "UPDATE sync_queue "
                            "SET stato='synced', eraro='', modifita_je=? "
                            "WHERE id=?",
                            (now, queue_id),
                        )
                con.commit()
            finally:
                con.close()
        time.sleep(0.05)


def _start_sync_worker() -> None:
    global _sync_worker_started
    if _sync_worker_started:
        return
    _sync_worker_started = True

    def _run() -> None:
        global _sync_worker_started
        try:
            _sync_worker()
        finally:
            _sync_worker_started = False

    thread = threading.Thread(target=_run, name="kalendaro-sync", daemon=True)
    thread.start()


def _push_undo(con: sqlite3.Connection, operation: str, payload: dict) -> str:
    change_id = str(_uuid_mod.uuid4())[:8]
    con.execute(
        "INSERT INTO undo_changes (id, operacio, payload, kreita_je) "
        "VALUES (?, ?, ?, ?)",
        (change_id, operation, json.dumps(payload, ensure_ascii=False), now_iso()),
    )
    rows = con.execute("SELECT id FROM undo_changes ORDER BY kreita_je DESC").fetchall()
    for row in rows[_MAX_UNDO:]:
        con.execute("DELETE FROM undo_changes WHERE id=?", (str(row["id"]),))
    return change_id


def _iter_ics_events(text: str) -> list[dict]:
    events: list[dict] = []
    current: dict | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if line == "BEGIN:VEVENT":
            current = {}
            continue
        if line == "END:VEVENT":
            if current is not None:
                events.append(current)
            current = None
            continue
        if current is None or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.split(";", 1)[0].upper()
        current[key] = value.strip()
    return events


def _ics_dt(value: str) -> datetime:
    if value.endswith("Z"):
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    if "T" in value:
        return datetime.strptime(value, "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
    return datetime.strptime(value, "%Y%m%d").replace(tzinfo=timezone.utc)


def _event_exists(
    con: sqlite3.Connection,
    calendar_uuid: str,
    title: str,
    start_iso: str,
    end_iso: str,
) -> bool:
    row = con.execute(
        """
        SELECT 1 FROM events
        WHERE calendar_uuid = ? AND titolo = ? AND komenco = ? AND fino = ?
        """,
        (calendar_uuid, title, start_iso, end_iso),
    ).fetchone()
    return row is not None


def _insert_ics_events(
    con: sqlite3.Connection,
    calendar_uuid: str,
    text: str,
    *,
    now: str | None = None,
) -> list[str]:
    ts = now or now_iso()
    added: list[str] = []
    for event in _iter_ics_events(text):
        start = _to_iso(_ics_dt(str(event.get("DTSTART", ts))))
        end = _to_iso(_ics_dt(str(event.get("DTEND", event.get("DTSTART", ts)))))
        title = str(event.get("SUMMARY", ""))
        if _event_exists(con, calendar_uuid, title, start, end):
            continue
        uid = str(_uuid_mod.uuid4())
        participants = []
        if "ATTENDEE" in event:
            participants.append(str(event["ATTENDEE"]))
        con.execute(
            """
            INSERT INTO events (
              uuid, calendar_uuid, titolo, komenco, fino, kategorio, loko,
              ripeto, partoprenantoj, priskribo, kreita_je, modifita_je
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uid,
                calendar_uuid,
                title,
                start,
                end,
                str(event.get("CATEGORIES", "")),
                str(event.get("LOCATION", "")),
                str(event.get("RRULE", "")),
                json.dumps(participants, ensure_ascii=False),
                str(event.get("DESCRIPTION", "")),
                ts,
                ts,
            ),
        )
        added.append(uid)
    return added


def _row_to_event_dict(row: sqlite3.Row) -> dict:
    return {
        "uuid": str(row["uuid"]),
        "calendar_uuid": str(row["calendar_uuid"]),
        "titolo": str(row["titolo"] or ""),
        "komenco": str(row["komenco"]),
        "fino": str(row["fino"]),
        "kategorio": str(row["kategorio"] or ""),
        "loko": str(row["loko"] or ""),
        "ripeto": str(row["ripeto"] or ""),
        "partoprenantoj": json.loads(str(row["partoprenantoj"] or "[]")),
        "priskribo": str(row["priskribo"] or ""),
    }


@app.command(
    "aldoni",
    help=tr(
        "Aldoni foran aŭ lokan kalendaron, testi konfiguracion, kaj tuj provi "
        "komencan sinkronigon. Ekz: kalendaro aldoni https://cal.ex/k.ics "
        "-u alice --pasvorto sekret123",
        "Add a remote/local calendar, validate config, and attempt immediate "
        "initial sync. Example: kalendaro aldoni https://cal.ex/k.ics "
        "-u alice --pasvorto secret123",
        "Ajouter un calendrier distant/local, valider la configuration et tenter "
        "une synchronisation initiale immédiate. Exemple : kalendaro aldoni "
        "https://cal.ex/k.ics -u alice --pasvorto secret123",
    ),
)
def aldoni(
    url: str = typer.Argument(
        ...,
        help=tr(
            "URL de kalendaro. Ekz: https://example.com/caldav/calendar.ics",
            "Calendar URL. Example: https://example.com/caldav/calendar.ics",
            "URL du calendrier. Exemple : https://example.com/caldav/calendar.ics",
        ),
    ),
    uzantnomo: str = typer.Option(
        "",
        "-u",
        "--uzantnomo",
        help=tr(
            "Uzantnomo por fora kalendaro. Ekz: -u alice",
            "Username for remote calendar. Example: -u alice",
            "Nom d'utilisateur pour calendrier distant. Exemple : -u alice",
        ),
    ),
    pasvorto: str = typer.Option(
        "",
        "-p",
        "--pasvorto",
        help=tr(
            "Pasvorto por fora kalendaro. Ekz: --pasvorto sekret123",
            "Password for remote calendar. Example: --pasvorto secret123",
            "Mot de passe pour calendrier distant. Exemple : --pasvorto secret123",
        ),
    ),
) -> None:
    con = _connect()
    sync_warning = ""
    try:
        if _calendar_exists(con, url, uzantnomo):
            typer.echo("Kalendaro jam ekzistas kun sama URL kaj uzantnomo.", err=True)
            raise typer.Exit(code=1)
        try:
            _probe_calendar_config(url, uzantnomo, pasvorto)
        except ValueError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc
        uid = str(_uuid_mod.uuid4())
        now = now_iso()
        con.execute(
            """
            INSERT INTO calendars (uuid, url, username, remote, kreita_je, modifita_je)
            VALUES (?, ?, ?, 1, ?, ?)
            """,
            (uid, url.strip(), uzantnomo.strip(), now, now),
        )
        if pasvorto.strip():
            _set_password(uid, pasvorto.strip())
        imported = 0
        low_url = url.strip().lower()
        if low_url.startswith("file://"):
            file_path = Path(url.strip()[7:])
            if file_path.exists():
                imported_ids = _insert_ics_events(
                    con,
                    uid,
                    file_path.read_text(encoding="utf-8"),
                    now=now,
                )
                imported = len(imported_ids)
                if imported_ids:
                    _push_undo(con, "importi", {"event_ids": imported_ids})
        elif _is_remote_calendar_url(url):
            try:
                imported = _pull_calendar_events(con, uid, now=now)
            except RuntimeError as exc:
                sync_warning = str(exc)
        # Immediate sync attempt after add (for remote/local follow-up sync).
        _queue_sync(con, uid, "komenca-sinkronigo", {"source": "aldoni"})
        con.commit()
    finally:
        con.close()
    typer.echo(
        f"Aldonis kalendaron #{uid[:8]}: importitaj {imported} evento(j), "
        "komenca sinkronigo planita."
    )
    if sync_warning:
        typer.echo(
            f"[!] Komenca rekta sinkronigo malsukcesis: {sync_warning}",
            err=True,
        )


@app.command(
    "modifi",
    help=tr(
        "Modifi kalendaran agordon laŭ UUID. Ekz: kalendaro modifi abcdef12 "
        "--uzantnomo alice --pasvorto novaSekreto123",
        "Modify calendar settings by UUID. Example: kalendaro modifi abcdef12 "
        "--uzantnomo alice --pasvorto newSecret123",
        "Modifier les paramètres d'un calendrier par UUID. Exemple : "
        "kalendaro modifi abcdef12 --uzantnomo alice --pasvorto nouveauSecret123",
    ),
)
def modifi(
    ctx: typer.Context,
    kalendaro_uuid: str = typer.Argument(
        ...,
        help=tr(
            "UUID de kalendaro por modifi. Ekz: abcdef12",
            "Calendar UUID to modify. Example: abcdef12",
            "UUID du calendrier à modifier. Exemple : abcdef12",
        ),
    ),
    url: str | None = typer.Option(
        None,
        "--url",
        help=tr(
            "Nova kalendara URL. Ekz: --url https://example.com/caldav/cal/",
            "New calendar URL. Example: --url https://example.com/caldav/cal/",
            "Nouvelle URL de calendrier. Exemple : --url https://example.com/caldav/cal/",
        ),
    ),
    uzantnomo: str | None = typer.Option(
        None,
        "-u",
        "--uzantnomo",
        help=tr(
            "Nova uzantnomo. Ekz: --uzantnomo alice",
            "New username. Example: --uzantnomo alice",
            "Nouveau nom d'utilisateur. Exemple : --uzantnomo alice",
        ),
    ),
    pasvorto: str | None = typer.Option(
        None,
        "-p",
        "--pasvorto",
        help=tr(
            "Nova pasvorto. Uzu malplenan ĉenon por forigi: --pasvorto ''",
            "New password. Use empty string to clear: --pasvorto ''",
            "Nouveau mot de passe. Utilisez une chaîne vide pour supprimer : "
            "--pasvorto ''",
        ),
    ),
) -> None:
    if all(v is None for v in (url, uzantnomo, pasvorto)):
        typer.echo(ctx.get_help())
        return

    con = _connect()
    try:
        resolved = _resolve_calendar_uuid(con, kalendaro_uuid)
        if not resolved:
            typer.echo("Kalendaro ne trovita.", err=True)
            raise typer.Exit(code=1)
        row = con.execute(
            "SELECT url, username FROM calendars WHERE uuid = ?", (resolved,)
        ).fetchone()
        if row is None:
            typer.echo("Kalendaro ne trovita.", err=True)
            raise typer.Exit(code=1)
        old_url = str(row["url"] or "")
        old_username = str(row["username"] or "")
        current_password = _get_password(resolved)

        new_url = url.strip() if url is not None else old_url
        new_username = uzantnomo.strip() if uzantnomo is not None else old_username
        new_password = pasvorto if pasvorto is not None else current_password
        try:
            _probe_calendar_config(new_url, new_username, new_password)
        except ValueError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc

        now = now_iso()
        con.execute(
            "UPDATE calendars SET url=?, username=?, modifita_je=? WHERE uuid=?",
            (new_url, new_username, now, resolved),
        )
        if pasvorto is not None:
            if pasvorto.strip():
                _set_password(resolved, pasvorto.strip())
            else:
                _delete_password(resolved)
        _queue_sync(con, resolved, "komenca-sinkronigo", {"source": "modifi"})
        con.commit()
    finally:
        con.close()
    typer.echo(f"Modifis kalendaron #{resolved[:8]}.")


@app.command(
    "ls-kalendaro",
    help=tr(
        "Listigi kalendarojn (UUID + URL mallongigita por klareco). "
        "Ekz: kalendaro ls-kalendaro",
        "List calendars (UUID + truncated URL for clarity). "
        "Example: kalendaro ls-kalendaro",
        "Lister les calendriers (UUID + URL tronquée). "
        "Exemple : kalendaro ls-kalendaro",
    ),
)
def ls_kalendaro() -> None:
    con = _connect()
    try:
        rows = con.execute(
            "SELECT uuid, url FROM calendars ORDER BY kreita_je DESC"
        ).fetchall()
    finally:
        con.close()
    table = Table(header_style="dim", border_style="dim")
    table.add_column("UUID", style="dim", width=10)
    table.add_column("URL")
    for row in rows:
        table.add_row(str(row["uuid"])[:8], _render_calendar_url(str(row["url"])))
    console.print(table)


@app.command(
    "ls",
    help=tr(
        "Montri eventojn en datintervalo. Ekz: kalendaro ls 20260125 20260130 "
        "-k abcdef12",
        "Show events in a date range. Example: kalendaro ls 20260125 20260130 "
        "-k abcdef12",
        "Afficher les événements dans une plage de dates. Exemple : "
        "kalendaro ls 20260125 20260130 -k abcdef12",
    ),
)
def ls(
    dato1: str | None = typer.Argument(None, help="Komenca dato (YYYYMMDD/MMDD/DD)."),
    dato2: str | None = typer.Argument(None, help="Fina dato (opcia)."),
    kalendaro: list[str] | None = typer.Option(
        None, "-k", "--kalendaro", help="Filtri laŭ kalendaro UUID."
    ),
) -> None:
    start, end = _parse_range(dato1, dato2)
    con = _connect()
    try:
        cal_uuids: list[str] = []
        if kalendaro:
            for ref in kalendaro:
                resolved = _resolve_calendar_uuid(con, ref)
                if resolved:
                    cal_uuids.append(resolved)
        params: list[str] = [start.isoformat(), end.isoformat()]
        query = (
            "SELECT uuid, calendar_uuid, titolo, komenco, fino FROM events "
            "WHERE date(komenco) >= ? AND date(komenco) <= ?"
        )
        if cal_uuids:
            placeholders = ",".join("?" for _ in cal_uuids)
            query += f" AND calendar_uuid IN ({placeholders})"
            params.extend(cal_uuids)
        query += " ORDER BY komenco ASC"
        rows = con.execute(query, tuple(params)).fetchall()
    finally:
        con.close()
    table = Table(header_style="dim", border_style="dim")
    table.add_column("UUID", style="dim", width=10)
    table.add_column("Titolo")
    table.add_column("Dato", width=12)
    table.add_column("Komenco", width=8)
    table.add_column("Fino", width=8)
    table.add_column("Kalendaro", style="dim", width=10)
    for row in rows:
        table.add_row(
            str(row["uuid"])[:8],
            str(row["titolo"] or ""),
            _fmt_date(str(row["komenco"])),
            _fmt_hhmm(str(row["komenco"])),
            _fmt_hhmm(str(row["fino"])),
            str(row["calendar_uuid"])[:8],
        )
    console.print(table)


@app.command(
    "vidi",
    help=tr(
        "Montri detalojn de unu aŭ pluraj eventoj. Ekz: kalendaro vidi a1b2c3d4",
        "Show details for one or more events. Example: kalendaro vidi a1b2c3d4",
        "Afficher les détails d'un ou plusieurs événements. Exemple : "
        "kalendaro vidi a1b2c3d4",
    ),
)
def vidi(
    eventoj: list[str] = typer.Argument(..., help="UUID(j) de evento(j)."),
) -> None:
    con = _connect()
    try:
        for ref in eventoj:
            uid = _resolve_event_uuid(con, ref)
            if not uid:
                typer.echo(f"Evento ne trovita: {ref!r}", err=True)
                continue
            row = con.execute(
                """
                SELECT e.*, c.url AS calendar_url
                FROM events e JOIN calendars c ON c.uuid = e.calendar_uuid
                WHERE e.uuid = ?
                """,
                (uid,),
            ).fetchone()
            if row is None:
                continue
            participants = ", ".join(json.loads(str(row["partoprenantoj"] or "[]")))
            lines = [
                f"|{str(row['uuid'])[:8]}|{_fmt_date(str(row['komenco']))}|{str(row['calendar_uuid'])[:8]}|",
                f"|{_fmt_hhmm(str(row['komenco']))}|{_fmt_hhmm(str(row['fino']))}|",
                f"|{str(row['kategorio'] or '')}|{str(row['loko'] or '')}|",
                f"|{str(row['ripeto'] or 'never')}|",
                f"|{participants}|",
                f"|{str(row['priskribo'] or '')}|",
            ]
            for line in lines:
                typer.echo(line)
            typer.echo("")
    finally:
        con.close()


@app.command(
    "importi",
    help=tr(
        "Importi ICS-dosierojn en kalendaron. Ekz: kalendaro importi abcdef12 "
        "/tmp/e1.ics /tmp/e2.ics",
        "Import ICS files into a calendar. Example: kalendaro importi abcdef12 "
        "/tmp/e1.ics /tmp/e2.ics",
        "Importer des fichiers ICS dans un calendrier. Exemple : kalendaro importi "
        "abcdef12 /tmp/e1.ics /tmp/e2.ics",
    ),
)
def importi(
    kalendaro_uuid: str = typer.Argument(..., help="Kalendaro UUID."),
    dosieroj: list[str] = typer.Argument(..., help="ICS dosiero(j)."),
) -> None:
    con = _connect()
    try:
        resolved_cal = _resolve_calendar_uuid(con, kalendaro_uuid)
        if not resolved_cal:
            typer.echo("Kalendaro ne trovita.", err=True)
            raise typer.Exit(code=1)
        _warn_unsynced(con, [resolved_cal])
        now = now_iso()
        added: list[str] = []
        for file_path in dosieroj:
            text = Path(file_path).read_text(encoding="utf-8")
            added.extend(_insert_ics_events(con, resolved_cal, text, now=now))
        change_id = _push_undo(con, "importi", {"event_ids": added})
        _queue_sync(con, resolved_cal, "importi", {"event_ids": added})
        con.commit()
    finally:
        con.close()
    typer.echo(f"Importis {len(added)} evento(j)n. ŝanĝo={change_id}")


def _events_to_ics(rows: list[sqlite3.Row]) -> str:
    out = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//autish//kalendaro//EO"]
    for row in rows:
        start = _parse_dt(str(row["komenco"])).strftime("%Y%m%dT%H%M%SZ")
        end = _parse_dt(str(row["fino"])).strftime("%Y%m%dT%H%M%SZ")
        out.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{str(row['uuid'])}",
                f"SUMMARY:{str(row['titolo'] or '')}",
                f"DTSTART:{start}",
                f"DTEND:{end}",
                f"LOCATION:{str(row['loko'] or '')}",
                f"CATEGORIES:{str(row['kategorio'] or '')}",
                f"DESCRIPTION:{str(row['priskribo'] or '')}",
                "END:VEVENT",
            ]
        )
    out.append("END:VCALENDAR")
    return "\n".join(out) + "\n"


@app.command(
    "eksporti",
    help=tr(
        "Eksporti eventojn laŭ UUID aŭ laŭ kalendaro+datoj. Ekz: kalendaro "
        "eksporti -k abcdef12 20260101 20260131 -d /tmp/out.ics",
        "Export events by UUID or by calendar+date range. Example: kalendaro "
        "eksporti -k abcdef12 20260101 20260131 -d /tmp/out.ics",
        "Exporter des événements par UUID ou par calendrier+plage de dates. "
        "Exemple : kalendaro eksporti -k abcdef12 20260101 20260131 -d /tmp/out.ics",
    ),
)
def eksporti(
    argumentoj: list[str] = typer.Argument(
        None, help="Evento UUID(j) aŭ opciaj limdatoj (YYYYMMDD/MMDD/DD)."
    ),
    kalendaro: list[str] | None = typer.Option(
        None, "-k", "--kalendaro", help="Kalendaro UUID(j) por intervala eksporto."
    ),
    dosiero: str | None = typer.Option(
        None, "-d", "--dosiero", help="Cela .ics dosiero."
    ),
) -> None:
    args = argumentoj or []
    date_tokens: list[str] = []
    refs: list[str] = []
    for token in args:
        if token.isdigit() and len(token) in (2, 4, 8):
            date_tokens.append(token)
        else:
            refs.append(token)
    con = _connect()
    try:
        rows: list[sqlite3.Row] = []
        if refs:
            for ref in refs:
                uid = _resolve_event_uuid(con, ref)
                if uid:
                    row = con.execute(
                        "SELECT * FROM events WHERE uuid = ?", (uid,)
                    ).fetchone()
                    if row:
                        rows.append(row)
        else:
            start_token = date_tokens[0] if date_tokens else None
            end_token = date_tokens[1] if len(date_tokens) > 1 else None
            start, end = _parse_range(start_token, end_token)
            params: list[str] = [start.isoformat(), end.isoformat()]
            query = (
                "SELECT * FROM events WHERE date(komenco) >= ? AND date(komenco) <= ?"
            )
            if kalendaro:
                cals: list[str] = []
                for ref in kalendaro:
                    resolved = _resolve_calendar_uuid(con, ref)
                    if resolved:
                        cals.append(resolved)
                if cals:
                    placeholders = ",".join("?" for _ in cals)
                    query += f" AND calendar_uuid IN ({placeholders})"
                    params.extend(cals)
            rows = con.execute(
                query + " ORDER BY komenco ASC", tuple(params)
            ).fetchall()
    finally:
        con.close()
    payload = _events_to_ics(rows)
    if dosiero:
        path = Path(dosiero)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
        typer.echo(f"Eksportis {len(rows)} evento(j)n al {path}")
        return
    typer.echo(payload.rstrip("\n"))


def _confirm_events(rows: list[sqlite3.Row]) -> bool:
    typer.echo(f"Trafitaj eventoj: {len(rows)}")
    for row in rows[:20]:
        summary = (
            f" - #{str(row['uuid'])[:8]} "
            f"{_fmt_date(str(row['komenco']))} {str(row['titolo'] or '')}"
        )
        typer.echo(summary)
    answer = typer.prompt("Ĉu daŭrigi? (j/N)", default="N").strip().lower()
    return answer in {"j", "jes", "y", "yes"}


@app.command(
    "forigi",
    help=tr(
        "Forigi eventojn laŭ UUID. Ekz: kalendaro forigi a1b2c3d4 -a",
        "Delete events by UUID. Example: kalendaro forigi a1b2c3d4 -a",
        "Supprimer des événements par UUID. Exemple : kalendaro forigi a1b2c3d4 -a",
    ),
)
def forigi(
    eventoj: list[str] = typer.Argument(..., help="Evento UUID(j) por forigi."),
    cxiuj: bool = typer.Option(
        False, "-a", "--cxiuj", help="Por ripetaj eventoj, forigi ĉiujn okazojn."
    ),
) -> None:
    con = _connect()
    try:
        uuids: list[str] = []
        for ref in eventoj:
            uid = _resolve_event_uuid(con, ref)
            if uid:
                uuids.append(uid)
        if not uuids:
            typer.echo("Neniu valida evento por forigi.", err=True)
            raise typer.Exit(code=1)
        placeholders = ",".join("?" for _ in uuids)
        rows = con.execute(
            f"SELECT * FROM events WHERE uuid IN ({placeholders})", tuple(uuids)
        ).fetchall()
        if not _confirm_events(rows):
            typer.echo("Nuligita.")
            return
        _warn_unsynced(con, [str(r["calendar_uuid"]) for r in rows])
        payload = [_row_to_event_dict(r) for r in rows]
        if cxiuj:
            targets = []
            for row in rows:
                rep = str(row["ripeto"] or "")
                if rep:
                    same = con.execute(
                        "SELECT * FROM events "
                        "WHERE calendar_uuid = ? AND titolo = ? AND ripeto = ?",
                        (str(row["calendar_uuid"]), str(row["titolo"]), rep),
                    ).fetchall()
                    targets.extend(same)
                else:
                    targets.append(row)
            seen: set[str] = set()
            unique = []
            for row in targets:
                uid = str(row["uuid"])
                if uid not in seen:
                    seen.add(uid)
                    unique.append(row)
            rows = unique
            payload = [_row_to_event_dict(r) for r in rows]
        for row in rows:
            con.execute("DELETE FROM events WHERE uuid = ?", (str(row["uuid"]),))
            _queue_sync(
                con,
                str(row["calendar_uuid"]),
                "forigi",
                {"event_uuid": str(row["uuid"])},
            )
        change_id = _push_undo(con, "forigi", {"events": payload})
        con.commit()
    finally:
        con.close()
    typer.echo(f"Forigis {len(rows)} evento(j)n. ŝanĝo={change_id}")


@app.command(
    "amase-forigi",
    help=tr(
        "Forigi eventojn en intervalo, opcie laŭ kalendaro. Ekz: kalendaro "
        "amase-forigi 20260101 20260131 -k abcdef12",
        "Delete events in a range, optionally by calendar. Example: kalendaro "
        "amase-forigi 20260101 20260131 -k abcdef12",
        "Supprimer des événements dans une plage, optionnellement par calendrier. "
        "Exemple : kalendaro amase-forigi 20260101 20260131 -k abcdef12",
    ),
)
def amase_forigi(
    dato1: str = typer.Argument(..., help="Komenca dato."),
    dato2: str = typer.Argument(..., help="Fina dato."),
    kalendaro: list[str] | None = typer.Option(
        None, "-k", "--kalendaro", help="Filtri laŭ kalendaro UUID."
    ),
) -> None:
    start, end = _parse_range(dato1, dato2)
    con = _connect()
    try:
        params: list[str] = [start.isoformat(), end.isoformat()]
        query = "SELECT * FROM events WHERE date(komenco) >= ? AND date(komenco) <= ?"
        if kalendaro:
            cals: list[str] = []
            for ref in kalendaro:
                resolved = _resolve_calendar_uuid(con, ref)
                if resolved:
                    cals.append(resolved)
            if cals:
                placeholders = ",".join("?" for _ in cals)
                query += f" AND calendar_uuid IN ({placeholders})"
                params.extend(cals)
        rows = con.execute(query, tuple(params)).fetchall()
        if not rows:
            typer.echo("Neniu evento trovita.")
            return
        if not _confirm_events(rows):
            typer.echo("Nuligita.")
            return
        _warn_unsynced(con, [str(r["calendar_uuid"]) for r in rows])
        payload = [_row_to_event_dict(r) for r in rows]
        for row in rows:
            con.execute("DELETE FROM events WHERE uuid = ?", (str(row["uuid"]),))
            _queue_sync(
                con,
                str(row["calendar_uuid"]),
                "amase-forigi",
                {"event_uuid": str(row["uuid"])},
            )
        change_id = _push_undo(con, "forigi", {"events": payload})
        con.commit()
    finally:
        con.close()
    typer.echo(f"Forigis {len(rows)} evento(j)n. ŝanĝo={change_id}")


@app.command(
    "malfari",
    help=tr(
        "Montri aŭ malfari ŝanĝojn. Ekz: kalendaro malfari ls ; kalendaro "
        "malfari 12ab34cd",
        "List or undo changes. Example: kalendaro malfari ls ; kalendaro "
        "malfari 12ab34cd",
        "Lister ou annuler des changements. Exemple : kalendaro malfari ls ; "
        "kalendaro malfari 12ab34cd",
    ),
)
def malfari(
    argumentoj: list[str] = typer.Argument(
        None, help="ls por listi ŝanĝojn, aŭ unu/pluraj ŝanĝo-IDj."
    ),
) -> None:
    args = argumentoj or []
    con = _connect()
    try:
        if not args or args == ["ls"]:
            rows = con.execute(
                "SELECT id, operacio, kreita_je FROM undo_changes "
                "ORDER BY kreita_je DESC LIMIT 20"
            ).fetchall()
            for row in rows:
                typer.echo(
                    f"{str(row['id'])}  {str(row['operacio'])}  "
                    f"{(str(row['kreita_je'])[:19])}"
                )
            return
        for change_id in args:
            row = con.execute(
                "SELECT id, operacio, payload FROM undo_changes WHERE id = ?",
                (change_id,),
            ).fetchone()
            if row is None:
                typer.echo(f"Ŝanĝo ne trovita: {change_id}", err=True)
                continue
            payload = json.loads(str(row["payload"]))
            op = str(row["operacio"])
            if op == "importi":
                conflicts = []
                for uid in payload.get("event_ids", []):
                    exists = con.execute(
                        "SELECT 1 FROM events WHERE uuid = ?", (str(uid),)
                    ).fetchone()
                    if exists:
                        con.execute("DELETE FROM events WHERE uuid = ?", (str(uid),))
                    else:
                        conflicts.append(str(uid)[:8])
                if conflicts:
                    typer.echo(
                        "Averto: konflikto ĉe malfaro (jam forigita): "
                        + ", ".join(conflicts),
                        err=True,
                    )
            elif op == "forigi":
                conflicts = []
                for event in payload.get("events", []):
                    uid = str(event.get("uuid") or "")
                    exists = con.execute(
                        "SELECT 1 FROM events WHERE uuid = ?", (uid,)
                    ).fetchone()
                    if exists:
                        conflicts.append(uid[:8])
                        continue
                    con.execute(
                        """
                        INSERT INTO events(
                          uuid, calendar_uuid, titolo, komenco, fino, kategorio, loko,
                          ripeto, partoprenantoj, priskribo, kreita_je, modifita_je
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            uid,
                            str(event.get("calendar_uuid") or ""),
                            str(event.get("titolo") or ""),
                            str(event.get("komenco") or now_iso()),
                            str(event.get("fino") or now_iso()),
                            str(event.get("kategorio") or ""),
                            str(event.get("loko") or ""),
                            str(event.get("ripeto") or ""),
                            json.dumps(
                                event.get("partoprenantoj") or [], ensure_ascii=False
                            ),
                            str(event.get("priskribo") or ""),
                            now_iso(),
                            now_iso(),
                        ),
                    )
                if conflicts:
                    typer.echo(
                        "Averto: konflikto ĉe malfaro (UUID jam ekzistas): "
                        + ", ".join(conflicts),
                        err=True,
                    )
                    typer.echo("Sugesto: forigu la konfliktajn eventojn kaj reprovu.")
            elif op == "forigi-kalendaro":
                for item in payload.get("items", []):
                    cal = item.get("calendar") or {}
                    cal_uuid = str(cal.get("uuid") or "")
                    if not cal_uuid:
                        continue
                    exists = con.execute(
                        "SELECT 1 FROM calendars WHERE uuid = ?", (cal_uuid,)
                    ).fetchone()
                    if not exists:
                        con.execute(
                            """
                            INSERT INTO calendars(
                              uuid, url, username, remote, kreita_je, modifita_je
                            )
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (
                                cal_uuid,
                                str(cal.get("url") or ""),
                                str(cal.get("username") or ""),
                                int(cal.get("remote") or 1),
                                str(cal.get("kreita_je") or now_iso()),
                                str(cal.get("modifita_je") or now_iso()),
                            ),
                        )
                    for event in item.get("events") or []:
                        uid = str(event.get("uuid") or "")
                        if not uid:
                            continue
                        exists_ev = con.execute(
                            "SELECT 1 FROM events WHERE uuid = ?", (uid,)
                        ).fetchone()
                        if exists_ev:
                            continue
                        con.execute(
                            """
                            INSERT INTO events(
                              uuid, calendar_uuid, titolo, komenco, fino,
                              kategorio, loko,
                              ripeto, partoprenantoj, priskribo, kreita_je, modifita_je
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                uid,
                                str(event.get("calendar_uuid") or cal_uuid),
                                str(event.get("titolo") or ""),
                                str(event.get("komenco") or now_iso()),
                                str(event.get("fino") or now_iso()),
                                str(event.get("kategorio") or ""),
                                str(event.get("loko") or ""),
                                str(event.get("ripeto") or ""),
                                json.dumps(
                                    event.get("partoprenantoj") or [],
                                    ensure_ascii=False,
                                ),
                                str(event.get("priskribo") or ""),
                                now_iso(),
                                now_iso(),
                            ),
                        )
            con.execute("DELETE FROM undo_changes WHERE id = ?", (str(row["id"]),))
        con.commit()
    finally:
        con.close()
    typer.echo("Malfaro preta.")


@app.command(
    "serci",
    help=tr(
        "Serĉi eventojn kun kombineblaj filtriloj. Ekz: kalendaro serci kunveno "
        "--dato-de 20260101 --dato-gis 20260131 --kategorio laboro",
        "Search events with combinable filters. Example: kalendaro serci meeting "
        "--dato-de 20260101 --dato-gis 20260131 --kategorio work",
        "Rechercher des événements avec filtres combinables. Exemple : kalendaro "
        "serci réunion --dato-de 20260101 --dato-gis 20260131 --kategorio travail",
    ),
)
def serci(
    demando: str | None = typer.Argument(None, help="Serĉ-demando (titolo/priskribo)."),
    kalendaro: list[str] | None = typer.Option(
        None, "-k", "--kalendaro", help="Filtri laŭ kalendaro UUID."
    ),
    kategorio: str | None = typer.Option(
        None, "--kategorio", help="Filtri laŭ kategorio."
    ),
    loko: str | None = typer.Option(None, "--loko", help="Filtri laŭ loko."),
    dato_de: str | None = typer.Option(None, "--dato-de", help="Komenca dato."),
    dato_gis: str | None = typer.Option(None, "--dato-gis", help="Fina dato."),
    preciza: bool = typer.Option(
        False, "-p", "--preciza", help="Malŝalti malklaran kongruigon."
    ),
    limo: int = typer.Option(50, "-lo", "--limo", help="Maksimuma nombro da rezultoj."),
) -> None:
    con = _connect()
    try:
        rows = con.execute("SELECT * FROM events").fetchall()
        filtered = list(rows)
        if kalendaro:
            allowed: set[str] = set()
            for ref in kalendaro:
                resolved = _resolve_calendar_uuid(con, ref)
                if resolved:
                    allowed.add(resolved)
            filtered = [r for r in filtered if str(r["calendar_uuid"]) in allowed]
        if kategorio:
            low = kategorio.lower()
            filtered = [r for r in filtered if low in str(r["kategorio"] or "").lower()]
        if loko:
            low = loko.lower()
            filtered = [r for r in filtered if low in str(r["loko"] or "").lower()]
        if dato_de:
            start, _ = _parse_range(dato_de, None)
            filtered = [
                r for r in filtered if _fmt_date(str(r["komenco"])) >= start.isoformat()
            ]
        if dato_gis:
            _, end = _parse_range(dato_gis, None)
            filtered = [
                r for r in filtered if _fmt_date(str(r["komenco"])) <= end.isoformat()
            ]
        if demando:
            q = demando.lower()
            exact = [
                r
                for r in filtered
                if q in str(r["titolo"] or "").lower()
                or q in str(r["priskribo"] or "").lower()
            ]
            if exact or preciza:
                filtered = exact
            else:
                scored: list[tuple[float, sqlite3.Row]] = []
                for row in filtered:
                    hay = f"{row['titolo']} {row['priskribo']}".lower()
                    ratio = SequenceMatcher(None, q, hay).ratio()
                    if ratio >= 0.45:
                        scored.append((ratio, row))
                scored.sort(key=lambda x: x[0], reverse=True)
                filtered = [r for _, r in scored]
        filtered = filtered[: max(0, limo)]
    finally:
        con.close()
    table = Table(header_style="dim", border_style="dim")
    table.add_column("UUID", style="dim", width=10)
    table.add_column("Titolo")
    table.add_column("Dato", width=12)
    table.add_column("Komenco", width=8)
    table.add_column("Fino", width=8)
    table.add_column("Kalendaro", style="dim", width=10)
    for row in filtered:
        table.add_row(
            str(row["uuid"])[:8],
            str(row["titolo"] or ""),
            _fmt_date(str(row["komenco"])),
            _fmt_hhmm(str(row["komenco"])),
            _fmt_hhmm(str(row["fino"])),
            str(row["calendar_uuid"])[:8],
        )
    console.print(table)


@app.command(
    "forigi-kalendaro",
    help=tr(
        "Forigi unu aŭ plurajn kalendarojn laŭ UUID, aŭ ĉion sen UUID "
        "(kun konfirmo). Ekz: kalendaro forigi-kalendaro abcdef12",
        "Delete one or more calendars by UUID, or all without UUID "
        "(with confirmation). Example: kalendaro forigi-kalendaro abcdef12",
        "Supprimer un ou plusieurs calendriers par UUID, ou tout sans UUID "
        "(avec confirmation). Exemple : kalendaro forigi-kalendaro abcdef12",
    ),
)
def forigi_kalendaro(
    kalendaroj: list[str] | None = typer.Argument(
        None, help="Kalendaro UUID(j). Se malplena, forigi ĉiujn."
    ),
) -> None:
    con = _connect()
    try:
        resolved: list[str] = []
        if kalendaroj:
            for ref in kalendaroj:
                uid = _resolve_calendar_uuid(con, ref)
                if uid:
                    resolved.append(uid)
        else:
            rows = con.execute(
                "SELECT uuid FROM calendars ORDER BY kreita_je DESC"
            ).fetchall()
            if not rows:
                typer.echo("Neniu kalendaro por forigi.")
                return
            typer.echo(f"Trafitaj kalendaroj: {len(rows)}")
            answer = typer.prompt("Ĉu forigi ĉiujn kalendarojn? (j/N)", default="N")
            if answer.strip().lower() not in {"j", "jes", "y", "yes"}:
                typer.echo("Nuligita.")
                return
            resolved = [str(row["uuid"]) for row in rows]
        if not resolved:
            typer.echo("Neniu valida kalendaro por forigi.", err=True)
            raise typer.Exit(code=1)
        _warn_unsynced(con, resolved)
        payload: list[dict] = []
        for uid in resolved:
            cal = con.execute(
                "SELECT * FROM calendars WHERE uuid = ?", (uid,)
            ).fetchone()
            events = con.execute(
                "SELECT * FROM events WHERE calendar_uuid = ?", (uid,)
            ).fetchall()
            payload.append(
                {
                    "calendar": dict(cal) if cal is not None else {"uuid": uid},
                    "events": [_row_to_event_dict(e) for e in events],
                }
            )
            con.execute("DELETE FROM events WHERE calendar_uuid = ?", (uid,))
            con.execute("DELETE FROM calendars WHERE uuid = ?", (uid,))
            _delete_password(uid)
        change_id = _push_undo(con, "forigi-kalendaro", {"items": payload})
        con.commit()
    finally:
        con.close()
    typer.echo(f"Forigis {len(resolved)} kalendaro(j)n. ŝanĝo={change_id}")


@app.command(
    "sinkronigi",
    help=tr(
        "Sinkronigi pendajn lokajn ŝanĝojn al foraj kalendaroj. Ekz: kalendaro "
        "sinkronigi -k abcdef12",
        "Synchronize pending local changes to remote calendars. Example: kalendaro "
        "sinkronigi -k abcdef12",
        "Synchroniser les changements locaux en attente vers calendriers distants. "
        "Exemple : kalendaro sinkronigi -k abcdef12",
    ),
)
def sinkronigi(
    kalendaro: list[str] | None = typer.Option(
        None,
        "-k",
        "--kalendaro",
        help=tr(
            "Filtri sinkronigon laŭ kalendaro UUID. Ekz: -k abcdef12",
            "Filter sync by calendar UUID. Example: -k abcdef12",
            "Filtrer la synchro par UUID calendrier. Exemple : -k abcdef12",
        ),
    ),
) -> None:
    con = _connect()
    try:
        target_uuids: list[str] = []
        if kalendaro:
            for ref in kalendaro:
                uid = _resolve_calendar_uuid(con, ref)
                if uid:
                    target_uuids.append(uid)
            if not target_uuids:
                typer.echo("Neniu valida kalendaro por sinkronigi.", err=True)
                raise typer.Exit(code=1)
        else:
            rows = con.execute("SELECT uuid FROM calendars").fetchall()
            target_uuids = [str(row["uuid"]) for row in rows]

        where = ""
        params: list[str] = []
        if target_uuids:
            placeholders = ",".join("?" for _ in target_uuids)
            where = f" AND calendar_uuid IN ({placeholders})"
            params.extend(target_uuids)

        # Add pull-sync jobs for selected remote calendars when not already pending.
        if target_uuids:
            remote_rows = con.execute(
                "SELECT uuid, url FROM calendars WHERE uuid IN ("
                + ",".join("?" for _ in target_uuids)
                + ")",
                tuple(target_uuids),
            ).fetchall()
            for row in remote_rows:
                uid = str(row["uuid"])
                url = str(row["url"] or "")
                if not _is_remote_calendar_url(url):
                    continue
                already_pending = con.execute(
                    "SELECT 1 FROM sync_queue "
                    "WHERE calendar_uuid = ? AND operacio = 'tiri' "
                    "AND stato = 'pending'",
                    (uid,),
                ).fetchone()
                if already_pending:
                    continue
                _queue_sync(con, uid, "tiri", {"source": "sinkronigi"})

        # Retry failed jobs when user explicitly asks for sync.
        now = now_iso()
        con.execute(
            "UPDATE sync_queue SET stato='pending', modifita_je=? "
            "WHERE stato='failed'" + where,
            (now, *params),
        )
        pending = con.execute(
            "SELECT id FROM sync_queue WHERE stato='pending'" + where,
            tuple(params),
        ).fetchall()
        if not pending:
            typer.echo("Nenio por sinkronigi.")
            return
        # Preserve queue order and never drop pending local changes.
        con.commit()
        _start_sync_worker()
    finally:
        con.close()
    typer.echo(f"Lanĉis sinkronigon por {len(pending)} pendaj ŝanĝoj.")
