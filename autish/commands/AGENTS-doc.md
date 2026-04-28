# AGENTS-doc.md — doc Command Agent Instructions

## Summary
Documentation management microapp — store and retrieve Markdown manuals with encik integration.

## Purpose and Expected Behavior
- CRUD operations: `aldoni` (from .md files), `vidi`, `modifi`, `forigi`, `serci`.
- Link manuals to encik entries via `-L`/`--ligilo` (bidirectional).
- Markdown rendering with Rich `Markdown` for display.
- Export manual as HTML via `autish.services.markmap` (if available).
- Integration with `encik vidi`: display linked manuals.

## Constraints and Invariants
- SQLite database at `~/.local/share/autish/doc.db` (WAL mode).
- Shared `encik.db` reference for cross-linking with encik entries.
- Ligilo relations stored in `doc_ligiloj` table; bidirectional enforcement required.
- Markdown rendering: `rich.markdown.Markdown` for terminal display.
- HTML export: uses `autish.services.markmap` or `weasyprint` (check availability).
- Search performance: normalized `titolo_search` column with index.

## Input/Output Expectations
- Subcommands: `aldoni`, `vidi`, `modifi`, `forigi`, `serci`
- Key CLI Options:
  - `--titolo`: manual title
  - `--teksto-dosiero`/`-td`: Markdown file path
  - `-L`/`--ligilo`: link to encik entry (UUID or title)
  - `-l`/`--lingvo`: language filter
  - `-L`/`--limo`: result limit (note: `-L` shared with `--ligilo`)
- Output: Rich panels with Markdown rendering, tables for listings
- Side Effects: SQLite writes, HTML file exports, bidirectional ligilo updates

## Documentation Reference
- `docs/man/doc.md` (check if exists, otherwise reference main autish docs)

## Domain-Specific Rules for Agents
- Always use `fold_search_text()` for title search normalization; store in `titolo_search`.
- `ligilo` relations MUST be bidirectional: when adding doc→encik, also add encik→doc.
- Markdown files: read with `Path.read_text(encoding="utf-8")`; handle errors gracefully.
- Modifi: write temp .md file, open in `$EDITOR`, read back changes.
- Check `has_markmap_cli()` before offering HTML export via markmap.
- Use `autish.i18n.tr()` for multilingual help text (eo/en/fr).
- When modifying schema, add migration in `_init_db()`; use `PRAGMA user_version`.
