"""Shared pytest configuration and fixtures for autish tests."""

from __future__ import annotations

import pytest
from unittest.mock import patch


@pytest.fixture(autouse=True)
def mock_webbrowser_globally():
    """Globally mock webbrowser.open() to prevent browser windows from opening during tests.

    This fixture is automatically used by all tests (autouse=True) and prevents
    actual browser windows from being opened during test runs, which would disrupt
    development workflows. Tests that need custom behavior can still override this
    by using their own patch decorators or monkeypatch.
    """
    with patch("webbrowser.open", return_value=True):
        yield
