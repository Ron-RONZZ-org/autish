# AGENTS-sekurkopio.md — sekurkopio Command Agent Instructions

## Summary
Backup and restore all autish user data with encryption support (7z/zip formats).

## Purpose and Expected Behavior
- Export all autish data: `eksporti <dosiero>` (encrypted .7z or .zip).
- Import/restore from export: `importi <dosiero>`.
- Automatic scheduled backups: `auto [dosierujo]` (configure interval and location).
- Change history: `historio` (show last 5 entries from `historio` table).
- Backs up all SQLite databases, config files, and profile data.

## Constraints and Invariants
- SQLite database: `~/.local/share/autish/sekurkopio.db` (history + auto-backup strategy).
- Data directory: `~/.local/share/autish/` (all .db files, profile TOML, config files).
- Config directory: `~/.config/autish/` (encik.toml, etc.).
- Archive formats: 7z (via `py7zr`), zip (stdlib `zipfile`).
- Encryption: password-based (prompted at export, stored in keyring for auto-backup).
- History table: `historio` (max 5 entries, `_HISTORY_MAX = 5`).
- Auto-backup strategy table: `auto_strategio` (one-row config, `id=1`).

## Input/Output Expectations
- Subcommands: `eksporti`, `importi`, `auto`, `historio`
- Key CLI Options:
  - `eksporti`: `<dosiero>` (output path, .7z or .zip)
  - `importi`: `<dosiero>` (input archive, required)
  - `auto`: `[dosierujo]` (backup directory, optional), `--intervalo` (minutes), `--nombro` (max copies)
- Output: Rich tables for history/strategy, status messages for export/import
- Side Effects: File I/O (archive creation/extraction), keyring updates, DB writes

## Documentation Reference
- `docs/man/sekurkopio.md`

## Domain-Specific Rules for Agents
- Always use `_connect()` helper for DB access (sets row_factory=sqlite3.Row, WAL mode).
- Export: discover all .db files + TOML configs + profile files; add to archive.
- Import: extract archive, validate contents, restore to proper locations (with confirmation).
- Auto-backup: use `subprocess` to schedule via system cron or systemd timer (platform-dependent).
- History: insert new entry, trim to `_HISTORY_MAX` entries (FIFO).
- Encryption password: prompt via `typer.prompt()` with `hide_input=True, confirmation_prompt=True`.
- When adding new data files, update the export file discovery logic.
