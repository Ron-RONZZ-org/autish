# AGENTS-md.md — md Command Agent Instructions

## Summary
Markdown utilities: render in browser, export to HTML/PDF, import from other formats.

## Purpose and Expected Behavior
- View Markdown: `vidi` (render as HTML and open in browser).
- Export: `eksporti` (Markdown → HTML or PDF).
- Import: `importi` (other formats → Markdown via pandoc).
- Supports URLs and local files for `vidi`.

## Constraints and Invariants
- HTML export: uses `autish.utils.markdown_to_html()` (markdown library) + `weasyprint` for PDF.
- Import requires `pandoc` (external tool); supported formats: xml, pdf, docx, html, odt, tex.
- Browser rendering: `autish.utils.open_html_in_browser()`.
- Output: HTML files or PDF files; browser opens for `vidi`.

## Input/Output Expectations
- Subcommands: `vidi`, `eksporti`, `importi`
- Key CLI Options:
  - `vidi`: `<path/url>` (Markdown file or URL, required)
  - `eksporti`: `<src>` (Markdown file, required), `<dst>` (output path, required)
  - `importi`: `<src>` (source file, required), `<dst>` (output .md path, required)
- Output: HTML/PDF files, browser window for viewing
- Side Effects: File writes, browser spawn, pandoc subprocess calls

## Documentation Reference
- `docs/man/md.md`

## Domain-Specific Rules for Agents
- Always use `open_html_in_browser()` for browser rendering; do not call browser directly.
- Export format detection: check `-EXPORT_FORMAT_FROM_SUFFIX` dict (`.html`→html, `.pdf`→pdf).
- Import format detection: check `-PANDOC_FORMAT` dict (`.xml`→docbook, `.pdf`→pdf, etc.).
- Validate import format against `_IMPORT_FORMATS` frozenset before calling pandoc.
- Fallback: if `weasyprint` unavailable, provide clear error message.
- When adding new export/import formats, update format maps and `_IMPORT_FORMATS`.
- URL handling: use `urllib.request.urlopen()` for fetching remote Markdown; handle `URLError`.
