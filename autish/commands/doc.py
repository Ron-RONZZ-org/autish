"""doc — documentation management microapp.

Usage:
    doc aldoni <file.md>        — add a new manual from a .md file
    doc vidi <UUID>             — view a manual entry
    doc modifi <UUID>           — edit a manual entry
    doc forigi <UUID>           — delete a manual entry
    doc serci <term>            — search manuals (title by default)

Data is stored in an SQLite database at ~/.local/share/autish/doc.db.
Manuals can be linked to encik entries with -L/--ligilo option.
"""

from __future__ import annotations

import sqlite3
import subprocess
import tempfile
import uuid as _uuid_mod
from datetime import datetime, timezone
from pathlib import Path

import typer
from rich.markdown import Markdown

from autish.commands.uzanto import _load_profile
from autish.console import console
from autish.services.markmap import has_markmap_cli, markmap_cli_path
from autish.utils import (
    best_text_match_score,
    confirm_esperante,
    markdown_to_html,
    open_html_in_browser,
    open_path_in_browser,
)

# ──────────────────────────────────────────────────────────────────────────────
# Typer app
# ──────────────────────────────────────────────────────────────────────────────

app = typer.Typer(
    name="doc",
    help="Doc — dokumentaro-mastruma mikroapo.",
    no_args_is_help=False,
    invoke_without_command=True,
    context_settings={"help_option_names": ["-h", "--help", "--helpo"]},
)

# ──────────────────────────────────────────────────────────────────────────────
# Storage paths
# ──────────────────────────────────────────────────────────────────────────────

_DATA_DIR: Path = Path.home() / ".local" / "share" / "autish"
_DB_FILE: Path = _DATA_DIR / "doc.db"
_ENCIK_DB_FILE: Path = _DATA_DIR / "encik.db"

# ──────────────────────────────────────────────────────────────────────────────
# DB schema
# ──────────────────────────────────────────────────────────────────────────────

_CREATE_MAN = """
CREATE TABLE IF NOT EXISTS man (
    uuid        TEXT PRIMARY KEY,
    titolo      TEXT NOT NULL,
    enhavo      TEXT NOT NULL,
    encik_uuid  TEXT,
    kreita_je   TEXT NOT NULL,
    modifita_je TEXT NOT NULL
);
"""

_CREATE_MAN_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_man_titolo_lower ON man(LOWER(titolo));
CREATE INDEX IF NOT EXISTS idx_man_uuid_prefix ON man(substr(uuid, 1, 8));
CREATE INDEX IF NOT EXISTS idx_man_encik_uuid ON man(encik_uuid);
CREATE INDEX IF NOT EXISTS idx_man_kreita_je ON man(kreita_je);
"""

_CREATE_MAN_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS man_fts USING fts5(
    uuid UNINDEXED,
    titolo,
    enhavo,
    content=man,
    content_rowid=rowid
);
"""


# ──────────────────────────────────────────────────────────────────────────────
# Database initialization and helpers
# ──────────────────────────────────────────────────────────────────────────────


def _ensure_db() -> None:
    """Create database and tables if they don't exist."""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_FILE)
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        conn.executescript(_CREATE_MAN)
        conn.executescript(_CREATE_MAN_INDEXES)
        try:
            conn.executescript(_CREATE_MAN_FTS)
        except sqlite3.OperationalError:
            # FTS table may already exist or fail silently
            pass
        conn.commit()
    finally:
        conn.close()


def _get_now_iso() -> str:
    """Get current timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def _extract_title_from_markdown(content: str, filename: str) -> str:
    """Extract title from markdown content or use filename."""
    lines = content.split("\n")
    for line in lines:
        if line.startswith("# "):
            return line[2:].strip()
    # Fallback to filename without extension
    return Path(filename).stem.replace("-", " ").replace("_", " ").title()


def _get_encik_entry(uuid_or_title: str) -> dict | None:
    """Get encik entry by UUID or title (for reverse linking)."""
    if not _ENCIK_DB_FILE.exists():
        return None

    try:
        conn = sqlite3.connect(_ENCIK_DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Try UUID first
        if len(uuid_or_title) >= 8:
            cursor.execute(
                "SELECT * FROM encik WHERE uuid = ? OR uuid LIKE ? LIMIT 1",
                (uuid_or_title, uuid_or_title + "%"),
            )
            row = cursor.fetchone()
            if row:
                return dict(row)

        # Try fuzzy match on title
        cursor.execute(
            "SELECT * FROM encik WHERE LOWER(titolo) LIKE ? LIMIT 5",
            ("%" + uuid_or_title.lower() + "%",),
        )
        rows = cursor.fetchall()
        if rows:
            return dict(rows[0])

    except sqlite3.Error:
        pass
    finally:
        conn.close()

    return None


def _resolve_man_entry(
    ref: str, interactive: bool = False
) -> dict[str, str] | None:
    """Resolve a man entry by UUID or title."""
    _ensure_db()
    conn = sqlite3.connect(_DB_FILE)
    conn.row_factory = sqlite3.Row

    try:
        cursor = conn.cursor()

        # Try exact UUID match first
        if len(ref) >= 8 and ref.startswith("#"):
            uuid_ref = ref[1:]
        else:
            uuid_ref = ref

        cursor.execute(
            "SELECT * FROM man WHERE uuid = ? OR uuid LIKE ? LIMIT 1",
            (uuid_ref, uuid_ref + "%"),
        )
        row = cursor.fetchone()
        if row:
            return dict(row)

        # Try title fuzzy match
        cursor.execute(
            "SELECT * FROM man WHERE LOWER(titolo) LIKE ? LIMIT 10",
            ("%" + ref.lower() + "%",),
        )
        rows = cursor.fetchall()

        if len(rows) == 0:
            return None
        elif len(rows) == 1:
            return dict(rows[0])
        elif interactive:
            console.print("\n[bold cyan]Pluraj trovoj:[/]")
            for i, entry in enumerate(rows, 1):
                short_uuid = str(entry["uuid"])[:8]
                console.print(f"  {i}. [{entry['titolo']}] #{short_uuid}")
            choice = typer.prompt(f"Elektu (1-{len(rows)})")
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(rows):
                    return dict(rows[idx])
            except (ValueError, IndexError):
                pass
            return None
        else:
            return dict(rows[0])

    finally:
        conn.close()


def _get_user_locale_languages() -> list[str]:
    """Get user's preferred languages from uzanto profilo."""
    try:
        profile = _load_profile()
        if profile and "lingvoj" in profile:
            lingvoj = profile["lingvoj"]
            if isinstance(lingvoj, str):
                return [lingvoj]
            elif isinstance(lingvoj, list):
                return lingvoj
    except (KeyError, TypeError, ValueError):
        pass
    return ["eo", "en"]


# ──────────────────────────────────────────────────────────────────────────────
# Commands
# ──────────────────────────────────────────────────────────────────────────────


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Man — dokumentaro-mastruma mikroapo."""
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


@app.command("aldoni")
def aldoni(
    dosiero: str = typer.Argument(
        ...,
        help=(
            "Vojo al .md dosiero.\n"
            "Ekzemplo: doc aldoni ./manlibro/suno.md"
        ),
    ),
    ligilo: str | None = typer.Option(
        None,
        "-L",
        "--ligilo",
        help=(
            "UUID de encik-nodo al kiu ĉi tiu manlibro estas ligita.\n"
            "Ekzemplo: -L e0a5d3b7"
        ),
    ),
    vidi_poste: bool = typer.Option(
        False,
        "-v",
        "--vidi",
        help="Montri la aldonitan manlibron post konservado.",
    ),
) -> None:
    """Aldoni novan manualan dosieron."""
    _ensure_db()

    dosiero_path = Path(dosiero).expanduser().resolve()
    if not dosiero_path.exists():
        typer.echo(f"Dosiero ne trovita: {dosiero}", err=True)
        raise typer.Exit(code=1)

    if not dosiero_path.is_file():
        typer.echo(f"Ne dosiero: {dosiero}", err=True)
        raise typer.Exit(code=1)

    try:
        content = dosiero_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        typer.echo(f"Eraro dum lego de dosiero: {e}", err=True)
        raise typer.Exit(code=1) from e

    # Extract title and validate
    titolo = _extract_title_from_markdown(content, dosiero_path.name)
    if not titolo:
        typer.echo("Ne povis ekstrakti titolon de la manlibro.", err=True)
        raise typer.Exit(code=1)

    # Generate UUID
    uuid_str = str(_uuid_mod.uuid4())
    now = _get_now_iso()

    # Validate encik linkage if provided
    encik_uuid = None
    if ligilo:
        encik_entry = _get_encik_entry(ligilo)
        if encik_entry:
            encik_uuid = str(encik_entry.get("uuid", ""))
        else:
            typer.echo(f"Encik-nodo ne trovita: {ligilo}", err=True)
            raise typer.Exit(code=1)

    # Store in database
    conn = sqlite3.connect(_DB_FILE)
    try:
        conn.execute(
            (
                "INSERT INTO man "
                "(uuid, titolo, enhavo, encik_uuid, kreita_je, modifita_je) "
                "VALUES (?, ?, ?, ?, ?, ?)"
            ),
            (uuid_str, titolo, content, encik_uuid, now, now),
        )
        conn.commit()
    except sqlite3.Error as e:
        typer.echo(f"Datumbazo eraro: {e}", err=True)
        raise typer.Exit(code=1) from e
    finally:
        conn.close()

    short_uuid = uuid_str[:8]
    typer.echo(f"✓ Manlibro aldonita: {titolo} #{short_uuid}")

    if vidi_poste:
        vidi(short_uuid)


@app.command("vidi")
def vidi(
    ref: str | None = typer.Argument(
        None,
        help=(
            "UUID, #UUID, aŭ titolo de la manlibro.\n"
            'Ekzemplo: doc vidi "#e0a5d3b7"'
        ),
    ),
    html: bool = typer.Option(
        False,
        "--html",
        "-h",
        help=(
            "Malfermi en defaŭlta retumilo kun HTML-a rendera.\n"
            'Ekzemplo: doc vidi "#abc" --html'
        ),
    ),
    markmap: bool = typer.Option(
        False,
        "--markmap",
        "-mm",
        help=(
            "Malfermi kiel markmap-a diagramo.\n"
            'Ekzemplo: doc vidi "#abc" --markmap'
        ),
    ),
    pager: bool | None = typer.Option(
        None,
        "--pager",
        "-p",
        help=(
            "Uzis 'less' pagilo por vidado (aŭtomate en terminaloj).\n"
            'Ekzemplo: doc vidi "#abc" --pager'
        ),
    ),
) -> None:
    """Montri unu manualan nodon."""
    import sys
    
    if not ref:
        typer.echo(
            "Mankas argumento REF. Se vi uzas UUID kun #, citu ĝin:\n"
            '  doc vidi "#e0a5d3b7"',
            err=True,
        )
        raise typer.Exit(code=2)

    # Check for conflicting options
    if (html or markmap) and pager is False:
        typer.echo(
            "Eraro: --html kaj --markmap ne povas esti uzataj kun --pager=false",
            err=True,
        )
        raise typer.Exit(code=2)

    entry = _resolve_man_entry(ref, interactive=True)
    if entry is None:
        typer.echo(f"Manlibro ne trovita: {ref!r}", err=True)
        raise typer.Exit(code=1)

    # Handle HTML display option
    if html:
        _display_as_html(entry)
        return

    # Handle Markmap display option
    if markmap:
        _display_as_markmap(entry)
        return

    # Default: determine pager based on whether stdout is a terminal
    # If pager is explicitly set, use that; otherwise auto-detect
    use_pager = pager if pager is not None else sys.stdout.isatty()
    
    if use_pager:
        _display_in_pager(entry)
    else:
        _display_in_console(entry)


def _display_in_console(entry: dict) -> None:
    """Display entry directly in console without pager."""
    console.clear()
    
    # Display title and UUID
    short_uuid = str(entry["uuid"])[:8]
    console.print(
        f"\n[bold cyan]{entry['titolo']}[/] [dim]#{short_uuid}[/]\n"
    )

    # Display linked encik entry if exists
    if entry.get("encik_uuid"):
        try:
            conn = sqlite3.connect(_ENCIK_DB_FILE)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT uuid, titolo FROM encik WHERE uuid = ?",
                (entry["encik_uuid"],),
            )
            encik_row = cursor.fetchone()
            if encik_row:
                encik_short = str(encik_row["uuid"])[:8]
                console.print(
                    f"[dim]Ligita al encik:[/] {encik_row['titolo']} #{encik_short}\n"
                )
            conn.close()
        except (sqlite3.Error, TypeError):
            pass

    # Display markdown content
    try:
        md = Markdown(entry["enhavo"])
        console.print(md)
    except (TypeError, ValueError):
        typer.echo(entry["enhavo"])

    # Display metadata
    console.print(
        f"\n[dim]Kreita: {entry['kreita_je']} | Modifita: {entry['modifita_je']}[/]"
    )


def _display_in_pager(entry: dict) -> None:
    """Display entry in less pager."""
    # Build formatted text content
    short_uuid = str(entry["uuid"])[:8]
    content = f"{entry['titolo']} #{short_uuid}\n\n"

    # Add linked encik entry if exists
    if entry.get("encik_uuid"):
        try:
            conn = sqlite3.connect(_ENCIK_DB_FILE)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT uuid, titolo FROM encik WHERE uuid = ?",
                (entry["encik_uuid"],),
            )
            encik_row = cursor.fetchone()
            if encik_row:
                encik_short = str(encik_row["uuid"])[:8]
                content += f"Ligita al encik: {encik_row['titolo']} #{encik_short}\n\n"
            conn.close()
        except (sqlite3.Error, TypeError):
            pass

    content += entry["enhavo"]
    content += f"\n\nKreita: {entry['kreita_je']} | Modifita: {entry['modifita_je']}"

    # Use less pager
    try:
        pager_cmd = ["less", "-R"]
        subprocess.run(pager_cmd, input=content.encode(), check=False)
    except FileNotFoundError:
        typer.echo("Eraro: 'less' pagilo ne trovita", err=True)
        _display_in_console(entry)


def _display_as_html(entry: dict) -> None:
    """Render and display entry as HTML in default browser."""
    # Generate HTML
    html_content = markdown_to_html(entry["enhavo"], title=entry["titolo"])

    try:
        temp_path = open_html_in_browser(html_content)
        typer.echo(f"[dim]Malferma en retumilo: {temp_path}[/]")
    except OSError as e:
        typer.echo(f"Eraro dum malfermo: {e}", err=True)
        raise typer.Exit(code=1) from None


def _display_as_markmap(entry: dict) -> None:
    """Render and display entry as markmap diagram using local CLI."""
    if not has_markmap_cli():
        typer.echo(
            "Eraro: markmap-cli ne instalita loke. Rulu: autish sistemo install",
            err=True,
        )
        raise typer.Exit(code=1)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as src:
        src.write(entry["enhavo"])
        src_path = src.name
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".html", delete=False, encoding="utf-8"
    ) as out:
        out_path = out.name

    try:
        result = subprocess.run(
            [str(markmap_cli_path()), src_path, "-o", out_path, "--no-open"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            details = (result.stderr or result.stdout or "").strip()
            typer.echo(f"Eraro dum markmap-generado: {details}", err=True)
            raise typer.Exit(code=1)
        open_path_in_browser(out_path)
        typer.echo(f"[dim]Markmap malferme: {out_path}[/]")
    except (subprocess.CalledProcessError, OSError) as e:
        typer.echo(f"Eraro dum malfermo: {e}", err=True)
        raise typer.Exit(code=1) from None
    finally:
        Path(src_path).unlink(missing_ok=True)


@app.command("modifi")
def modifi(
    ref: str = typer.Argument(
        ...,
        help=(
            "UUID, #UUID, aŭ titolo de la manlibro por modifi.\n"
            'Ekzemplo: doc modifi "#e0a5d3b7"'
        ),
    ),
    vidi_poste: bool = typer.Option(
        False,
        "-v",
        "--vidi",
        help="Montri la modifitan manualan nodon post konservado.",
    ),
) -> None:
    """Modifi manualan nodon en $EDITOR."""
    entry = _resolve_man_entry(ref, interactive=True)
    if entry is None:
        typer.echo(f"Manlibro ne trovita: {ref!r}", err=True)
        raise typer.Exit(code=1)

    uuid_str = entry["uuid"]

    # Create temp file with current content
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".md",
        delete=False,
        encoding="utf-8",
    ) as tmp:
        tmp.write(entry["enhavo"])
        tmp_path = tmp.name

    try:
        # Open in editor
        editor = _get_editor()
        if editor:
            subprocess.run([editor, tmp_path], check=False)
        else:
            typer.echo("Neniuj redaktiloj trovitaj ($EDITOR ne difinita).", err=True)
            raise typer.Exit(code=1)

        # Read modified content
        with open(tmp_path, encoding="utf-8") as f:
            new_content = f.read()

        # Update title if H1 changed
        new_titolo = _extract_title_from_markdown(new_content, tmp_path)

        # Store updates
        conn = sqlite3.connect(_DB_FILE)
        try:
            conn.execute(
                (
                    "UPDATE man SET titolo = ?, enhavo = ?, modifita_je = ? "
                    "WHERE uuid = ?"
                ),
                (new_titolo, new_content, _get_now_iso(), uuid_str),
            )
            conn.commit()
        except sqlite3.Error as e:
            typer.echo(f"Datumbazo eraro: {e}", err=True)
            raise typer.Exit(code=1) from e
        finally:
            conn.close()

        short_uuid = uuid_str[:8]
        typer.echo(f"✓ Manlibro modifita: {new_titolo} #{short_uuid}")

        if vidi_poste:
            vidi(short_uuid)

    finally:
        Path(tmp_path).unlink(missing_ok=True)


@app.command("forigi")
def forigi(
    ref: str = typer.Argument(
        ...,
        help=(
            "UUID, #UUID, aŭ titolo de la manlibro por forigi.\n"
            'Ekzemplo: doc forigi "#e0a5d3b7"'
        ),
    ),
) -> None:
    """Forigi manualan nodon."""
    entry = _resolve_man_entry(ref, interactive=True)
    if entry is None:
        typer.echo(f"Manlibro ne trovita: {ref!r}", err=True)
        raise typer.Exit(code=1)

    uuid_str = entry["uuid"]
    titolo = entry["titolo"]

    # Confirm deletion
    confirm = confirm_esperante(
        f"Ĉu vi certe volas forigi '{titolo}'?",
        default_yes=False,
    )
    if not confirm:
        typer.echo("Nuligita.")
        raise typer.Exit(code=0)

    conn = sqlite3.connect(_DB_FILE)
    try:
        conn.execute("DELETE FROM man WHERE uuid = ?", (uuid_str,))
        conn.commit()
    except sqlite3.Error as e:
        typer.echo(f"Datumbazo eraro: {e}", err=True)
        raise typer.Exit(code=1) from e
    finally:
        conn.close()

    short_uuid = uuid_str[:8]
    typer.echo(f"✓ Manlibro forigita: {titolo} #{short_uuid}")


@app.command("serci")
def serci(
    demando: str | None = typer.Argument(
        None,
        help=(
            "Serĉ-termo.\n"
            "Ekzemplo: doc serci fiziko"
        ),
    ),
    teksto: bool = typer.Option(
        False,
        "-t",
        "--teksto",
        help="Serĉi en tuta enhavo anstataŭ nur titolo.",
    ),
    encik: bool = typer.Option(
        False,
        "-e",
        "--encik",
        help="Serĉi nur por manlibro ligitaj al encik-nodo.",
    ),
) -> None:
    """Serĉi manualajn nodojn."""
    if not demando:
        typer.echo(
            "Mankas serĉ-termo.\n"
            "Ekzemplo: doc serci fiziko",
            err=True,
        )
        raise typer.Exit(code=2)

    _ensure_db()
    conn = sqlite3.connect(_DB_FILE)
    conn.row_factory = sqlite3.Row

    try:
        # Build base query
        query = "SELECT * FROM man WHERE 1=1"
        params = []

        if encik:
            query += " AND encik_uuid IS NOT NULL"

        query += " ORDER BY titolo"

        cursor = conn.cursor()
        cursor.execute(query, params)
        all_results = cursor.fetchall()

        # Filter by centralized folded+compact+fuzzy matching
        results = []
        for entry in all_results:
            targets = (
                [entry["titolo"], entry["enhavo"]]
                if teksto
                else [entry["titolo"]]
            )
            score = best_text_match_score(demando, targets, threshold=0.5)
            if score is not None:
                results.append((score, entry))

        if not results:
            typer.echo("Neniuj rezultoj trovitaj.")
            raise typer.Exit(code=0)

        # Sort by relevance score (highest first)
        results.sort(key=lambda x: x[0], reverse=True)
        sorted_entries = [entry for _, entry in results]

        # Display results
        console.print(f"\n[bold cyan]Trovoj ({len(sorted_entries)}):[/]\n")

        for entry in sorted_entries:
            short_uuid = str(entry["uuid"])[:8]
            encik_marker = " [dim]→ encik[/]" if entry["encik_uuid"] else ""
            console.print(
                f"  [{entry['titolo']}] #{short_uuid}{encik_marker}"
            )

        # Interactive selection
        if len(sorted_entries) == 1:
            choice = "1"
        else:
            console.print("")
            num_entries = len(sorted_entries)
            choice = typer.prompt(
                f"Elektu (1-{num_entries}) aŭ <Enteri> por eliri"
            )

        if choice.strip():
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(sorted_entries):
                    vidi(str(sorted_entries[idx]["uuid"])[:8])
            except (ValueError, IndexError):
                pass

    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _get_editor() -> str | None:
    """Get editor from environment or defaults."""
    import os
    return os.environ.get("EDITOR") or os.environ.get("VISUAL")


# ──────────────────────────────────────────────────────────────────────────────
# Public helper for encik integration
# ──────────────────────────────────────────────────────────────────────────────


def get_manuals_for_encik(encik_uuid: str) -> list[dict[str, str]]:
    """Get all man entries linked to a specific encik UUID.
    
    Used by encik.py to display linked manuals in the manlibro(j) section.
    Returns list of dicts with 'uuid', 'titolo' keys.
    """
    if not _DB_FILE.exists():
        return []
    
    try:
        conn = sqlite3.connect(_DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            """SELECT uuid, titolo FROM man WHERE encik_uuid = ? ORDER BY titolo""",
            (encik_uuid,),
        )
        rows = cursor.fetchall()
        conn.close()
        return [{"uuid": row["uuid"], "titolo": row["titolo"]} for row in rows]
    except (sqlite3.Error, TypeError):
        return []


if __name__ == "__main__":
    app()
