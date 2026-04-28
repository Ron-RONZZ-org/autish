# AGENTS-etikedo.md — etikedo Command Agent Instructions

## Summary
Shared label management for todo and taglibro microapps.

## Purpose and Expected Behavior
- List all labels: `listigi` (or invoke without subcommand).
- Add new label: `aldoni`.
- Modify label text: `modifi`.
- Delete label: `forigi` (with confirmation).
- Labels are shared between `todo` and `taglibro` via many-to-many junction tables.

## Constraints and Invariants
- SQLite database shared with `todo` and `taglibro` via `_tasklib.connect()`.
- Labels stored in `etikedo` table (uuid, teksto, other metadata).
- Junction tables: `todo_etikedo`, `taglibro_etikedo`.
- Uses `_tasklib.list_etikedoj()` for loading; `_tasklib.connect()` for writes.
- Markdown link rendering in label text via `_tasklib.normalize_markdown_links()`.

## Input/Output Expectations
- Subcommands: `listigi` (default), `aldoni`, `modifi`, `forigi`
- Key CLI Options:
  - `aldoni`: `--teksto` (label text, required)
  - `modifi`: `<uuid>` (label UUID, required), `--teksto` (new text)
  - `forigi`: `<uuid>` (label UUID, required)
  - `-L`/`--limo`: result limit for listigi
- Output: Rich tables with UUID, text; Markdown rendering for label text
- Side Effects: SQLite writes to etikedo table and junction tables

## Documentation Reference
- `docs/man/etikedo.md`

## Domain-Specific Rules for Agents
- Always use `_tasklib.connect()` context manager for DB access.
- Label reference resolution: use `_find_exact()` for UUID/text lookup.
- Deletion check: ensure label not in use, or handle cascade deletion gracefully.
- Markdown links in labels: use `_render_label_text()` → `_tasklib` helpers.
- When modifying schema, update in `_tasklib.init_db()` with migration logic.
- Labels are global: changes affect both `todo` and `taglibro` commands.
- Validation: check for duplicate label text before adding new labels.
