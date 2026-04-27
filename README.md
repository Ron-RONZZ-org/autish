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

**Note:** verki may surface router/Cloudflare or host-blocking errors (403/Error 1010 or HTML 404 fallback). See VERKI.md Troubleshooting for recommended actions (try another model/network or contact model owner).
| `autish verki modelo` | Browse available AI models |

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

### 4. Install autish globally (RECOMMENDED for full functionality)

**To use bash aliases and have `autish` available system-wide, install it globally:**

```bash
cd /path/to/autish
poetry install
autish sistemo install           # Install in ~/.local/bin (default, no sudo needed)
# or for system-wide:
sudo autish sistemo install --sistema  # Install in /usr/local/bin (requires sudo)
```

**What this does:**
- Creates a symlink to the `autish` binary from your Poetry environment
- Makes `autish` available in any shell session without activating Poetry
- Ensures bash aliases work correctly (e.g., `ess='autish encik serci -sk'`)
- Regenerates existing bash aliases to work with the global installation

**Required PATH setup (user scope only):**

If you installed to `~/.local/bin` (default), ensure `~/.local/bin` is on your PATH:

```bash
# Check if already present
echo $PATH | grep -q "$HOME/.local/bin" && echo "✓ PATH OK" || echo "✗ Add ~/.local/bin to PATH"

# Add to PATH if needed
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

Verify installation:

```bash
which autish     # Should output ~/.local/bin/autish (or /usr/local/bin/autish)
autish --help    # Should work without 'poetry run'
```

### 5. Manual setup (alternative — not recommended)

If you prefer manual setup without using `autish sistemo install`:

```bash
# Find the virtualenv path
poetry env info --path

# Example output: /home/youruser/.cache/pypoetry/virtualenvs/autish-XYZ-py3.12
# Add its bin/ to PATH:
echo 'export PATH="$(poetry -C /path/to/autish env info --path)/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

Or create a symlink manually:

```bash
ln -s "$(poetry env info --path)/bin/autish" ~/.local/bin/autish
autish --help
```

### 6. Run tests and linting

```bash
# Run tests
poetry run pytest

# Lint and format check
poetry run ruff check .
poetry run ruff format --check .

# Auto-format
poetry run ruff format .
```

### 7. Build a distributable package

```bash
poetry build
# Creates dist/autish-0.0.1.tar.gz and dist/autish-0.0.1-py3-none-any.whl
```

---

## Documentation

### Command Reference

Complete documentation for all 22 autish commands is available in the [Manual Pages](docs/man/INDEX.md) directory:

- View all commands: [docs/man/INDEX.md](docs/man/INDEX.md)
- Query-specific command help with: `autish {command} --help`
- Example: `autish vorto --help` for personal wordbank documentation

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

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for style guide and development instructions.

---

## Roadmap

See [TODO.md](TODO.md) for the detailed implementation plan and roadmap.

---

## License

[GPL-3.0](LICENSE)
