API Reference
=============

This section provides API documentation for autish's Python modules.
The documentation is generated from docstrings using Sphinx autodoc.

Core Modules
------------

:mod:`autish.main` — Main Typer Application
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The main entry point for the autish CLI. Registers all sub-applications
and provides the root Typer app.

.. automodule:: autish.main
   :members:
   :undoc-members:
   :show-inheritance:

:mod:`autish.i18n` — Internationalization Helpers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Simple CLI i18n helpers for Typer built-in help strings. Supports
Esperanto, English, and French locales.

.. automodule:: autish.i18n
   :members:
   :undoc-members:
   :show-inheritance:

:mod:`autish.utils` — Utility Functions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Common utility functions used across autish commands, including text
matching, search helpers, and browser integration.

.. automodule:: autish.utils
   :members:
   :undoc-members:
   :show-inheritance:

Services
--------

:mod:`autish.services` — Service Layer
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Service-layer modules for autish commands, including database base classes,
AI integration, and system services.

.. automodule:: autish.services
   :members:
   :undoc-members:
   :show-inheritance:

.. toctree::
   :maxdepth: 1

   main
   i18n
   utils
   services
