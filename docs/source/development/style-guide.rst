Style Guide
===========

Python Style
------------

* Follow **PEP 8** (line length 88, use ``ruff`` for linting/formatting)
* Use **type hints** on all public functions
* Keep functions small and single-purpose
* Prefer **f-strings** over ``.format()`` or ``%``
* Do not use ``print()`` directly; use Typer's ``typer.echo()`` or ``rich``-based output

Linting and Formatting
-----------------------

.. code-block:: bash

   # Lint
   poetry run ruff check .

   # Auto-format
   poetry run ruff format .

   # Check formatting without changes
   poetry run ruff format --check .

Esperanto Keyword Policy
-------------------------

All **command names and long option names** must be in Esperanto. This lowers
the barrier for non-English speakers. Short single-letter flags may use any
letter that is intuitive (e.g. ``-p`` for password/pasvorto).

Examples: ``tempo``, ``wifi``, ``konekti``, ``malkonekti``, ``forigi``,
``horzono``, ``sistemo``, ``bluhdento``.

Naming Conventions
-------------------

.. list-table::
   :header-rows: 1

   * - Concept
     - Convention
   * - CLI commands / options
     - Esperanto, lowercase, hyphen-separated
   * - Python identifiers
     - English, ``snake_case``
   * - Test functions
     - ``test_<what>_<condition>``

Short CLI Flag Alias Convention (Priority Order)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

1. First letter of long option name in lowercase (e.g. ``-i`` for ``--instrukcio``)
2. First letter in uppercase if lowercase conflicts (e.g. ``-L`` for ``--ligilo``)
3. First letter of each word in sequence if further specificity needed (e.g. ``-td`` for ``--teksto-dosiero``)

Option Alias Normalization
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Use ``-L`` for ``--ligilo``, ``-l`` for ``--lingvo``/``--lingvoj``, and ``-lo``
for ``--limo``.

Commit Messages
----------------

Use `Conventional Commits <https://www.conventionalcommits.org/>`_:

* ``feat:`` new feature
* ``fix:`` bug fix
* ``docs:`` documentation only
* ``chore:`` tooling / maintenance
* ``test:`` tests only

Keep commits small and focused (one logical change per commit).

Output Guidelines
------------------

* **No bare ``print()``** — use ``typer.echo()`` or ``rich.print()`` / ``rich.console.Console``
* **Type-hint** all public functions
* **Keep output calm and minimal** — no spinners, animations, or excessive colour
* **Use muted colours** (dim, cyan)
* **Errors go to stderr** — use ``typer.echo(..., err=True)`` or ``typer.BadParameter``
* **Action notifications must auto-expire** — transient messages should clear after ~3 seconds
