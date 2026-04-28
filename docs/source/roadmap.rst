Roadmap
=======

This is the development roadmap for autish. It is organized by priority and
impact.

Version 0.1.0 (Next Milestone)
---------------------------------

**Core Stability**

* Add comprehensive test coverage for all 22 commands
* Improve error handling and user-facing error messages
* Add automated CI/CD pipeline (GitHub Actions)
* Complete Sphinx documentation (this documentation site)
* Add ReadTheDocs publishing

**Enhanced i18n**

* Complete French translation for all commands
* Add locale auto-detection improvements
* Add ``--lingvo`` flag consistency across all commands

**Microapp Improvements**

* Add data import/export UI improvements
* Add database migration system for schema changes
* Implement full-text search for ``encik`` and ``vorto``
* Add attachment support for ``taglibro`` entries

Version 0.2.0
---------------

**Platform Expansion**

* Add support for Fedora/RHEL-based distributions
* Add support for Arch Linux
* Consider macOS support (investigation)

**New Features**

* Add ``noto`` (notes) microapp
* Add ``pasvorto`` (password manager) integration
* Add ``sankcio`` (sync) for data synchronization
* Enhance ``verki`` with more AI providers (OpenAI, Anthropic)

**UI Improvements**

* Add optional TUI (Terminal User Interface) mode for complex commands
* Add ``fzf`` integration for interactive selection
* Improve Rich output formatting

Version 1.0.0 (Long-term)
---------------------------

**Maturity**

* API stability guarantee
* Plugin system for custom commands
* Full offline documentation bundle
* Mobile companion app (investigation)

**Accessibility**

* Screen reader optimization
* High contrast theme option
* Configurable output verbosity levels
* Sensory-friendly mode (minimal all non-essential output)

Stretch Goals
-------------

* Graphical (GUI) wrapper using Tkinter or similar
* Web interface (local server)
* Cloud backup integration (optional)
* Collaborative features (shared ``kontakto``, ``encik``)

How to Contribute
------------------

See :doc:`development/contributing` for guidelines on contributing to autish.

If you're interested in working on any of these roadmap items:

1. Check the `GitHub Issues <https://github.com/Ron-RONZZ-org/autish/issues>`_
2. Open a new issue to discuss the feature
3. Submit a Pull Request with your implementation
