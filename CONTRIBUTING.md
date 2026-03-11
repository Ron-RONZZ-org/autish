# Contributing to autish

Thank you for your interest in contributing! This guide covers how to set up your development environment, coding style, and the contribution workflow.

---

## Table of Contents

1. [Getting Started](#getting-started)
2. [Development Setup](#development-setup)
3. [Project Structure](#project-structure)
4. [Style Guide](#style-guide)
5. [Running and Building](#running-and-building)
6. [Submitting Changes](#submitting-changes)

---

## Getting Started

- **Target platform (v0.0.1):** Debian-based Linux (Ubuntu, Debian, Mint, …)
- **Python version:** 3.10+
- **CLI framework:** [Typer](https://typer.tiangolo.com/)
- **Command keywords:** Esperanto (see below)

### Esperanto keyword policy

All command names and long option names **must** be in Esperanto. This lowers the barrier for non-English speakers. Short single-letter flags may use any letter that is intuitive (e.g. `-p` for password/pasvorto).

Examples: `tempo`, `wifi`, `konekti`, `malkonekti`, `forigi`, `horzono`, `sistemo`.

---

## Development Setup

```bash
# 1. Clone the repository
git clone https://github.com/Ron-RONZZ-org/autish.git
cd autish

# 2. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install the package in editable mode with dev dependencies
pip install -e ".[dev]"

# 4. Verify the CLI is available
autish --help
```

---

## Project Structure

```
autish/
├── autish/              # Main Python package
│   ├── __init__.py
│   ├── main.py          # Typer app entry point; registers all sub-apps
│   └── commands/        # One module per command group
│       ├── __init__.py
│       ├── tempo.py
│       ├── wifi.py
│       ├── bluetooth.py
│       ├── sistemo.py
│       └── kp.py
├── tests/               # pytest tests (mirror package structure)
│   ├── __init__.py
│   └── test_tempo.py
├── pyproject.toml       # PEP 517/518 build config, deps, entry points
├── README.md
├── CONTRIBUTING.md      # This file
└── TODO.md
```

---

## Style Guide

### Python

- Follow **PEP 8** (line length 88, use `ruff` for linting/formatting).
- Use **type hints** on all public functions.
- Keep functions small and single-purpose.
- Prefer **f-strings** over `.format()` or `%`.
- Do not use `print()` directly; use Typer's `typer.echo()` or `rich`-based output so output can be tested and suppressed easily.

### Commits

- Use [Conventional Commits](https://www.conventionalcommits.org/):
  - `feat:` new feature
  - `fix:` bug fix
  - `docs:` documentation only
  - `chore:` tooling / maintenance
  - `test:` tests only
- Keep commits small and focused (one logical change per commit).

### Naming

| Concept | Convention |
|---|---|
| CLI commands / options | Esperanto, lowercase, hyphen-separated |
| Python identifiers | English, `snake_case` |
| Test functions | `test_<what>_<condition>` |

---

## Running and Building

### Run from source (development)

```bash
# After `pip install -e ".[dev]"`
autish --help
autish tempo
```

### Run tests

```bash
pytest
```

### Lint and format

```bash
ruff check .
ruff format .
```

### Build a distributable package

```bash
python -m build
```

The `dist/` directory will contain a `.whl` and a `.tar.gz`.

---

## Submitting Changes

1. Fork the repo and create a feature branch:
   ```bash
   git checkout -b feat/my-feature
   ```
2. Make your changes following the style guide above.
3. Add or update tests under `tests/`.
4. Run tests and linting locally before opening a PR.
5. Open a Pull Request with a clear description of *what* changed and *why*.
6. Link any related issues in the PR description.

---

## Code of Conduct

Be kind, patient, and inclusive. This project is designed with neurodivergent people in mind — that ethos extends to our contributor community.
