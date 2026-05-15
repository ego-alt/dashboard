"""Auth: argon2id hashing, server-side sessions, FastAPI dependencies.

Sessions live in the ``user_sessions`` table — one row per active login, revoke
via DELETE. ``/auth/verify`` reuses ``current_user_optional`` so an indexed
SELECT covers each nginx auth_request subrequest.
"""

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request, Response
from passlib.hash import argon2
from sqlalchemy import delete
from sqlalchemy.orm import Session as DbSession

from .db import get_db
from .models import User, UserSession

SESSION_COOKIE = "session"
SESSION_TTL = timedelta(days=14)

# Flip to True once nginx-TLS is in front. Cookie-set in main; checked here so
# the cookie attributes are owned by one module.
SESSION_COOKIE_SECURE = False


def hash_password(plain: str) -> str:
    return argon2.using(type="ID").hash(plain)


def verify_password(plain: str, stored_hash: str) -> bool:
    try:
        return argon2.verify(plain, stored_hash)
    except (ValueError, TypeError):
        return False


def mint_session(db: DbSession, user: User, *, ip: str = "", user_agent: str = "") -> str:
    """Issue a server-side session. Returns the opaque token for the cookie."""
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    db.add(
        UserSession(
            token=token,
            user_id=user.id,
            created_at=now,
            expires_at=now + SESSION_TTL,
            ip=ip or None,
            user_agent=user_agent[:255] if user_agent else None,
        )
    )
    db.commit()
    return token


def lookup_session(db: DbSession, token: str) -> Optional[UserSession]:
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
    result = db.execute(
        delete(UserSession).where(UserSession.expires_at <= datetime.now(timezone.utc))
    )
    db.commit()
    return result.rowcount or 0


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True,
        secure=SESSION_COOKIE_SECURE,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def current_user_optional(
    request: Request, db: DbSession = Depends(get_db)
) -> Optional[User]:
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
