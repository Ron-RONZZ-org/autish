"""kontakto — standalone contact management command."""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from autish.commands import retposto as retposto_mod
from autish.commands.uzanto import _normalize_multi_contact_list

app = typer.Typer(
    name="kontakto",
    help="Administri kontaktojn.",
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help", "--helpo"]},
)

kategorio_app = typer.Typer(
    name="kategorio",
    help="Administri kontaktajn kategoriojn.",
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help", "--helpo"]},
)
app.add_typer(kategorio_app, name="kategorio")

_MAX_UNDO = 10


def _print_wide_table(table: Table) -> None:
    Console(width=220).print(table)


def _norm_kategorioj(raw: list[str] | None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in raw or []:
        k = item.strip()
        if not k:
            continue
        low = k.lower()
        if low in seen:
            continue
        seen.add(low)
        out.append(k)
    return out


def _norm_kampoj(raw: list[str] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in raw or []:
        if ":" not in item:
            raise ValueError(f"Kampo-formato malĝusta (KEY:VALUE): {item}")
        key, _, value = item.partition(":")
        out[key.strip()] = value.strip()
    return out


def _row_to_contact(row: Any) -> dict:
    d = dict(row)
    raw = d.get("kategorioj")
    if isinstance(raw, str):
        try:
            d["kategorioj"] = json.loads(raw)
        except json.JSONDecodeError:
            d["kategorioj"] = []
    elif raw is None:
        d["kategorioj"] = []
    for field in ("lingvoj", "telefonnumeroj", "retposhtadresoj"):
        raw_field = d.get(field)
        if isinstance(raw_field, str):
            try:
                d[field] = json.loads(raw_field)
            except json.JSONDecodeError:
                d[field] = []
        elif raw_field is None:
            d[field] = []
    kampoj_raw = d.get("kampoj")
    if isinstance(kampoj_raw, str):
        try:
            d["kampoj"] = json.loads(kampoj_raw)
        except json.JSONDecodeError:
            d["kampoj"] = {}
    elif kampoj_raw is None:
        d["kampoj"] = {}
    return d


def _load_contacts() -> list[dict]:
    with retposto_mod._get_db() as con:
        rows = con.execute("SELECT * FROM kontakto ORDER BY nomo ASC").fetchall()
    return [_row_to_contact(r) for r in rows]


def _contact_to_row_args(contact: dict) -> tuple:
    return (
        contact.get("id"),
        contact.get("uuid"),
        contact.get("nomo"),
        contact.get("familia_nomo"),
        contact.get("naskig_dato"),
        contact.get("naskig_loko"),
        json.dumps(contact.get("lingvoj") or [], ensure_ascii=False),
        contact.get("retposto"),
        contact.get("organizo"),
        contact.get("organiza_identiga_numero"),
        contact.get("telefono"),
        json.dumps(contact.get("telefonnumeroj") or [], ensure_ascii=False),
        json.dumps(contact.get("retposhtadresoj") or [], ensure_ascii=False),
        json.dumps(contact.get("kampoj") or {}, ensure_ascii=False),
        int(contact.get("konfirmita") or 0),
        json.dumps(contact.get("kategorioj") or [], ensure_ascii=False),
        contact.get("noto"),
        contact.get("kreita_je"),
        contact.get("modifita_je"),
    )


def _find_by_uuid(identifier: str) -> dict | None:
    lookup = identifier[1:] if identifier.startswith("#") else identifier
    contacts = _load_contacts()
    exact = [c for c in contacts if c.get("uuid") == lookup]
    if len(exact) == 1:
        return exact[0]
    prefix = [c for c in contacts if str(c.get("uuid") or "").startswith(lookup)]
    if len(prefix) == 1:
        return prefix[0]
    return None


def _save_undo(operation: dict) -> None:
    now = retposto_mod._now_iso()
    with retposto_mod._get_db() as con:
        con.execute(
            "INSERT INTO kontakto_undo (operation, kreita_je) VALUES (?, ?)",
            (json.dumps(operation, ensure_ascii=False), now),
        )
        rows = con.execute(
            "SELECT id FROM kontakto_undo ORDER BY id DESC"
        ).fetchall()
        for row in rows[_MAX_UNDO:]:
            con.execute("DELETE FROM kontakto_undo WHERE id = ?", (row["id"],))


def _pop_undo() -> dict | None:
    with retposto_mod._get_db() as con:
        row = con.execute(
            "SELECT id, operation FROM kontakto_undo ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        con.execute("DELETE FROM kontakto_undo WHERE id = ?", (row["id"],))
        return json.loads(row["operation"])


def _ensure_categories_exist(categories: list[str]) -> None:
    now = retposto_mod._now_iso()
    with retposto_mod._get_db() as con:
        for category in categories:
            con.execute(
                "INSERT OR IGNORE INTO kontakto_kategorio (nomo, kreita_je) "
                "VALUES (?,?)",
                (category, now),
            )


def _search_contact_match(contact: dict, query: str) -> bool:
    q = query.lower().strip()
    if not q:
        return True
    if q in (contact.get("nomo") or "").lower():
        return True
    if q in (contact.get("familia_nomo") or "").lower():
        return True
    if any(q in email.lower() for email in _contact_email_values(contact)):
        return True
    if q in (contact.get("organizo") or "").lower():
        return True
    if q in (contact.get("organiza_identiga_numero") or "").lower():
        return True
    if q in (contact.get("naskig_loko") or "").lower():
        return True
    if q in str((contact.get("kampoj") or {}).get("postadreso") or "").lower():
        return True
    if any(q in str(v).lower() for v in (contact.get("kampoj") or {}).values()):
        return True
    return False


def _contact_email_values(contact: dict) -> list[str]:
    values: list[str] = []
    primary = str(contact.get("retposto") or "").strip()
    if primary:
        values.append(primary)
    extra_values: list[str] = []
    for item in contact.get("retposhtadresoj") or []:
        if isinstance(item, dict):
            value = str(item.get("valoro") or "").strip()
            if value:
                extra_values.append(value)
        elif isinstance(item, str) and item.strip():
            extra_values.append(item.strip())
    values.extend(extra_values)
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        low = value.lower()
        if low in seen:
            continue
        seen.add(low)
        unique.append(value)
    return unique


def _contact_primary_email(contact: dict) -> str:
    emails = _contact_email_values(contact)
    return emails[0] if emails else ""


def _contact_full_name(contact: dict) -> str:
    return " ".join(
        part
        for part in [contact.get("nomo") or "", contact.get("familia_nomo") or ""]
        if part
    ).strip()


def _contact_search_blob(contact: dict) -> str:
    phones = " ".join(
        str(item.get("valoro") or "")
        for item in (contact.get("telefonnumeroj") or [])
        if isinstance(item, dict)
    )
    mails = " ".join(
        str(item.get("valoro") or "")
        for item in (contact.get("retposhtadresoj") or [])
        if isinstance(item, dict)
    )
    cats = " ".join(contact.get("kategorioj") or [])
    custom = " ".join(
        f"{k} {v}" for k, v in (contact.get("kampoj") or {}).items()
    )
    return " ".join(
        [
            _contact_full_name(contact),
            str(contact.get("retposto") or ""),
            str(contact.get("organizo") or ""),
            str(contact.get("organiza_identiga_numero") or ""),
            str(contact.get("naskig_loko") or ""),
            str(contact.get("telefono") or ""),
            str((contact.get("kampoj") or {}).get("postadreso") or ""),
            phones,
            mails,
            cats,
            custom,
        ]
    )


def _insert_contact_without_email(
    nomo: str | None = None,
    familia_nomo: str | None = None,
    naskig_dato: str | None = None,
    naskig_loko: str | None = None,
    lingvoj: list[str] | None = None,
    organizo: str | None = None,
    organiza_identiga_numero: str | None = None,
    telefono: str | None = None,
    telefonnumeroj: list[dict] | None = None,
    retposhtadresoj: list[dict] | None = None,
    kategorioj: list[str] | None = None,
    kampoj: dict[str, str] | None = None,
    noto: str | None = None,
    konfirmita: int = 1,
) -> dict:
    now = retposto_mod._now_iso()
    uid = retposto_mod._make_uuid()
    with retposto_mod._get_db() as con:
        con.execute(
            """INSERT INTO kontakto
               (uuid, nomo, familia_nomo, naskig_dato, naskig_loko, lingvoj,
                retposto, organizo, organiza_identiga_numero,
                 telefono, telefonnumeroj, retposhtadresoj, kampoj, konfirmita,
                 kategorioj, noto, kreita_je, modifita_je)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                uid,
                nomo,
                familia_nomo,
                naskig_dato,
                naskig_loko,
                json.dumps(lingvoj or [], ensure_ascii=False),
                None,
                organizo,
                organiza_identiga_numero,
                telefono,
                json.dumps(telefonnumeroj or [], ensure_ascii=False),
                json.dumps(retposhtadresoj or [], ensure_ascii=False),
                json.dumps(kampoj or {}, ensure_ascii=False),
                int(bool(konfirmita)),
                json.dumps(kategorioj or [], ensure_ascii=False),
                noto,
                now,
                now,
            ),
        )
        row = con.execute("SELECT * FROM kontakto WHERE uuid = ?", (uid,)).fetchone()
    return _row_to_contact(row) if row is not None else {"uuid": uid}


def _update_contact_by_uuid(
    contact_uuid: str, update_fields: dict[str, object]
) -> None:
    allowed = {
        "nomo",
        "familia_nomo",
        "naskig_dato",
        "naskig_loko",
        "lingvoj",
        "retposto",
        "organizo",
        "organiza_identiga_numero",
        "telefono",
        "telefonnumeroj",
        "retposhtadresoj",
        "kampoj",
        "noto",
        "konfirmita",
        "kategorioj",
        "modifita_je",
    }
    invalid = set(update_fields) - allowed
    if invalid:
        raise ValueError(f"Nevalidaj kampoj por ĝisdatigo: {invalid}")
    set_clause = ", ".join(f"{k} = ?" for k in update_fields)
    with retposto_mod._get_db() as con:
        con.execute(
            f"UPDATE kontakto SET {set_clause} WHERE uuid = ?",
            [*update_fields.values(), contact_uuid],
        )


def _matches_potential_duplicate(
    candidate: dict,
    nomo: str | None,
    familia_nomo: str | None,
    organizo: str | None,
) -> bool:
    checks = [
        (nomo, candidate.get("nomo")),
        (familia_nomo, candidate.get("familia_nomo")),
        (organizo, candidate.get("organizo")),
    ]
    for wanted, existing in checks:
        if wanted is None:
            continue
        if wanted.strip() == "":
            continue
        if wanted.strip().lower() != str(existing or "").strip().lower():
            return False
    return True


def _match_contacts_by_regex(pattern: str) -> list[dict]:
    try:
        rx = re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        typer.echo(f"[!] Nevalida regex: {exc}", err=True)
        raise typer.Exit(1) from exc
    return [c for c in _load_contacts() if rx.search(_contact_search_blob(c))]


def _resolve_targets(
    identigiloj: list[str],
    regex_pattern: str | None,
    action_label: str,
) -> tuple[list[dict], bool]:
    if regex_pattern:
        matched = _match_contacts_by_regex(regex_pattern)
        if not matched:
            typer.echo("Neniuj kontaktoj kongruas kun la regex.")
            raise typer.Exit(1)
        typer.echo(f"Regex kongruoj por '{regex_pattern}':")
        for c in matched:
            typer.echo(
                f"- #{str(c.get('uuid') or '')[:8]}  "
                f"{_contact_full_name(c) or '—'}  <{c.get('retposto') or ''}>"
            )
        if not retposto_mod._confirm_esperante(
            f"{action_label} {len(matched)} regex-kongruajn kontaktojn?",
            default_yes=False,
        ):
            typer.echo("Nuligita.")
            raise typer.Exit(0)
        return matched, True
    if not identigiloj:
        typer.echo("[!] Donu UUID(j)n aŭ uzu --regex.", err=True)
        raise typer.Exit(1)
    targets: list[dict] = []
    seen: set[str] = set()
    for ident in identigiloj:
        row = _find_by_uuid(ident)
        if row is None:
            typer.echo(f"[!] Kontakto ne trovita: {ident}", err=True)
            raise typer.Exit(1)
        uid = str(row.get("uuid") or "")
        if uid and uid not in seen:
            seen.add(uid)
            targets.append(row)
    return targets, False


def _fuzzy_match_score(contact: dict, query: str) -> float:
    q = query.lower().strip()
    tokens = [
        str(contact.get("nomo") or "").lower(),
        str(contact.get("familia_nomo") or "").lower(),
        str(contact.get("retposto") or "").lower(),
        str(contact.get("organizo") or "").lower(),
        str(contact.get("naskig_loko") or "").lower(),
    ]
    email = str(contact.get("retposto") or "").lower()
    if "@" in email:
        tokens.append(email.split("@", 1)[0])
    return max(
        (SequenceMatcher(None, q, token).ratio() for token in tokens if token),
        default=0.0,
    )


def _fuzzy_contains(query: str, candidate: str, threshold: float = 0.7) -> bool:
    q = (query or "").strip().lower()
    c = (candidate or "").strip().lower()
    if not q:
        return True
    if not c:
        return False
    if q in c:
        return True
    if "@" in c:
        local = c.split("@", 1)[0]
        if q in local:
            return True
        c = local
    if len(c) >= len(q):
        win = len(q)
        best = max(
            (
                SequenceMatcher(None, q, c[i : i + win]).ratio()
                for i in range(len(c) - win + 1)
            ),
            default=0.0,
        )
    else:
        best = SequenceMatcher(None, q, c).ratio()
    return best >= threshold


@app.command("listigi")
def listigi() -> None:
    contacts = _load_contacts()
    if not contacts:
        typer.echo("Neniuj kontaktoj trovitaj.")
        return
    table = Table(title="Kontaktoj")
    table.add_column("UUID", style="dim")
    table.add_column("Nomo")
    table.add_column("Retpoŝto")
    table.add_column("Konfirmita")
    table.add_column("Kategorioj")
    for c in contacts:
        table.add_row(
            f"#{str(c.get('uuid') or '')[:8]}",
            c.get("nomo") or "",
            _contact_primary_email(c),
            "1" if int(c.get("konfirmita") or 0) else "0",
            ", ".join(c.get("kategorioj") or []),
        )
    _print_wide_table(table)


@app.command("vidi")
def vidi(
    identigilo: str | None = typer.Argument(None, help="UUID aŭ prefikso."),
) -> None:
    if not identigilo:
        typer.echo(
            "Mankas identigilo. Se vi uzas UUID kun #, citu ĝin:\n"
            '  kontakto vidi "#3217c312"',
            err=True,
        )
        raise typer.Exit(2)
    row = _find_by_uuid(identigilo)
    if row is None:
        typer.echo(f"[!] Kontakto ne trovita: {identigilo}", err=True)
        raise typer.Exit(1)
    table = Table(title=f"Kontakto #{str(row.get('uuid') or '')[:8]}")
    table.add_column("Kampo", style="cyan")
    table.add_column("Valoro")
    fields = [
        ("organizo", row.get("organizo"), True, False),
        ("nomo", row.get("nomo"), True, False),
        ("familia-nomo", row.get("familia_nomo"), True, True),
        ("retpoŝto", _contact_primary_email(row), False, False),
        ("telefonnumero", row.get("telefono"), False, False),
        ("naskiĝdato", row.get("naskig_dato"), False, False),
        ("naskiĝloko", row.get("naskig_loko"), False, False),
        ("organiza-identiga-numero", row.get("organiza_identiga_numero"), False, False),
        ("konfirmita", row.get("konfirmita"), False, False),
        ("uuid", f"#{str(row.get('uuid') or '')}", False, False),
    ]
    for label, val, bold, upper in fields:
        if val in (None, "", [], {}):
            continue
        text = str(val).upper() if upper else str(val)
        if bold:
            text = f"[bold]{text}[/bold]"
        table.add_row(label, text)
    if row.get("lingvoj"):
        table.add_row("lingvoj", ", ".join(str(v) for v in row["lingvoj"]))
    if row.get("kategorioj"):
        table.add_row("kategorioj", ", ".join(str(v) for v in row["kategorioj"]))
    if row.get("telefonnumeroj"):
        phones = ", ".join(
            str(item.get("valoro") or "")
            for item in row.get("telefonnumeroj") or []
            if isinstance(item, dict)
        )
        if phones:
            table.add_row("telefonnumeroj", phones)
    if row.get("retposhtadresoj"):
        mails = ", ".join(
            str(item.get("valoro") or "")
            for item in row.get("retposhtadresoj") or []
            if isinstance(item, dict)
        )
        if mails:
            table.add_row("retposhtadresoj", mails)
    kampoj = row.get("kampoj") or {}
    for k, v in kampoj.items():
        table.add_row(f"kampo:{k}", str(v))
    _print_wide_table(table)


@app.command("serci")
def serci(
    demando: str | None = typer.Argument(None, help="Ĝenerala serĉ-demando."),
    fuzzy: bool = typer.Option(False, "-f", "--fuzzy", help="Uzi fuzzy-serĉon."),
    regex: bool = typer.Option(
        False, "-R", "--regex", help="Trakti demandon kiel regex."
    ),
    nomo: str | None = typer.Option(None, "-n", "--nomo", help="Filtri laŭ nomo."),
    familia_nomo: str | None = typer.Option(
        None, "-F", "--familia-nomo", help="Filtri laŭ familia nomo."
    ),
    naskig_dato: str | None = typer.Option(
        None, "-d", "--naskig-dato", help="Filtri laŭ naskiĝdato (YYYYMMDD)."
    ),
    naskig_loko: str | None = typer.Option(
        None, "--naskig-loko", help="Filtri laŭ naskiĝloko."
    ),
    lingvo: list[str] | None = typer.Option(
        None, "-l", "--lingvo", help="Filtri laŭ lingvo-kodo (ripetebla)."
    ),
    retpostadreso: str | None = typer.Option(
        None, "--retpostadreso", help="Filtri laŭ ĉefa aŭ aldonita retpoŝto."
    ),
    organizo: str | None = typer.Option(
        None, "-o", "--organizo", help="Filtri laŭ organizo."
    ),
    organiza_identiga_numero: str | None = typer.Option(
        None, "--organiza-identiga-numero", help="Filtri laŭ organiza identigilo."
    ),
    telefonnumero: str | None = typer.Option(
        None, "--telefonnumero", help="Filtri laŭ telefono."
    ),
    postadreso: str | None = typer.Option(
        None, "-p", "--postadreso", help="Filtri laŭ poŝtadreso."
    ),
    kategorio: list[str] | None = typer.Option(
        None, "-k", "--kategorio", help="Filtri laŭ kategorio (ripetebla)."
    ),
    kampo: list[str] | None = typer.Option(
        None, "-c", "--kampo", help="Filtri laŭ propra kampo KEY:VALUE (ripetebla)."
    ),
    konfirmita: int | None = typer.Option(
        None, "-K", "--konfirmita", help="Filtri laŭ konfirmita stato (0/1)."
    ),
) -> None:
    if konfirmita is not None and konfirmita not in (0, 1):
        typer.echo("[!] --konfirmita devas esti 0 aŭ 1.", err=True)
        raise typer.Exit(1)
    if demando is None and not any(
        [
            nomo,
            familia_nomo,
            naskig_dato,
            naskig_loko,
            lingvo,
            retpostadreso,
            organizo,
            organiza_identiga_numero,
            telefonnumero,
            postadreso,
            kategorio,
            kampo,
            konfirmita is not None,
        ]
    ):
        typer.echo("[!] Donu demando-n aŭ almenaŭ unu filtrilon.", err=True)
        raise typer.Exit(1)

    kampo_filters: dict[str, str] = {}
    if kampo:
        try:
            kampo_filters = _norm_kampoj(kampo)
        except ValueError as exc:
            typer.echo(f"[!] {exc}", err=True)
            raise typer.Exit(1) from exc

    def _matches_filters(contact: dict) -> bool:
        if nomo and not _fuzzy_contains(
            nomo, str(contact.get("nomo") or ""), threshold=0.7 if fuzzy else 1.0
        ):
            return False
        if familia_nomo and not _fuzzy_contains(
            familia_nomo,
            str(contact.get("familia_nomo") or ""),
            threshold=0.7 if fuzzy else 1.0,
        ):
            return False
        if naskig_dato and naskig_dato != str(contact.get("naskig_dato") or ""):
            return False
        if naskig_loko and not _fuzzy_contains(
            naskig_loko,
            str(contact.get("naskig_loko") or ""),
            threshold=0.7 if fuzzy else 1.0,
        ):
            return False
        if retpostadreso:
            mail_values = _contact_email_values(contact)
            if not any(
                _fuzzy_contains(
                    retpostadreso,
                    mail,
                    threshold=0.7 if fuzzy else 1.0,
                )
                for mail in mail_values
            ):
                return False
        if organizo and not _fuzzy_contains(
            organizo,
            str(contact.get("organizo") or ""),
            threshold=0.7 if fuzzy else 1.0,
        ):
            return False
        if organiza_identiga_numero and not _fuzzy_contains(
            organiza_identiga_numero,
            str(contact.get("organiza_identiga_numero") or ""),
            threshold=0.7 if fuzzy else 1.0,
        ):
            return False
        if telefonnumero:
            phone_q = telefonnumero
            phone_values = [str(contact.get("telefono") or "").lower()]
            phone_values.extend(
                str(item.get("valoro") or "").lower()
                for item in (contact.get("telefonnumeroj") or [])
                if isinstance(item, dict)
            )
            if not any(
                _fuzzy_contains(phone_q, p, threshold=0.7 if fuzzy else 1.0)
                for p in phone_values
            ):
                return False
        if postadreso and not _fuzzy_contains(
            postadreso,
            str((contact.get("kampoj") or {}).get("postadreso") or ""),
            threshold=0.7 if fuzzy else 1.0,
        ):
            return False
        if lingvo:
            contact_langs = [str(v).lower() for v in (contact.get("lingvoj") or [])]
            if any(lang.lower() not in contact_langs for lang in lingvo):
                return False
        if kategorio:
            contact_cats = [str(v).lower() for v in (contact.get("kategorioj") or [])]
            if any(k.lower() not in contact_cats for k in kategorio):
                return False
        if kampo_filters:
            custom = contact.get("kampoj") or {}
            for k, v in kampo_filters.items():
                if not _fuzzy_contains(
                    v,
                    str(custom.get(k, "")),
                    threshold=0.7 if fuzzy else 1.0,
                ):
                    return False
        if konfirmita is not None and int(contact.get("konfirmita") or 0) != konfirmita:
            return False
        return True

    contacts = _load_contacts()
    if demando is None:
        results = contacts
    elif regex:
        results = _match_contacts_by_regex(demando)
    elif fuzzy:
        ranked = sorted(
            (
                (score, c)
                for c in contacts
                for score in [_fuzzy_match_score(c, demando)]
                if score >= 0.55
            ),
            key=lambda item: item[0],
            reverse=True,
        )
        results = [c for _, c in ranked]
    else:
        results = [c for c in contacts if _search_contact_match(c, demando)]
    results = [c for c in results if _matches_filters(c)]
    if not results:
        typer.echo("Neniuj kontaktoj trovitaj.")
        return
    table = Table(title=f"Serĉrezultoj: {len(results)}")
    extra_cols: list[tuple[str, str]] = []
    if naskig_dato:
        extra_cols.append(("naskig_dato", "Naskiĝdato"))
    if naskig_loko:
        extra_cols.append(("naskig_loko", "Naskiĝloko"))
    if lingvo:
        extra_cols.append(("lingvoj", "Lingvoj"))
    if organiza_identiga_numero:
        extra_cols.append(("organiza_identiga_numero", "Organiza-ID"))
    if kategorio:
        extra_cols.append(("kategorioj", "Kategorioj"))
    if kampo:
        extra_cols.append(("kampoj", "Kampoj"))
    if postadreso:
        extra_cols.append(("kampoj", "Poŝtadreso"))
    if konfirmita is not None:
        extra_cols.append(("konfirmita", "Konfirmita"))
    for _key, label in extra_cols:
        table.add_column(label, overflow="fold")
    table.add_column("Organizo", overflow="fold")
    table.add_column("Nomo", overflow="fold")
    table.add_column("Familia-nomo", overflow="fold")
    table.add_column("Retpoŝto", overflow="fold")
    table.add_column("Telefonnumero", overflow="fold")
    table.add_column("UUID", style="dim", overflow="fold")
    for c in results:
        row_values: list[str] = []
        for key, _label in extra_cols:
            if key == "kampoj" and postadreso:
                val = (c.get("kampoj") or {}).get("postadreso")
            else:
                val = c.get(key)
            if isinstance(val, list):
                row_values.append(", ".join(str(v) for v in val))
            elif isinstance(val, dict):
                row_values.append(
                    ", ".join(f"{k}:{v}" for k, v in val.items())
                )
            else:
                row_values.append(str(val or ""))
        row_values.extend(
            [
                str(c.get("organizo") or ""),
                str(c.get("nomo") or ""),
                str(c.get("familia_nomo") or ""),
                _contact_primary_email(c),
                str(c.get("telefono") or ""),
                f"#{str(c.get('uuid') or '')[:8]}",
            ]
        )
        table.add_row(*row_values)
    _print_wide_table(table)


@app.command("aldoni")
def aldoni(
    retpostadreso: str | None = typer.Argument(None, help="Retpoŝta adreso."),
    nomo: str | None = typer.Option(None, "-n", "--nomo", help="Nomo."),
    familia_nomo: str | None = typer.Option(
        None, "-F", "--familia-nomo", help="Familia nomo."
    ),
    naskig_dato: str | None = typer.Option(
        None, "-d", "--naskig-dato", help="Naskiĝdato (YYYYMMDD)."
    ),
    naskig_loko: str | None = typer.Option(
        None, "--naskig-loko", help="Naskiĝloko."
    ),
    lingvoj: str | None = typer.Option(
        None, "-l", "--lingvoj", help="Lingvoj (ekz. en,fr)."
    ),
    organizo: str | None = typer.Option(None, "-o", "--organizo", help="Organizo."),
    organiza_identiga_numero: str | None = typer.Option(
        None, "--organiza-identiga-numero", help="Organiza identiga numero."
    ),
    telefonnumeroj: list[str] | None = typer.Option(
        None,
        "-t",
        "--telefonnumero",
        help="Ripetu numero:etikedo[:prima], ekz. 0033...:hejmo:prima",
    ),
    retposhtadreso: list[str] | None = typer.Option(
        None,
        "-r",
        "--retposhtadreso",
        help="Ripetu adreso:etikedo[:prima], ekz. uzanto@x.com:labora:prima",
    ),
    postadreso: str | None = typer.Option(
        None, "-p", "--postadreso", help="Poŝtadreso."
    ),
    kampo: list[str] | None = typer.Option(
        None, "-c", "--kampo", help="Propra kampo KEY:VALUE (ripetebla)."
    ),
    noto: str | None = typer.Option(None, "-N", "--noto", help="Noto."),
    kategorio: list[str] | None = typer.Option(
        None, "-k", "--kategorio", help="Kategorio (ripetebla)."
    ),
    konfirmita: int = typer.Option(
        1, "-K", "--konfirmita", help="Ĉu konfirmita (0/1)."
    ),
) -> None:
    if not any([nomo, familia_nomo, organizo]):
        typer.echo(
            "[!] Donu almenaŭ unu el: --nomo, --familia-nomo, --organizo.",
            err=True,
        )
        raise typer.Exit(1)
    if konfirmita not in (0, 1):
        typer.echo("[!] --konfirmita devas esti 0 aŭ 1.", err=True)
        raise typer.Exit(1)
    if naskig_dato is not None and not re.match(r"^\d{8}$", naskig_dato):
        typer.echo("[!] --naskig-dato devas esti YYYYMMDD.", err=True)
        raise typer.Exit(1)
    lingvo_list = [c.strip() for c in (lingvoj or "").split(",") if c.strip()]
    try:
        telefono_list = _normalize_multi_contact_list(
            telefonnumeroj or [], kind="telefono"
        )
        retposhto_list = _normalize_multi_contact_list(
            retposhtadreso or [], kind="retposhto"
        )
        kampoj_dict = _norm_kampoj(kampo)
    except ValueError as exc:
        typer.echo(f"[!] {exc}", err=True)
        raise typer.Exit(1) from exc
    if postadreso is not None:
        kampoj_dict["postadreso"] = postadreso
    telefono_primara = (
        str((telefono_list[0] or {}).get("valoro") or "") if telefono_list else None
    )
    cats = _norm_kategorioj(kategorio)
    _ensure_categories_exist(cats)
    all_contacts = _load_contacts()
    potential_dupes = [
        c
        for c in all_contacts
        if _matches_potential_duplicate(c, nomo, familia_nomo, organizo)
    ]
    if potential_dupes:
        sorted_dupes = sorted(
            potential_dupes, key=lambda c: str(c.get("modifita_je") or ""), reverse=True
        )
        chosen = sorted_dupes[0]
        typer.echo("Eblaj duoblaĵoj trovitaj:")
        for c in sorted_dupes[:5]:
            typer.echo(
                f"- #{str(c.get('uuid') or '')[:8]} "
                f"{c.get('organizo') or '—'} / "
                f"{c.get('nomo') or '—'} {c.get('familia_nomo') or ''}".strip()
            )
        if retposto_mod._confirm_esperante(
            "Ĉu ĝisdatigi ekzistantan eniron anstataŭ krei novan?",
            default_yes=False,
        ):
            target = chosen
            update_fields: dict[str, object] = {"modifita_je": retposto_mod._now_iso()}
            if nomo is not None:
                update_fields["nomo"] = nomo
            if familia_nomo is not None:
                update_fields["familia_nomo"] = familia_nomo
            if naskig_dato is not None:
                update_fields["naskig_dato"] = naskig_dato
            if naskig_loko is not None:
                update_fields["naskig_loko"] = naskig_loko
            update_fields["lingvoj"] = json.dumps(lingvo_list, ensure_ascii=False)
            if retpostadreso is not None:
                update_fields["retposto"] = retpostadreso.lower().strip()
            if organizo is not None:
                update_fields["organizo"] = organizo
            if organiza_identiga_numero is not None:
                update_fields["organiza_identiga_numero"] = organiza_identiga_numero
            update_fields["telefono"] = telefono_primara
            update_fields["telefonnumeroj"] = json.dumps(
                telefono_list, ensure_ascii=False
            )
            update_fields["retposhtadresoj"] = json.dumps(
                retposhto_list, ensure_ascii=False
            )
            update_fields["kampoj"] = json.dumps(kampoj_dict, ensure_ascii=False)
            if noto is not None:
                update_fields["noto"] = noto
            update_fields["konfirmita"] = int(bool(konfirmita))
            update_fields["kategorioj"] = json.dumps(cats, ensure_ascii=False)
            _save_undo({"op": "modifi", "old": [dict(target)]})
            _update_contact_by_uuid(str(target.get("uuid") or ""), update_fields)
            typer.echo(
                f"[✓] Ĝisdatigis ekzistantan kontakton "
                f"#{str(target.get('uuid') or '')[:8]}."
            )
            return

    before = None
    if retpostadreso:
        normalized_addr = retpostadreso.lower().strip()
        before = next(
            (c for c in _load_contacts() if c.get("retposto") == normalized_addr),
            None,
        )
        retposto_mod._upsert_contact(
            normalized_addr,
            nomo=nomo,
            familia_nomo=familia_nomo,
            naskig_dato=naskig_dato,
            naskig_loko=naskig_loko,
            lingvoj=lingvo_list,
            organizo=organizo,
            organiza_identiga_numero=organiza_identiga_numero,
            telefono=telefono_primara,
            telefonnumeroj=telefono_list,
            retposhtadresoj=retposhto_list,
            kampoj=kampoj_dict,
            noto=noto,
            konfirmita=konfirmita,
            kategorioj=cats,
        )
        after = next(
            (c for c in _load_contacts() if c.get("retposto") == normalized_addr),
            None,
        )
    else:
        after = _insert_contact_without_email(
            nomo=nomo,
            familia_nomo=familia_nomo,
            naskig_dato=naskig_dato,
            naskig_loko=naskig_loko,
            lingvoj=lingvo_list,
            organizo=organizo,
            organiza_identiga_numero=organiza_identiga_numero,
            telefono=telefono_primara,
            telefonnumeroj=telefono_list,
            retposhtadresoj=retposhto_list,
            kategorioj=cats,
            kampoj=kampoj_dict,
            noto=noto,
            konfirmita=konfirmita,
        )
    if after is None:
        typer.echo("[!] Ne povis savi kontakton.", err=True)
        raise typer.Exit(1)
    if before is None:
        _save_undo({"op": "aldoni", "uuid": after["uuid"]})
    else:
        _save_undo({"op": "modifi", "old": [before]})
    typer.echo(f"[✓] Saviĝis kontakto #{after['uuid'][:8]}.")


@app.command("modifi")
def modifi(
    identigiloj: list[str] = typer.Argument(
        [], help="UUID(j) aŭ prefikso(j). (Nedeviga kun --regex)"
    ),
    nomo: str | None = typer.Option(None, "-n", "--nomo"),
    familia_nomo: str | None = typer.Option(None, "-F", "--familia-nomo"),
    naskig_dato: str | None = typer.Option(None, "-d", "--naskig-dato"),
    naskig_loko: str | None = typer.Option(None, "--naskig-loko"),
    lingvoj: str | None = typer.Option(None, "-l", "--lingvoj"),
    organizo: str | None = typer.Option(None, "-o", "--organizo"),
    organiza_identiga_numero: str | None = typer.Option(
        None, "--organiza-identiga-numero"
    ),
    telefonnumeroj: list[str] | None = typer.Option(
        None, "-t", "--telefonnumero"
    ),
    retposhtadreso: list[str] | None = typer.Option(
        None, "-r", "--retposhtadreso"
    ),
    postadreso: str | None = typer.Option(None, "-p", "--postadreso"),
    kampo: list[str] | None = typer.Option(None, "-c", "--kampo"),
    noto: str | None = typer.Option(None, "-N", "--noto"),
    kategorio: list[str] | None = typer.Option(None, "-k", "--kategorio"),
    anstatauxigi_kategoriojn: bool = typer.Option(
        False, "--anstatauxigi-kategoriojn", help="Anstataŭigi anstataŭ aldoni."
    ),
    konfirmita: int | None = typer.Option(None, "-K", "--konfirmita"),
    regex: str | None = typer.Option(
        None, "-R", "--regex", help="Regex por elekti plurajn kontaktojn."
    ),
) -> None:
    if konfirmita is not None and konfirmita not in (0, 1):
        typer.echo("[!] --konfirmita devas esti 0 aŭ 1.", err=True)
        raise typer.Exit(1)
    if naskig_dato is not None and not re.match(r"^\d{8}$", naskig_dato):
        typer.echo("[!] --naskig-dato devas esti YYYYMMDD.", err=True)
        raise typer.Exit(1)
    lingvo_list = (
        [c.strip() for c in lingvoj.split(",") if c.strip()]
        if lingvoj is not None
        else None
    )
    try:
        telefono_list = (
            _normalize_multi_contact_list(telefonnumeroj or [], kind="telefono")
            if telefonnumeroj is not None
            else None
        )
        retposhto_list = (
            _normalize_multi_contact_list(retposhtadreso or [], kind="retposhto")
            if retposhtadreso is not None
            else None
        )
        kampoj_dict = _norm_kampoj(kampo) if kampo is not None else None
    except ValueError as exc:
        typer.echo(f"[!] {exc}", err=True)
        raise typer.Exit(1) from exc
    targets, used_regex = _resolve_targets(identigiloj, regex, "Modifi")
    if konfirmita is not None and len(targets) > 1:
        if not used_regex and not retposto_mod._confirm_esperante(
            f"Modifi konfirmita={konfirmita} por {len(targets)} kontaktoj?",
            default_yes=False,
        ):
            typer.echo("Nuligita.")
            return
    cats = _norm_kategorioj(kategorio)
    if cats:
        _ensure_categories_exist(cats)
    old_rows = [dict(t) for t in targets]
    for target in targets:
        merged_cats = _norm_kategorioj(target.get("kategorioj") or [])
        if cats:
            if anstatauxigi_kategoriojn:
                merged_cats = cats
            else:
                merged_cats = _norm_kategorioj([*merged_cats, *cats])
        update_fields = {"modifita_je": retposto_mod._now_iso()}
        update_fields["nomo"] = nomo if nomo is not None else target.get("nomo")
        update_fields["familia_nomo"] = (
            familia_nomo if familia_nomo is not None else target.get("familia_nomo")
        )
        update_fields["naskig_dato"] = (
            naskig_dato if naskig_dato is not None else target.get("naskig_dato")
        )
        update_fields["naskig_loko"] = (
            naskig_loko if naskig_loko is not None else target.get("naskig_loko")
        )
        update_fields["lingvoj"] = json.dumps(
            lingvo_list if lingvo_list is not None else target.get("lingvoj") or [],
            ensure_ascii=False,
        )
        update_fields["organizo"] = (
            organizo if organizo is not None else target.get("organizo")
        )
        update_fields["organiza_identiga_numero"] = (
            organiza_identiga_numero
            if organiza_identiga_numero is not None
            else target.get("organiza_identiga_numero")
        )
        telefono_primara = (
            str((telefono_list[0] or {}).get("valoro") or "")
            if telefono_list is not None and telefono_list
            else None
        )
        update_fields["telefono"] = (
            telefono_primara if telefono_list is not None else target.get("telefono")
        )
        update_fields["telefonnumeroj"] = json.dumps(
            (
                telefono_list
                if telefono_list is not None
                else target.get("telefonnumeroj") or []
            ),
            ensure_ascii=False,
        )
        update_fields["retposhtadresoj"] = json.dumps(
            retposhto_list
            if retposhto_list is not None
            else target.get("retposhtadresoj") or [],
            ensure_ascii=False,
        )
        merged_kampoj = dict(target.get("kampoj") or {})
        if kampoj_dict is not None:
            merged_kampoj = dict(kampoj_dict)
        if postadreso is not None:
            merged_kampoj["postadreso"] = postadreso
        update_fields["kampoj"] = json.dumps(merged_kampoj, ensure_ascii=False)
        update_fields["noto"] = noto if noto is not None else target.get("noto")
        update_fields["konfirmita"] = int(
            bool(konfirmita if konfirmita is not None else target.get("konfirmita"))
        )
        update_fields["kategorioj"] = json.dumps(merged_cats, ensure_ascii=False)
        _update_contact_by_uuid(str(target.get("uuid") or ""), update_fields)
    _save_undo({"op": "modifi", "old": old_rows})
    typer.echo(f"[✓] Modifitaj {len(targets)} kontakto(j).")


@app.command("forigi")
def forigi(
    identigiloj: list[str] = typer.Argument(
        [], help="UUID(j) aŭ prefikso(j). (Nedeviga kun --regex)"
    ),
    regex: str | None = typer.Option(
        None, "-R", "--regex", help="Regex por elekti plurajn kontaktojn."
    ),
) -> None:
    targets, used_regex = _resolve_targets(identigiloj, regex, "Forigi")
    if not used_regex and not retposto_mod._confirm_esperante(
        f"Forigi {len(targets)} kontakto(j)n?", default_yes=False
    ):
        typer.echo("Nuligita.")
        return
    with retposto_mod._get_db() as con:
        for row in targets:
            con.execute("DELETE FROM kontakto WHERE uuid = ?", (row["uuid"],))
    _save_undo({"op": "forigi", "rows": targets})
    typer.echo(f"[✓] Forigis {len(targets)} kontakto(j)n.")


@app.command("purigi")
def purigi() -> None:
    contacts = _load_contacts()
    if not contacts:
        typer.echo("Neniuj kontaktoj por purigi.")
        return
    actions: list[tuple[str, dict]] = []
    marked_uuid: set[str] = set()

    by_mail: dict[str, list[dict]] = {}
    for c in contacts:
        addr = str(c.get("retposto") or "").lower().strip()
        if not addr:
            continue
        by_mail.setdefault(addr, []).append(c)
    for addr, rows in by_mail.items():
        if len(rows) <= 1:
            continue
        rows_sorted = sorted(
            rows,
            key=lambda r: (
                str(r.get("kreita_je") or ""),
                str(r.get("uuid") or ""),
            ),
        )
        for dup in rows_sorted[1:]:
            uid = str(dup.get("uuid") or "")
            if uid and uid not in marked_uuid:
                marked_uuid.add(uid)
                actions.append(
                    (
                        "forigi",
                        {
                            "uuid": uid,
                            "retposto": addr,
                            "kialo": "duobligo laŭ retpoŝto",
                        },
                    )
                )

    for c in contacts:
        uid = str(c.get("uuid") or "")
        addr = str(c.get("retposto") or "")
        if not uid or uid in marked_uuid or not addr:
            continue
        if not retposto_mod._should_autosave_contact_email(addr):
            marked_uuid.add(uid)
            actions.append(
                (
                    "forigi",
                    {
                        "uuid": uid,
                        "retposto": addr,
                        "kialo": "probable aŭtomata adreso",
                    },
                )
            )

    if not actions:
        typer.echo("Neniuj purigaj agoj proponitaj.")
        return

    typer.echo("Proponitaj purigaj agoj:")
    for idx, (_kind, payload) in enumerate(actions, start=1):
        typer.echo(
            f"{idx}. Forigi #{str(payload.get('uuid') or '')[:8]} "
            f"<{payload.get('retposto') or ''}> ({payload.get('kialo')})"
        )

    choice = typer.prompt(
        "Elektu agojn (j/N, '! 2 5' = ĉiuj krom, '2 3' = nur tiuj)",
        default="N",
    ).strip()
    if not choice or choice.lower() in {"n", "ne"}:
        typer.echo("Nuligita.")
        return

    selected: list[tuple[str, dict]]
    if choice.lower() == "j":
        selected = actions
    else:
        if choice.startswith("!"):
            nums = choice[1:].strip().split()
            exclude: set[int] = set()
            for token in nums:
                if not token.isdigit():
                    typer.echo(f"[!] Nevalida numero: {token}", err=True)
                    raise typer.Exit(1)
                val = int(token)
                if val < 1 or val > len(actions):
                    typer.echo(f"[!] Numero ekster gamo: {val}", err=True)
                    raise typer.Exit(1)
                exclude.add(val)
            selected = [
                act for i, act in enumerate(actions, start=1) if i not in exclude
            ]
        else:
            nums = choice.split()
            include: list[int] = []
            for token in nums:
                if not token.isdigit():
                    typer.echo(f"[!] Nevalida numero: {token}", err=True)
                    raise typer.Exit(1)
                val = int(token)
                if val < 1 or val > len(actions):
                    typer.echo(f"[!] Numero ekster gamo: {val}", err=True)
                    raise typer.Exit(1)
                include.append(val)
            selected = [actions[i - 1] for i in include]

    if not selected:
        typer.echo("Neniuj agoj elektitaj.")
        return

    delete_uids = [str(payload.get("uuid") or "") for _kind, payload in selected]
    targets = [c for c in contacts if str(c.get("uuid") or "") in set(delete_uids)]
    if not targets:
        typer.echo("Neniuj validaj kontaktoj por forigi.")
        return
    with retposto_mod._get_db() as con:
        for uid in delete_uids:
            con.execute("DELETE FROM kontakto WHERE uuid = ?", (uid,))
    _save_undo({"op": "forigi", "rows": targets})
    typer.echo(f"[✓] Purigado finita: forigis {len(targets)} kontakto(j)n.")


@app.command("malfari")
def malfari() -> None:
    op = _pop_undo()
    if op is None:
        typer.echo("Nenio por malfari.")
        return
    typ = op.get("op")
    with retposto_mod._get_db() as con:
        if typ == "aldoni":
            uid = op.get("uuid")
            con.execute("DELETE FROM kontakto WHERE uuid = ?", (uid,))
            typer.echo(f"Malfaris aldoni: #{str(uid)[:8]}.")
            return
        if typ == "forigi":
            for row in op.get("rows") or []:
                con.execute(
                    """INSERT OR REPLACE INTO kontakto
                       (id, uuid, nomo, familia_nomo, naskig_dato, naskig_loko,
                        lingvoj, retposto, organizo, organiza_identiga_numero,
                        telefono, telefonnumeroj, retposhtadresoj, kampoj,
                        konfirmita, kategorioj, noto, kreita_je, modifita_je)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    _contact_to_row_args(row),
                )
            typer.echo("Malfaris forigon de kontakto(j).")
            return
        if typ == "modifi":
            for row in op.get("old") or []:
                con.execute(
                    """UPDATE kontakto
                       SET nomo=?, familia_nomo=?, naskig_dato=?, naskig_loko=?,
                           lingvoj=?, organizo=?, organiza_identiga_numero=?,
                           telefono=?, telefonnumeroj=?, retposhtadresoj=?,
                           kampoj=?, konfirmita=?, kategorioj=?, noto=?,
                           modifita_je=?
                       WHERE uuid=?""",
                    (
                        row.get("nomo"),
                        row.get("familia_nomo"),
                        row.get("naskig_dato"),
                        row.get("naskig_loko"),
                        json.dumps(row.get("lingvoj") or [], ensure_ascii=False),
                        row.get("organizo"),
                        row.get("organiza_identiga_numero"),
                        row.get("telefono"),
                        json.dumps(row.get("telefonnumeroj") or [], ensure_ascii=False),
                        json.dumps(
                            row.get("retposhtadresoj") or [], ensure_ascii=False
                        ),
                        json.dumps(row.get("kampoj") or {}, ensure_ascii=False),
                        int(row.get("konfirmita") or 0),
                        json.dumps(row.get("kategorioj") or [], ensure_ascii=False),
                        row.get("noto"),
                        row.get("modifita_je"),
                        row.get("uuid"),
                    ),
                )
            typer.echo("Malfaris modifon de kontakto(j).")
            return
    typer.echo("Nekonata malfaro-operacio.", err=True)
    raise typer.Exit(1)


@kategorio_app.command("listigi")
def kategorio_listigi() -> None:
    with retposto_mod._get_db() as con:
        rows = con.execute(
            "SELECT nomo FROM kontakto_kategorio ORDER BY nomo ASC"
        ).fetchall()
    if not rows:
        typer.echo("Neniuj kategorioj.")
        return
    for row in rows:
        typer.echo(row["nomo"])


@kategorio_app.command("aldoni")
def kategorio_aldoni(
    nomo: str = typer.Argument(..., help="Nomo de kategorio."),
) -> None:
    now = retposto_mod._now_iso()
    with retposto_mod._get_db() as con:
        con.execute(
            "INSERT OR IGNORE INTO kontakto_kategorio (nomo, kreita_je) VALUES (?,?)",
            (nomo.strip(), now),
        )
    typer.echo(f"[✓] Aldonita kategorio: {nomo.strip()}")


@kategorio_app.command("forigi")
def kategorio_forigi(
    nomo: str = typer.Argument(..., help="Nomo de kategorio."),
) -> None:
    category = nomo.strip()
    with retposto_mod._get_db() as con:
        con.execute("DELETE FROM kontakto_kategorio WHERE nomo = ?", (category,))
        rows = con.execute("SELECT uuid, kategorioj FROM kontakto").fetchall()
        for row in rows:
            try:
                cats = json.loads(row["kategorioj"] or "[]")
            except json.JSONDecodeError:
                cats = []
            new_cats = [c for c in cats if c != category]
            if new_cats != cats:
                con.execute(
                    "UPDATE kontakto SET kategorioj = ?, modifita_je = ? "
                    "WHERE uuid = ?",
                    (
                        json.dumps(new_cats, ensure_ascii=False),
                        retposto_mod._now_iso(),
                        row["uuid"],
                    ),
                )
    typer.echo(f"[✓] Forigita kategorio: {category}")
