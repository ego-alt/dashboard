"""Database engine, declarative base, and FastAPI session dependency.

SQLite for now; flip ``DATABASE_URL`` to Postgres later without code changes.
"""

import os
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./dashboard.db")

_engine_kwargs: dict = {}
if DATABASE_URL.startswith("sqlite"):
    # FastAPI's threaded worker model + a single SQLite connection.
    _engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, **_engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    """Create tables if they don't exist. Idempotent."""
    from . import models  # noqa: F401 — register mappings on Base.metadata
    Base.metadata.create_all(bind=engine)


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
