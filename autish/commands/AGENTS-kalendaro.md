# AGENTS-kalendaro.md — kalendaro Command Agent Instructions

## Summary
Calendar microapp with local event storage and remote CalDAV sync support.

## Purpose and Expected Behavior
- Manage multiple calendars (local and remote CalDAV).
- CRUD events: `aldoni`, `vidi`, `modifi`, `forigi`, `serci`.
- Calendar management: `aldoni-kalendaron`, `forigi-kalendaron`, `listigi-kalendarojn`.
- Remote sync: `sinkronigi` (pull/push to CalDAV servers).
- Undo support: `malfari` (last 30 operations).
- Reminder support via `rememorigo` sub-typer.

## Constraints and Invariants
- SQLite database at `~/.local/share/autish/kalendaro.db` (WAL mode).
- Remote sync uses CalDAV protocol (via `urllib.request`, XML parsing with `ElementTree`).
- Credentials stored in system keyring: service=`autish.kalendaro`, key=`{calendar_uuid}:password`.
- Thread-safe sync: `_sync_lock` threading.Lock, `_sync_worker_started` flag for background sync.
- Max undo: 30 operations (`_MAX_UNDO = 30`).
- Event times stored as ISO 8601 strings; parsed with `date`/`datetime`.

## Input/Output Expectations
- Subcommands: `aldoni`, `vidi`, `modifi`, `forigi`, `serci`, `malfari`, `sinkronigi`
- Calendar subcommands: `aldoni-kalendaron`, `forigi-kalendaron`, `listigi-kalendarojn`
- `rememorigo` subcommands: reminder management
- Key CLI Options:
  - `--titolo`: event title
  - `--komenco`/`--fino`: start/end datetime (ISO 8601)
  - `--kalendaro`: calendar UUID
  - `-l`/`--lingvo`: language filter
  - `-L`/`--limo`: result limit
- Output: Rich tables, event details with participants, recurrence info
- Side Effects: SQLite writes, CalDAV network I/O, keyring updates

## Documentation Reference
- `docs/man/kalendaro.md`

## Domain-Specific Rules for Agents
- Always use `_connect()` helper for DB access (sets row_factory=sqlite3.Row, WAL mode).
- CalDAV sync: handle network errors gracefully; use `_sync_lock` for thread safety.
- Credentials: store in keyring with calendar_uuid as identifier; retrieve via `keyring.get_password()`.
- Recurrence (`ripeto`) stored as iCal RRULE strings; parse with care.
- Undo operations: use `undo_kalendaro` table; respect `_MAX_UNDO` limit.
- When adding new fields, update schema in `_init_db()` with `PRAGMA user_version` migration.
- Background sync: check `_sync_worker_started` before spawning new sync thread.
