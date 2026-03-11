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
- **Dependency manager:** [Poetry](https://python-poetry.org/) ≥ 2.0
- **CLI framework:** [Typer](https://typer.tiangolo.com/)
- **Command keywords:** Esperanto (see below)

### Esperanto keyword policy

All command names and long option names **must** be in Esperanto. This lowers the barrier for non-English speakers. Short single-letter flags may use any letter that is intuitive (e.g. `-p` for password/pasvorto).

Examples: `tempo`, `wifi`, `konekti`, `malkonekti`, `forigi`, `horzono`, `sistemo`.

---

## Development Setup

### 1. Install Poetry

```bash
curl -sSL https://install.python-poetry.org | python3 -
```

Ensure Poetry's bin directory (`~/.local/bin`) is on your PATH:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
poetry --version
```

### 2. Clone and install

```bash
git clone https://github.com/Ron-RONZZ-org/autish.git
cd autish

# Install all dependencies (runtime + dev) into an isolated virtualenv
poetry install

# Verify the CLI works
poetry run autish --help
```

### 3. (Optional) Activate the Poetry shell

```bash
poetry shell    # spawns a subshell with the venv active
autish --help   # no prefix needed
exit            # return to your normal shell
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
├── pyproject.toml       # Poetry build config, deps, entry points, tool config
├── poetry.lock          # Locked dependency versions (commit this file)
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
poetry run autish --help
poetry run autish tempo
```

Or activate the Poetry shell first (`poetry shell`) and use `autish` directly.

### Run tests

```bash
poetry run pytest
```

### Lint and format

```bash
poetry run ruff check .
poetry run ruff format .
```

### Build a distributable package

```bash
poetry build
```

The `dist/` directory will contain a `.whl` and a `.tar.gz`.

### Add or update a dependency

```bash
# Runtime dependency
poetry add <package>

# Dev-only dependency
poetry add --group dev <package>

# Update all dependencies to latest compatible versions
poetry update
```

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
