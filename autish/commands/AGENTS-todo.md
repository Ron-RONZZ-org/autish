# AGENTS-todo.md — todo Command Agent Instructions

## Summary
Lightweight task manager with labels (etikedoj) and priority formulas.

## Purpose and Expected Behavior
- Task CRUD: `aldoni`, `vidi`, `modifi`, `forigi`, `serci`.
- Status workflow: `malfermita` (open) → `farita` (done), `prokrastita` (deferred), `nuligita` (cancelled).
- Label assignment: tasks can have multiple `etikedo` labels (many-to-many via `todo_etikedo` table).
- Priority calculation: formula-based (stored as `prioritato` field, computed from formula).
- Markdown link rendering in task text and notes.

## Constraints and Invariants
- SQLite database shared with `taglibro` and `etikedo` via `_tasklib.connect()`.
- Valid statuses: `{"malfermita", "farita", "prokrastita", "nuligita"}` (enforced in `_VALID_STATOJ`).
- Labels stored in `etikedo` table; assignment via `todo_etikedo` junction table.
- Priority formulas parsed via `ast.literal_eval()` for safe evaluation.
- Uses `_tasklib` helpers for DB connection, markdown link normalization, and rendering.

## Input/Output Expectations
- Subcommands: `aldoni`, `vidi`, `modifi`, `forigi`, `serci`
- Key CLI Options:
  - `--teksto`: task text (supports Markdown links)
  - `--stato`: status (valid values: malfermita, farita, prokrastita, nuligita)
  - `--etikedoj`: label UUIDs (comma-separated)
  - `--prioritato`: priority value or formula
  - `-L`/`--limo`: result limit
- Output: Rich tables with priority, status, labels; Markdown rendering for text
- Side Effects: SQLite writes, label assignments

## Documentation Reference
- `docs/man/todo.md`

## Domain-Specific Rules for Agents
- Always use `_tasklib.connect()` context manager for DB access (sets row_factory=sqlite3.Row, WAL mode).
- Label blob parsing: `uuid:text|uuid:text` format; use `_parse_label_blob()` helper.
- Status validation: check against `_VALID_STATOJ` before DB write; show valid values in help.
- Priority formulas: store formula string, compute on display; handle evaluation errors gracefully.
- Markdown links in text: use `_render_text()` → `_tasklib.normalize_markdown_links()` → `_tasklib.render_markdown_links_plain()`.
- When adding new fields, update schema in `_tasklib.init_db()` with migration logic.
