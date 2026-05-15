"""Auth: argon2id hashing, server-side sessions, FastAPI dependencies.

Sessions live in the ``user_sessions`` table (one row per active login); revoke
is one ``DELETE``. The ``/auth/verify`` endpoint nginx subrequests for every
backend hit reuses ``current_user_optional`` and so trades only an indexed
SELECT per request.
"""

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request
from passlib.hash import argon2
from sqlalchemy.orm import Session as DbSession

from .db import get_db
from .models import User, UserSession

SESSION_COOKIE = "session"
SESSION_TTL = timedelta(days=14)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------- password hashing ----------

def hash_password(plain: str) -> str:
    return argon2.using(type="ID").hash(plain)


def verify_password(plain: str, stored_hash: str) -> bool:
    try:
        return argon2.verify(plain, stored_hash)
    except (ValueError, TypeError):
        return False


# ---------- session lifecycle ----------

def mint_session(db: DbSession, user: User, *, ip: str = "", user_agent: str = "") -> str:
    """Issue a new server-side session for ``user``. Returns the opaque token
    intended to be set on the client as an HttpOnly cookie."""
    token = secrets.token_urlsafe(32)
    db.add(
        UserSession(
            token=token,
            user_id=user.id,
            created_at=_utc_now(),
            expires_at=_utc_now() + SESSION_TTL,
            ip=ip or None,
            user_agent=(user_agent or None) and user_agent[:255],
        )
    )
    db.commit()
    return token


def lookup_session(db: DbSession, token: str) -> Optional[UserSession]:
    """Return the live session for ``token``, or None if missing/expired."""
    sess = db.get(UserSession, token)
    if sess is None or sess.is_expired():
        return None
    return sess


def revoke_session(db: DbSession, token: str) -> None:
    sess = db.get(UserSession, token)
    if sess is not None:
        db.delete(sess)
        db.commit()


def purge_expired_sessions(db: DbSession) -> int:
    """Delete every expired session. Returns the number deleted.

    Cheap maintenance routine; call from a periodic job or before any user-list
    operation. Not required for correctness — ``lookup_session`` already rejects
    expired rows.
    """
    rows = (
        db.query(UserSession)
        .filter(UserSession.expires_at <= _utc_now())
        .all()
    )
    for r in rows:
        db.delete(r)
    db.commit()
    return len(rows)


# ---------- FastAPI dependencies ----------

def current_user_optional(
    request: Request, db: DbSession = Depends(get_db)
) -> Optional[User]:
    """Resolve the request's user without raising. Used by /auth/verify so it
    can return 401 cleanly without exception-handler noise."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    sess = lookup_session(db, token)
    return sess.user if sess is not None else None


def current_user(user: Optional[User] = Depends(current_user_optional)) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    return user


def current_admin(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="admin only")
    return user
