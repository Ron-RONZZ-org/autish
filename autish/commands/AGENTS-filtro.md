# AGENTS-filtro.md — filtro Subcommand Agent Instructions

## Summary
Email filter management subcommand under `retposto filtro` — configure and test IMAP/email filters.

## Purpose and Expected Behavior
- Configure filters: `agordi` (interactive filter setup).
- Show configured filters: `montri`.
- Test filter against mailbox: `testi`.
- Filters applied during `retposto preni` (fetch mail) operations.
- Rules stored in `retposto.db` SQLite database.

## Constraints and Invariants
- Sub-typer of `retposto` command (registered as `retposto.filtro`).
- Database: `~/.local/share/autish/retposto.db` (shared with retposto).
- Filter rules stored in `retposto_filtro` table (check retposto schema).
- Filter actions may include: move to folder, mark read, delete, forward.
- Applied during IMAP fetch via `preni` subcommand.

## Input/Output Expectations
- Subcommands: `agordi`, `montri`, `testi`
- Key CLI Options:
  - `agordi`: interactive prompt for filter criteria and actions
  - `montri`: list all configured filters
  - `testi`: `[mesagho_id]` (optional, test specific message)
- Output: Rich tables for filter listing, test results
- Side Effects: SQLite writes (filter config), IMAP operations (testi)

## Documentation Reference
- `docs/man/retposto.md` (filtro section)

## Domain-Specific Rules for Agents
- This is a sub-typer of `retposto`; always access via `retposto filtro`.
- Filter criteria: support IMAP SEARCH syntax (FROM, TO, SUBJECT, etc.).
- Filter actions: store as JSON in database; parse with clear error messages.
- Testing: apply filter rules to recent emails; show matches without modifying.
- When modifying schema, coordinate with `retposto` command changes.
- Use `retposto._connect()` pattern for DB access (if exposed) or `sqlite3.connect(retposto._DATA_DIR / "retposto.db")`.
- Integration: filters auto-applied in `preni` command; ensure new filters are picked up.
