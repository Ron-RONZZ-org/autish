Contributing
============

Thank you for your interest in contributing to autish!

Submitting Changes
------------------

1. Fork the repo and create a feature branch:

   .. code-block:: bash

      git checkout -b feat/my-feature

2. Make your changes following the :doc:`style-guide`.

3. Add or update tests under ``tests/``.

4. Run tests and linting locally before opening a PR:

   .. code-block:: bash

      poetry run pytest
      poetry run ruff check .
      poetry run ruff format --check .

5. Open a Pull Request with a clear description of *what* changed and *why*.

6. Link any related issues in the PR description.

Pull Request Guidelines
-----------------------

* Keep PRs focused on a single logical change
* Write a clear PR title and description
* Include ``Fixes #issue_number`` in the description if applicable
* Ensure all tests pass
* Follow the :doc:`style-guide`
* Use `Conventional Commits <https://www.conventionalcommits.org/>`_ style for PR title

Code of Conduct
----------------

Be kind, patient, and inclusive. This project is designed with neurodivergent
people in mind — that ethos extends to our contributor community.

Communication Guidelines
~~~~~~~~~~~~~~~~~~~~~~~~~

* Be **clear and direct** in communication
* Be **patient** with questions and explanations
* Be **inclusive** of different communication styles
* Be **respectful** of boundaries and sensory needs
* Assume **good faith** in all interactions

Reporting Issues
-----------------

When reporting issues, please include:

* autish version (``autish --help`` or check ``pyproject.toml``)
* Python version (``python --version``)
* OS version (``lsb_release -a`` or ``uname -a``)
* Steps to reproduce the issue
* Expected vs actual behaviour
* Any relevant error messages or logs

Feature Requests
-----------------

For feature requests, please:

* Check existing issues to avoid duplicates
* Clearly describe the use case
* Explain why this feature would be beneficial
* Consider if it aligns with autish's philosophy (minimum stimulation, neurodiversity-first)
