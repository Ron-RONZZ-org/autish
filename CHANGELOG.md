# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.0.2] - 2026-05-01

### Added
- Major restructure complete - leaner code, better performance
- Lazy imports: yt-dlp, cryptography
- Centralized modules: paths.py, console.py, db.py, utils.py
- Service layer extraction: vorto_repo, encik_repo

### Fixed
- Fixed all test_sistemo.py failures: psutil v7.x API (mock classes), bash-alias commands, UID usage, battery assertions
- Fixed test_error_handling.py: replaced requests with urllib (not a dependency)
- Fixed test_help_i18n.py: monkeypatched correct module (autish.profile)
- Fixed F821 undefined name errors across 8 files (_retposto_tui.py, encik.py, retposto.py, rubo.py, sekurkopio.py, uzanto.py, verki.py, vorto.py)
- Added pyperclip import (is a dependency), changed requests exception to generic Exception

### Verified
- All 1035 tests pass
- Linter: 0 F821/F822/F823 errors
- Build: autish-0.0.2-py3-none-any.whl, autish-0.0.2.tar.gz

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

### Added (Phase 4)
- `autish/utils.py` now includes `now_iso()` - canonical timestamp function
- Consolidated timestamp handling across vorto, kalendaro, retposto, encik, kunteksto
- `autish/services/vorto_repo.py` - extracted database layer from vorto.py
- `autish/services/encik_repo.py` - extracted database layer from encik.py
- Extended vorto_repo with full CRUD: load_entries, find_entry_by_uuid/teksto, save_entries, insert/update/delete, rubujo, undo stack
- Extended encik_repo with: init_db, get_conn, load_all, find_by_uuid, FTS search, insert/update/delete, count

### Fixed (Phase 4)
- Fixed timestamp inconsistency bug: vorto/kalendaro stripped microseconds but retposto/encik/kunteksto kept them - now all use consistent seconds-precision timestamps

### Added (Phase 5)
- `tests/conftest.py` now includes: temp_db, mock_profile, isolated_config fixtures
- Parametrized timezone offset tests in test_tempo.py (27 valid offsets, 6 invalid)

### Performance
- Lazy import yt-dlp in filmeto.py - only loaded when filmeto commands are used, not at startup
- Lazy import cryptography in _crypto.py - loaded only when encrypt/decrypt functions called

### Fixed
- Removed invalid `rich_traceback` parameter from console.py that caused import errors
- Added subprocess timeouts to: md.py, retposto.py, doc.py, kunteksto.py, kp.py, bluetooth.py, wifi.py, usb.py

### Refactored
- Renamed internal search functions to canonical names: `fold_search_text()`, `normalize_search_text()`
- Replaced broad `Exception` handlers with specific types across all commands
- Parametrized validation tests in test_vorto.py: tipo, tono, etikedo normalization

### Refactored
- Removed dead code: unused _DB_FILE and schema constants in vorto.py and encik.py after repo extraction

---

## [0.0.1] - 2026-04-30

### Added
- Initial release with commands: tempo, wifi, bluhdento, sistemo, kp, shelo, vorto, retposto, kontakto, sekurkopio, uzanto, verki, md, doc, encik, kalendaro, disko, usb, filmeto, etikedo, todo, taglibro, rubo