"""md — Markdown utilities: view in browser, export, and import.

Usage:
    md vidi {path/url}            — render markdown in the default browser
    md eksporti {src} {dst}       — export markdown as HTML or PDF
    md importi {src} {dst}        — convert a document to Markdown
"""

from __future__ import annotations

import subprocess
import tempfile
import webbrowser
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import typer
from rich.console import Console

# ──────────────────────────────────────────────────────────────────────────────
# Typer app
# ──────────────────────────────────────────────────────────────────────────────

app = typer.Typer(
    name="md",
    help="Markdown utilities: view in browser, export, and import.",
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help", "--helpo"]},
)

console = Console()

# ──────────────────────────────────────────────────────────────────────────────
# Supported import formats and pandoc format map
# ──────────────────────────────────────────────────────────────────────────────

_IMPORT_FORMATS: frozenset[str] = frozenset(
    {"xml", "pdf", "docx", "html", "odt", "tex"}
)

# Map file extension → pandoc reader name
_PANDOC_FORMAT: dict[str, str] = {
    "xml": "docbook",
    "pdf": "pdf",
    "docx": "docx",
    "html": "html",
    "odt": "odt",
    "tex": "latex",
}

# KaTeX CDN version — pinned for reproducibility
_KATEX_VERSION = "0.16.11"

# ──────────────────────────────────────────────────────────────────────────────
# HTML template
# ──────────────────────────────────────────────────────────────────────────────

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<link rel="stylesheet"
  href="https://cdn.jsdelivr.net/npm/katex@{katex_version}/dist/katex.min.css">
<script defer
  src="https://cdn.jsdelivr.net/npm/katex@{katex_version}/dist/katex.min.js">
</script>
<script defer
  src="https://cdn.jsdelivr.net/npm/katex@{katex_version}/dist/contrib/auto-render.min.js"
  onload="renderMathInElement(document.body, {{
    delimiters: [
      {{left: '$$', right: '$$', display: true}},
      {{left: '$', right: '$', display: false}},
      {{left: '\\\\[', right: '\\\\]', display: true}},
      {{left: '\\\\(', right: '\\\\)', display: false}}
    ]
  }});">
</script>
<style>
  body {{
    font-family: system-ui, -apple-system, sans-serif;
    max-width: 860px;
    margin: 2rem auto;
    padding: 0 1.2rem;
    line-height: 1.65;
    color: #333;
  }}
  details {{ margin-bottom: 0.4rem; }}
  summary {{
    cursor: pointer;
    list-style: none;
    padding: 0.15rem 0;
  }}
  summary::-webkit-details-marker {{ display: none; }}
  summary::before {{
    content: '▶\\00a0';
    font-size: 0.7em;
    vertical-align: middle;
    color: #888;
    transition: transform 0.15s;
    display: inline-block;
  }}
  details[open] > summary::before {{ transform: rotate(90deg); }}
  pre {{
    background: #f6f6f6;
    padding: 1rem;
    overflow-x: auto;
    border-radius: 4px;
  }}
  code {{ font-family: monospace; font-size: 0.92em; }}
  blockquote {{
    border-left: 3px solid #ccc;
    margin-left: 0;
    padding-left: 1rem;
    color: #666;
  }}
  table {{ border-collapse: collapse; width: 100%; margin-bottom: 1rem; }}
  th, td {{ border: 1px solid #ddd; padding: 0.4rem 0.75rem; text-align: left; }}
  th {{ background: #f0f0f0; }}
  .fold-notice {{
    color: #888;
    font-size: 0.82rem;
    margin-bottom: 1rem;
    font-style: italic;
  }}
</style>
</head>
<body>
{fold_notice}
{content}
<script>
(function () {{
  var foldLevel = {fold_level};

  function makeCollapsible(heading) {{
    var level = parseInt(heading.tagName.substring(1), 10);
    var siblings = [];
    var next = heading.nextElementSibling;
    while (next && !next.matches('h1,h2,h3,h4,h5,h6')) {{
      siblings.push(next);
      next = next.nextElementSibling;
    }}
    if (siblings.length === 0) return;

    var details = document.createElement('details');
    var shouldOpen = foldLevel === 0 || level < foldLevel;
    details.open = shouldOpen;

    var summary = document.createElement('summary');
    summary.innerHTML = heading.innerHTML;
    details.appendChild(summary);
    siblings.forEach(function (el) {{ details.appendChild(el); }});
    heading.parentNode.replaceChild(details, heading);
  }}

  // Process headings from deepest to shallowest to avoid DOM conflicts
  var headings = Array.from(
    document.querySelectorAll('h1,h2,h3,h4,h5,h6')
  );
  headings.reverse().forEach(makeCollapsible);
}})();
</script>
</body>
</html>
"""


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────


def _read_source(source: str) -> str:
    """Read text from a file path or a http/https URL."""
    if source.startswith(("http://", "https://")):
        try:
            with urlopen(source, timeout=15) as resp:  # noqa: S310
                return resp.read().decode("utf-8", errors="replace")
        except URLError as exc:
            typer.echo(f"Eraro ĉe elŝuto de URL: {exc}", err=True)
            raise typer.Exit(code=1) from exc
    path = Path(source)
    if not path.exists():
        typer.echo(f"Dosiero ne trovita: {source}", err=True)
        raise typer.Exit(code=1)
    return path.read_text(encoding="utf-8")


def _markdown_to_html_body(md_text: str) -> str:
    """Convert markdown text to an HTML fragment (body content only)."""
    try:
        import markdown  # type: ignore[import-untyped]
    except ImportError:
        typer.echo(
            "Eraro: pako 'markdown' ne instalita. Rulu: pip install markdown",
            err=True,
        )
        raise typer.Exit(code=1) from None

    extensions = ["extra", "toc", "tables", "fenced_code", "codehilite"]
    return markdown.markdown(md_text, extensions=extensions)


def _build_html(
    md_text: str,
    title: str = "Markdown",
    fold_level: int = 0,
) -> str:
    """Build a complete standalone HTML document from markdown text."""
    body_html = _markdown_to_html_body(md_text)
    fold_notice = ""
    if fold_level > 0:
        fold_notice = (
            f'<p class="fold-notice">Faldite ĝis nivelo {fold_level}. '
            f"Alklaku titolojn por pligrandigi.</p>"
        )
    return _HTML_TEMPLATE.format(
        title=title,
        katex_version=_KATEX_VERSION,
        fold_level=fold_level,
        fold_notice=fold_notice,
        content=body_html,
    )


def _source_title(source: str) -> str:
    """Derive a display title from a source path or URL."""
    if source.startswith(("http://", "https://")):
        return "Markdown"
    return Path(source).stem


def _check_pandoc() -> None:
    """Raise typer.Exit if pandoc is not installed."""
    try:
        subprocess.run(
            ["pandoc", "--version"],
            capture_output=True,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        typer.echo(
            "Eraro: 'pandoc' ne instalita. Instalu per: sudo apt install pandoc",
            err=True,
        )
        raise typer.Exit(code=1) from None


# ──────────────────────────────────────────────────────────────────────────────
# Subcommands
# ──────────────────────────────────────────────────────────────────────────────


@app.command("vidi")
def vidi(
    source: str = typer.Argument(..., help="Path or URL to the Markdown file."),
    faldnivelo: int = typer.Option(
        0,
        "-f",
        "--faldnivelo",
        help=(
            "Fold (collapse) headings at this level and deeper on initial render. "
            "0 = all expanded (default)."
        ),
    ),
) -> None:
    """Render a Markdown file in the default browser.

    Supports KaTeX math ($…$ and $$…$$) and collapsible heading sections.
    """
    md_text = _read_source(source)
    title = _source_title(source)
    html = _build_html(md_text, title=title, fold_level=faldnivelo)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".html", delete=False, encoding="utf-8"
    ) as fh:
        fh.write(html)
        tmp_path = fh.name

    typer.echo(f"Malfermas en retumilo: {tmp_path}")
    webbrowser.open(f"file://{tmp_path}")


@app.command("eksporti")
def eksporti(
    source: str = typer.Argument(..., help="Path or URL to the source Markdown file."),
    destination: str = typer.Argument(..., help="Destination file path."),
    formato: str = typer.Option(
        "html",
        "-f",
        "--formato",
        help="Output format: html (default) or pdf.",
    ),
) -> None:
    """Export a Markdown file as HTML or PDF."""
    fmt = formato.lower().strip()
    if fmt not in ("html", "pdf"):
        typer.echo(
            f"Eraro: nesubtenata formato '{formato}'. Uzu 'html' aŭ 'pdf'.",
            err=True,
        )
        raise typer.Exit(code=1)

    md_text = _read_source(source)
    title = _source_title(source)
    html = _build_html(md_text, title=title, fold_level=0)

    dest = Path(destination)
    dest.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "html":
        dest.write_text(html, encoding="utf-8")
        typer.echo(f"Eksportis al: {destination}")
        return

    # PDF export — requires weasyprint >= 68.0
    try:
        import weasyprint  # type: ignore[import-untyped]
    except ImportError:
        typer.echo(
            "Eraro: pako 'weasyprint' ne instalita. "
            "Rulu: pip install 'weasyprint>=68.0'",
            err=True,
        )
        raise typer.Exit(code=1) from None

    try:
        weasyprint.HTML(string=html, base_url=str(dest.parent)).write_pdf(str(dest))
    except (OSError, ValueError) as exc:
        typer.echo(f"Eraro dum kreado de PDF: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Eksportis al: {destination}")


@app.command("importi")
def importi(
    source: str = typer.Argument(
        ..., help="Path or URL to the source document (docx/pdf/html/odt/xml/tex)."
    ),
    destination: str = typer.Argument(..., help="Destination .md file path."),
) -> None:
    """Convert a document (docx/pdf/html/odt/xml/tex) to Markdown.

    Requires pandoc to be installed (sudo apt install pandoc).
    """
    is_url = source.startswith(("http://", "https://"))

    if is_url:
        from urllib.parse import urlparse

        url_path = urlparse(source).path
        ext = Path(url_path).suffix.lstrip(".").lower()
    else:
        src_path = Path(source)
        if not src_path.exists():
            typer.echo(f"Dosiero ne trovita: {source}", err=True)
            raise typer.Exit(code=1)
        ext = src_path.suffix.lstrip(".").lower()

    if ext not in _IMPORT_FORMATS:
        typer.echo(
            f"Nesubtenata dosierformato: '.{ext}'. "
            f"Subtenataj: {', '.join(sorted(_IMPORT_FORMATS))}",
            err=True,
        )
        raise typer.Exit(code=1)

    _check_pandoc()

    pandoc_fmt = _PANDOC_FORMAT.get(ext, ext)
    dest = Path(destination)
    dest.parent.mkdir(parents=True, exist_ok=True)

    if is_url:
        # Download to a temporary file first
        raw = _read_source(source)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=f".{ext}", delete=False, encoding="utf-8"
        ) as tf:
            tf.write(raw)
            tmp_src = tf.name
        input_path = tmp_src
    else:
        input_path = str(Path(source))

    cmd = [
        "pandoc",
        "-f", pandoc_fmt,
        "-t", "markdown",
        "-o", str(dest),
        input_path,
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        typer.echo(f"Eraro dum konverto: {exc.stderr}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Importis al: {destination}")
