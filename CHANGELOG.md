# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added
- `tests/test_wifi.py` - Test coverage for wifi command
- `tests/test_sistemo.py` - Test coverage for sistemo command  
- `tests/test_shelo.py` - Test coverage for shelo command
- `autish/profile.py` - New module for non-interactive profile loading (breaks circular dependency)
- SQL-based search functions in vorto.py: `_find_entry_by_uuid()`, `_find_entry_by_teksto()`, `_find_entries_by_uuid_prefix()`
- Incremental undo functions in vorto.py: `_undo_add()`, `_undo_modify()`, `_undo_delete()`

### Fixed
- **Critical**: Fixed circular dependency where `i18n.py` imported from `autish.commands.uzanto` - now imports from `autish.profile` instead
- Added subprocess timeouts to `disko.py` and `sekurkopio.py` to prevent indefinite hangs
- Optimized undo system in vorto.py - now uses efficient per-operation undo instead of full table rewrite

### Changed
- Updated `autish/commands/uzanto.py` to import profile loading from `autish.profile` module
- Updated `autish/i18n.py` to use new `autish.profile.load_profile()` function
- Updated undo operation storage in vorto.py to include full entry data for efficient restoration

### Added (Phase 3)
- `autish/paths.py` - Centralized path handling module with `data_dir()`, `config_dir()`, database path functions

### Fixed (Phase 3)
- Improved exception handling in `_crypto.py` - more specific exception catching for decryption
- Improved exception handling in `retposto.py` - catch specific exceptions (InvalidDateFormat, OSError) instead of broad `Exception`

---

## [0.0.1] - 2026-04-30

### Added
- Initial release with commands: tempo, wifi, bluhdento, sistemo, kp, shelo, vorto, retposto, kontakto, sekurkopio, uzanto, verki, md, doc, encik, kalendaro, disko, usb, filmeto, etikedo, todo, taglibro, rubo