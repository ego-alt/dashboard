"""Managing people (admins): add, set passwords, roles, reset 2FA, delete."""
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session as DbSession

from app.auth import (
    SESSION_COOKIE,
    check_new_password,
    current_admin,
    current_user,
    current_user_optional,
    hash_password,
    revoke_user_sessions,
)
from app.db import get_db
from app.models import ApiToken, LoginEvent, User, UserSession, WebauthnCredential

router = APIRouter(prefix="/users", tags=["users"])


def _user_dto(u: User) -> Dict[str, Any]:
    return {
        "id": u.id,
        "username": u.username,
        "display_name": u.display_name,
        "is_admin": u.is_admin,
        "totp_enabled": u.totp_enabled,
        "created_at": u.created_at.isoformat(),
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
    }


def _require_user(db: DbSession, user_id: int) -> User:
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(status_code=404, detail="no such user")
    return u


def _admin_count(db: DbSession) -> int:
    return db.query(User).filter(User.is_admin.is_(True)).count()


@router.get("")
def list_users_endpoint(
    request: Request,
    user: Optional[User] = Depends(current_user_optional),
    db: DbSession = Depends(get_db),
):
    # A browser opening /users (an old bookmark) gets the page, not the JSON.
    if "text/html" in request.headers.get("accept", ""):
        return RedirectResponse("/admin/users", status_code=307)
    current_admin(current_user(user))
    return [_user_dto(u) for u in db.query(User).order_by(User.id).all()]


@router.post("")
def create_user_endpoint(
    username: str = Form(...),
    password: str = Form(...),
    display_name: str = Form(""),
    is_admin: bool = Form(False),
    _: User = Depends(current_admin),
    db: DbSession = Depends(get_db),
):
    username = username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="username is required")
    if db.query(User).filter(User.username == username).one_or_none() is not None:
        raise HTTPException(status_code=409, detail="username already exists")
    check_new_password(password)
    user = User(
        username=username,
        display_name=display_name.strip() or username,
        password_hash=hash_password(password),
        is_admin=is_admin,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _user_dto(user)


@router.post("/{user_id}/password")
def set_user_password_endpoint(
    user_id: int,
    request: Request,
    password: str = Form(...),
    _: User = Depends(current_admin),
    db: DbSession = Depends(get_db),
):
    """Set a user's password and end their sessions (a reset usually means a
    lost device or a leaked password). Your own current session survives."""
    user = _require_user(db, user_id)
    check_new_password(password)
    user.password_hash = hash_password(password)
    db.commit()
    ended = revoke_user_sessions(db, user.id, keep_token=request.cookies.get(SESSION_COOKIE))
    return {"ok": True, "sessions_ended": ended}


@router.post("/{user_id}/admin")
def set_user_admin_endpoint(
    user_id: int,
    is_admin: bool = Form(...),
    admin: User = Depends(current_admin),
    db: DbSession = Depends(get_db),
):
    user = _require_user(db, user_id)
    # Anti-lockout: an admin can't demote themselves or the last remaining admin.
    if not is_admin and user.is_admin:
        if user.id == admin.id:
            raise HTTPException(status_code=400, detail="you can't demote yourself")
        if _admin_count(db) <= 1:
            raise HTTPException(status_code=400, detail="can't remove the last admin")
    user.is_admin = is_admin
    db.commit()
    return _user_dto(user)


@router.post("/{user_id}/reset-2fa")
def reset_user_2fa_endpoint(
    user_id: int,
    _: User = Depends(current_admin),
    db: DbSession = Depends(get_db),
):
    """Clear a user's TOTP enrollment so a locked-out user (lost authenticator)
    can sign in with their password alone and re-enroll."""
    user = _require_user(db, user_id)
    user.totp_secret = None
    user.totp_enabled = False
    user.totp_recovery_codes = None
    db.commit()
    return {"ok": True}


@router.delete("/{user_id}")
def delete_user_endpoint(
    user_id: int,
    admin: User = Depends(current_admin),
    db: DbSession = Depends(get_db),
):
    user = _require_user(db, user_id)
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="you can't delete yourself")
    if user.is_admin and _admin_count(db) <= 1:
        raise HTTPException(status_code=400, detail="can't delete the last admin")
    # SQLite FK enforcement is off, so ON DELETE CASCADE won't fire — explicitly
    # purge this user's credentials/sessions so no live token or passkey outlives
    # the account. Login events stay (audit) but lose the user link (SET NULL).
    db.query(ApiToken).filter(ApiToken.user_id == user.id).delete()
    db.query(WebauthnCredential).filter(WebauthnCredential.user_id == user.id).delete()
    db.query(UserSession).filter(UserSession.user_id == user.id).delete()
    db.query(LoginEvent).filter(LoginEvent.user_id == user.id).update(
        {LoginEvent.user_id: None}
    )
    db.delete(user)
    db.commit()
    return {"ok": True}
