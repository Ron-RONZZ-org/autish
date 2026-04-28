# AGENTS-retposto.md — retposto Command Agent Instructions

## Summary
TUI email microapp (Retpoŝto) with IMAP/SMTP support, contact management, filtering, and signature management.

## Purpose and Expected Behavior
- Primary TUI interface for email management (interactive mode when invoked with no args).
- Account management: `aldoni-konton`, `forigi-konton`, `listigi-kontojn`.
- Compose & send: `sendi` (CLI compose) or TUI compose.
- Fetch mail: `preni` (from all configured accounts).
- Contact sub-typer: `kontakto` (list, search, view, import/export VCF).
- Filter sub-typer: `filtro` (configure/manage email filters) — see `AGENTS-filtro.md`.
- Signature sub-typer: `subskribo` (manage signatures) — see `AGENTS-subskribo.md`.
- Passwords stored in system keyring (`keyring` library), not in SQLite.

## Constraints and Invariants
- SQLite database at `~/.local/share/autish/retposto.db` (WAL mode).
- Passwords in system keyring: service=`autish-retposto-{account_id}`, key=`password`.
- IMAP/SMTP via stdlib `imaplib`, `smtplib`, `email` package.
- Concurrent mail fetch via `concurrent.futures.ThreadPoolExecutor`.
- VCF import/export via `vobject` library.
- TUI mode is the primary interface; CLI subcommands for automation.

## Input/Output Expectations
- Main subcommands: `aldoni-konton`, `forigi-konton`, `listigi-kontojn`, `sendi`, `preni`
- `kontakto` subcommands: `listigi`, `serci`, `vidi`, `importi`, `eksporti`
- `filtro` subcommands: `agordi`, `montri`, `testi` (see AGENTS-filtro.md)
- `subskribo` subcommands: see AGENTS-subskribo.md
- Output: TUI interface, Rich tables for listings, status messages
- Side Effects: SQLite writes, keyring updates, emails sent, network I/O

## Documentation Reference
- `docs/man/retposto.md`

## Domain-Specific Rules for Agents
- Always use `keyring` for password storage; never store passwords in SQLite.
- IMAP/SMTP errors must be caught and reported via `typer.echo(..., err=True)`.
- When adding new account settings, update both the DB schema and `aldoni-konton` interactive flow.
- Contact management uses the same DB but separate `kontakto` sub-typer (registered in `main.py` as standalone too).
- Thread pool for `preni`: respect timeout and error handling per-account.
- Email body rendering: prefer plain text; HTML fallback with careful sanitization.
