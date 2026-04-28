Testing
=======

autish uses `pytest <https://pytest.org/>`_ and `pytest-mock
<https://pytest-mock.readthedocs.io/>`_ for testing.

Running Tests
-------------

.. code-block:: bash

   # Run all tests
   poetry run pytest

   # Run tests with verbose output
   poetry run pytest -v

   # Run a specific test file
   poetry run pytest tests/test_tempo.py

   # Run a specific test function
   poetry run pytest tests/test_tempo.py::test_specific_function

Test Structure
--------------

Tests mirror the package structure under the ``tests/`` directory:

.. code-block:: text

   tests/
   ├── __init__.py
   ├── test_tempo.py
   ├── test_vorto.py
   ├── test_encik.py
   ├── test_kontakto.py
   └── conftest.py

Every command module **must** have a corresponding test file under ``tests/``.

Writing Tests
-------------

Example test:

.. code-block:: python

   from typer.testing import CliRunner
   from autish.commands.tempo import app

   runner = CliRunner()

   def test_tempo_help():
       result = runner.invoke(app, ["--help"])
       assert result.exit_code == 0
       assert "tempo" in result.output

   def test_tempo_default():
       result = runner.invoke(app)
       assert result.exit_code == 0

Test Coverage
-------------

Test coverage is important for ensuring reliability. Aim for:

* All command entry points tested
* All subcommands tested
* Error handling tested
* Edge cases covered

Database Testing
-----------------

For microapps with SQLite databases:

* Use temporary databases in tests
* Clean up after each test
* Test import/export functionality
* Test undo/redo functionality where applicable

CI Integration
---------------

Tests should pass in CI before merging:

.. code-block:: bash

   # Local pre-commit check
   poetry run pytest
   poetry run ruff check .
   poetry run ruff format --check .
