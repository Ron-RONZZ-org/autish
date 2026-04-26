"""taglibro — diary-style entries with markdown and labels."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone

import typer
from rich.console import Console
from rich.table import Table

from autish.commands import _tasklib
from autish.i18n import tr

app = typer.Typer(
    name="taglibro",
    help=tr(
        "Taglibro — administri taglibrajn enirojn kun etikedoj.",
        "Taglibro — manage diary entries with labels.",
        "Taglibro — gérer des entrées de journal avec étiquettes.",
    ),
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help", "--helpo"]},
)

console = Console()


def _render_text(text: str, *, show_ref: bool = False) -> str:
    normalized = _tasklib.normalize_markdown_links(text)
    return _tasklib.render_markdown_links_plain(normalized, show_ref=show_ref)


def _parse_label_blob(raw: str | None) -> list[tuple[str, str]]:
    if not raw:
        return []
    pairs: list[tuple[str, str]] = []
    for chunk in str(raw).split("|"):
        if not chunk.strip():
            continue
        uid, _, text = chunk.partition(":")
        if uid.strip():
            pairs.append((uid.strip(), text.strip()))
    return pairs


def _load_entries() -> list[dict]:
    with _tasklib.connect() as con:
        rows = con.execute(
            """
            SELECT
                t.*,
                GROUP_CONCAT(e.uuid || ':' || e.teksto, '|') AS etikedoj_blob
            FROM taglibro t
            LEFT JOIN taglibro_etikedo te ON te.taglibro_uuid = t.uuid
            LEFT JOIN etikedo e ON e.uuid = te.etikedo_uuid
            GROUP BY t.uuid
            ORDER BY t.tempo DESC, t.kreita_je DESC
            """
        ).fetchall()
    data: list[dict] = []
    for row in rows:
        item = dict(row)
        item["etikedoj"] = _parse_label_blob(item.get("etikedoj_blob"))
        data.append(item)
    return data


def _set_labels(con, entry_uuid: str, etikedo_ids: list[str]) -> None:
    con.execute("DELETE FROM taglibro_etikedo WHERE taglibro_uuid = ?", (entry_uuid,))
    for etikedo_uuid in etikedo_ids:
        con.execute(
            "INSERT OR IGNORE INTO taglibro_etikedo (taglibro_uuid, etikedo_uuid) "
            "VALUES (?, ?)",
            (entry_uuid, etikedo_uuid),
        )


def _parse_partial_date(token: str, *, ref: date) -> date:
    raw = str(token).strip()
    if not raw.isdigit():
        raise ValueError("Dato devas esti numeroj.")
    if len(raw) == 8:
        return datetime.strptime(raw, "%Y%m%d").date()
    if len(raw) == 4:
        return datetime.strptime(f"{ref.year}{raw}", "%Y%m%d").date()
    if len(raw) == 2:
        return datetime.strptime(f"{ref.year}{ref.month:02d}{raw}", "%Y%m%d").date()
    raise ValueError("Nevalida dato-formo (uzu YYYYMMDD, MMDD aŭ DD).")


def _parse_tempo(raw: str | None) -> str:
    if raw is None or not str(raw).strip():
        return _tasklib.now_iso()
    token = str(raw).strip()
    now_local = datetime.now().astimezone()
    date_part: str
    time_part: str
    if "_" in token:
        date_part, time_part = token.split("_", 1)
        date_part = date_part.strip()
        time_part = time_part.strip()
    else:
        date_part = token
        time_part = f"{now_local.hour:02d}{now_local.minute:02d}"
    if not re.fullmatch(r"\d{4}", time_part):
        raise ValueError("Tempo devas esti HHMM (ekz: 0930).")
    d = _parse_partial_date(date_part, ref=now_local.date())
    hh = int(time_part[:2])
    mm = int(time_part[2:])
    if hh > 23 or mm > 59:
        raise ValueError("Nevalida horo/minuto.")
    dt_local = datetime(
        d.year,
        d.month,
        d.day,
        hh,
        mm,
        tzinfo=now_local.tzinfo or timezone.utc,
    )
    return (
        dt_local.astimezone(timezone.utc).replace(second=0, microsecond=0).isoformat()
    )


def _resolve_entry(
    reference: str, *, allow_fuzzy: bool, interactive: bool
) -> dict | None:
    return _tasklib.resolve_reference(
        _load_entries(),
        reference,
        text_getter=lambda item: str(item.get("titolo") or ""),
        kind_label="taglibro",
        allow_fuzzy=allow_fuzzy,
        interactive=interactive,
    )


def _render_label_pairs(pairs: list[tuple[str, str]]) -> str:
    if not pairs:
        return "-"
    return ", ".join(
        _tasklib.render_markdown_links_plain(text) for _, text in pairs if text
    )


def _show_detail(item: dict) -> None:
    typer.echo(f"uuid: #{str(item.get('uuid') or '')[:8]}")
    typer.echo(f"titolo: {_render_text(str(item.get('titolo') or ''), show_ref=True)}")
    typer.echo(
        f"priskribo: {_render_text(str(item.get('priskribo') or ''), show_ref=True)}"
    )
    typer.echo(f"tempo: {_tasklib.format_iso_short(str(item.get('tempo') or ''))}")
    typer.echo(f"etikedoj: {_render_label_pairs(item.get('etikedoj') or [])}")
    typer.echo(
        f"kreita_je: {_tasklib.format_iso_short(str(item.get('kreita_je') or ''))}"
    )
    typer.echo(
        f"modifita_je: {_tasklib.format_iso_short(str(item.get('modifita_je') or ''))}"
    )


def _print_results(items: list[dict], *, numerate: bool = False) -> None:
    table = Table(show_header=True, header_style="bold", box=None)
    if numerate:
        table.add_column("#", justify="right", style="dim", no_wrap=True)
    table.add_column("UUID", style="cyan", no_wrap=True)
    table.add_column("TEMPO", no_wrap=True)
    table.add_column("TITOLO")
    table.add_column("ETIKEDOJ")
    for idx, item in enumerate(items, start=1):
        row = [
            f"#{str(item.get('uuid') or '')[:8]}",
            _tasklib.format_iso_short(str(item.get("tempo") or "")),
            _render_text(str(item.get("titolo") or ""), show_ref=True),
            _render_label_pairs(item.get("etikedoj") or []),
        ]
        if numerate:
            row = [str(idx), *row]
        table.add_row(*row)
    console.print(table)


@app.command("aldoni")
def aldoni(
    titolo: str = typer.Argument(
        ...,
        help='Taglibra titolo. Ekzemplo: taglibro aldoni "Hodiaŭ".',
    ),
    etikedo: list[str] | None = typer.Option(
        None,
        "-e",
        "--etikedo",
        help="Etikedo UUID/teksto; ripetu por pluraj. Ekzemplo: -e #a1b2c3d4 -e ideo.",
    ),
    priskribo: str = typer.Option(
        "",
        "-p",
        "--priskribo",
        help=(
            "Priskribo (markdown). Ekzemplo: --priskribo "
            '""Rilatas al [koncepto](ec#4feb123f)".'
        ),
    ),
    tempo: str | None = typer.Option(
        None,
        "-t",
        "--tempo",
        help=(
            "Tempo en YYYYMMDD_HHMM aŭ parta dato. Ekzemplo: --tempo 20260420_0915 "
            "aŭ --tempo 0420_0915."
        ),
    ),
) -> None:
    """Aldoni taglibran eniron."""
    titolo_text = _tasklib.normalize_markdown_links(titolo).strip()
    if not titolo_text:
        typer.echo("Malplena titolo ne permesata.", err=True)
        raise typer.Exit(1)
    priskribo_text = _tasklib.normalize_markdown_links(priskribo).strip()
    _tasklib.auto_create_semantic_link_etikedoj(titolo_text)
    _tasklib.auto_create_semantic_link_etikedoj(priskribo_text)
    try:
        tempo_iso = _parse_tempo(tempo)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    etikedo_ids = _tasklib.resolve_etikedo_refs(etikedo, interactive=True)
    uid = _tasklib.new_uuid()
    now = _tasklib.now_iso()
    with _tasklib.connect() as con:
        con.execute(
            """
            INSERT INTO taglibro (
                uuid, titolo, titolo_norm, priskribo, priskribo_norm,
                tempo, kreita_je, modifita_je
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uid,
                titolo_text,
                _tasklib.fold_search_text(titolo_text),
                priskribo_text,
                _tasklib.fold_search_text(priskribo_text),
                tempo_iso,
                now,
                now,
            ),
        )
        _set_labels(con, uid, etikedo_ids)
        con.commit()
    typer.echo(f"Aldonis taglibran eniron #{uid[:8]}: {_render_text(titolo_text)}")


@app.command("serci")
def serci(
    teksto: str | None = typer.Argument(
        None,
        help="Serĉa teksto. Ekzemplo: taglibro serci hodiaŭ.",
    ),
    titolo: str | None = typer.Option(
        None,
        "--titolo",
        help="Filtri laŭ titolo. Ekzemplo: --titolo ideo.",
    ),
    priskribo: str | None = typer.Option(
        None,
        "--priskribo",
        help="Filtri laŭ priskribo. Ekzemplo: --priskribo [vorto](vt#8bf534dc).",
    ),
    etikedo: list[str] | None = typer.Option(
        None,
        "-e",
        "--etikedo",
        help=(
            "Filtri laŭ etikedo UUID/teksto; ripetu por pluraj. "
            "Ekzemplo: -e #a1b2c3d4."
        ),
    ),
    de_tempo: str | None = typer.Option(
        None,
        "--de",
        help=(
            "Filtri ekde tempo (YYYYMMDD_HHMM aŭ parta). "
            "Ekzemplo: --de 20260401_0000."
        ),
    ),
    gxis_tempo: str | None = typer.Option(
        None,
        "--gxis",
        help=(
            "Filtri ĝis tempo (YYYYMMDD_HHMM aŭ parta). "
            "Ekzemplo: --gxis 20260430_2359."
        ),
    ),
    limo: int = typer.Option(
        50,
        "-lo",
        "--limo",
        help="Maksimumaj rezultoj. Ekzemplo: --limo 20.",
    ),
) -> None:
    """Serĉi taglibrajn enirojn per kombineblaj filtriloj."""
    items = _load_entries()
    results = list(items)
    fuzzy_used = False

    if teksto:
        temp, fuzzy_used = _tasklib.search_items(
            results,
            teksto,
            text_getter=lambda item: (
                f"{item.get('titolo') or ''} {item.get('priskribo') or ''}"
            ),
            limit=max(limo, 1),
        )
        results = temp
    if titolo:
        needle = _tasklib.fold_search_text(titolo)
        results = [
            item
            for item in results
            if needle in _tasklib.fold_search_text(str(item.get("titolo") or ""))
        ]
    if priskribo:
        normalized_filter = _tasklib.normalize_markdown_links(priskribo)
        needle = _tasklib.fold_search_text(normalized_filter)
        results = [
            item
            for item in results
            if needle in _tasklib.fold_search_text(str(item.get("priskribo") or ""))
        ]
    if etikedo:
        etikedo_ids = _tasklib.resolve_etikedo_refs(etikedo, interactive=True)
        wanted = set(etikedo_ids)
        results = [
            item
            for item in results
            if wanted.issubset({uid for uid, _ in (item.get("etikedoj") or [])})
        ]
    if de_tempo:
        try:
            lower_iso = _parse_tempo(de_tempo)
        except ValueError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        results = [
            item for item in results if str(item.get("tempo") or "") >= lower_iso
        ]
    if gxis_tempo:
        try:
            upper_iso = _parse_tempo(gxis_tempo)
        except ValueError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        results = [
            item for item in results if str(item.get("tempo") or "") <= upper_iso
        ]

    if limo > 0:
        results = results[:limo]
    if fuzzy_used:
        typer.echo("Neniu preciza rezulto; montrante similajn kongruojn.")
    typer.echo(f"{len(results)} rezulto(j) trovita(j).")
    if not results:
        return
    should_numerate = bool(teksto and len(results) > 1)
    _print_results(results, numerate=should_numerate)
    if not should_numerate:
        return
    picked = _tasklib.prompt_pick(
        results,
        title=f"Elektu eniron por vidi (serĉo: {teksto!r}):",
        text_getter=lambda item: str(item.get("titolo") or ""),
    )
    if picked is None:
        typer.echo("Nuligita.")
        return
    _show_detail(picked)


@app.command("vidi")
def vidi(
    referenco: str = typer.Argument(
        ...,
        help="Taglibro UUID aŭ titolo. Ekzemplo: taglibro vidi #a1b2c3d4.",
    ),
) -> None:
    """Montri unu taglibran eniron laŭ UUID aŭ titolo."""
    item = _resolve_entry(referenco, allow_fuzzy=True, interactive=True)
    if item is None:
        typer.echo(f"Taglibro-eniro ne trovita: {referenco!r}", err=True)
        raise typer.Exit(1)
    _show_detail(item)


@app.command("modifi")
def modifi(
    referenco: str = typer.Argument(
        ...,
        help=(
            "Taglibro UUID aŭ titolo. "
            "Ekzemplo: taglibro modifi #a1b2c3d4 --titolo Nova."
        ),
    ),
    titolo: str | None = typer.Option(
        None,
        "-T",
        "--titolo",
        help='Nova titolo. Ekzemplo: --titolo "Nova tago".',
    ),
    priskribo: str | None = typer.Option(
        None,
        "-p",
        "--priskribo",
        help=(
            "Nova priskribo (markdown). Ekzemplo: --priskribo "
            '""Vidu [nodo](ec#4feb123f)".'
        ),
    ),
    tempo: str | None = typer.Option(
        None,
        "-t",
        "--tempo",
        help="Nova tempo. Ekzemplo: --tempo 20260421_0830.",
    ),
    etikedo: list[str] | None = typer.Option(
        None,
        "-e",
        "--etikedo",
        help="Nova etikedo-listo (anstataŭigas ekzistantajn); ripetu por pluraj.",
    ),
) -> None:
    """Modifi ekzistantan taglibran eniron."""
    item = _resolve_entry(referenco, allow_fuzzy=True, interactive=True)
    if item is None:
        typer.echo(f"Taglibro-eniro ne trovita: {referenco!r}", err=True)
        raise typer.Exit(1)
    if titolo is None and priskribo is None and tempo is None and etikedo is None:
        typer.echo("Nenio por modifi. Uzu almenaŭ unu opcion.", err=True)
        raise typer.Exit(1)

    uid = str(item.get("uuid") or "")
    new_titolo = (
        _tasklib.normalize_markdown_links(titolo).strip()
        if titolo is not None
        else str(item.get("titolo") or "")
    )
    if not new_titolo:
        typer.echo("Malplena titolo ne permesata.", err=True)
        raise typer.Exit(1)
    new_priskribo = (
        _tasklib.normalize_markdown_links(priskribo).strip()
        if priskribo is not None
        else str(item.get("priskribo") or "")
    )
    if titolo is not None:
        _tasklib.auto_create_semantic_link_etikedoj(new_titolo)
    if priskribo is not None:
        _tasklib.auto_create_semantic_link_etikedoj(new_priskribo)
    if tempo is None:
        new_tempo = str(item.get("tempo") or "")
    else:
        try:
            new_tempo = _parse_tempo(tempo)
        except ValueError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
    label_ids = (
        [label_uid for label_uid, _ in (item.get("etikedoj") or [])]
        if etikedo is None
        else _tasklib.resolve_etikedo_refs(etikedo, interactive=True)
    )
    with _tasklib.connect() as con:
        con.execute(
            """
            UPDATE taglibro
            SET titolo = ?, titolo_norm = ?, priskribo = ?, priskribo_norm = ?,
                tempo = ?, modifita_je = ?
            WHERE uuid = ?
            """,
            (
                new_titolo,
                _tasklib.fold_search_text(new_titolo),
                new_priskribo,
                _tasklib.fold_search_text(new_priskribo),
                new_tempo,
                _tasklib.now_iso(),
                uid,
            ),
        )
        _set_labels(con, uid, label_ids)
        con.commit()
    updated = _resolve_entry(uid, allow_fuzzy=False, interactive=False)
    if updated is None:
        typer.echo("Ne povis relegi modifitan eniron.", err=True)
        raise typer.Exit(1)
    typer.echo(f"Modifis taglibro-eniron #{uid[:8]}.")
    _show_detail(updated)


@app.command("forigi")
def forigi(
    referenco: str = typer.Argument(
        ...,
        help="Taglibro UUID aŭ titolo. Ekzemplo: taglibro forigi #a1b2c3d4.",
    ),
) -> None:
    """Forigi taglibran eniron laŭ UUID aŭ titolo."""
    item = _resolve_entry(referenco, allow_fuzzy=True, interactive=True)
    if item is None:
        typer.echo(f"Taglibro-eniro ne trovita: {referenco!r}", err=True)
        raise typer.Exit(1)
    uid = str(item.get("uuid") or "")
    answer = typer.prompt(
        (
            f'Forigi taglibro-eniron #{uid[:8]} '
            f'"{_render_text(str(item.get("titolo") or ""))}"? (j/N)'
        ),
        default="N",
    )
    if answer.strip().lower() != "j":
        typer.echo("Nuligita.")
        return
    with _tasklib.connect() as con:
        con.execute("DELETE FROM taglibro WHERE uuid = ?", (uid,))
        con.commit()
    typer.echo(f"Forigis taglibro-eniron #{uid[:8]}.")
