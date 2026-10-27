"""Signing in and out, and your own account: who you are, your password, where
you're signed in, your recent sign-ins. Also /auth/verify, which nginx asks
before serving any app (a session cookie or an API token)."""
import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from sqlalchemy.orm import Session as DbSession

from app.auth import (
    SESSION_COOKIE,
    check_new_password,
    clear_session_cookie,
    current_user,
    current_user_cookie_or_token,
    hash_password,
    mint_pending_session,
    mint_session,
    record_login_event,
    revoke_session,
    revoke_user_sessions,
    session_public_id,
    set_session_cookie,
    timing_safe_no_such_user,
    verify_password,
)
from app.db import get_db
from app.models import LoginEvent, User, UserSession
from app.ratelimit import LOGIN_RATE_LIMIT, limiter

router = APIRouter(tags=["account"])


@router.post("/login")
@limiter.limit(LOGIN_RATE_LIMIT)
def login(
    request: Request,
    response: Response,
    username: str = Form(...),
    password: str = Form(...),
    db: DbSession = Depends(get_db),
):
    ip = (request.client.host if request.client else "") or ""
    user_agent = request.headers.get("user-agent", "")
    user = db.query(User).filter(User.username == username).one_or_none()
    if user is None:
        # Run a constant-time argon2 verify against a fake hash so timing
        # doesn't leak which usernames exist.
        timing_safe_no_such_user(password)
        record_login_event(
            db,
            username=username,
            success=False,
            reason="unknown-user",
            ip=ip,
            user_agent=user_agent,
        )
        raise HTTPException(status_code=401, detail="bad credentials")
    if not verify_password(password, user.password_hash):
        record_login_event(
            db,
            username=username,
            user_id=user.id,
            success=False,
            reason="bad-password",
            ip=ip,
            user_agent=user_agent,
        )
        raise HTTPException(status_code=401, detail="bad credentials")
    if user.totp_enabled:
        # First factor passed; gate the rest of the app behind /auth/totp/verify.
        token = mint_pending_session(db, user, ip=ip, user_agent=user_agent)
        set_session_cookie(request, response, token)
        record_login_event(
            db,
            username=user.username,
            user_id=user.id,
            success=True,
            reason="needs-2fa",
            ip=ip,
            user_agent=user_agent,
        )
        return {"ok": True, "needs_2fa": True}
    user.last_login_at = datetime.now(timezone.utc)
    token = mint_session(db, user, ip=ip, user_agent=user_agent)
    set_session_cookie(request, response, token)
    record_login_event(
        db,
        username=user.username,
        user_id=user.id,
        success=True,
        ip=ip,
        user_agent=user_agent,
    )
    return {"ok": True, "username": user.username}


@router.post("/logout")
def logout(request: Request, response: Response, db: DbSession = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        revoke_session(db, token)
    clear_session_cookie(response)
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "is_admin": bool(user.is_admin),
        "totp_enabled": bool(user.totp_enabled),
        "totp_recovery_left": _recovery_left(user),
    }


def _recovery_left(user: User) -> Optional[int]:
    if not user.totp_enabled or not user.totp_recovery_codes:
        return None
    try:
        return len(json.loads(user.totp_recovery_codes))
    except ValueError:
        return None


@router.post("/me/password")
@limiter.limit(LOGIN_RATE_LIMIT)
def change_own_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    sign_out_others: bool = Form(True),
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    # 400, not 401: a wrong current password isn't a lost session.
    if not verify_password(current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="current password is wrong")
    check_new_password(new_password)
    user.password_hash = hash_password(new_password)
    db.commit()
    ended = 0
    if sign_out_others:
        ended = revoke_user_sessions(
            db, user.id, keep_token=request.cookies.get(SESSION_COOKIE)
        )
    return {"ok": True, "sessions_ended": ended}


@router.get("/auth/sessions")
def list_own_sessions(
    request: Request, user: User = Depends(current_user), db: DbSession = Depends(get_db)
):
    mine = request.cookies.get(SESSION_COOKIE)
    now = datetime.now(timezone.utc)
    rows = (
        db.query(UserSession)
        .filter(UserSession.user_id == user.id, UserSession.mfa_pending.is_(False))
        .all()
    )

    def iso(d):
        return d.replace(tzinfo=d.tzinfo or timezone.utc).isoformat() if d else None

    out = [
        {
            "id": session_public_id(s.token),
            "current": s.token == mine,
            "created_at": iso(s.created_at),
            "last_seen_at": iso(s.last_seen_at or s.created_at),
            "ip": s.ip,
            "user_agent": s.user_agent,
        }
        for s in rows
        if s.expires_at.replace(tzinfo=s.expires_at.tzinfo or timezone.utc) > now
    ]
    return sorted(out, key=lambda s: (s["current"], s["last_seen_at"] or ""), reverse=True)


@router.delete("/auth/sessions/{session_id}")
def revoke_own_session(
    session_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    if session_id == session_public_id(request.cookies.get(SESSION_COOKIE) or ""):
        raise HTTPException(status_code=400, detail="use sign out to end this session")
    for s in db.query(UserSession).filter(UserSession.user_id == user.id).all():
        if session_public_id(s.token) == session_id:
            db.delete(s)
            db.commit()
            return {"ok": True}
    raise HTTPException(status_code=404, detail="no such session")


@router.post("/auth/sessions/revoke-others")
def revoke_other_sessions(
    request: Request, user: User = Depends(current_user), db: DbSession = Depends(get_db)
):
    n = revoke_user_sessions(db, user.id, keep_token=request.cookies.get(SESSION_COOKIE))
    return {"ok": True, "sessions_ended": n}


@router.get("/auth/login-events")
def own_login_events(
    limit: int = 10, user: User = Depends(current_user), db: DbSession = Depends(get_db)
):
    """Your recent sign-ins, including failed attempts against your username."""
    rows = (
        db.query(LoginEvent)
        .filter(LoginEvent.username == user.username)
        .order_by(LoginEvent.at.desc())
        .limit(max(1, min(limit, 50)))
        .all()
    )
    return [
        {
            "at": e.at.replace(tzinfo=e.at.tzinfo or timezone.utc).isoformat(),
            "success": e.success,
            "reason": e.reason,
            "ip": e.ip,
            "user_agent": e.user_agent,
        }
        for e in rows
    ]


@router.get("/auth/verify")
def auth_verify(user: Optional[User] = Depends(current_user_cookie_or_token)):
    if user is None:
        return Response(status_code=401)
    return Response(status_code=200, headers={"X-User": user.username})
