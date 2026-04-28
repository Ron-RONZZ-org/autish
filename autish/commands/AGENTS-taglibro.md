# AGENTS-taglibro.md — taglibro Command Agent Instructions

## Summary
Diary-style entries with Markdown support and label (etikedo) assignments.

## Purpose and Expected Behavior
- CRUD operations: `aldoni`, `vidi`, `modifi`, `forigi`, `serci`.
- Diary entries with timestamp (`tempo` field, defaults to now).
- Markdown support in entry text.
- Label assignments: entries can have multiple `etikedo` labels (many-to-many via `taglibro_etikedo` table).
- Date-based filtering and search.

## Constraints and Invariants
- SQLite database shared with `todo` and `etikedo` via `_tasklib.connect()`.
- Labels stored in `etikedo` table; assignment via `taglibro_etikedo` junction table.
- Entry timestamp (`tempo`) stored as ISO 8601; defaults to `datetime.now(timezone.utc)`.
- Uses `_tasklib` helpers for DB connection, markdown link normalization, and rendering.
- Label blob format: `uuid:text|uuid:text` (parsed via `_parse_label_blob()`).

## Input/Output Expectations
- Subcommands: `aldoni`, `vidi`, `modifi`, `forigi`, `serci`
- Key CLI Options:
  - `--teksto`: diary entry text (supports Markdown)
  - `--tempo`: entry timestamp (ISO 8601, default: now)
  - `--etikedoj`: label UUIDs (comma-separated)
  - `-L`/`--limo`: result limit
- Output: Rich tables with timestamps, Markdown rendering for text
- Side Effects: SQLite writes, label assignments

## Documentation Reference
- `docs/man/taglibro.md`

## Domain-Specific Rules for Agents
- Always use `_tasklib.connect()` context manager for DB access (sets row_factory=sqlite3.Row, WAL mode).
- Label blob parsing: use `_parse_label_blob()` helper; format is `uuid:text|uuid:text`.
- Markdown links in text: use `_render_text()` → `_tasklib.normalize_markdown_links()` → `_tasklib.render_markdown_links_plain()`.
- Search: SQL WHERE with `LIKE` on teksto; use indexed columns where possible.
- When adding new fields, update schema in `_tasklib.init_db()` with migration logic.
- Date filtering: use `date()` function in SQL for date-based queries.
