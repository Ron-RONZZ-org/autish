Installation
============

Requirements
-------------

* **Python**: 3.10 or higher
* **Platform**: Debian-based Linux (Ubuntu, Debian, Mint, ...) for v0.0.1
* **Dependency manager**: Poetry ≥ 2.0 (for development)

Option A — Install from PyPI (recommended for regular users)
------------------------------------------------------------

.. code-block:: bash

   pip install --user autish

After installing with ``--user``, the ``autish`` command is placed in
``~/.local/bin/``. If that directory is not already on your ``PATH``, add it:

.. code-block:: bash

   # Add to ~/.bashrc (bash) or ~/.zshrc (zsh)
   echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
   source ~/.bashrc

Verify the install:

.. code-block:: bash

   autish --help

Option B — Install with pipx (recommended for isolated global install)
---------------------------------------------------------------------

`pipx <https://pipx.pypa.io/>`_ installs CLI tools in isolated environments and
automatically adds them to your ``PATH``:

.. code-block:: bash

   # Install pipx if not already present
   pip install --user pipx
   pipx ensurepath          # adds ~/.local/bin to PATH; restart your shell after

   # Install autish
   pipx install autish

   # Verify
   autish --help

Making autish available system-wide
------------------------------------

If you want ``autish`` available for all users on the machine:

.. code-block:: bash

   sudo pip install autish
   # or with pipx:
   sudo pipx install autish --global

Development Setup
-----------------

See :doc:`development/setup` for detailed instructions on setting up a
development environment.
