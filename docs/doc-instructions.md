# Documentation Setup and Publishing Guide

This guide explains how to set up dependencies, build the Sphinx documentation
locally, and publish to ReadTheDocs.

## Prerequisites

* **Python 3.10+** installed
* **pip** or **poetry** for installing dependencies
* **Git** repository hosted on GitHub (for ReadTheDocs integration)
* **ReadTheDocs account** (free for open-source projects)

---

## Step 1: Install Documentation Dependencies

### Option A: Using pip

```bash
# Install Sphinx and required extensions
pip install sphinx sphinx_rtd_theme myst-parser sphinx_copybutton

# Or install from the requirements file
pip install -r docs/requirements.txt
```

### Option B: Using Poetry (recommended for autish developers)

Add the documentation dependencies to your development environment:

```bash
# Install all autish dependencies including docs
poetry install

# Activate the virtual environment
poetry shell

# Or run commands with poetry run prefix
poetry run sphinx-build --version
```

### Option C: Install from requirements.txt

```bash
cd /path/to/autish
pip install -r docs/requirements.txt
```

The `docs/requirements.txt` includes:
- `sphinx>=7.0`
- `sphinx_rtd_theme`
- `myst-parser`
- `sphinx_copybutton`
- All autish runtime dependencies (needed for autodoc)

---

## Step 2: Build Documentation Locally

### Quick Build

```bash
cd /path/to/autish/docs
make html
```

The built documentation will be in `docs/build/html/`.

### View Locally

```bash
# Open in your default browser
xdg-open docs/build/html/index.html

# Or with a specific browser
firefox docs/build/html/index.html
chromium docs/build/html/index.html
```

### Other Build Targets

```bash
cd docs

# Clean previous builds
make clean

# Build HTML (default)
make html

# Build PDF (requires LaTeX)
make latexpdf

# Build ePub
make epub

# Check for broken links
make linkcheck

# Show all available targets
make help
```

### Common Build Issues

**Issue: `sphinx-build: command not found`**
```bash
# Make sure sphinx is installed
pip install sphinx

# Or use poetry run
poetry run sphinx-build --version
```

**Issue: `myst_parser not found`**
```bash
pip install myst-parser
```

**Issue: Autodoc can't import autish**
```bash
# Make sure you're in the autish root directory
cd /path/to/autish

# Or install autish in development mode
pip install -e .
```

---

## Step 3: Set Up ReadTheDocs

### 3.1 Create ReadTheDocs Account

1. Go to https://readthedocs.org/
2. Click **"Sign up"**
3. Sign up using your **GitHub account** (recommended) or email
4. Confirm your email address

### 3.2 Connect Your GitHub Repository

1. Log in to ReadTheDocs
2. Click **"Import a Project"**
3. Authorize ReadTheDocs to access your GitHub account
4. Find and select the **`Ron-RONZZ-org/autish`** repository
5. Click **"Next"**

### 3.3 Configure Project Settings

On the configuration page, set:

| Setting | Value |
|---------|-------|
| **Name** | `autish` |
| **Repository URL** | `https://github.com/Ron-RONZZ-org/autish.git` |
| **Default branch** | `main` (or `master`) |
| **Language** | `English` (or `Esperanto` if available) |
| **Programming Language** | `Python` |

### 3.4 Advanced Settings (Optional)

In your project dashboard, go to **Admin** → **Advanced Settings**:

| Setting | Value |
|---------|-------|
| **Requirements file** | `docs/requirements.txt` |
| **Documentation type** | `Sphinx HTML` |
| **Build environment** | `Ubuntu 22.04` |
| **Python interpreter** | `CPython 3.12` |

Click **"Save"**.

---

## Step 4: The `.readthedocs.yaml` Configuration

The repository already includes `.readthedocs.yaml` at the root:

```yaml
version: 2

build:
  os: ubuntu-22.04
  tools:
    python: "3.12"

python:
  install:
    - requirements: docs/requirements.txt
    - path: .

sphinx:
  configuration: docs/source/conf.py

formats:
  - pdf
  - epub
```

This file tells ReadTheDocs:
- Which OS and Python version to use
- Which requirements file to install
- Where to find the Sphinx configuration
- Which output formats to build (HTML, PDF, ePub)

---

## Step 5: Trigger a Build

### Automatic Builds

Once connected, ReadTheDocs will **automatically build** documentation when you:
- Push to the default branch (`main`/`master`)
- Create a new tag (for versioned documentation)
- Create a pull request (for preview builds)

### Manual Build

1. Go to your project on ReadTheDocs
2. Click **"Builds"** tab
3. Click **"Build Version"** button
4. Select the branch/tag to build
5. Click **"Build"**

### Monitor Build Progress

- Click on a build in the **"Builds"** tab to see the build log
- Green checkmark = successful build
- Red X = build failed (click to see error log)

---

## Step 6: Access Your Documentation

After a successful build:

### Main Documentation URL
```
https://autish.readthedocs.io/
```

### Version-Specific URLs
```
https://autish.readthedocs.io/en/latest/    # Latest development version
https://autish.readthedocs.io/en/stable/   # Stable release (if configured)
https://autish.readthedocs.io/en/v0.0.1/  # Tag-based version
```

---

## Step 7: Configure Versions (Optional)

### Enable Versioning

1. Go to project **Admin** → **Versions**
2. Activate the versions you want to build:
   - `latest` (tracks default branch)
   - `stable` (tracks a specific branch/tag)
   - Specific tags (e.g., `v0.0.1`)

### Set Default Version

1. Go to **Admin** → **Advanced Settings**
2. Set **"Default version"** to `latest` or `stable`
3. Click **"Save"**

---

## Troubleshooting

### Build Fails with "ImportError: No module named 'autish'"

**Solution:** The `.readthedocs.yaml` already includes `- path: .` to install autish. If still failing:
- Check that `pyproject.toml` is valid
- Ensure `packages = [{ include = "autish" }]` is set

### Build Fails with "myst_parser not found"

**Solution:** Ensure `docs/requirements.txt` includes `myst-parser`.

### PDF Build Fails

PDF builds require LaTeX. ReadTheDocs uses `latexmk` and TeXLive.

**Solution:**
- Check the build log for missing LaTeX packages
- Add required packages to `.readthedocs.yaml` (advanced)
- Or disable PDF builds in **Admin** → **Advanced Settings**

### Documentation Not Updating

**Solution:**
1. Check that you pushed to the correct branch
2. Verify webhook is working (GitHub → Settings → Webhooks)
3. Manually trigger a build in ReadTheDocs

---

## Quick Reference

| Task | Command/Action |
|------|----------------|
| Install deps | `pip install -r docs/requirements.txt` |
| Build locally | `cd docs && make html` |
| View locally | `xdg-open docs/build/html/index.html` |
| Clean build | `cd docs && make clean` |
| RTD dashboard | https://readthedocs.org/dashboard/ |
| RTD builds | https://readthedocs.org/projects/autish/builds/ |

---

## Next Steps

After publishing:

1. **Add documentation link** to `README.md`:
   ```markdown
   [Documentation](https://autish.readthedocs.io/)
   ```

2. **Set up badge** in `README.md`:
   ```markdown
   [![Documentation Status](https://readthedocs.org/projects/autish/badge/?version=latest)](https://autish.readthedocs.io/en/latest/?badge=latest)
   ```

3. **Announce** the documentation in your project's README and release notes

4. **Maintain** documentation by:
   - Updating `docs/source/` files when adding features
   - Running `make html` locally to verify changes
   - Committing and pushing to trigger RTD builds
