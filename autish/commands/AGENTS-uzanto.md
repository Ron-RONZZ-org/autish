# AGENTS-uzanto.md — uzanto Command Agent Instructions

## Summary
User profile management and master password setup for autish personalization.

## Purpose and Expected Behavior
- Profile management via `profilo` sub-typer: `vidi`, `modifi`, `eksporti`, `importi`.
- Master password: `pasvorto` command to set/clear user master password (stored in keyring).
- Profile fields: `nomo`, `familia_nomo`, `naskig_dato`, `naskig_loko`, `lingvoj`, `organizo`, `telefonnumeroj`, `retposhtadresoj`, `api_slosilo_huggingface`.
- Profile stored as TOML: `~/.local/share/autish/uzanto_profilo.toml`.
- Encrypted profile export/import for backup.

## Constraints and Invariants
- Profile file: `~/.local/share/autish/uzanto_profilo.toml` (plain TOML).
- Encrypted profile: `~/.local/share/autish/uzanto_profilo.enc` (via `cryptography` library).
- Master password in system keyring: service=`autish-uzanto`, key=`master`.
- API keys (e.g., HuggingFace) stored in profile TOML, not in keyring.
- Language preference (`lingvoj`) is a comma-separated list used for locale resolution.

## Input/Output Expectations
- `profilo` subcommands: `vidi`, `modifi`, `eksporti`, `importi`
- `pasvorto` command: interactive password set/clear
- Key CLI Options:
  - `profilo modifi`: any profile field as option (e.g., `--nomo`, `--lingvoj`)
  - `profilo eksporti`: `[dosiero]` (output path, optional)
  - `profilo importi`: `<file>` (encrypted profile file, required)
- Output: Rich tables for profile display, status messages
- Side Effects: TOML file writes, keyring updates, encrypted file I/O

## Documentation Reference
- `docs/man/uzanto.md`

## Domain-Specific Rules for Agents
- Profile loading: use `_load_profile(quiet=True)` for silent loading (no stderr on missing).
- Language resolution: `_ui_lang()` checks `LC_ALL`/`LANG` env vars; falls back to "eo".
- URL action labels (Visit/Copy): use `_url_action_labels()` for multilingual support.
- Encryption: use `autish.commands._crypto` helpers; never implement crypto directly.
- When adding new profile fields, update `_STANDARD_FIELDS` tuple and `profilo modifi` options.
- TOML parsing: use `tomllib` (Python 3.11+) or `tomli` (via import compatibility shim).
- Master password: stored in keyring only; not in profile TOML for security.
