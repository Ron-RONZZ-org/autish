"""rubo — Linux recycle bin management command."""

from datetime import datetime
from pathlib import Path

import sqlite3
import typer
from rich.console import Console
from rich.table import Table

from autish.services.recycle_bin import RecycleBinDB, TrashItem

app = typer.Typer(
    name="rubo",
    help=(
        "Administri la rikirejon (rubujon) — movo, reparo, "
        "serĉo de forigitaj dosieroj."
    ),
    context_settings={"help_option_names": ["-h", "--help", "--helpo"]},
)
console = Console()


def _format_size(size: int) -> str:
    """Format bytes to human-readable size."""
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"


@app.command(
    "forigi",
    help="forigi|rm Movi dosierojn al rikirejon (recycle bin).",
)
def delete_files(
    paths: list[str] = typer.Argument(
        ...,
        help="Dosieroj aŭ dosierujo por foriĝi al rikirejon"
    ),
    definitive: bool = typer.Option(
        False,
        "-d",
        "--definitive",
        help="Foriĝi ĉapele, sen stokado en rikirejon"
    ),
) -> None:
    """Movi dosierojn al rikirejon (recycle bin).
    
    Alias: rubo rm
    """
    if not paths:
        typer.echo("[!] Bonvolu specifu dosierojn.", err=True)
        raise typer.Exit(1)
    
    db = RecycleBinDB()
    
    for path_str in paths:
        path = Path(path_str).expanduser()
        
        if not path.exists():
            typer.echo(f"[!] Ne trovita: {path}", err=True)
            continue
        
        if definitive:
            # Permanent deletion
            import shutil
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                typer.echo(f"[✓] Ĉapele forigita: {path}")
            except OSError as e:
                typer.echo(f"[!] Eraro: {e}", err=True)
        else:
            # Move to trash
            uid = db.move_to_trash(str(path))
            if uid:
                typer.echo(f"[✓] Al rikirejon: {path} (UID: {uid})")
            else:
                typer.echo(f"[!] Eraro movante al rikirejon: {path}", err=True)


@app.command("rm", hidden=True)
def delete_files_alias(
    paths: list[str] = typer.Argument(
        ...,
        help="Dosieroj aŭ dosierujo por foriĝi al rikirejon"
    ),
    definitive: bool = typer.Option(
        False,
        "-d",
        "--definitive",
        help="Foriĝi ĉapele, sen stokado en rikirejon"
    ),
) -> None:
    """Movi dosierojn al rikirejon (recycle bin). Alias por 'rubo forigi'."""
    delete_files(paths, definitive)


@app.command("ls")
def list_trash(
    alfabeto: bool = typer.Option(
        False,
        "-al",
        "--alfabeto",
        help="Ordigi alfabete (nomon)"
    ),
    inversigi: bool = typer.Option(
        False,
        "-i",
        "--inversigi",
        help="Inversa ordo"
    ),
    grandeco: bool = typer.Option(
        False,
        "-g",
        "--grandeco",
        help="Ordigi laŭ grandeco"
    ),
) -> None:
    """Listigi dosierojn en la rikirejon."""
    db = RecycleBinDB()
    items = db.list_items()
    
    # Also check the physical trash directory for any files not in database
    trash_files_dir = db.trash_dir / "files"
    if trash_files_dir.exists():
        # Get files from database (keyed by trash_path)
        db_paths = {item.trash_path for item in items}
        
        # Add any physical files not in database
        for trash_file in trash_files_dir.iterdir():
            if trash_file.name not in db_paths:
                try:
                    size = trash_file.stat().st_size if trash_file.is_file() else 0
                    # Estimate deleted time from file creation time
                    deleted_at = datetime.fromtimestamp(trash_file.stat().st_mtime).isoformat()
                    item = TrashItem(
                        uid=str(len(items) + 1),
                        original_path=trash_file.name,
                        trash_path=str(trash_file),
                        deleted_at=deleted_at,
                        size=size
                    )
                    items.append(item)
                except (OSError, ValueError):
                    continue
    
    if not items:
        typer.echo("[i] La rikirejon estas malplena.")
        return
    
    # Sort
    if alfabeto:
        items.sort(key=lambda x: x.original_path, reverse=inversigi)
    elif grandeco:
        items.sort(key=lambda x: x.size, reverse=inversigi)
    else:
        items.sort(key=lambda x: x.deleted_at, reverse=not inversigi)
    
    # Create table
    table = Table(show_header=True, header_style="bold", border_style="dim")
    table.add_column("UID", style="cyan")
    table.add_column("Nomo (unuaj 50 ĉaroj)", style="green")
    table.add_column("Grandeco", justify="right")
    table.add_column("Forigita (unuaj 19 ĉaroj)", style="dim")
    
    for item in items:
        name = Path(item.original_path).name
        if len(name) > 50:
            name = name[:47] + "..."
        
        deleted = item.deleted_at[:19]
        
        table.add_row(
            item.uid,
            name,
            _format_size(item.size),
            deleted
        )
    
    console.print(table)


@app.command("serci")
def search_trash(
    keyword: str = typer.Argument(..., help="Serĉtermo aŭ ĝeneralo (wildcard: *)"),
    regex: bool = typer.Option(
        False,
        "-R",
        "--regex",
        help="Uzi POSIX-n eraron"
    ),
) -> None:
    r"""Serĉi en la rikirejon.
    
    Examples:
        rubo serci foto      # Serĉi 'foto'
        rubo serci *.txt     # Serĉi .txt dosierojn
        rubo serci -R '.*\.pdf$'  # Regex serĉo
    """
    db = RecycleBinDB()
    
    try:
        items = db.search_items(keyword, use_regex=regex)
    except (sqlite3.Error, ValueError) as e:
        typer.echo(f"[!] Eraro en serĉo: {e}", err=True)
        raise typer.Exit(1) from None
    
    if not items:
        typer.echo(f"[i] Neniuj rezultoj por '{keyword}'")
        return
    
    # Create table
    table = Table(show_header=True, header_style="bold", border_style="dim")
    table.add_column("UID", style="cyan")
    table.add_column("Dosiero (unuaj 50 ĉaroj)", style="green")
    table.add_column("Grandeco", justify="right")
    table.add_column("Forigita (unuaj 19 ĉaroj)", style="dim")
    
    for item in items:
        name = Path(item.original_path).name
        if len(name) > 50:
            name = name[:47] + "..."
        
        deleted = item.deleted_at[:19]
        
        table.add_row(
            item.uid,
            name,
            _format_size(item.size),
            deleted
        )
    
    console.print(table)
    typer.echo(f"\n[i] {len(items)} rezultoj trovitaj")


@app.command("restarigi")
def restore_files(
    uids: list[str] = typer.Argument(
        ...,
        help="UID(oj) de dosieroj por restarigo"
    ),
    celo: str | None = typer.Option(
        None,
        "-c",
        "--celo",
        help="Cela vojo por restarigo (se malsama ol originala)"
    ),
) -> None:
    """Restarigi dosierojn el la rikirejon.
    
    Alias: rubo rs
    """
    if not uids:
        typer.echo("[!] Bonvolu specifu UID(ojn).", err=True)
        raise typer.Exit(1)
    
    db = RecycleBinDB()
    
    for uid in uids:
        item = db.get_item(uid)
        if not item:
            typer.echo(f"[!] UID ne trovita: {uid}", err=True)
            continue
        
        success = db.restore_item(uid, celo)
        if success:
            dest = celo or item.original_path
            typer.echo(f"[✓] Restarigita: {dest}")
        else:
            typer.echo(f"[!] Eraro restarigante UID {uid}", err=True)


@app.command("rs")
def restore_files_alias(
    uids: list[str] = typer.Argument(
        ...,
        help="UID(oj) de dosieroj por restarigo"
    ),
    celo: str | None = typer.Option(
        None,
        "-c",
        "--celo",
        help="Cela vojo por restarigo (se malsama ol originala)"
    ),
) -> None:
    """Restarigi dosierojn el la rikirejon. Alias por 'rubo restarigi'."""
    restore_files(uids, celo)


@app.command("forigi-cxape")
def delete_permanent(
    uids: list[str] = typer.Argument(
        ...,
        help="UID(oj) de dosieroj por ĉapela forigado"
    ),
) -> None:
    """Ĉapele foriĝi dosierojn el la rikirejon."""
    if not uids:
        typer.echo("[!] Bonvolu specifu UID(ojn).", err=True)
        raise typer.Exit(1)
    
    db = RecycleBinDB()
    
    for uid in uids:
        success = db.delete_item(uid)
        if success:
            typer.echo(f"[✓] Ĉapele forigita: UID {uid}")
        else:
            typer.echo(f"[!] UID ne trovita: {uid}", err=True)
