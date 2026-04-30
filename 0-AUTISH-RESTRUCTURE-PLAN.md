# Autish Restructure Plan

Based on sub-agent critical reviews in `0-AUTISH-RESTRUCTURING.md`.

---

## Phase 1: Critical Fixes (Immediate)

### 1.1 Fix Circular Dependency
**Issue:** `i18n.py` imports from `autish.commands.uzanto`

**Action:**
- Move `_load_profile` to a standalone module: `autish/profile.py`
- Update i18n.py to import from `autish.profile`
- Update all imports of `_load_profile` to use new location

**File:** `autish/i18n.py`, `autish/commands/uzanto.py`, `autish/profile.py` (new)

---

### 1.2 Add Missing Tests
**Issue:** wifi, sistemo, shelo commands have zero test coverage

**Action:**
- Create `tests/test_wifi.py` — test konekti/malkonekti/listigi
- Create `tests/test_sistemo.py` — test info/show commands
- Create `tests/test_shelo.py` — test shell integration

**Files:** `tests/test_wifi.py`, `tests/test_sistemo.py`, `tests/test_shelo.py` (new)

---

### 1.3 Add Subprocess Timeouts
**Issue:** `subprocess.run()` without timeout can hang indefinitely

**Action:**
- Add `timeout=30` to all `subprocess.run()` calls in:
  - `autish/commands/disko.py`
  - `autish/commands/sekurkopio.py`
  - Other commands with subprocess calls

**Files:** `autish/commands/disko.py`, `autish/commands/sekurkopio.py`

---

## Phase 2: Performance Improvements (Short-term)

### 2.1 Replace In-Memory Search with SQL
**Issue:** `_load_entries()` loads all to memory, Python-side filtering

**Action:**
- Add indexes on `teksto`, `uuid`, `language` columns
- Replace `_find_entry()` Python iteration with SQL `SELECT ... WHERE uuid = ?`
- Add FTS5 search tables where appropriate

**Files:** `autish/commands/vorto.py`, `autish/commands/encik.py`

---

### 2.2 Implement Incremental Undo
**Issue:** `_save_entries()` does full DELETE + INSERT for undo

**Action:**
- Store only diffs (changed rows) instead of full DB snapshots
- Or use SQLite transaction savepoints
- Reduce undo stack memory usage

**Files:** `autish/commands/vorto.py`, `autish/commands/encik.py`

---

### 2.3 Lazy Import Heavy Dependencies
**Issue:** weasyprint, yt-dlp, cryptography, pyvis loaded at startup

**Action:**
- Import heavy dependencies only in commands that use them:
  - `yt-dlp` → only in `filmeto.py`
  - `weasyprint` → only in `md.py`
  - `cryptography` → only in `_crypto.py`
  - `pyvis` → only in `encik.py` (graph visualization)

**Files:** `autish/commands/filmeto.py`, `autish/commands/md.py`, `autish/commands/encik.py`, `autish/commands/_crypto.py`

---

## Phase 3: Code Quality (Medium-term)

### 3.1 Improve Exception Handling
**Issue:** Broad `except Exception` masks specific errors

**Action:**
- Replace with specific exceptions: `ValueError`, `OSError`, `sqlite3.Error`
- Preserve stack traces in `_crypto.py`

**Files:** `autish/commands/retposto.py`, `autish/commands/_retposto_tui.py`, `autish/commands/encik.py`, `autish/commands/_crypto.py`

---

### 3.2 Add Return Type Hints
**Issue:** Missing return type hints on private functions

**Action:**
- Add `-> ...` to functions: `_find_entry`, `_load_entries`, `_render_*`

**Files:** `autish/commands/vorto.py`, `autish/commands/encik.py`, `autish/commands/todo.py`

---

### 3.3 Centralize Path Handling
**Issue:** Hardcoded `~/.local/share/autish/` scattered across files

**Action:**
- Create `autish/paths.py` with:
  ```python
  def data_dir() -> Path: ...
  def config_dir() -> Path: ...
  ```
- Replace all hardcoded paths with centralized functions

**Files:** `autish/paths.py` (new), update all command modules

---

## Phase 4: Architecture Refactoring (Long-term)

### 4.1 Split Monolithic Files
**Issue:** vorto.py (250KB), encik.py (300KB), retporto.py (300KB+) are unmaintainable

**Action:**

**encik.py → encik/ subpackage:**
```
autish/commands/encik/
├── __init__.py       # exports app
├── _db.py            # connection, schema, migrations
├── _search.py        # search/filter logic
├── _semantika.py     # semantika CSV handling
├── _html.py          # HTML rendering
├── _wikidata.py      # Wikidata API
└── _cli.py           # Typer commands only
```

**vorto.py → vorto/ subpackage:**
```
autish/commands/vorto/
├── __init__.py
├── _db.py
├── _search.py
├── _render.py
├── _tui.py
└── _cli.py
```

**retporto.py → retporto/ subpackage:**
```
autish/commands/retporto/
├── __init__.py
├── _smtp.py
├── _imap.py
├── _db.py
├── _contacts.py
├── _filters.py
└── _cli.py
```

---

### 4.2 Create Shared Database Module
**Issue:** 5 different database patterns across codebase

**Action:**
- Create `autish/db.py`:
  ```python
  def get_connection(db_path: Path, timeout: float = 5.0) -> sqlite3.Connection
  def ensure_schema(con: sqlite3.Connection, schema_sql: str, version: int) -> None
  def row_to_dict(row: sqlite3.Row) -> dict
  ```
- Deprecate inline `_get_db()` patterns

**Files:** `autish/db.py` (new), update all command modules

---

### 4.3 Consolidate Duplicated Code
**Issue:** _now_iso() in 5 places, Console() instantiated 20x

**Action:**
- Move `_now_iso()` → `autish/utils.py` (or create `autish/time_utils.py`)
- Create `autish/console.py` with `get_console()` singleton
- Remove duplicates from vorto, encik, retporto, kalendaro, kunteksto

**Files:** `autish/utils.py`, `autish/console.py` (new), update command modules

---

### 4.4 Unify Search Patterns
**Issue:** _tasklib has generic search but encik/retporto don't use it

**Action:**
- Extend `_tasklib.py` search capabilities
- Update encik.py, retporto.py, kontakto.py to use shared search
- Or create `autish/search.py` with reusable search components

**Files:** `autish/commands/_tasklib.py`, `autish/search.py` (new)

---

## Phase 5: Testing Improvements (Ongoing)

### 5.1 Add Shared Fixtures
**Issue:** Minimal fixtures in conftest.py

**Action:**
- Add to `tests/conftest.py`:
  ```python
  @pytest.fixture
  def temp_db(tmp_path):
      """Create temporary SQLite database."""
  
  @pytest.fixture
  def mock_profile():
      """Mock user profile."""
  
  @pytest.fixture
  def isolated_config(tmp_path, monkeypatch):
      """Isolated config directory."""
  ```

**File:** `tests/conftest.py`

---

### 5.2 Add Error Handling Tests
**Issue:** No tests for network failures, DB corruption, permission errors

**Action:**
- Add tests for:
  - Network timeout handling in encik, retporto
  - SQLite corruption recovery
  - Permission denied on file operations
  - Empty database states

**Files:** Existing test files

---

### 5.3 Add Parametrized Tests
**Issue:** Manual repetition of similar test cases

**Action:**
- Use `@pytest.mark.parametrize` for:
  - Timezone offsets in tempo
  - Language codes in i18n
  - Edge cases in vorto/encik validation

**Files:** Existing test files

---

## Summary Checklist

| Phase | Actions | Priority |
|-------|---------|----------|
| **1. Critical** | Fix i18n circular dep, add wifi/sistemo/shelo tests, add subprocess timeouts | HIGH |
| **2. Performance** | SQL search, incremental undo, lazy imports | HIGH |
| **3. Quality** | Exception handling, type hints, centralized paths | MEDIUM |
| **4. Architecture** | Split monoliths, shared DB module, deduplicate | LOW |
| **5. Testing** | Fixtures, error tests, parametrization | MEDIUM |

---

## Notes

- Phase 1 can be completed in 1-2 days
- Phase 2-3 in 1-2 weeks
- Phase 4 requires significant refactoring — consider doing incrementally
- Phase 5 is ongoing throughout development