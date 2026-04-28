# AGENTS-kontakto.md — kontakto Command Agent Instructions

## Summary
Standalone contact management command with category support — shared between `retposto` and independent use.

## Purpose and Expected Behavior
- CRUD operations for contacts: `aldoni`, `vidi`, `modifi`, `forigi`, `serci`.
- Category management via `kategorio` sub-typer: `aldoni`, `modifi`, `forigi`, `listigi`.
- Multi-contact field normalization via `uzanto._normalize_multi_contact_list()`.
- Integration with `retposto`: contacts used for email addressing.
- Fuzzy search with fold-normalized text matching.

## Constraints and Invariants
- Uses `retposto.db` SQLite database (shared with retposto command).
- Contact data stored in `retposto_kontakto` table (check retposto schema).
- Category data in `retposto_kategorio` table.
- Max undo: 10 operations (via undo table in same DB).
- Fuzzy matching via `fuzzy_match_ignore_whitespace()` and `best_text_match_score()`.

## Input/Output Expectations
- Subcommands: `aldoni`, `vidi`, `modifi`, `forigi`, `serci`
- `kategorio` subcommands: `aldoni`, `modifi`, `forigi`, `listigi`
- Key CLI Options:
  - `--nomo`: contact name
  - `--retposhto`: email address(es)
  - `--telefono`: phone number(s)
  - `--kategorioj`: category assignments
  - `-l`/`--lingvo`: language filter
  - `-L`/`--limo`: result limit
- Output: Rich tables (wide, 220 width), Markdown link rendering
- Side Effects: SQLite writes to retposto.db

## Documentation Reference
- `docs/man/kontakto.md` (referenced in retposto docs)

## Domain-Specific Rules for Agents
- This command shares DB with `retposto`; do not create separate DB.
- Contact import from VCF is handled in `retposto kontakto importi`, not here.
- Multi-value fields (emails, phones) use `|` separator; normalize via `_normalize_multi_contact_list()`.
- When modifying schema, coordinate with `retposto` command changes.
- Use `_print_wide_table()` helper for consistent table output (220 width).
- Category operations use `kategorio_app` sub-typer registered under `kontakto_app`.
