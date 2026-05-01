## Current problems

### Ron:

- missing CHANGELOG.md
- Git commits are intermittant and do not correspond to functional units
- serious performance issue
  - many autish functions are just wrappers of existing Linux packages
  - why has the repo become so large ?

---

## Sub-agent Critical Reviews

### 1. Architect Review

**Overall architecture**: Single flat Typer CLI application with 23 command modules registered in `main.py`.

**Strengths:**
- Clear entry point
- Plugin-style command registration
- SQLite with WAL mode used correctly
- FTS5 in doc.py is proper

**Weaknesses:**

| Area | Problem |
|------|---------|
| **No layered architecture** | Commands, business logic, data access tightly coupled in same modules |
| **Service layer unused** | `autish/services/` exists but only `bash_alias.py` uses `SQLiteDB` base class |
| **Massive monoliths** | `vorto.py` (250KB), `encik.py` (300KB), `retposto.py` contain everything (SQL, HTML rendering, CLI) in single files |
| **5 different DB patterns** | Inline sqlite3 in vorto/encik, FTS5 in doc, shared `_tasklib` in etikedo/todo, `BashAliasDB` service, direct in i18n |
| **Circular dependency** | `i18n.py` imports `autish.commands.uzanto._load_profile` — i18n shouldn't depend on commands |
| **Duplicate code** | `fold_search_text()`, `normalize_oe()`, `SequenceMatcher` fuzzy matching duplicated in utils, vorto, _tasklib |
| **Heavy dependencies** | weasyprint (68MB+), yt-dlp (30MB+), cryptography, pyvis - all loaded at startup |
| **No lazy imports** | All 23 commands import on every `autish` invocation |

**Performance concerns:**
- `_load_entries()` loads ALL entries to memory, then Python-side filtering — O(n) per search
- `_find_entry()` is linear Python list iteration instead of SQL indexed lookup
- `_save_entries()` does full table DELETE + INSERT for simple undo operations
- No connection reuse — opens/closes per operation
- Undo stack stores full serialized DB snapshots — O(MB) per snapshot with 10k+ entries

**Recommendations:**
1. Split vorto.py/encik.py into data access, rendering, search, CLI layers
2. Decouple i18n.py from uzanto command
3. Replace in-memory search with SQL WHERE + indexes
4. Implement incremental undo instead of full table rewrite
5. Lazy import heavy dependencies (yt-dlp, cryptography, weasyprint, pyvis)
6. Centralize database strategy (single DB or connection pool)

---

### 2. Code Quality Review

| Severity | Location | Issue |
|----------|----------|-------|
| **Medium** | `retposto.py:2079`, `_retposto_tui.py`, `encik.py`, `sistemo.py` | Broad `except Exception` masks specific errors |
| **Medium** | `autish/commands/_crypto.py:102` | Swallowed exception loses stack trace context |
| **Medium** | `vorto.py`, `ENCIK*.py`, `todo.py` | Missing return type hints on many private functions |
| **Low** | `doc.py:141` | SQL string interpolation pattern — verify parameterized queries |
| **Low** | `disko.py`, `sekurkopio.py` | `subprocess.run()` without timeout can hang |

**Action items:**
- Add timeout to all `subprocess.run()` calls
- Replace broad `except Exception` with specific types
- Add return type hints to `_find_entry`, `_load_entries`, `_render_*`
- Verify SQL uses parameterized style consistently

**Positive:** Clean separation, Esperanto naming, Typer/Rich usage, no bare print(), SQLite WAL + indexes, no hardcoded secrets

---

### 3. Testing Review

**Coverage:** ~87% of commands have test files (20 test files for 23 commands)

| Status | Commands |
|--------|----------|
| **Has tests** | tempo, vorto, kalendaro, encik, retposto, kontakto, doc, md, rubo, filmeto, uzanto, bluetooth, usb, kp, verki, disko, todo, taglibro, etikedo, sekurkopio |
| **NO TESTS** | wifi, sistemo, shelo |

**Quality issues:**
- Inconsistent fixture usage — mix of `monkeypatch` and `patch()` decorators
- Magic strings in tests (hardcoded error messages)
- Many tests only check `exit_code == 0` without verifying output content
- No `@pytest.mark.parametrize` — manual repetition of similar test cases
- Minimal shared fixtures in conftest.py (only 1: `mock_webbrowser_globally`)

**Missing critical tests:**
- wifi command — completely untested
- sistemo command — completely untested
- shelo command — completely untested
- Error handling (network failures, DB corruption, permission errors)
- Edge cases (empty DB, concurrent access, unicode in filenames)
- Integration tests (vorto+encik ligilo interaction, kalendaro+retposto sync)

**Test balance:** 70% CLI integration, 30% unit — over-weighted toward slow integration tests

---

### 4. Refactoring Review

**Code duplication:**
| Pattern | Locations |
|---------|-----------|
| `_now_iso()` | vorto.py, encik.py, retposto.py, kalendaro.py, kunteksto.py (5x) |
| `fold_search_text()` | utils.py (canonical), _tasklib.py (duplicate) |
| `Console()` instantiation | 20 modules each create own instance |
| `confirm_esperante()` | utils.py (canonical), vorto.py, retposto.py (duplicates) |
| `render_label_pairs()` | todo.py, taglibro.py, vorto.py (nearly identical) |

**Complex functions needing simplification:**
- `resolve_etikedo_refs()` in _tasklib.py (65 lines, does too much)
- `resolve_reference()` in _tasklib.py (60 lines, nested fallback logic)
- `serci` in encik.py (100+ lines, 8 nested inner functions)
- `serci` in retposto.py (100+ lines, email-specific complexity)

**Missing abstractions:**
- Database connection: each microapp reimplements `_get_db()`, `_init_db()`, migration
- Search/filter: _tasklib has generic helpers but encik/retposto/kontakto don't use them

**Inconsistent naming:**
- `_now_iso()` vs `now_iso()` (different modules)
- `_row_to_dict()` vs `_row_to_contact()` vs `_row_to_event_dict()`
- `_DATA_DIR` defined differently per module

**Technical debt:**
- Monolithic files: encik.py (5100 lines), retporto.py (5100 lines), vorto.py (2400 lines)
- Hardcoded paths: `~/.local/share/autish/` scattered instead of centralized
- Magic numbers: fuzzy matching threshold 0.62 scattered, different `_MAX_UNDO` values

**Priority refactoring:**
1. Extract `_now_iso()` to shared module
2. Unify `Console()` instantiation
3. Split encik.py/retporto.py into sub-modules
4. Create `autish/db.py` with connection factory
5. Consolidate search patterns into reusable components
