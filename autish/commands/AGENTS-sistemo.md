# AGENTS-sistemo.md — sistemo Command Agent Instructions

## Summary
System information display and bash alias management.

## Purpose and Expected Behavior
- Display system information (OS, kernel, CPU, memory, disk, network) via `psutil` and system commands.
- Manage bash aliases stored in SQLite database (`BashAliasDB` from `autish.services.bash_alias`).
- Subcommands: `info` (system info), `bash alias` (alias management sub-typer).

## Constraints and Invariants
- System info uses `psutil` for cross-platform metrics; falls back to `platform`/`subprocess` for OS details.
- Bash alias sub-typer uses dedicated `BashAliasDB` with SQLite storage.
- `_confirm_esperante()` helper for user confirmation in Esperanto.
- Output uses Rich `Table` for formatted system info.

## Input/Output Expectations
- Subcommands: `info`, `bash` (sub-typer with `alias` subcommands)
- `bash alias` subcommands: `ls`, `aldoni`, `modifi`, `forigi`, `sh` (export to shell)
- Output: Rich tables for system info; status messages for alias operations
- Side Effects: Bash alias database modifications

## Documentation Reference
- `docs/man/sistemo.md`

## Domain-Specific Rules for Agents
- System info subcommand is read-only; no modifications.
- Bash alias management uses `BashAliasDB` service — do not bypass with raw SQL.
- Confirmation prompts use Esperanto (`_confirm_esperante`).
- When adding new system metrics, use `psutil` where possible for cross-platform support.
- `_run()` helper has 5-second timeout; preserve for safety.
