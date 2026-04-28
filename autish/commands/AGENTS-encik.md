# AGENTS-encik.md — encik Command Agent Instructions

## Summary
Personal knowledge management microapp — semantic knowledge nodes with Wikidata integration.

## Purpose and Expected Behavior
- Interactive welcome screen when invoked with no args.
- CRUD operations: `aldoni` (from .enc files), `vidi`, `modifi`, `eksporti`.
- Semantic search: `semantika-serci` with typed value conditions.
- Recursive class search: `-s/--subklasoj`, `-S/--superklasoj`, `-P/--paralela`.
- Settings management: `agordi` (display settings in `~/.config/autish/encik.toml`).
- Wikidata integration for online metadata (respects user `lingvoj` preference order, falls back eo→en).
- Integration with `doc` command: display linked manuals via `get_manuals_for_encik()`.

## Constraints and Invariants
- SQLite database at `~/.local/share/autish/encik.db` (WAL mode).
- Shared `vorto.db` reference for cross-linking.
- Settings stored in TOML: `~/.config/autish/encik.toml` (uses `tomllib`/`tomli`).
- Wikidata fetches require network; always provide offline fallback.
- AI service integration via `autish.services.ai_common` and `autish.services.verki`.
- Search performance: normalized search columns with indexes; SQL WHERE before Python filtering.

## Input/Output Expectations
- Subcommands: `aldoni`, `vidi`, `modifi`, `eksporti`, `agordi`, `serci`, `semantika-serci`
- Key CLI Options:
  - `-t`/`--teksto`: search full text instead of title
  - `-s`/`--subklasoj`: recursive subclass search
  - `-S`/`--superklasoj`: recursive superclass search
  - `-P`/`--paralela`: sister-class search
  - `-L`/`--limo`: depth limit or max results
  - `-l`/`--lingvo`: language filter
- Output: Rich panels, tables, Markdown rendering, semantic graphs
- Side Effects: SQLite writes, TOML config updates, network requests (Wikidata)

## Documentation Reference
- `docs/man/encik.md`

## Domain-Specific Rules for Agents
- Always use `fold_search_text()`/`fold_search_compact()` for search normalization.
- Wikidata fetches: respect `uzanto profilo lingvoj` order; fallback eo→en.
- Semantic search conditions are typed values; parse with clear error messages.
- `.enc` file format: TOML frontmatter + Markdown body.
- When modifying schema, add migration in `_init_db()`; use `PRAGMA user_version`.
- `$EDITOR` integration for `modifi`: write temp .enc file, open in editor, read back.
- Use `autish.i18n.tr()` for multilingual help text.
