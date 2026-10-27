"""Auth: argon2id hashing, server-side sessions, FastAPI dependencies.

Sessions live in the ``user_sessions`` table — one row per active login, revoke
via DELETE. ``/auth/verify`` reuses ``current_user_optional`` so an indexed
SELECT covers each nginx auth_request subrequest. Successful and failed login
attempts are recorded in ``login_events`` for audit/incident-response.
"""

import hashlib
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
from .hibp import password_breach_count
from .models import LoginEvent, User, UserSession

SESSION_COOKIE = "session"
SESSION_TTL = timedelta(days=14)
# Short window for the first-factor session, after which the user must complete
# the TOTP verify step. Long enough for fumbling, short enough to be useless to
# steal the cookie before second factor.
MFA_PENDING_TTL = timedelta(minutes=5)
# How stale a session's last_seen_at may get before a request refreshes it.
SESSION_SEEN_INTERVAL = timedelta(minutes=5)

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
    dirty = False
    if not sess.mfa_pending and exp - now < SESSION_TTL / 2:
        sess.expires_at = now + SESSION_TTL
        dirty = True
    seen = sess.last_seen_at
    if seen is not None and seen.tzinfo is None:
        seen = seen.replace(tzinfo=timezone.utc)
    if seen is None or now - seen >= SESSION_SEEN_INTERVAL:
        sess.last_seen_at = now
        dirty = True
    if dirty:
        db.commit()
    return sess


def session_public_id(token: str) -> str:
    """A stable, non-secret id for a session, so the UI can list and revoke
    sessions without ever seeing another session's cookie value."""
    return hashlib.sha256(token.encode()).hexdigest()[:16]


def revoke_user_sessions(db: DbSession, user_id: int, *, keep_token: Optional[str] = None) -> int:
    """End every session of a user, except ``keep_token`` (the caller's own)."""
    q = db.query(UserSession).filter(UserSession.user_id == user_id)
    if keep_token:
        q = q.filter(UserSession.token != keep_token)
    n = q.delete(synchronize_session=False)
    db.commit()
    return n


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


# ---------- API tokens (long-lived, for native clients) ----------

API_TOKEN_PREFIX_LEN = 8


def _hash_api_token(raw: str) -> str:
    """SHA-256 is enough here: the token is 256-bit random, so there's nothing
    to brute-force — we only need to avoid storing the raw value at rest."""
    return hashlib.sha256(raw.encode()).hexdigest()


def mint_api_token(db: DbSession, user: User, *, name: str) -> str:
    """Create a long-lived API token for ``user`` and return the raw value.
    Shown once; only the hash is stored, so it can't be recovered later."""
    from .models import ApiToken

    raw = secrets.token_urlsafe(32)
    db.add(
        ApiToken(
            user_id=user.id,
            token_hash=_hash_api_token(raw),
            prefix=raw[:API_TOKEN_PREFIX_LEN],
            name=(name or "API token")[:120],
        )
    )
    db.commit()
    return raw


# How stale last_used_at may get before a lookup refreshes it. Every app call
# made with a token passes through /auth/verify, so writing on each one would
# be a SQLite write per request (the MCP server's stdio mode makes several per
# tool call). Same idea as the session's bounded sliding expiry.
API_TOKEN_TOUCH_INTERVAL = timedelta(minutes=1)


def lookup_api_token(db: DbSession, raw: str) -> Optional[User]:
    """Resolve a raw Bearer token to its user, refreshing last_used_at at most
    once per ``API_TOKEN_TOUCH_INTERVAL``. Returns None if the token is unknown."""
    from .models import ApiToken

    tok = (
        db.query(ApiToken)
        .filter(ApiToken.token_hash == _hash_api_token(raw))
        .one_or_none()
    )
    if tok is None:
        return None
    now = datetime.now(timezone.utc)
    last = tok.last_used_at
    if last is not None and last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)  # SQLite hands back naive datetimes
    if last is None or now - last >= API_TOKEN_TOUCH_INTERVAL:
        tok.last_used_at = now
        try:
            db.commit()
        except Exception:
            db.rollback()
    return tok.user


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


def current_user_cookie_or_token(
    request: Request, db: DbSession = Depends(get_db)
) -> Optional[User]:
    """Session cookie *or* ``Authorization: Bearer <api-token>``.

    Used only by ``/auth/verify`` so nginx's auth_request can authorize native
    clients (the scanner app) that hold an API token but no session cookie. All
    dashboard-native endpoints keep using ``current_user`` (cookie only), so a
    token grants downstream-app access — not dashboard control."""
    user = current_user_optional(request, db)
    if user is not None:
        return user
    auth = request.headers.get("authorization", "")
    if auth[:7].lower() == "bearer ":
        raw = auth[7:].strip()
        if raw:
            return lookup_api_token(db, raw)
    return None


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


MIN_PASSWORD_LEN = 8


def password_problem(password: str, *, check_breaches: bool = True) -> Optional[str]:
    """Why a new password isn't allowed, or None: the one rule for the pages and
    the CLI. At least MIN_PASSWORD_LEN characters, and not in a known breach
    (HaveIBeenPwned; allowed when it can't be reached)."""
    if len(password) < MIN_PASSWORD_LEN:
        return f"password must be at least {MIN_PASSWORD_LEN} characters"
    if check_breaches and (count := password_breach_count(password)) > 0:
        return f"that password appears in {count:,} known breach(es) — pick another"
    return None



def check_new_password(password: str) -> None:
    """Refuse a new password that breaks the rule, as a 400 saying why."""
    problem = password_problem(password)
    if problem:
        raise HTTPException(status_code=400, detail=problem)
