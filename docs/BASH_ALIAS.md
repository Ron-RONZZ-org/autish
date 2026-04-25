# Bash Alias Management

Autish provides a simple way to manage bash aliases through the CLI without directly editing `~/.bashrc`. This ensures your aliases are version-controlled and easily portable.

## Overview

The `sistemo bash alias` subcommand lets you:
- **Add** new bash aliases with optional notes
- **Modify** existing aliases
- **Delete** aliases (with confirmation)
- **View** single alias details
- **List** all aliases with sorting and pagination
- **Search** aliases with fuzzy matching

## Database Storage

Aliases are stored in an SQLite database at `~/.config/autish/bash_aliases.db`. Each alias is assigned a sequential UID that is never recycled, ensuring referential integrity.

## Shell Integration

After managing aliases, autish generates a shell script at `~/.autish_aliases` containing all your aliases. To use these aliases in your shell, source the file in your `~/.bashrc`:

```bash
# Add this to ~/.bashrc:
source ~/.autish_aliases
```

This approach keeps your main `.bashrc` clean and lets autish manage aliases declaratively.

## Commands

### Add a Bash Alias

```bash
sistemo bash aldoni --alias "ll" --function "ls -lah" --notes "List all files with details"
```

**Options:**
- `--alias TEXT` (required): The alias name (e.g., `ll`)
- `--function TEXT` (required): The command to execute
- `--notes TEXT` (optional): Markdown notes (supports `[text](ec#uuid)` and `[text](vt#uuid)` links)

**Example with markdown link:**
```bash
sistemo bash aldoni --alias "prot" --function "print | lpr" --notes "Print to [encik](ec#12345678)"
```

### Modify an Alias

```bash
sistemo bash modifi 1 --function "ls -la"
```

**Options:**
- `{uid}` (positional, required): Alias UID
- `--alias TEXT` (optional): New alias name
- `--function TEXT` (optional): New function
- `--notes TEXT` (optional): New notes

### Delete an Alias

```bash
sistemo bash forigi 1
sistemo bash forigi 1 --justa  # Skip confirmation
```

**Options:**
- `{uid}` (positional, required): Alias UID
- `--justa` / `-j` (optional): Skip confirmation prompt

### View Alias Details

```bash
sistemo bash vidi 1
```

Displays the alias UID, name, function, notes, and timestamps in a formatted table.

### List All Aliases

```bash
sistemo bash ls
sistemo bash ls --alfabeto     # Alphabetical order
sistemo bash ls --inversigi     # Reverse order
sistemo bash ls --alfabeto --inversigi
```

**Options:**
- `--alfabeto` / `-al` (optional): Sort alphabetically by alias name (default: by creation date)
- `--inversigi` / `-i` (optional): Reverse the sort order

Output is displayed in a Rich table. If the output is longer than one screen, it will be paginated.

### Search Aliases

```bash
sistemo bash serci "ls"
sistemo bash serci
```

Performs fuzzy text search across alias names, functions, and notes. Displays matching results in a table and prompts you to select one to view in detail.

## Markdown Links in Notes

Alias notes support markdown links to **encik** entries and **vorto** entries:

- **Encik link:** `[Entry Name](ec#uuid)` → Links to encik entry with UUID
- **Vorto link:** `[Word](vt#uuid)` → Links to vorto entry with UUID

Example:
```bash
sistemo bash aldoni --alias "mk" --function "make" --notes "Build tool. See [Make](ec#87654321) for details."
```

When viewing the alias with `vidi`, the links will be rendered as clickable Rich links in the CLI.

## Examples

### Create Common Aliases

```bash
# List with details
sistemo bash aldoni --alias "ll" --function "ls -lah"

# List with hidden files
sistemo bash aldoni --alias "la" --function "ls -la"

# Find files by name
sistemo bash aldoni --alias "ff" --function "find . -name"

# Grep with colors
sistemo bash aldoni --alias "grep" --function "grep --color=auto"

# Show file without pager
sistemo bash aldoni --alias "less" --function "less -F"
```

### Add Alias with Context Notes

```bash
sistemo bash aldoni \
  --alias "pydoc" \
  --function "python3 -m pydoc" \
  --notes "Python documentation viewer. See [Python Docs](vt#11223344)."
```

### Workflow Example

1. Add an alias:
   ```bash
   sistemo bash aldoni --alias "ll" --function "ls -lah"
   ```

2. List aliases:
   ```bash
   sistemo bash ls
   ```

3. Verify it in shell:
   ```bash
   source ~/.autish_aliases
   ll
   ```

4. Modify if needed:
   ```bash
   sistemo bash modifi 1 --function "ls -laoh"
   ```

5. Delete when no longer needed:
   ```bash
   sistemo bash forigi 1
   ```

## Technical Details

### UID Management

- UIDs start at 1 and increment sequentially
- Deleted aliases do not recycle their UIDs (ensures referential integrity)
- Maximum UID tracks highest ever used, not current count

### Shell Script Generation

The generated `~/.autish_aliases` script includes:
- Shebang (`#!/bin/bash`)
- Comment header explaining the file is auto-generated
- Instructions for sourcing in `~/.bashrc`
- All aliases with properly escaped shell syntax

Special characters in function definitions are automatically escaped for shell safety.

### Database Schema

```sql
CREATE TABLE bash_aliases (
    uid INTEGER PRIMARY KEY NOT NULL,
    alias TEXT UNIQUE NOT NULL,
    function TEXT NOT NULL,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE _metadata (
    key TEXT PRIMARY KEY,
    value TEXT
);
```

The `_metadata` table tracks the next available UID for non-recycling behavior.

## Troubleshooting

### Aliases Not Available in New Shell

**Problem:** You added aliases but they don't work in a new terminal.

**Solution:** Add `source ~/.autish_aliases` to your `~/.bashrc` and reload your shell:
```bash
source ~/.bashrc
```

### Alias Already Exists

**Problem:** Adding an alias fails with "Alias 'X' jam ekzistas" (already exists).

**Solution:** Either update the existing alias:
```bash
sistemo bash modifi 1 --function "new-command"
```

Or delete and re-create it:
```bash
sistemo bash forigi 1
sistemo bash aldoni --alias "ll" --function "ls -lah"
```

### Special Characters in Function

**Problem:** Your function contains quotes or special characters.

**Solution:** Autish automatically escapes characters. Just provide the raw command:
```bash
sistemo bash aldoni --alias "echo" --function "echo 'Hello, world!'"
```

## See Also

- [Autish README](../README.md) — Main documentation
- [Kontakto](KONTAKTO.md) — Contact management with markdown link support
