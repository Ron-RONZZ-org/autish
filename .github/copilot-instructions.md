# Copilot Instructions for autish

## Project overview

**autish** is a cross-platform (starting with Debian-based Linux) CLI tool built with Python 3 and [Typer](https://typer.tiangolo.com/). It provides essential desktop tasks (time, Wi-Fi, Bluetooth, system info, clipboard) with minimum stimulation, designed with neurodivergent users in mind.

---

## Language and naming conventions

- **CLI command names and long option names must be in Esperanto.**
  Examples: `tempo`, `wifi`, `konekti`, `malkonekti`, `forigi`, `horzono`, `sistemo`, `bluhdento`.
- **Prefer base-form verbs for command names whenever possible.**
  Use imperative/base forms like `agordi` instead of noun forms like `agordo`, unless
  a non-verb name is unavoidable for backward compatibility or domain meaning.
- **Python source code (variables, functions, modules) uses English `snake_case`.**
- **Short CLI flag alias convention (priority order):**
  1. First letter of long option name in lowercase (e.g. `-i` for `--instrukcio`)
  2. First letter in uppercase if lowercase conflicts (e.g. `-L` for `--ligilo`)
  3. First letter of each word in sequence if further specificity needed (e.g. `-td` for `--teksto-dosiero`)
  Use this fallback strategy consistently to avoid conflicts while keeping aliases readable.
- **Option alias normalization is mandatory across commands.**
  Use `-L` for `--ligilo`, `-l` for `--lingvo`/`--lingvoj`, and `-lo` for `--limo`.
- **Esperanto locale consistency is mandatory.**
  Always prefer correct Esperanto field names and labels (`difino`, `difinoj`, `ligilo`,
  `superklaso`, `subklaso`, `helpo`, etc.). If user input or legacy aliases are non-Esperanto
  or misspelled, parse them for compatibility when needed, but normalize stored/output names to
  the correct Esperanto forms.
- **`ligilo` relations are bidirectional by default in Autish.**
  When an entry links to another via `ligilo`, the reverse `ligilo` must be persisted
  automatically so both sides remain consistent in `vidi`/`serci` outputs.
- **Personalized language display is the default behavior.**
  When user language preferences are set in `uzanto profilo` (`lingvoj`),
  commands that display multilingual content should prioritize/filter output using
  those preferences by default; full output should remain available via explicit
  all-fields options (e.g. `-a/--cxio`).
- **Multilingual help UX (eo/en/fr) with Esperanto command stability.**
  User-facing help text and interactive hints should support Esperanto, English,
  and French locales where feasible, while command names/options and backend field
  semantics remain strictly Esperanto for portability and consistency.
- **Locale resolution must prioritize `uzanto profilo lingvoj`.**
  Resolve locale using `lingvoj` in user-specified order (first to last). Only
  fall back to system locale when no valid profile language is configured.
- **Wikidata fetches must follow user language preference order with fixed fallback.**
  For `encik semantika` online metadata/search content, request and resolve text
  using profile `lingvoj` order first; if not found, fall back to Esperanto (`eo`)
  and then English (`en`).

---

## Tech stack

| Concern | Choice |
|---|---|
| Language | Python 3.10+ |
| CLI framework | [Typer](https://typer.tiangolo.com/) |
| Rich output | [Rich](https://github.com/Textualize/rich) |
| System info | [psutil](https://github.com/giampaolo/psutil) |
| Clipboard | [pyperclip](https://github.com/asweigart/pyperclip) |
| Microapp data storage | **SQLite** (stdlib `sqlite3`) — scalable, efficient, single-file, no extra dependency |
| Linting / formatting | [Ruff](https://docs.astral.sh/ruff/) |
| Testing | [pytest](https://pytest.org/) + [pytest-mock](https://pytest-mock.readthedocs.io/) |
| Build / dep management | [Poetry](https://python-poetry.org/) ≥ 2.0 via `pyproject.toml` + `poetry.lock` |

---

## Project structure

```
autish/
├── autish/
│   ├── __init__.py        # version string
│   ├── main.py            # Typer root app; registers sub-apps
│   └── commands/
│       ├── __init__.py
│       ├── tempo.py       # time command
│       ├── wifi.py        # Wi-Fi subcommands
│       ├── bluetooth.py   # Bluetooth subcommands
│       ├── sistemo.py     # system info
│       ├── kp.py          # clipboard copy
│       ├── md.py          # Markdown utilities (view, export, import)
│       └── vorto.py       # Mia Vorto wordbook microapp (SQLite)
├── tests/
│   ├── __init__.py
│   ├── test_tempo.py
│   ├── test_kp.py
│   ├── test_vorto.py
│   └── test_md.py
├── pyproject.toml
├── README.md
├── CONTRIBUTING.md
└── TODO.md
```

---

## Coding guidelines

1. **No bare `print()`** — use `typer.echo()` for plain text or `rich.print()` / `rich.console.Console` for styled output.
2. **Type-hint all public functions.**
3. **Keep output calm and minimal** — no spinners, animations, or excessive colour. Use muted colours (dim, cyan) rather than bright/bold unless highlighting an error.
4. **Errors go to stderr** — use `typer.echo(..., err=True)` or `typer.BadParameter`.
5. **Inline help on incomplete commands** — call `ctx.get_help()` and exit with code 0 when required arguments are missing.
6. **Subprocess calls** — wrap `subprocess.run()` calls; capture `CalledProcessError` and surface a clean error message.
7. **Maximum offline capability by default** — features should work offline whenever possible, but internet-backed enhancements are allowed when valuable. Always keep a clear offline fallback path.
8. **Test coverage** — every command module should have a corresponding test file under `tests/`.
9. **Microapp data storage** — use SQLite (stdlib `sqlite3`) for any microapp that needs to persist structured data. Scalability and efficiency matter: prefer granular `INSERT`/`UPDATE`/`DELETE` over full-table rewrites; use `WAL` journal mode; store JSON arrays/objects in `TEXT` columns when normalisation would be overkill for the data size. Never use plain JSON files for databases.
10. **Action notifications must auto-expire** — transient success/info/error status messages should clear after ~3 seconds to reduce sensory load. Keep persistent status only when explicit user action is required (prompts, confirmations, modal choices, blocking errors).
11. **Prevent key conflicts proactively** — before assigning or changing `retposto` shortcuts, verify they do not conflict with existing global/list/compose/read-view keys and update inline hints/help text in the same change.
12. **Default duplicate-safe add flow for DB entries** — for database-backed `aldoni` commands, if a potential duplicate is detected by primary identity fields, prompt user to choose updating the existing entry or creating a new one.
13. **retposto read-view links must preserve full target for actions** — if a URL is visually truncated/wrapped for readability, copy/open actions must still use the full URL value (never the visible fragment only).
14. **Any truncated link in CLI output must keep full action target** — if URLs are shortened in tables/panels (e.g., `kalendaro ls-kalendaro`), Ctrl+click/copy/open must always use the full original URL, and UI should warn that display text is truncated.
15. **Do not manually shorten URLs when action fidelity matters** — prefer rendering full URLs with link metadata and let terminal layout handle visual clipping; always warn that any visual truncation is display-only and actions still target the full URL.
16. **Help text must include concrete value examples** — for every command option that requires a value (paths, UUIDs, language codes, filters, etc.), include at least one usage example directly in the help string.
17. **Semantic-link help should be category-first and relevance-ranked** — for `encik semantika`, prefer subcommands by domain (e.g., `generala`, `persono`, `geografio`, `abstrakta`), list rdf/rdfs links first, then add the most relevant Wikidata properties as fallback.
18. **`agordi` commands should persist to TOML under `~/.config/autish/`** — each command-level settings surface should map to a dedicated editable TOML file (e.g., `~/.config/autish/encik.toml`, `~/.config/autish/filmeto.toml`) so users can configure via CLI or direct file edits.
19. **Encik semantic groups are user-editable CSV files** — store `encik semantika` groups in `~/.config/autish/semantika/*.csv` with columns `LIGILO,PRISKRIBO,ALIAZOJ`; each file corresponds to one semantic group/subcommand.
20. **All command output must be clear, meaningful, succinct, and human-readable** — prefer resolved labels/text over raw IDs, and keep confirmations/results understandable at a glance.
21. **CLI colors must preserve contrast on light/dark terminals and in grayscale/BW filters** — avoid fixed low-contrast accents and hue-only cues; adapt styles to terminal background so key fields (e.g., `LIGILO`) remain clearly readable even without color perception.
22. **Legacy command aliases must be hidden from help text** — when adding backward-compatibility aliases for renamed commands, use `@command(hidden=True)` so users see the recommended name in help. The legacy alias still functions but doesn't clutter help output. Example: `disko particio shrink` is hidden; users see `srumpi` instead.

---

## Help Text Standards (for first-time users)

**Options with restricted values MUST document all valid values:**
- For options that accept only specific values (enums, fixed choices), list them all exhaustively in the help string
- Example: `--stato` option for `todo serci` must document: "Valid values: malfermita (open), farita (done), prokrastita (deferred), nuligita (cancelled)"
- For semantic link types in `encik`, reference the relevant groups: "See: encik semantika generala, encik semantika persono, etc."

**Every help string must include concrete usage examples:**
- Include at least one real example that demonstrates actual usage patterns
- Format: `Example: --lingvo fr` or `Example: -P 30,80` or `Example: -lo mallonga`
- Examples should be diverse: show common cases, edge cases, and format variations

**Descriptive help improves clarity:**
- Prefer: "Target text length. Valid values: mallonga (short), normala (normal), longa (long)." 
- Over: "Text length (mallonga|normala|longa)"
- Include brief explanation of what each value does, especially for less obvious options

**Semantic link documentation pattern:**
- When documenting semantic link types, group by domain: RDF/OWL first, then Wikidata properties
- Include key aliases: "rdf:type (also: type, wdt:P31, instance of)"
- Reference command: "Full reference: encik semantika"

---

## Database Optimization Standards

**Scalability is critical for vorto and encik microapps:**
- Use indexes on frequently searched columns (teksto, titolo, uuid, language codes)
- Implement normalized search text columns with indexes for case-insensitive matching
- Avoid full-table loads in memory for operations that can be filtered at SQL level
- Cache results per command execution, not per function call (reduces redundant queries)

**Performance guidelines:**
- Target: aldoni operations complete in <100ms even with 10k+ entries
- Use WHERE clauses in SQL instead of Python-side filtering
- Implement batch resolution for semantic links instead of per-item lookups
- Consider full-text search (FTS5) for complex text searches across multiple fields

**SQL patterns to avoid:**
- Don't use `SELECT *` when you only need specific columns
- Don't iterate through loaded entries for lookups; use SQL WHERE + indexes
- Don't recompute aggregate metrics (e.g., subclass counts) on every operation
- Don't create new database connections for each query; reuse within transaction

---

## Direct CLI access (standard for new commands)

Every new command module **must** be registered both in `autish/main.py` (as a
sub-app under `autish <command>`) **and** in `pyproject.toml` as a standalone
entry-point script so users can invoke it directly without the `autish` prefix.

This is a strict default behavior for all future commands: if a command is
added and only available through `autish <command>` (without standalone script
entry), the implementation is considered incomplete.

Example — adding a new `foo` command:
1. Create `autish/commands/foo.py` with a `app = typer.Typer(name="foo", ...)`.
2. Import and register in `autish/main.py`:
   ```python
   from autish.commands import foo
   app.add_typer(foo.app, name="foo")
   ```
3. Add the entry point in `pyproject.toml`:
   ```toml
   [tool.poetry.scripts]
   foo = "autish.commands.foo:app"
   ```
4. Run `poetry lock && poetry install` to install the new script.

---

## Commit message format

Use [Conventional Commits](https://www.conventionalcommits.org/):
- `feat:`, `fix:`, `docs:`, `chore:`, `test:`, `refactor:`

---

## What to avoid

- Do not use `click` directly; always go through Typer's API.
- Do not add heavy dependencies (e.g. no Django, Flask, SQLAlchemy).
- Do not add GUI/TUI widgets; keep the interface purely text-line-based.
- Do not hard-code paths; use `pathlib.Path` and environment variables.
- **File-path prompts that accept a directory**: if the resolved path `is_dir()`, automatically append the default filename (e.g. `autish_recovery_hint.txt`) inside that directory instead of raising `IsADirectoryError`. Apply this pattern consistently wherever users are prompted for an output file path.
