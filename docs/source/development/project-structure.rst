Project Structure
===============

::

   autish/
   ├── autish/                  # Main Python package
   │   ├── __init__.py
   │   ├── main.py              # Typer app entry point; registers all sub-apps
   │   ├── i18n.py              # Internationalization helpers
   │   ├── utils.py             # Common utility functions
   │   ├── commands/            # One module per command group
   │   │   ├── __init__.py
   │   │   ├── tempo.py
   │   │   ├── wifi.py
   │   │   ├── bluhdento.py
   │   │   ├── sistemo.py
   │   │   ├── kp.py
   │   │   ├── vorto.py
   │   │   ├── retposto.py
   │   │   ├── kontakto.py
   │   │   ├── verki.py
   │   │   └── ... (22 commands total)
   │   └── services/            # Service-layer modules
   │       ├── __init__.py
   │       ├── db_base.py
   │       ├── ai_common.py
   │       ├── bash_alias.py
   │       └── providers/
   │           ├── __init__.py
   │           ├── base.py
   │           └── huggingface.py
   ├── tests/                   # pytest tests (mirror package structure)
   │   ├── __init__.py
   │   ├── test_tempo.py
   │   ├── test_vorto.py
   │   └── ...
   ├── docs/                    # Documentation
   │   ├── source/              # Sphinx source files
   │   ├── man/                # Man page markdown files
   │   └── ...
   ├── pyproject.toml          # Poetry build config, deps, entry points, tool config
   ├── poetry.lock             # Locked dependency versions (commit this file)
   ├── README.md
   ├── CONTRIBUTING.md
   └── AGENTS.md               # Root project rules for AI agents

Microapp Data Storage
---------------------

Microapps use SQLite for persistent data storage:

* Database location: ``~/.local/share/autish/``
* Database files: ``vorto.db``, ``encik.db``, ``retposto.db``, etc.
* Journal mode: **WAL** (Write-Ahead Logging)
* JSON stored in ``TEXT`` columns when appropriate

Command Module Structure
------------------------

Each command module follows this pattern:

.. code-block:: python

   """command_name — short description.

   Usage:
       command_name subcommand [OPTIONS]...
   """

   import typer
   from rich.console import Console

   app = typer.Typer(
       name="command_name",
       help="...",
       no_args_is_help=False,
       context_settings={"help_option_names": ["-h", "--help"]},
   )

   console = Console()

   @app.command("subcommand")
   def subcommand_handler(...) -> None:
       """Subcommand description."""
       ...
