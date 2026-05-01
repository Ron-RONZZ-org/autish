"""verki kunteksto — AI context file management for repeated work.

Manage reusable AI contexts (prompts, instructions, examples) that can be
attached to verki generi calls and referenced across sessions.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import tempfile
import uuid as _uuid_mod
from pathlib import Path

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

from autish.utils import (
    confirm_esperante,
    markdown_to_html,
    now_iso,
    parse_markdown_links,
    score_text_match,
)

app = typer.Typer(
    name="kunteksto",
    help="Kunteksto — administri AI-kuntekstojn por ripetata verko.",
    no_args_is_help=True,
)

_DB_PATH = Path.home() / ".local" / "share" / "autish" / "verki_kunteksto.db"


# ============================================================================
# Database setup and management
# ============================================================================


def _get_db() -> sqlite3.Connection:
    """Get or create database connection."""
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    _init_db(conn)
    return conn


def _init_db(conn: sqlite3.Connection) -> None:
    """Initialize database schema if needed."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS kunteksto (
            uuid          TEXT PRIMARY KEY,
            titolo        TEXT NOT NULL,
            enhavo        TEXT NOT NULL,
            linked_uuids  TEXT,
            kreita_je     TEXT NOT NULL,
            modifita_je   TEXT NOT NULL
        )
    """)
    # Create index on titolo for faster searches
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_kunteksto_titolo
        ON kunteksto(titolo)
    """)
    conn.commit()


# ============================================================================
# Helper functions
# ============================================================================


def _find_by_uuid(uuid_str: str) -> dict | None:
    """Find context entry by UUID (supports partial UUIDs)."""
    conn = _get_db()
    clean_uuid = str(uuid_str or "").strip()
    
    # Try exact match first
    row = conn.execute(
        "SELECT * FROM kunteksto WHERE uuid = ?", (clean_uuid,)
    ).fetchone()
    
    # If not found and clean_uuid is a partial UUID, try prefix match
    if not row and len(clean_uuid) >= 8:
        row = conn.execute(
            "SELECT * FROM kunteksto WHERE uuid LIKE ?",
            (f"{clean_uuid}%",),
        ).fetchone()
    
    # If still not found, try exact title match
    if not row:
        row = conn.execute(
            "SELECT * FROM kunteksto WHERE titolo = ?", (clean_uuid,)
        ).fetchone()
    
    conn.close()
    return dict(row) if row else None


def _find_by_title_exact(title: str) -> dict | None:
    """Find context entry by exact title match."""
    conn = _get_db()
    row = conn.execute(
        "SELECT * FROM kunteksto WHERE titolo = ?", (title,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def _extract_title_from_md(content: str) -> str:
    """Extract title from markdown (first H1 or first line)."""
    lines = content.strip().split("\n")
    for line in lines:
        if line.startswith("# "):
            return line[2:].strip()
    # Fallback to first line if no H1
    return lines[0].strip() if lines else "Sense-titolo"


def _insert_entry(entry: dict) -> None:
    """Insert a new context entry into the database."""
    conn = _get_db()
    conn.execute(
        """
        INSERT INTO kunteksto
        (uuid, titolo, enhavo, linked_uuids, kreita_je, modifita_je)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            entry["uuid"],
            entry["titolo"],
            entry["enhavo"],
            entry.get("linked_uuids") or "",
            entry["kreita_je"],
            entry["modifita_je"],
        ),
    )
    conn.commit()
    conn.close()


def _update_entry(entry: dict) -> None:
    """Update an existing context entry."""
    conn = _get_db()
    conn.execute(
        """
        UPDATE kunteksto
        SET titolo = ?, enhavo = ?, linked_uuids = ?, modifita_je = ?
        WHERE uuid = ?
        """,
        (
            entry["titolo"],
            entry["enhavo"],
            entry.get("linked_uuids") or "",
            entry["modifita_je"],
            entry["uuid"],
        ),
    )
    conn.commit()
    conn.close()


def _delete_entry(uuid_str: str) -> None:
    """Delete a context entry."""
    conn = _get_db()
    conn.execute("DELETE FROM kunteksto WHERE uuid = ?", (uuid_str,))
    conn.commit()
    conn.close()


def _load_all() -> list[dict]:
    """Load all context entries."""
    conn = _get_db()
    rows = conn.execute(
        "SELECT * FROM kunteksto ORDER BY modifita_je DESC"
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def _display_in_pager(entry: dict) -> None:
    """Display entry in less pager with markdown rendering."""
    console = Console(force_terminal=True)
    md = Markdown(entry["enhavo"])

    # Use less -R to handle ANSI colors
    try:
        pager_cmd = ["less", "-R", "-K"]  # -K: quit on CTRL-C
        process = subprocess.Popen(
            pager_cmd,
            stdin=subprocess.PIPE,
        )
        # Render markdown with Rich then convert to string
        from io import StringIO
        buffer = StringIO()
        console_str = Console(file=buffer, force_terminal=True)
        console_str.print(md)
        rendered_text = buffer.getvalue()
        process.communicate(input=rendered_text.encode())
    except FileNotFoundError:
        typer.echo("Eraro: 'less' pagilo ne trovita", err=True)
        # Fallback: print to console
        console.print(md)


# ============================================================================
# Subcommands
# ============================================================================


@app.command("aldoni")
def aldoni(
    dosiero: Path = typer.Argument(
        ...,
        help="Markdown-dosiero por aldoni (.md).",
        exists=True,
    ),
    titolo: str | None = typer.Option(
        None,
        "-t",
        "--titolo",
        help="Propra titolo (defaŭlte: unua H1 aŭ unua linio).",
    ),
) -> None:
    """Aldoni novan AI-kuntekston el Markdown-dosiero."""
    try:
        content = dosiero.read_text(encoding="utf-8")
    except OSError as exc:
        typer.echo(f"[!] Ne povis legi dosieron: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    # Extract or use provided title
    extracted_title = _extract_title_from_md(content)
    final_title = titolo if titolo else extracted_title

    # Check for duplicates
    if _find_by_title_exact(final_title):
        typer.echo(
            f'[!] Kunteksto kun titolo "{final_title}" jam ekzistas.',
            err=True,
        )
        raise typer.Exit(code=1)

    # Extract linked UUIDs from markdown links
    links = parse_markdown_links(content)
    linked_uuids = ",".join([link.uuid for link in links]) if links else ""

    # Create entry
    now = now_iso()
    entry = {
        "uuid": str(_uuid_mod.uuid4()),
        "titolo": final_title,
        "enhavo": content,
        "linked_uuids": linked_uuids,
        "kreita_je": now,
        "modifita_je": now,
    }

    _insert_entry(entry)
    typer.echo(f'[✓] Aldonis kuntekston: #{entry["uuid"][:8]} "{final_title}"')


@app.command("vidi")
def vidi(
    uuid_str: str = typer.Argument(
        ...,
        help="UUID de la kunteksto.",
    ),
    html: bool = typer.Option(
        False,
        "--html",
        "-h",
        help="Malfermi en retumilo (HTML-a verkeisto).",
    ),
) -> None:
    """Rigardi kuntekston."""
    entry = _find_by_uuid(uuid_str)
    if not entry:
        typer.echo(f"[!] Kunteksto ne trovita: {uuid_str}", err=True)
        raise typer.Exit(code=1)

    if html:
        html_doc = markdown_to_html(entry["enhavo"], title=entry["titolo"])
        from autish.utils import open_html_in_browser as open_html

        out_path = open_html(html_doc)
        typer.echo(f"[i] Malfermas en retumilo: {out_path}")
    else:
        # Display in less pager (default behavior)
        _display_in_pager(entry)


@app.command("modifi")
def modifi(
    uuid_str: str = typer.Argument(
        ...,
        help="UUID de la kunteksto por ĝisdatigi.",
    ),
) -> None:
    """Modifi kuntekston en $EDITOR."""
    entry = _find_by_uuid(uuid_str)
    if not entry:
        typer.echo(f"[!] Kunteksto ne trovita: {uuid_str}", err=True)
        raise typer.Exit(code=1)

    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".md",
        delete=False,
        encoding="utf-8",
    ) as tmp:
        tmp.write(entry["enhavo"])
        tmp_path = tmp.name

    try:
        editor = os.environ.get("EDITOR", "nano")
        result = subprocess.run([editor, tmp_path], check=False, timeout=30)
        if result.returncode != 0:
            typer.echo("[i] Ĝisdatigo nuligita.", err=True)
            raise typer.Exit(code=0)

        updated_content = Path(tmp_path).read_text(encoding="utf-8")
        if updated_content == entry["enhavo"]:
            typer.echo("[i] Neniuj ŝanĝoj faritaj.")
            raise typer.Exit(code=0)

        # Update entry
        entry["enhavo"] = updated_content
        entry["modifita_je"] = now_iso()

        # Re-extract links
        links = parse_markdown_links(updated_content)
        entry["linked_uuids"] = (
            ",".join([link.uuid for link in links]) if links else ""
        )

        _update_entry(entry)
        typer.echo(f'[✓] Ĝisdatigis kuntekston: #{entry["uuid"][:8]}')
    finally:
        Path(tmp_path).unlink(missing_ok=True)


@app.command("forigi")
def forigi(
    uuid_str: str = typer.Argument(
        ...,
        help="UUID de la kunteksto por forigi.",
    ),
) -> None:
    """Forigi kuntekston."""
    entry = _find_by_uuid(uuid_str)
    if not entry:
        typer.echo(f"[!] Kunteksto ne trovita: {uuid_str}", err=True)
        raise typer.Exit(code=1)

    # Confirm deletion
    if not confirm_esperante(
        f'Ĉu forigi "{entry["titolo"]}"?',
        default_yes=False,
    ):
        typer.echo("[i] Nuligita.")
        raise typer.Exit(code=0)

    _delete_entry(uuid_str)
    typer.echo(f'[✓] Forigis kuntekston: {entry["uuid"][:8]}')


@app.command("serci")
def serci(
    demando: str | None = typer.Argument(
        None,
        help="Serĉ-termo (fuzzy-aran kontraŭ titolo kaj enhavo).",
    ),
    ligilo: str | None = typer.Option(
        None,
        "-L",
        "--ligilo",
        help="Serĉi enirojn ligitajn al UUID (ec#... aŭ vt#...).",
    ),
) -> None:
    """Serĉi en kuntekstoj."""
    all_entries = _load_all()

    if not all_entries:
        typer.echo("[i] Neniuj kuntekstoj trovitaj.")
        raise typer.Exit(code=0)

    # Filter by linked UUID if provided
    if ligilo:
        all_entries = [
            e for e in all_entries if ligilo in (e.get("linked_uuids") or "")
        ]

    # Fuzzy filter by search term
    if demando:
        scored = []
        for entry in all_entries:
            title_score = score_text_match(demando, entry["titolo"]) or 0
            content_score = score_text_match(demando, entry["enhavo"]) or 0
            max_score = max(title_score, content_score)
            if max_score > 0:
                scored.append((entry, max_score))
        # Sort by score descending
        scored.sort(key=lambda x: x[1], reverse=True)
        all_entries = [e for e, _ in scored]

    if not all_entries:
        typer.echo("[i] Neniuj kongruaj kuntekstoj.")
        raise typer.Exit(code=0)

    # Display results
    table = Table(title="Serĉ-rezultoj")
    table.add_column("UUID", style="cyan")
    table.add_column("Titolo", style="magenta")
    table.add_column("Ĝisdatigita", style="green")

    for entry in all_entries:
        uid_short = entry["uuid"][:8]
        modifita = entry["modifita_je"][:10] if entry["modifita_je"] else ""
        table.add_row(uid_short, entry["titolo"][:50], modifita)

    console = Console()
    console.print(table)

    # Allow user to select one
    if len(all_entries) > 1:
        typer.echo(
            "\nUzu 'verki kunteksto vidi <UUID>' por vidi detale.",
        )
