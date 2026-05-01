"""etikedo — manage labels shared by todo/taglibro."""

from __future__ import annotations

import typer
from rich.table import Table

from autish.commands import _tasklib
from autish.console import console
from autish.i18n import tr

app = typer.Typer(
    name="etikedo",
    help=tr(
        "Etikedo — administri etikedojn por todo kaj taglibro.",
        "Etikedo — manage labels for todo and taglibro.",
        "Etikedo — gérer les étiquettes pour todo et taglibro.",
    ),
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help", "--helpo"]},
)


def _load_all() -> list[dict]:
    with _tasklib.connect() as con:
        return _tasklib.list_etikedoj(con)


def _render_label_text(text: str, *, show_ref: bool = False) -> str:
    normalized = _tasklib.normalize_markdown_links(text)
    return _tasklib.render_markdown_links_plain(normalized, show_ref=show_ref)


def _print_table(items: list[dict]) -> None:
    table = Table(show_header=True, header_style="bold", box=None)
    table.add_column("#", justify="right", style="dim", no_wrap=True)
    table.add_column("UUID", style="cyan", no_wrap=True)
    table.add_column("TEKSTO")
    for idx, item in enumerate(items, start=1):
        table.add_row(
            str(idx),
            f"#{str(item.get('uuid') or '')[:8]}",
            _render_label_text(str(item.get("teksto") or ""), show_ref=True),
        )
    console.print(table)


def _find_exact(reference: str) -> dict | None:
    labels = _load_all()
    return _tasklib.resolve_reference(
        labels,
        reference,
        text_getter=lambda item: str(item.get("teksto") or ""),
        kind_label="etikedo",
        allow_fuzzy=False,
        interactive=False,
    )


def _search(query: str | None, *, limit: int) -> tuple[list[dict], bool]:
    labels = _load_all()
    results, fuzzy_used = _tasklib.search_items(
        labels,
        query,
        text_getter=lambda item: str(item.get("teksto") or ""),
        limit=max(limit, 1),
    )
    return results[: max(limit, 1)], fuzzy_used


def _show_detail(item: dict) -> None:
    typer.echo(f"uuid: #{str(item.get('uuid') or '')[:8]}")
    typer.echo(
        f"teksto: {_render_label_text(str(item.get('teksto') or ''), show_ref=True)}"
    )
    typer.echo(
        f"kreita_je: {_tasklib.format_iso_short(str(item.get('kreita_je') or ''))}"
    )
    typer.echo(
        f"modifita_je: {_tasklib.format_iso_short(str(item.get('modifita_je') or ''))}"
    )


@app.command("aldoni")
def aldoni(
    teksto: str = typer.Argument(
        ...,
        help=('Etikedo-teksto. Ekzemplo: etikedo aldoni "[Filozofio](ec#4feb123f)".'),
    ),
) -> None:
    """Aldoni novan etikedon kun aŭtomata UUID."""
    normalized = _tasklib.normalize_markdown_links(teksto).strip()
    if not normalized:
        typer.echo("Malplena etikedo ne permesata.", err=True)
        raise typer.Exit(1)
    folded = _tasklib.fold_search_text(normalized)
    now = _tasklib.now_iso()
    with _tasklib.connect() as con:
        existing = con.execute(
            "SELECT uuid FROM etikedo WHERE teksto_norm = ?",
            (folded,),
        ).fetchone()
        if existing:
            typer.echo(
                f"Etikedo jam ekzistas: #{str(existing['uuid'])[:8]}",
                err=True,
            )
            raise typer.Exit(1)
        uid = _tasklib.new_uuid()
        con.execute(
            "INSERT INTO etikedo (uuid, teksto, teksto_norm, kreita_je, modifita_je) "
            "VALUES (?, ?, ?, ?, ?)",
            (uid, normalized, folded, now, now),
        )
        con.commit()
    typer.echo(
        f"Aldonis etikedo #{uid[:8]}: {_render_label_text(normalized, show_ref=True)}"
    )


@app.command("modifi")
def modifi(
    referenco: str = typer.Argument(
        ...,
        help="Etikedo UUID aŭ teksto. Ekzemplo: etikedo modifi #a1b2c3d4 nova-etikedo.",
    ),
    nova_teksto: str = typer.Argument(
        ...,
        help=(
            "Nova etikedo-teksto. Ekzemplo: etikedo modifi #a1b2c3d4 "
            '"[Nova](vt#8bf534dc)".'
        ),
    ),
) -> None:
    """Modifi ekzistantan etikedon."""
    target = _tasklib.resolve_reference(
        _load_all(),
        referenco,
        text_getter=lambda item: str(item.get("teksto") or ""),
        kind_label="etikedo",
        allow_fuzzy=True,
        interactive=True,
    )
    if target is None:
        typer.echo(f"Etikedo ne trovita: {referenco!r}", err=True)
        raise typer.Exit(1)
    normalized = _tasklib.normalize_markdown_links(nova_teksto).strip()
    if not normalized:
        typer.echo("Malplena etikedo ne permesata.", err=True)
        raise typer.Exit(1)
    folded = _tasklib.fold_search_text(normalized)
    uid = str(target.get("uuid") or "")
    with _tasklib.connect() as con:
        conflict = con.execute(
            "SELECT uuid FROM etikedo WHERE teksto_norm = ? AND uuid != ?",
            (folded, uid),
        ).fetchone()
        if conflict:
            typer.echo(
                f"Alia etikedo jam uzas ĉi tiun tekston: #{str(conflict['uuid'])[:8]}",
                err=True,
            )
            raise typer.Exit(1)
        con.execute(
            "UPDATE etikedo SET teksto = ?, teksto_norm = ?, modifita_je = ? "
            "WHERE uuid = ?",
            (normalized, folded, _tasklib.now_iso(), uid),
        )
        con.commit()
    typer.echo(f"Modifis #{uid[:8]}: {_render_label_text(normalized, show_ref=True)}")


@app.command("forigi")
def forigi(
    referenco: str = typer.Argument(
        ...,
        help="Etikedo UUID aŭ teksto. Ekzemplo: etikedo forigi #a1b2c3d4.",
    ),
) -> None:
    """Forigi etikedon laŭ UUID aŭ teksto."""
    target = _tasklib.resolve_reference(
        _load_all(),
        referenco,
        text_getter=lambda item: str(item.get("teksto") or ""),
        kind_label="etikedo",
        allow_fuzzy=True,
        interactive=True,
    )
    if target is None:
        typer.echo(f"Etikedo ne trovita: {referenco!r}", err=True)
        raise typer.Exit(1)
    uid = str(target.get("uuid") or "")
    shown = _render_label_text(str(target.get("teksto") or ""), show_ref=True)
    answer = typer.prompt(f"Forigi {shown}? (j/N)", default="N")
    if answer.strip().lower() != "j":
        typer.echo("Nuligita.")
        return
    with _tasklib.connect() as con:
        con.execute("DELETE FROM etikedo WHERE uuid = ?", (uid,))
        con.commit()
    typer.echo(f"Forigis etikedon #{uid[:8]}.")


@app.command("serci")
def serci(
    teksto: str | None = typer.Argument(
        None,
        help=(
            "Serĉ-teksto por etikedo. Ekzemplo: etikedo serci filozofio "
            "(malplena = listigi ĉion)."
        ),
    ),
    limo: int = typer.Option(
        20,
        "-lo",
        "--limo",
        help="Maksimumaj rezultoj. Ekzemplo: etikedo serci filozo -lo 10.",
    ),
) -> None:
    """Serĉi etikedojn per teksto (kun fuzzy fallback)."""
    results, fuzzy_used = _search(teksto, limit=limo)
    if fuzzy_used:
        typer.echo("Neniu preciza rezulto; montrante similajn kongruojn.")
    typer.echo(f"{len(results)} rezulto(j) trovita(j).")
    if not results:
        return
    _print_table(results)


@app.command("vidi")
def vidi(
    referenco: str = typer.Argument(
        ...,
        help="Etikedo UUID aŭ teksto. Ekzemplo: etikedo vidi #a1b2c3d4.",
    ),
) -> None:
    """Montri unu etikedon; se ne ekzakta, uzi serĉan elekton."""
    exact = _find_exact(referenco)
    if exact is not None:
        _show_detail(exact)
        return
    results, fuzzy_used = _search(referenco, limit=20)
    if fuzzy_used:
        typer.echo("Neniu preciza rezulto; montrante similajn kongruojn.")
    if not results:
        typer.echo(f"Etikedo ne trovita: {referenco!r}", err=True)
        raise typer.Exit(1)
    if len(results) == 1:
        _show_detail(results[0])
        return
    picked = _tasklib.prompt_pick(
        results,
        title=f"Pluraj kandidatoj por {referenco!r}:",
        text_getter=lambda item: _render_label_text(str(item.get("teksto") or "")),
    )
    if picked is None:
        typer.echo("Nuligita.")
        return
    _show_detail(picked)
