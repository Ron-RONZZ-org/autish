# AGENTS.md — Root Project Rules for autish

This is the canonical, repo-wide instruction file for AI agents working on **autish**.

## Hierarchical Context Model

Agents **must** follow this rule:

> When working inside a directory, load the nearest `AGENTS.md` file and merge it with the root `AGENTS.md`.  
> Local rules override global rules.

Context resolution order (highest priority first):
1. `AGENTS-[command].md` in `autish/commands/` — command-specific context
2. `AGENTS.md` in current working directory (if present)
3. Root `AGENTS.md` — global project rules

---

## Project Overview

**autish** is a cross-platform (starting with Debian-based Linux) CLI tool built with Python 3 and [Typer](https://typer.tiangolo.com/). It provides essential desktop and info management tasks (time, Wi-Fi, Bluetooth, system info, clipboard, calendar, personal encyclopedia/dictionary/documentation library) with minimum stimulation, designed with neurodivergent users in mind.

---

## Language and Naming Conventions

- **CLI command names and long option names must be in Esperanto.**
  Examples: `tempo`, `wifi`, `konekti`, `malkonekti`, `forigi`, `horzono`, `sistemo`, `bluhdento`.
- **Prefer base-form verbs for command names whenever possible.**
  Use imperative/base forms like `agordi` instead of noun forms like `agordo`, unless a non-verb name is unavoidable for backward compatibility or domain meaning.
- **Python source code (variables, functions, modules) uses English `snake_case`.**
- **Short CLI flag alias convention (priority order):**
  1. First letter of long option name in lowercase (e.g. `-i` for `--instrukcio`)
  2. First letter in uppercase if lowercase conflicts (e.g. `-L` for `--ligilo`)
  3. First letter of each word in sequence if further specificity needed (e.g. `-td` for `--teksto-dosiero`)
- **Option alias normalization is mandatory across commands.**
  Use `-L` for `--ligilo`, `-l` for `--lingvo`/`--lingvoj`, and `-lo` for `--limo`.
- **Esperanto locale consistency is mandatory.**
  Always prefer correct Esperanto field names and labels (`difino`, `difinoj`, `ligilo`, `superklaso`, `subklaso`, `helpo`, etc.).
- **`ligilo` relations are bidirectional by default in Autish.**
  When an entry links to another via `ligilo`, the reverse `ligilo` must be persisted automatically.
- **Personalized language display is the default behavior.**
  Commands that display multilingual content should prioritize/filter output using `uzanto profilo` (`lingvoj`) preferences.
- **Multilingual help UX (eo/en/fr) with Esperanto command stability.**
  User-facing help text should support Esperanto, English, and French locales where feasible.
- **Locale resolution must prioritize `uzanto profilo lingvoj`.**
  Resolve locale using `lingvoj` in user-specified order. Only fall back to system locale when no valid profile language is configured.
- **Wikidata fetches must follow user language preference order with fixed fallback.**
  For `encik semantika` online metadata, request text using profile `lingvoj` order first; fall back to `eo`, then `en`.

---

## Tech Stack

| Concern | Choice |
|---|---|
| Language | Python 3.10+ |
| CLI framework | [Typer](https://typer.tiangolo.com/) |
| Rich output | [Rich](https://github.com/Textualize/rich) |
| System info | [psutil](https://github.com/giampaolo/psutil) |
| Clipboard | [pyperclip](https://github.com/asweigart/pyperclip) |
| Microapp data storage | **SQLite** (stdlib `sqlite3`) |
| Linting / formatting | [Ruff](https://docs.astral.sh/ruff/) |
| Testing | [pytest](https://pytest.org/) + [pytest-mock](https://pytest-mock.readthedocs.io/) |
| Build / dep management | [Poetry](https://python-poetry.org/) ≥ 2.0 |

---

## Coding Guidelines

1. **No bare `print()`** — use `typer.echo()` or `rich.print()` / `rich.console.Console`.
2. **Type-hint all public functions.**
3. **Keep output calm and minimal** — no spinners, animations, or excessive colour. Use muted colours (dim, cyan).
4. **Errors go to stderr** — use `typer.echo(..., err=True)` or `typer.BadParameter`.
5. **Inline help on incomplete commands** — call `ctx.get_help()` and exit with code 0 when required arguments are missing.
6. **Subprocess calls** — wrap `subprocess.run()` calls; capture `CalledProcessError`.
7. **Maximum offline capability by default** — keep a clear offline fallback path.
8. **Test coverage** — every command module must have a corresponding test file under `tests/`.
9. **Microapp data storage** — use SQLite for persistent data. Use `WAL` journal mode; store JSON in `TEXT` columns when appropriate.
10. **Action notifications must auto-expire** — transient messages should clear after ~3 seconds.
11. **Help text must include concrete value examples** — include at least one usage example in help strings.
12. **All command output must be clear, meaningful, succinct, and human-readable.**
13. **CLI colors must preserve contrast** on light/dark terminals and in grayscale/BW filters.
14. **Legacy command aliases must be hidden from help text** — use `@command(hidden=True)`.

---

## Help Text Standards

**Options with restricted values MUST document all valid values.**
Example: `--stato` option must document: "Valid values: malfermita (open), farita (done), prokrastita (deferred), nuligita (cancelled)"

**Every help string must include concrete usage examples:**
Format: `Example: --lingvo fr` or `Example: -P 30,80`

**Command | Alias help text convention:**
When documenting options with both long and short forms, use "command|alias explanation".

---

## Database Optimization Standards

**Scalability is critical for SQLite microapps (vorto, encik, retposto, kalendaro, todo, taglibro, doc):**
- Use indexes on frequently searched columns (teksto, titolo, uuid, language codes)
- Implement normalized search text columns with indexes for case-insensitive matching
- Use WHERE clauses in SQL instead of Python-side filtering
- Cache results per command execution, not per function call
- Target: aldoni operations complete in <100ms even with 10k+ entries

**SQL patterns to avoid:**
- Don't use `SELECT *` when you only need specific columns
- Don't iterate through loaded entries for lookups; use SQL WHERE + indexes
- Don't create new database connections for each query; reuse within transaction

---

## Direct CLI Access (Standard for New Commands)

Every new command module **must** be registered both in `autish/main.py` (as a sub-app) **and** in `pyproject.toml` as a standalone entry-point script.

Example:
1. Create `autish/commands/foo.py` with `app = typer.Typer(name="foo", ...)`
2. Register in `autish/main.py`: `app.add_typer(foo.app, name="foo")`
3. Add entry point in `pyproject.toml`: `foo = "autish.commands.foo:app"`
4. Run `poetry lock && poetry install`

---

## Commit Message Format

Use [Conventional Commits](https://www.conventionalcommits.org/):
- `feat:`, `fix:`, `docs:`, `chore:`, `test:`, `refactor:`

---

## What to Avoid

- Do not use `click` directly; always go through Typer's API.
- Do not add heavy dependencies (e.g. no Django, Flask, SQLAlchemy).
- Do not add GUI/TUI widgets; keep the interface purely text-line-based.
- Do not hard-code paths; use `pathlib.Path` and environment variables.
- **File-path prompts that accept a directory**: if the resolved path `is_dir()`, automatically append the default filename inside that directory.

---

## Command-Level AGENTS Files

The following command-specific AGENTS files are located in `autish/commands/`:

| Command | AGENTS File | Documentation |
|---|---|---|
| tempo | `AGENTS-tempo.md` | `docs/man/tempo.md` |
| wifi | `AGENTS-wifi.md` | `docs/man/wifi.md` |
| bluetooth (bluhdento) | `AGENTS-bluhdento.md` | `docs/man/bluhdento.md` |
| sistemo | `AGENTS-sistemo.md` | `docs/man/sistemo.md` |
| kp | `AGENTS-kp.md` | `docs/man/kp.md` |
| md | `AGENTS-md.md` | `docs/man/md.md` |
| vorto | `AGENTS-vorto.md` | `docs/man/vorto.md` |
| encik | `AGENTS-encik.md` | `docs/man/encik.md` |
| retposto | `AGENTS-retposto.md` | `docs/man/retposto.md` |
| kontakto | `AGENTS-kontakto.md` | `docs/man/kontakto.md` |
| todo | `AGENTS-todo.md` | `docs/man/todo.md` |
| disko | `AGENTS-disko.md` | `docs/man/disko.md` |
| kalendaro | `AGENTS-kalendaro.md` | `docs/man/kalendaro.md` |
| doc | `AGENTS-doc.md` | `docs/man/doc.md` |
| taglibro | `AGENTS-taglibro.md` | `docs/man/taglibro.md` |
| uzanto | `AGENTS-uzanto.md` | `docs/man/uzanto.md` |
| sekurkopio | `AGENTS-sekurkopio.md` | `docs/man/sekurkopio.md` |
| verki | `AGENTS-verki.md` | `docs/man/verki.md` |
| filmeto | `AGENTS-filmeto.md` | `docs/man/filmeto.md` |
| etikedo | `AGENTS-etikedo.md` | `docs/man/etikedo.md` |
| rubo | `AGENTS-rubo.md` | `docs/man/rubo.md` |
| shelo | `AGENTS-shelo.md` | `docs/man/shelo.md` |
| usb | `AGENTS-usb.md` | `docs/man/usb.md` |

---

## Compatibility

This structure works with:
- GitHub Copilot (reads AGENTS.md files automatically)
- Claude / Cursor / Opencode (hierarchical context loading)
- MCP-based agents (via context resolution protocol)
- Any LLM-driven coding assistant (declarative, machine-readable format)

---

## Dependency and Inheritance Map

```
Root AGENTS.md (global rules)
    │
    ├── autish/commands/AGENTS-[command].md (command-specific)
    │       └── References docs/man/[command].md
    │
    └── Future: AGENTS.md in any subdirectory (local context)
```

Local rules override global rules. Command-level files focus on domain-specific behavior, constraints, and invariants.
