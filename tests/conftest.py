"""Pytest fixtures: isolated SQLite DB per test, FastAPI TestClient with the
get_db dependency overridden so handlers see the test session."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth import hash_password
from app.db import Base, get_db
from app.main import app
from app.models import User


@pytest.fixture
def test_engine(tmp_path):
    url = f"sqlite:///{tmp_path}/test.db"
    engine = create_engine(url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture
def TestSession(test_engine):
    return sessionmaker(bind=test_engine, autoflush=False, autocommit=False)


@pytest.fixture
def client(TestSession):
    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    # Skip the lifespan (which would create tables on the production engine);
    # the test_engine fixture already created them on the test DB.
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def make_user(TestSession):
    def _make(username="alice", password="hunter2-secret", is_admin=False):
        db = TestSession()
        try:
            u = User(
                username=username,
                password_hash=hash_password(password),
                is_admin=is_admin,
            )
            db.add(u)
            db.commit()
            db.refresh(u)
            return u
        finally:
            db.close()

    return _make
