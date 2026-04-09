"""SQLAlchemy engine and session factory."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from career_agent.models.job import Base
from career_agent.models.application import ApplicationRecord  # noqa: F401 — ensure table registered

_DEFAULT_DB_PATH = Path("data/jobs.db")

_engine = None
_SessionLocal = None


def get_engine(db_path: Path = _DEFAULT_DB_PATH):
    global _engine
    if _engine is None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{db_path}"
        _engine = create_engine(url, connect_args={"check_same_thread": False})
        # Enable WAL mode for better concurrent read performance
        @event.listens_for(_engine, "connect")
        def set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()
        Base.metadata.create_all(_engine)
    return _engine


def get_session(db_path: Path = _DEFAULT_DB_PATH) -> Session:
    global _SessionLocal
    engine = get_engine(db_path)
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return _SessionLocal()


def init_db(db_path: Path = _DEFAULT_DB_PATH) -> None:
    """Create all tables if they don't exist."""
    engine = get_engine(db_path)
    Base.metadata.create_all(engine)
