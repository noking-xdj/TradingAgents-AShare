"""Deterministic process-wide test database setup.

The application database module creates its engine at import time, so the
temporary URL must be installed before pytest imports any test module that
touches ``api.database``.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest


_TEST_DB_DIR = Path(tempfile.mkdtemp(prefix="tradingagents-pytest-"))
_TEST_DB_PATH = _TEST_DB_DIR / "tradingagents-test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_PATH}"


@pytest.fixture(scope="session", autouse=True)
def initialized_test_database():
    """Create every registered table once on a brand-new database per run."""
    from api import main as _api_main  # noqa: F401 - registers application models
    from api.database import engine, init_db

    assert not _TEST_DB_PATH.exists(), "pytest database must start empty"
    init_db()
    yield
    engine.dispose()
    shutil.rmtree(_TEST_DB_DIR, ignore_errors=True)
