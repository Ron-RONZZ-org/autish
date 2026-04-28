Development Setup
================

This guide covers how to set up your development environment for autish.

Requirements
------------

* **Target platform (v0.0.1):** Debian-based Linux (Ubuntu, Debian, Mint, …)
* **Python version:** 3.10+
* **Dependency manager:** `Poetry <https://python-poetry.org/>`_ ≥ 2.0
* **CLI framework:** `Typer <https://typer.tiangolo.com/>`_

Install Poetry
--------------

.. code-block:: bash

   curl -sSL https://install.python-poetry.org | python3 -

Ensure Poetry's bin directory (``~/.local/bin``) is on your PATH:

.. code-block:: bash

   echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
   source ~/.bashrc
   poetry --version

Clone and Install
------------------

.. code-block:: bash

   git clone https://github.com/Ron-RONZZ-org/autish.git
   cd autish

   # Install all dependencies (runtime + dev) into an isolated virtualenv
   poetry install

   # Verify the CLI works
   poetry run autish --help

Activate Poetry Shell (Optional)
---------------------------------

Instead of prefixing every command with ``poetry run``, you can activate the
virtualenv directly:

.. code-block:: bash

   poetry shell    # spawns a subshell with the venv active
   autish --help   # no prefix needed
   exit            # return to your normal shell

Global Installation (Recommended for Full Functionality)
--------------------------------------------------------

To use bash aliases and have ``autish`` available system-wide, install it globally:

.. code-block:: bash

   cd /path/to/autish
   poetry install
   autish sistemo install           # Install in ~/.local/bin (default, no sudo needed)
   # or for system-wide:
   sudo autish sistemo install --sistema  # Install in /usr/local/bin (requires sudo)

Verify Installation
--------------------

.. code-block:: bash

   which autish     # Should output ~/.local/bin/autish (or /usr/local/bin/autish)
   autish --help    # Should work without 'poetry run'
