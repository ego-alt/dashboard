"""Auth: argon2id hashing, server-side sessions, FastAPI dependencies.

Sessions live in the ``user_sessions`` table — one row per active login, revoke
via DELETE. ``/auth/verify`` reuses ``current_user_optional`` so an indexed
SELECT covers each nginx auth_request subrequest. Successful and failed login
attempts are recorded in ``login_events`` for audit/incident-response.
"""

import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import delete
from sqlalchemy.orm import Session as DbSession

from .db import get_db
from .models import LoginEvent, User, UserSession

SESSION_COOKIE = "session"
SESSION_TTL = timedelta(days=14)
# Short window for the first-factor session, after which the user must complete
# the TOTP verify step. Long enough for fumbling, short enough to be useless to
# steal the cookie before second factor.
MFA_PENDING_TTL = timedelta(minutes=5)

# Single PasswordHasher instance: argon2-cffi recommends reuse so memory/time
# parameters are amortized. ``hash`` produces ``$argon2id$v=19$...`` which is
# the same wire format passlib used, so existing hashes verify without migration.
_PH = PasswordHasher()

# A precomputed argon2id hash of an arbitrary value, used to make the failure
# path of /login take the same time when the username doesn't exist as when it
# does. Defeats trivial timing-based username enumeration without per-call work.
_FAKE_HASH = _PH.hash("not-a-real-password-timing-only")


def _cookie_secure(request: Request) -> bool:
    """Decide whether to mark the session cookie ``Secure``.

    Explicit ``SESSION_COOKIE_SECURE=0|1`` wins. Otherwise default to True iff
    the request looks like it came in over HTTPS (direct or via nginx, which
    sets ``X-Forwarded-Proto: https``). This prevents accidentally setting
    ``Secure`` on a plain-HTTP cookie (which the browser would then refuse to
    send back, silently breaking auth).
    """
    val = os.environ.get("SESSION_COOKIE_SECURE")
    if val is not None:
        return val.lower() in ("1", "true", "yes")
    forwarded = request.headers.get("x-forwarded-proto", "").lower()
    return forwarded == "https" or request.url.scheme == "https"


def hash_password(plain: str) -> str:
    return _PH.hash(plain)


def verify_password(plain: str, stored_hash: str) -> bool:
    if not stored_hash:
        return False
    try:
        return _PH.verify(stored_hash, plain)
    except (VerificationError, InvalidHashError):
        return False


def timing_safe_no_such_user(password: str) -> None:
    """Spend the same time we'd spend on a real argon2 verify, then bail.

    Call when looking up by username returned None — keeps the response time
    indistinguishable from a real wrong-password attempt.
    """
    verify_password(password, _FAKE_HASH)


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
            mfa_pending=False,
        )
    )
    db.commit()
    return token


def mint_pending_session(
    db: DbSession, user: User, *, ip: str = "", user_agent: str = ""
) -> str:
    """First-factor only. The session is restricted to /auth/totp/verify until
    the second factor completes (see ``current_user_optional`` rejection and
    ``mfa_pending_user`` opt-in dependency)."""
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    db.add(
        UserSession(
            token=token,
            user_id=user.id,
            created_at=now,
            expires_at=now + MFA_PENDING_TTL,
            ip=ip or None,
            user_agent=user_agent[:255] if user_agent else None,
            mfa_pending=True,
        )
    )
    db.commit()
    return token


def complete_pending_session(db: DbSession, sess: UserSession) -> None:
    """Promote a first-factor session to full access. Caller already verified
    the second factor."""
    sess.mfa_pending = False
    sess.expires_at = datetime.now(timezone.utc) + SESSION_TTL
    db.commit()


def lookup_session(db: DbSession, token: str) -> Optional[UserSession]:
    """Fetch a non-expired session, sliding the expiry forward when more than
    half the TTL has elapsed since the last extension.

    Bounded write rate per session: at most once per ``SESSION_TTL / 2`` window.
    Active users no longer get logged out mid-use; idle ones still expire on the
    original schedule.
    """
    sess = db.get(UserSession, token)
    if sess is None or sess.is_expired():
        return None
    now = datetime.now(timezone.utc)
    exp = sess.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    # Sliding extension only for fully-authenticated sessions; pending-2FA
    # sessions keep their short fixed TTL so a stolen first-factor cookie
    # can't be kept alive without ever completing the second factor.
    if not sess.mfa_pending and exp - now < SESSION_TTL / 2:
        sess.expires_at = now + SESSION_TTL
        db.commit()
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


def record_login_event(
    db: DbSession,
    *,
    username: str,
    success: bool,
    user_id: Optional[int] = None,
    reason: Optional[str] = None,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> None:
    """Append one row to ``login_events``. Best-effort; never raises."""
    try:
        db.add(
            LoginEvent(
                username=(username or "")[:64],
                user_id=user_id,
                success=success,
                reason=reason,
                ip=ip or None,
                user_agent=(user_agent or "")[:255] or None,
            )
        )
        db.commit()
    except Exception:
        db.rollback()


def set_session_cookie(request: Request, response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True,
        secure=_cookie_secure(request),
        samesite="strict",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def current_user_optional(
    request: Request, db: DbSession = Depends(get_db)
) -> Optional[User]:
    """The user behind a *fully authenticated* session. Pending-2FA sessions
    are treated as anonymous everywhere except ``mfa_pending_session``."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    sess = lookup_session(db, token)
    if sess is None or sess.mfa_pending:
        return None
    return sess.user


def current_user(user: Optional[User] = Depends(current_user_optional)) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    return user


def current_admin(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="admin only")
    return user


def mfa_pending_session(
    request: Request, db: DbSession = Depends(get_db)
) -> UserSession:
    """The session behind a first-factor-only cookie, for /auth/totp/verify."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="no pending session")
    sess = lookup_session(db, token)
    if sess is None or not sess.mfa_pending:
        raise HTTPException(status_code=401, detail="no pending session")
    return sess
