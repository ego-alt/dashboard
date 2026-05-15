"""CLI helpers: create-admin / create-user."""

from sqlalchemy.orm import sessionmaker

from app.auth import verify_password
from app.cli import _add_user
from app.db import Base
from app.models import User


def test_add_user_non_admin(test_engine):
    Base.metadata.create_all(test_engine)
    Session = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)
    db = Session()
    try:
        user = _add_user(
            db,
            username="bob",
            password="longpassword1",
            is_admin=False,
        )
        assert user.is_admin is False
        assert verify_password("longpassword1", user.password_hash)
        again = db.query(User).filter_by(username="bob").one()
        assert again.id == user.id
    finally:
        db.close()


def test_add_user_admin(test_engine):
    Base.metadata.create_all(test_engine)
    Session = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)
    db = Session()
    try:
        user = _add_user(
            db,
            username="carol",
            password="longpassword2",
            is_admin=True,
        )
        assert user.is_admin is True
    finally:
        db.close()
