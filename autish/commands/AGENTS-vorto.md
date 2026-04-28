# AGENTS-vorto.md — vorto Command Agent Instructions

## Summary
Personal wordbook microapp (Mia Vorto) — manage words, phrases, and sentences in a local SQLite database.

## Purpose and Expected Behavior
- Interactive welcome screen when invoked with no args (`invoke_without_command=True`).
- CRUD operations: `aldoni`, `vidi`, `modifi`, `forigi`, `serci`.
- Undo support: `malfari` (last 10 operations, stack-based).
- Export: all entries as JSON, or single entry as TOML.
- Import: JSON import (optionally encrypted via `_crypto`).
- Bidirectional `ligilo` (link) management with other entries.
- Search with fuzzy matching and fold-normalized text for case-insensitive matching.

## Constraints and Invariants
- SQLite database at `~/.local/share/autish/vorto.db` (WAL mode).
- Undo stack (max 10) stored in same database (`undo_vorto` table).
- Shared `encik.db` reference for cross-linking with encik entries.
- Uses `autish.i18n.tr()` for multilingual help text (eo/en/fr).
- Search performance: normalized `teksto_search` column with index; SQL WHERE before Python filtering.
- Maximum 10k+ entries target: <100ms aldoni operations.

## Input/Output Expectations
- Subcommands: `aldoni`, `vidi`, `modifi`, `forigi`, `serci`, `malfari`, `eksporti`, `importi`, `rubujo`
- Key CLI Options:
  - `--lingvo`/`-l`: language code (normalized to 2-3 chars)
  - `--kategorio`: category filter
  - `--limo`/`-lo`: result limit
  - `-L`/`--ligilo`: link to another entry (bidirectional)
- Output: Rich tables, Markdown-rendered definitions, TOML/JSON export
- Side Effects: SQLite writes, undo stack updates, TOML/JSON file exports

## Documentation Reference
- `docs/man/vorto.md`

## Domain-Specific Rules for Agents
- Always use `fold_search_text()` for search normalization; store in `teksto_search` column.
- `ligilo` relations MUST be bidirectional: when adding A→B, also add B→A.
- Undo operations use `undo_vorto` table; respect `_MAX_UNDO = 10` limit.
- When modifying schema, add migration in `_init_db()`; check `PRAGMA user_version`.
- Use `_tasklib.connect()` pattern for DB connections (context manager with row_factory=sqlite3.Row).
- Fuzzy matching via `difflib.SequenceMatcher` or `best_text_match_score()`.
- Rich output: use `Console()`, `Table`, `Panel`, `Markdown` from rich library.
