# autish

Cross-platform CLI software for essential tasks with minimum stimulation. Designed with neurodiversity in mind.

---

## Goals

- **Minimum stimulation** — calm, predictable output with no unnecessary noise
- **Sensible defaults** — works well out of the box without memorising options
- **Neurodiversity-first** — clear, minimalist syntax; Esperanto keywords so non-English speakers can participate equally
- **Offline-first** — core functionality works without internet access
- **Humble scope** — v0.0.1 targets Debian-based Linux

---

## Commands (v0.0.1)

All keywords are in **Esperanto** to lower the barrier for non-English speakers.

| Command | Description |
|---|---|
| `autish tempo` | Print current local time (ISO) and day of week |
| `autish wifi ls` | List Wi-Fi connections |
| `autish wifi konekti` | Connect to a Wi-Fi network |
| `autish wifi malkonekti` | Disconnect from Wi-Fi |
| `autish wifi forigi` | Delete a saved Wi-Fi profile |
| `autish bluhdento ls` | List Bluetooth devices |
| `autish bluhdento konekti` | Connect a Bluetooth device |
| `autish bluhdento malkonekti` | Disconnect a Bluetooth device |
| `autish sistemo` | Print system information |
| `autish kp` | Copy last command output to clipboard |
| `autish verki generi` | AI-assisted text generation and rewriting; see [VERKI.md](VERKI.md) |
| `autish verki modelo` | Browse available AI models |
| `autish encik generi` | AI-generate `.enc` terminology/definition content with language controls |
| `autish retposto analizi` | AI analysis/summarization/event extraction for email conversations |
| `autish retposto generi` | AI-generate email draft text to Drafts or file output |

**Note:** verki may surface router/Cloudflare or host-blocking errors (403/Error 1010 or HTML 404 fallback). See VERKI.md Troubleshooting for recommended actions (try another model/network or contact model owner).

---

## Installation

> **Requirements:** Python 3.10+, Debian-based Linux (Ubuntu, Debian, Mint, …)

### Option A — Install from PyPI (recommended for regular users)

```bash
pip install --user autish
```

After installing with `--user`, the `autish` command is placed in `~/.local/bin/`.
If that directory is not already on your `PATH`, add it:

```bash
# Add to ~/.bashrc (bash) or ~/.zshrc (zsh)
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

Verify the install:

```bash
autish --help
```

### Option B — Install with pipx (recommended for isolated global install)

[pipx](https://pipx.pypa.io/) installs CLI tools in isolated environments and
automatically adds them to your `PATH`:

```bash
# Install pipx if not already present
pip install --user pipx
pipx ensurepath          # adds ~/.local/bin to PATH; restart your shell after

# Install autish
pipx install autish

# Verify
autish --help
```

### Option C — Install from source globally (development mode)

To install autish from your local source repository globally (so the `autish` command is available in your PATH), use Poetry's `install` command with the `--directory` flag:

```bash
cd /path/to/autish
poetry install

# Create a symlink to make autish available globally
ln -s "$(poetry -C . env info --path)/bin/autish" ~/.local/bin/autish

# Verify
autish --help
```

Alternatively, if `~/.local/bin` is already on your PATH, you can use:

```bash
cd /path/to/autish
poetry install
poetry run pip install --user -e .
```

This installs autish in editable mode globally while keeping dependencies isolated in the Poetry environment.

**Why install from source?**

- **Bash aliases work system-wide** — With `autish` in your PATH, bash aliases like `ess='autish encik serci -sk'` work in any shell session without needing to activate the Poetry environment
- **Development workflow** — Changes to the source code are immediately reflected without reinstalling
- **Standalone entry-point scripts** — Commands like `vorto`, `encik`, `retposto` work directly if registered in `pyproject.toml`

**Note for bash aliases:** After installing globally, regenerate your bash aliases:

```bash
sistemo bash-alias ls  # View existing aliases
# Aliases will now use the global autish command
```

### Making autish available system-wide

If you want `autish` available for all users on the machine:

```bash
sudo pip install autish
# or with pipx:
sudo pipx install autish --global
```

---

## Development Setup

> Requires [Poetry](https://python-poetry.org/) ≥ 2.0 for dependency management.

### 1. Install Poetry

```bash
curl -sSL https://install.python-poetry.org | python3 -
```

Make sure Poetry's bin directory is on your PATH (the installer will tell you
where; typically `~/.local/bin`):

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
poetry --version   # should print e.g. "Poetry (version 2.x.x)"
```

### 2. Clone and install

```bash
git clone https://github.com/Ron-RONZZ-org/autish.git
cd autish

# Install all dependencies (including dev) into an isolated virtualenv
poetry install

# Verify the CLI is available inside the Poetry environment
poetry run autish --help
```

### 3. Activate the shell (optional)

Instead of prefixing every command with `poetry run`, you can activate the
virtualenv directly:

```bash
eval $(poetry env activate) # spawns a subshell with the venv active
autish --help         # works without the prefix
exit                  # return to your normal shell
```

### 4. Adding the dev `autish` to your PATH globally

If you want `autish` (from source) to be available without `poetry run` or a
shell activation, you can add the virtualenv's `bin/` directory to your PATH:

```bash
# Find the virtualenv path
poetry env info --path

# Example output: /home/youruser/.cache/pypoetry/virtualenvs/autish-XYZ-py3.12
# Add its bin/ to PATH:
echo 'export PATH="$(poetry -C /path/to/autish env info --path)/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

Or symlink the binary for a simpler approach:

```bash
# One-time symlink — update it if you move the repo
ln -s "$(poetry env info --path)/bin/autish" ~/.local/bin/autish
autish --help
```

### 5. Run tests and linting

```bash
# Run tests
poetry run pytest

# Lint and format check
poetry run ruff check .
poetry run ruff format --check .

# Auto-format
poetry run ruff format .
```

### 6. Build a distributable package

```bash
poetry build
# Creates dist/autish-0.0.1.tar.gz and dist/autish-0.0.1-py3-none-any.whl
```

---

## Quick Start

```bash
# Show current time and day
autish tempo

# Show time for UTC+9
autish tempo --horzono 9

# Show time for all UTC offsets
autish tempo --horzono

# List Wi-Fi connections
autish wifi ls

# Connect to a network
autish wifi konekti "MyNetwork" -p "mypassword"

# Show system info
autish sistemo

# Run a command and copy its output to clipboard
autish kp echo "hello"

# Copy the last captured kp output again (without re-running)
autish kp
```

---

## Documentation

Detailed command-specific documentation:

- [**VERKI.md**](VERKI.md) — AI-assisted text generation and rewriting
- [**BASH_ALIAS.md**](docs/BASH_ALIAS.md) — Bash alias management (`sistemo bash alias`)
- [**KONTAKTO.md**](docs/KONTAKTO.md) — Contact management with markdown links
- [**ENCIK.md**](ENCIK.md) — Encyclopedia (terminology and definitions)
- [**VORTO.md**](VORTO.md) — Word vocabulary management

All commands support Esperanto keywords and work offline by default. AI-backed commands (verki, encik generi, retposto analizi/generi) require API keys for online features; see [VERKI.md](VERKI.md) for setup.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for style guide and development instructions.

---

## Roadmap

See [TODO.md](TODO.md) for the detailed implementation plan and roadmap.

---

## License

[GPL-3.0](LICENSE)
