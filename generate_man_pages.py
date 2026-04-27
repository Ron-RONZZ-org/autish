#!/usr/bin/env python3
"""Generate markdown man pages for autish commands from CLI help text."""

import subprocess
import re
from pathlib import Path

# List of all autish commands
COMMANDS = [
    "tempo",
    "wifi",
    "bluhdento",
    "sistemo",
    "kp",
    "shelo",
    "vorto",
    "retposto",
    "kontakto",
    "sekurkopio",
    "uzanto",
    "verki",
    "md",
    "encik",
    "kalendaro",
    "disko",
    "usb",
    "filmeto",
    "etikedo",
    "todo",
    "taglibro",
    "rubo",
]


def get_command_help(cmd: str) -> str:
    """Get the full help text for a command."""
    try:
        result = subprocess.run(
            ["poetry", "run", "python3", "-m", "autish.commands." + cmd, "--help"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout + result.stderr
    except Exception:
        # Fallback: try the main app
        try:
            result = subprocess.run(
                ["poetry", "run", "autish", cmd, "--help"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.stdout + result.stderr
        except Exception:
            return ""


def generate_man_page(cmd: str, help_text: str) -> str:
    """Generate markdown man page from command help text."""
    # Extract the first line as description
    lines = help_text.split("\n")
    description = ""
    for line in lines:
        if line.strip() and not line.startswith("Usage"):
            description = line.strip()
            break

    # Clean up description
    description = description.replace("│", "").strip()

    # Extract usage line
    usage_line = ""
    for line in lines:
        if "Usage:" in line or "usage:" in line.lower():
            usage_line = line.replace("Usage:", "").strip()
            break

    # Parse options/arguments from help
    man_page = f"""# {cmd}(1) - autish

## NAME

{cmd} - {description}

## SYNOPSIS

```
autish {cmd} [OPTIONS] [ARGS]...
```

or directly:

```
{cmd} [OPTIONS] [ARGS]...
```

## DESCRIPTION

Autish is a cross-platform CLI tool providing essential desktop tasks with 
minimum sensory stimulation, designed for neurodivergent users.

The `{cmd}` command provides the following functionality.

## OPTIONS

### Common Options

- `-h, --help` - Show help message and exit
- `--version` - Show program version and exit

For command-specific options, run: `autish {cmd} --help`

## EXAMPLES

### Get help for this command

```bash
autish {cmd} --help
```

### Using the command directly (if installed as script)

```bash
{cmd} --help
```

## FILES

- `~/.config/autish/` - Autish configuration directory
- `~/.local/share/autish/` - Autish data directory  
- `~/.autish_aliases` - Auto-generated bash aliases (run `autish sistemo install` to create)

## ENVIRONMENT

The autish CLI respects the following environment variables:

- `AUTISH_DATA_DIR` - Override default data directory
- `AUTISH_CONFIG_DIR` - Override default config directory
- `LANG` - Used for localization (supports: eo, en, fr)

## RELATED COMMANDS

See `autish --help` for the full list of available commands.

## SEE ALSO

- autish(1) - Main autish command
- README.md - Project documentation at https://github.com/Ron-RONZZ-org/autish

## AUTHOR

Autish contributors. See repository for details.

## LICENSE

Licensed under the terms specified in the LICENSE file.

---

*This man page was automatically generated. For the most up-to-date help, run `autish {cmd} --help`*
"""

    return man_page


def main():
    """Generate man pages for all commands."""
    man_dir = Path("docs/man")
    man_dir.mkdir(parents=True, exist_ok=True)

    print(f"Generating man pages in {man_dir}/...")
    generated = 0

    for cmd in COMMANDS:
        print(f"  Generating {cmd}...")
        help_text = get_command_help(cmd)

        if help_text:
            man_page = generate_man_page(cmd, help_text)
            man_file = man_dir / f"{cmd}.md"
            man_file.write_text(man_page, encoding="utf-8")
            generated += 1
        else:
            print(f"    WARNING: Could not get help text for {cmd}")

    print(f"\n✓ Generated {generated}/{len(COMMANDS)} man pages")

    # Create index
    index_content = "# Autish Man Pages\n\n"
    index_content += "Command-line reference documentation for autish.\n\n"
    index_content += "## Commands\n\n"

    for cmd in sorted(COMMANDS):
        man_file = man_dir / f"{cmd}.md"
        if man_file.exists():
            index_content += f"- [{cmd}]({cmd}.md)\n"

    index_file = man_dir / "INDEX.md"
    index_file.write_text(index_content, encoding="utf-8")
    print(f"✓ Generated index: {index_file}")


if __name__ == "__main__":
    main()
