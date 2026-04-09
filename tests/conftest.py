"""pytest configuration — in-memory SQLite fixture."""
from __future__ import annotations

from pathlib import Path

import pytest

from career_agent.db.engine import get_engine, get_session, init_db
from career_agent.models.job import Base

# Use an in-memory SQLite DB for tests
_TEST_DB = Path(":memory:")


@pytest.fixture(autouse=True)
def reset_engine(tmp_path):
    """Redirect the DB engine to a fresh temp file for each test."""
    import career_agent.db.engine as eng
    import career_agent.db.repository as repo

    db_path = tmp_path / "test_jobs.db"

    # Reset module-level singletons
    eng._engine = None
    eng._SessionLocal = None

    # Patch the default path used by repository functions
    original_get_session = eng.get_session
    original_get_engine = eng.get_engine

    def patched_get_session(path=None):
        return original_get_session(db_path)

    def patched_get_engine(path=None):
        return original_get_engine(db_path)

    eng.get_session = patched_get_session
    eng.get_engine = patched_get_engine
    repo.get_session = patched_get_session

    init_db(db_path)
    yield

    # Teardown
    eng.get_session = original_get_session
    eng.get_engine = original_get_engine
    repo.get_session = original_get_session
    eng._engine = None
    eng._SessionLocal = None
