"""Timestamps: every column stores UTC and reads back aware, so every time the
API sends carries its zone (a time without one is read as local by browsers)."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import DateTime

from app import models  # noqa: F401  — register mappings on Base.metadata
from app.db import Base
from app.models import User


@pytest.fixture(autouse=True)
def _no_hibp(monkeypatch):
    monkeypatch.setattr("app.auth.password_breach_count", lambda pw: 0)


def test_every_datetime_column_is_utc():
    plain = [
        f"{t.name}.{c.name}"
        for t in Base.metadata.tables.values()
        for c in t.columns
        if isinstance(c.type, DateTime)
    ]
    assert plain == []


def test_reads_back_aware_utc(TestSession, make_user):
    make_user(username="alice")
    db = TestSession()
    hk = timezone(timedelta(hours=8))
    user = db.query(User).one()
    user.last_login_at = datetime(2026, 11, 8, 11, 59, tzinfo=hk)
    db.commit()
    db.expire_all()
    assert db.query(User).one().last_login_at == datetime(2026, 11, 8, 3, 59, tzinfo=timezone.utc)
    assert db.query(User).one().last_login_at.tzinfo is timezone.utc


def test_refuses_naive(TestSession, make_user):
    make_user(username="alice")
    db = TestSession()
    db.query(User).one().last_login_at = datetime(2026, 11, 8, 3, 59)
    with pytest.raises(Exception, match="aware datetime"):
        db.commit()


def test_api_times_carry_their_zone(client, make_user):
    make_user(username="admin", is_admin=True)
    assert client.post("/login", data={"username": "admin", "password": "hunter2-secret"}).status_code == 200
    user = client.get("/users").json()[0]
    assert user["created_at"].endswith("+00:00")
    assert user["last_login_at"].endswith("+00:00")
