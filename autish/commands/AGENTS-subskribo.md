# AGENTS-subskribo.md — subskribo Subcommand Agent Instructions

## Summary
Email signature management subcommand under `retposto subskribo` — create and manage email signatures.

## Purpose and Expected Behavior
- List signatures: `listigi` (or invoke without subcommand).
- Add new signature: `aldoni`.
- Modify existing signature: `modifi`.
- Delete signature: `forigi`.
- Signatures can be assigned to accounts in `retposto aldoni-konton`.
- Stored in `retposto.db` SQLite database.

## Constraints and Invariants
- Sub-typer of `retposto` command (registered as `retposto.subskribo`).
- Database: `~/.local/share/autish/retposto.db` (shared with retposto).
- Signature data stored in `retposto_subskribo` table (check retposto schema).
- Signatures are plain text or HTML; rendered at bottom of sent emails.
- Account assignment: `subskribo_uuid` field in `retposto_konto` table.

## Input/Output Expectations
- Subcommands: `listigi`, `aldoni`, `modifi`, `forigi`
- Key CLI Options:
  - `aldoni`: `--nomo` (signature name, required), `--teksto` (signature text, required), `--defauxlta` (set as default)
  - `modifi`: `<uuid>` (signature UUID, required), `--teksto` (new text)
  - `forigi`: `<uuid>` (signature UUID, required)
  - `-L`/`--limo`: result limit for listigi
- Output: Rich tables for signature listing, status messages
- Side Effects: SQLite writes to retposto.db

## Documentation Reference
- `docs/man/retposto.md` (subskribo section)

## Domain-Specific Rules for Agents
- This is a sub-typer of `retposto`; always access via `retposto subskribo`.
- Signature text: support both plain text and HTML; store as-is.
- Default signature: only one per account; enforce uniqueness if `--defauxlta` set.
- When modifying schema, coordinate with `retposto` command changes.
- Use `retposto._connect()` pattern for DB access (if exposed) or `sqlite3.connect(retposto._DATA_DIR / "retposto.db")`.
- Account linking: ensure `subskribo_uuid` in `retposto_konto` table is valid foreign key.
- Deletion check: if signature in use by account(s), warn user or handle cascade.
