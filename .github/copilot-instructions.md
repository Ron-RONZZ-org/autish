# Copilot Instructions for autish

## Project overview

**autish** is a cross-platform (starting with Debian-based Linux) CLI tool built with Python 3 and [Typer](https://typer.tiangolo.com/). It provides essential desktop tasks (time, Wi-Fi, Bluetooth, system info, clipboard) with minimum stimulation, designed with neurodivergent users in mind.

---

## Language and naming conventions

- **CLI command names and long option names must be in Esperanto.**
  Examples: `tempo`, `wifi`, `konekti`, `malkonekti`, `forigi`, `horzono`, `sistemo`, `bluhdento`.
- **Python source code (variables, functions, modules) uses English `snake_case`.**
- Short single-letter CLI flags may be any intuitive letter (e.g. `-p` for password).

---

## Tech stack

| Concern | Choice |
|---|---|
| Language | Python 3.10+ |
| CLI framework | [Typer](https://typer.tiangolo.com/) |
| Rich output | [Rich](https://github.com/Textualize/rich) |
| System info | [psutil](https://github.com/giampaolo/psutil) |
| Clipboard | [pyperclip](https://github.com/asweigart/pyperclip) |
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
│       └── kp.py          # clipboard copy
├── tests/
│   ├── __init__.py
│   └── test_tempo.py
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
7. **No internet dependency** — all v0.0.1 commands must work offline. Do not add network calls.
8. **Test coverage** — every command module should have a corresponding test file under `tests/`.

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
