Microapps
=========

autish includes several **microapplications** that use persistent SQLite databases
for local data storage. These apps provide personal information management
capabilities with offline-first design.

What is a Microapp?
--------------------

Microapps in autish are specialized tools that:

* Store data in **SQLite databases** under ``~/.local/share/autish/``
* Use **WAL journal mode** for performance
* Support **offline operation** by default
* Include **import/export** capabilities (typically JSON/TOML)
* Implement **bidirectional relationships** (e.g., ``ligilo`` links)

Available Microapps
--------------------

:doc:`vorto` — Personal Wordbook
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Store and search personal vocabulary entries with multilingual support.
Data is stored in ``~/.local/share/autish/vorto.db``.

:doc:`encik` — Knowledge Base
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Personal encyclopedia with semantic linking and Wikidata integration.
Supports bidirectional ``ligilo`` relationships.
Data is stored in ``~/.local/share/autish/encik.db``.

:doc:`retposto` — Email Management
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Local email client with folder management and filtering capabilities.
Data is stored in ``~/.local/share/autish/retposto.db``.

:doc:`kontakto` — Contact Management
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Personal contact database with vCard export support.
Data is stored in ``~/.local/share/autish/kontakto.db``.

:doc:`taglibro` — Daily Journal
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Daily journal with date-based entries and search capabilities.
Data is stored in ``~/.local/share/autish/taglibro.db``.

:doc:`todo` — Task Management
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Task manager with status tracking (open, done, deferred, cancelled).
Data is stored in ``~/.local/share/autish/todo.db``.

:doc:`kalendaro` — Calendar
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Calendar application with event management.
Data is stored in ``~/.local/share/autish/kalendaro.db``.

Database Optimization
---------------------

Microapps follow strict database optimization standards:

* Indexes on frequently searched columns (``teksto``, ``titolo``, ``uuid``)
* Normalized search text columns with indexes for case-insensitive matching
* SQL ``WHERE`` clauses instead of Python-side filtering
* Connection reuse within transactions (not per-query)
* Target: add operations complete in <100ms with 10k+ entries

.. toctree::
   :maxdepth: 1

   vorto
   encik
   retposto
   kontakto
   taglibro
   todo
   kalendaro
