"""todo — lightweight task manager with labels and priority formulas."""

from __future__ import annotations

import ast
import math
from datetime import datetime, timedelta, timezone

import typer
from rich.console import Console
from rich.table import Table

from autish.commands import _tasklib
from autish.i18n import tr

app = typer.Typer(
    name="todo",
    help=tr(
        "Todo — administri taskojn kun etikedoj kaj prioritato.",
        "Todo — manage tasks with labels and priority.",
        "Todo — gérer des tâches avec étiquettes et priorité.",
    ),
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help", "--helpo"]},
)

console = Console()

_VALID_STATOJ = {"malfermita", "farita", "prokrastita", "nuligita"}


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


def _load_todos() -> list[dict]:
    with _tasklib.connect() as con:
        rows = con.execute(
            """
            SELECT
                t.*,
                GROUP_CONCAT(e.uuid || ':' || e.teksto, '|') AS etikedoj_blob
            FROM todo t
            LEFT JOIN todo_etikedo te ON te.todo_uuid = t.uuid
            LEFT JOIN etikedo e ON e.uuid = te.etikedo_uuid
            GROUP BY t.uuid
            ORDER BY t.kreita_je DESC
            """
        ).fetchall()
    data: list[dict] = []
    for row in rows:
        item = dict(row)
        item["etikedoj"] = _parse_label_blob(item.get("etikedoj_blob"))
        data.append(item)
    return data


def _set_todo_labels(con, todo_uuid: str, etikedo_ids: list[str]) -> None:
    con.execute("DELETE FROM todo_etikedo WHERE todo_uuid = ?", (todo_uuid,))
    for etikedo_uuid in etikedo_ids:
        con.execute(
            "INSERT OR IGNORE INTO todo_etikedo "
            "(todo_uuid, etikedo_uuid) VALUES (?, ?)",
            (todo_uuid, etikedo_uuid),
        )


def _priority_context(created_at: str) -> dict[str, float]:
    created = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    delta = now - created.astimezone(timezone.utc)
    if delta.total_seconds() < 0:
        delta = timedelta(0)
    minutes = delta.total_seconds() / 60.0
    hours = delta.total_seconds() / 3600.0
    days = delta.total_seconds() / 86400.0
    months = days / 30.0
    return {
        "M": months,  # monato (30 tagoj)
        "D": days,  # tago
        "H": hours,  # horo
        "MIN": minutes,  # minuto
        "m": minutes,  # minuto (mallonga aliaso)
    }


def _assert_safe_expr(tree: ast.AST) -> None:
    allowed_nodes = (
        ast.Expression,
        ast.BinOp,
        ast.UnaryOp,
        ast.Constant,
        ast.Name,
        ast.Call,
        ast.Load,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.FloorDiv,
        ast.Mod,
        ast.Pow,
        ast.USub,
        ast.UAdd,
    )
    for node in ast.walk(tree):
        if not isinstance(node, allowed_nodes):
            raise ValueError("Nepermesita esprimo.")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise ValueError("Nepermesita funkcio-voko.")
            if node.func.id not in {"min", "max", "abs", "round", "int", "float"}:
                raise ValueError(f"Nepermesita funkcio: {node.func.id}")
        if isinstance(node, ast.Name):
            if node.id not in {
                "M",
                "D",
                "H",
                "MIN",
                "m",
                "min",
                "max",
                "abs",
                "round",
                "int",
                "float",
            }:
                raise ValueError(f"Nepermesita variablo: {node.id}")


def _compute_prioritato(raw_value: str, created_at: str) -> float:
    text = str(raw_value or "").strip()
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        pass
    tree = ast.parse(text, mode="eval")
    _assert_safe_expr(tree)
    context = _priority_context(created_at)
    safe_globals = {"__builtins__": {}}
    safe_locals = {
        "M": context["M"],
        "D": context["D"],
        "H": context["H"],
        "MIN": context["MIN"],
        "m": context["m"],
        "min": min,
        "max": max,
        "abs": abs,
        "round": round,
        "int": int,
        "float": float,
    }
    result = eval(compile(tree, "<prioritato>", "eval"), safe_globals, safe_locals)
    if not isinstance(result, (int, float)) or not math.isfinite(float(result)):
        raise ValueError("Prioritata esprimo ne redonis validan nombron.")
    return float(result)


def _parse_prioritato_filter(raw: str | None) -> tuple[float | None, float | None]:
    if raw is None:
        return None, None
    token = str(raw).strip()
    if not token:
        return None, None
    if "," in token:
        left, right = token.split(",", 1)
        lo = float(left.strip()) if left.strip() else None
        hi = float(right.strip()) if right.strip() else None
        return lo, hi
    return float(token), None


def _normalize_stato(raw: str) -> str:
    value = str(raw or "").strip().casefold()
    aliases = {
        "malfermita": "malfermita",
        "open": "malfermita",
        "farita": "farita",
        "done": "farita",
        "prokrastita": "prokrastita",
        "deferred": "prokrastita",
        "nuligita": "nuligita",
        "cancelled": "nuligita",
        "canceled": "nuligita",
    }
    normalized = aliases.get(value, value)
    if normalized not in _VALID_STATOJ:
        raise ValueError(
            "Nevalida stato. Uzu: malfermita, farita, prokrastita, nuligita."
        )
    return normalized


def _render_label_pairs(pairs: list[tuple[str, str]]) -> str:
    if not pairs:
        return "-"
    return ", ".join(
        _tasklib.render_markdown_links_plain(text) for _, text in pairs if text
    )


def _print_results(items: list[dict]) -> None:
    table = Table(show_header=True, header_style="bold", box=None)
    table.add_column("UUID", style="cyan", no_wrap=True)
    table.add_column("TITOLO")
    table.add_column("PRIORITATO", justify="right", no_wrap=True)
    table.add_column("STATO", no_wrap=True)
    table.add_column("ETIKEDOJ")
    for item in items:
        priority = _compute_prioritato(
            str(item.get("prioritato") or "0"),
            str(item.get("kreita_je") or ""),
        )
        table.add_row(
            f"#{str(item.get('uuid') or '')[:8]}",
            _render_text(str(item.get("titolo") or ""), show_ref=True),
            f"{priority:.2f}",
            str(item.get("stato") or ""),
            _render_label_pairs(item.get("etikedoj") or []),
        )
    console.print(table)


def _show_detail(item: dict) -> None:
    priority = _compute_prioritato(
        str(item.get("prioritato") or "0"),
        str(item.get("kreita_je") or ""),
    )
    typer.echo(f"uuid: #{str(item.get('uuid') or '')[:8]}")
    typer.echo(f"titolo: {_render_text(str(item.get('titolo') or ''), show_ref=True)}")
    typer.echo(
        f"priskribo: {_render_text(str(item.get('priskribo') or ''), show_ref=True)}"
    )
    typer.echo(f"stato: {str(item.get('stato') or '')}")
    typer.echo(
        f"prioritato: {priority:.2f} (kruda: {str(item.get('prioritato') or '0')})"
    )
    typer.echo(f"etikedoj: {_render_label_pairs(item.get('etikedoj') or [])}")
    typer.echo(
        f"kreita_je: {_tasklib.format_iso_short(str(item.get('kreita_je') or ''))}"
    )
    typer.echo(
        f"modifita_je: {_tasklib.format_iso_short(str(item.get('modifita_je') or ''))}"
    )


def _resolve_todo(
    reference: str, *, allow_fuzzy: bool, interactive: bool
) -> dict | None:
    return _tasklib.resolve_reference(
        _load_todos(),
        reference,
        text_getter=lambda item: str(item.get("titolo") or ""),
        kind_label="todo",
        allow_fuzzy=allow_fuzzy,
        interactive=interactive,
    )


@app.command("aldoni")
def aldoni(
    titolo: str = typer.Argument(
        ...,
        help='Taska titolo. Ekzemplo: todo aldoni "legi artikolon".',
    ),
    priskribo: str = typer.Option(
        "",
        "-p",
        "--priskribo",
        help=(
            "Taska priskribo (markdown). Ekzemplo: --priskribo "
            '""Vidu [temon](ec#4feb123f)".'
        ),
    ),
    etikedo: list[str] | None = typer.Option(
        None,
        "-e",
        "--etikedo",
        help=(
            "Etikedo UUID/teksto; ripetu por pluraj. Ekzemplo: -e #a1b2c3d4 -e "
            "urgxenta."
        ),
    ),
    prioritato: str = typer.Option(
        "0",
        "-P",
        "--prioritato",
        help=('Nombro aŭ esprimo. Ekzemplo: -P "min(20+2*D,70)" aŭ -P 40.'),
    ),
    stato: str = typer.Option(
        "malfermita",
        "-s",
        "--stato",
        help=(
            "Komenca stato. Ekzemplo: --stato malfermita "
            "(ebloj: malfermita, farita, prokrastita, nuligita)."
        ),
    ),
) -> None:
    """Aldoni novan todo-taskon."""
    titolo_text = _tasklib.normalize_markdown_links(titolo).strip()
    if not titolo_text:
        typer.echo("Malplena titolo ne permesata.", err=True)
        raise typer.Exit(1)
    priskribo_text = _tasklib.normalize_markdown_links(priskribo).strip()
    normalized_stato = _normalize_stato(stato)
    now = _tasklib.now_iso()
    _ = _compute_prioritato(prioritato, now)  # validates expression
    etikedo_ids = _tasklib.resolve_etikedo_refs(etikedo, interactive=True)
    uid = _tasklib.new_uuid()
    with _tasklib.connect() as con:
        con.execute(
            """
            INSERT INTO todo (
                uuid, titolo, titolo_norm, priskribo, priskribo_norm,
                prioritato, stato, kreita_je, modifita_je
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uid,
                titolo_text,
                _tasklib.fold_search_text(titolo_text),
                priskribo_text,
                _tasklib.fold_search_text(priskribo_text),
                prioritato.strip(),
                normalized_stato,
                now,
                now,
            ),
        )
        _set_todo_labels(con, uid, etikedo_ids)
        con.commit()
    typer.echo(f"Aldonis todo #{uid[:8]}: {_render_text(titolo_text, show_ref=True)}")


@app.command("serci")
def serci(
    teksto: str | None = typer.Argument(
        None,
        help="Serĉa teksto. Ekzemplo: todo serci legi.",
    ),
    titolo: str | None = typer.Option(
        None,
        "--titolo",
        help="Filtri laŭ titolo. Ekzemplo: --titolo raporto.",
    ),
    priskribo: str | None = typer.Option(
        None,
        "--priskribo",
        help="Filtri laŭ priskribo. Ekzemplo: --priskribo [temo](ec#4feb123f).",
    ),
    etikedo: list[str] | None = typer.Option(
        None,
        "-e",
        "--etikedo",
        help=(
            "Filtri laŭ etikedo UUID/teksto; ripetu por pluraj. "
            "Ekzemplo: -e urĝa -e #a1b2c3d4."
        ),
    ),
    prioritato: str | None = typer.Option(
        None,
        "-P",
        "--prioritato",
        help="Filtri laŭ prioritato MIN,MAX aŭ nur MIN. Ekzemplo: -P 30,80 aŭ -P 50.",
    ),
    stato: str | None = typer.Option(
        None,
        "-s",
        "--stato",
        help="Filtri laŭ stato. Ekzemplo: --stato malfermita.",
    ),
    limo: int = typer.Option(
        50,
        "-lo",
        "--limo",
        help="Maksimumaj rezultoj. Ekzemplo: --limo 25.",
    ),
) -> None:
    """Serĉi todo-taskojn per kombineblaj filtriloj."""
    items = _load_todos()
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
    if stato:
        normalized_stato = _normalize_stato(stato)
        results = [
            item for item in results if str(item.get("stato") or "") == normalized_stato
        ]
    if etikedo:
        etikedo_ids = _tasklib.resolve_etikedo_refs(etikedo, interactive=True)
        wanted = set(etikedo_ids)
        results = [
            item
            for item in results
            if wanted.issubset({uid for uid, _ in (item.get("etikedoj") or [])})
        ]
    lo, hi = _parse_prioritato_filter(prioritato)
    if lo is not None or hi is not None:
        filtered: list[dict] = []
        for item in results:
            value = _compute_prioritato(
                str(item.get("prioritato") or "0"),
                str(item.get("kreita_je") or ""),
            )
            if lo is not None and value < lo:
                continue
            if hi is not None and value > hi:
                continue
            filtered.append(item)
        results = filtered

    if limo > 0:
        results = results[:limo]
    if fuzzy_used:
        typer.echo("Neniu preciza rezulto; montrante similajn kongruojn.")
    typer.echo(f"{len(results)} rezulto(j) trovita(j).")
    if not results:
        return
    _print_results(results)


@app.command("vidi")
def vidi(
    referenco: str = typer.Argument(
        ...,
        help="Todo UUID aŭ titolo. Ekzemplo: todo vidi #a1b2c3d4.",
    ),
) -> None:
    """Montri unu todo-taskon laŭ UUID aŭ titolo."""
    item = _resolve_todo(referenco, allow_fuzzy=True, interactive=True)
    if item is None:
        typer.echo(f"Todo ne trovita: {referenco!r}", err=True)
        raise typer.Exit(1)
    _show_detail(item)


@app.command("modifi")
def modifi(
    referenco: str = typer.Argument(
        ...,
        help="Todo UUID aŭ titolo. Ekzemplo: todo modifi #a1b2c3d4 --stato farita.",
    ),
    titolo: str | None = typer.Option(
        None,
        "-T",
        "--titolo",
        help='Nova titolo. Ekzemplo: --titolo "fini raporton".',
    ),
    priskribo: str | None = typer.Option(
        None,
        "-p",
        "--priskribo",
        help=(
            "Nova priskribo (markdown). Ekzemplo: --priskribo "
            '""Vidu [noto](vt#8bf534dc)".'
        ),
    ),
    etikedo: list[str] | None = typer.Option(
        None,
        "-e",
        "--etikedo",
        help=(
            "Nova etikedo-listo (anstataŭigas ekzistantajn); ripetu por pluraj. "
            "Ekzemplo: -e #a1b2c3d4 -e grava."
        ),
    ),
    prioritato: str | None = typer.Option(
        None,
        "-P",
        "--prioritato",
        help='Nova prioritato nombro aŭ esprimo. Ekzemplo: -P "30+5*(H-10)".',
    ),
    stato: str | None = typer.Option(
        None,
        "-s",
        "--stato",
        help="Nova stato. Ekzemplo: --stato farita.",
    ),
) -> None:
    """Modifi ekzistantan todo-taskon."""
    item = _resolve_todo(referenco, allow_fuzzy=True, interactive=True)
    if item is None:
        typer.echo(f"Todo ne trovita: {referenco!r}", err=True)
        raise typer.Exit(1)
    if (
        titolo is None
        and priskribo is None
        and etikedo is None
        and prioritato is None
        and stato is None
    ):
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
    new_prioritato = (
        str(item.get("prioritato") or "0") if prioritato is None else prioritato
    )
    _ = _compute_prioritato(new_prioritato, str(item.get("kreita_je") or ""))
    new_stato = (
        str(item.get("stato") or "malfermita")
        if stato is None
        else _normalize_stato(stato)
    )
    label_ids = (
        [uid for uid, _ in (item.get("etikedoj") or [])]
        if etikedo is None
        else _tasklib.resolve_etikedo_refs(etikedo, interactive=True)
    )
    with _tasklib.connect() as con:
        con.execute(
            """
            UPDATE todo
            SET titolo = ?, titolo_norm = ?, priskribo = ?, priskribo_norm = ?,
                prioritato = ?, stato = ?, modifita_je = ?
            WHERE uuid = ?
            """,
            (
                new_titolo,
                _tasklib.fold_search_text(new_titolo),
                new_priskribo,
                _tasklib.fold_search_text(new_priskribo),
                new_prioritato.strip(),
                new_stato,
                _tasklib.now_iso(),
                uid,
            ),
        )
        _set_todo_labels(con, uid, label_ids)
        con.commit()
    updated = _resolve_todo(uid, allow_fuzzy=False, interactive=False)
    if updated is None:
        typer.echo("Ne povis relegi modifitan todo-eniron.", err=True)
        raise typer.Exit(1)
    typer.echo(f"Modifis todo #{uid[:8]}.")
    _show_detail(updated)


@app.command("forigi")
def forigi(
    referenco: str = typer.Argument(
        ...,
        help="Todo UUID aŭ titolo. Ekzemplo: todo forigi #a1b2c3d4.",
    ),
) -> None:
    """Forigi todo-taskon laŭ UUID aŭ titolo."""
    item = _resolve_todo(referenco, allow_fuzzy=True, interactive=True)
    if item is None:
        typer.echo(f"Todo ne trovita: {referenco!r}", err=True)
        raise typer.Exit(1)
    uid = str(item.get("uuid") or "")
    answer = typer.prompt(
        (
            f'Forigi todo #{uid[:8]} '
            f'"{_render_text(str(item.get("titolo") or ""))}"? (j/N)'
        ),
        default="N",
    )
    if answer.strip().lower() != "j":
        typer.echo("Nuligita.")
        return
    with _tasklib.connect() as con:
        con.execute("DELETE FROM todo WHERE uuid = ?", (uid,))
        con.commit()
    typer.echo(f"Forigis todo #{uid[:8]}.")
