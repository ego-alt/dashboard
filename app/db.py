import os
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator, Optional

from sqlalchemy import DateTime, create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./data/dashboard.db")

_engine_kwargs: dict = {}
if DATABASE_URL.startswith("sqlite"):
    _engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, **_engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


class UtcDateTime(TypeDecorator):
    """A timestamp stored as naive UTC and always read back as aware UTC.

    SQLite drops the zone, and a time sent without one is read by browsers as
    local time (8 hours early in Hong Kong). Every DateTime column uses this,
    so code only ever sees aware UTC and ``isoformat()`` always ends in +00:00.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: Optional[datetime], dialect) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("UtcDateTime needs an aware datetime, not a naive one")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value: Optional[datetime], dialect) -> Optional[datetime]:
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


# Additive column migrations run at boot. Cheap stand-in for Alembic — fine
# while the dashboard is a single-process home-stack DB. Append when adding
# new columns to existing tables; create_all handles new tables.
_ADDITIVE_MIGRATIONS: list[tuple[str, str, str]] = [
    ("users", "totp_secret", "VARCHAR(64)"),
    ("users", "totp_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
    ("users", "totp_recovery_codes", "TEXT"),
    ("user_sessions", "mfa_pending", "BOOLEAN NOT NULL DEFAULT 0"),
    ("user_sessions", "last_seen_at", "DATETIME"),
]


def _apply_additive_migrations(bind=None) -> None:
    target = bind or engine
    insp = inspect(target)
    table_names = set(insp.get_table_names())
    for table, col, col_def in _ADDITIVE_MIGRATIONS:
        if table not in table_names:
            continue  # create_all already added the column when creating the table
        existing = {c["name"] for c in insp.get_columns(table)}
        if col in existing:
            continue
        with target.begin() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}"))


def init_db() -> None:
    from . import models  # noqa: F401  — register mappings on Base.metadata
    Base.metadata.create_all(bind=engine)
    _apply_additive_migrations()


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
