"""Two-factor sign-in with an authenticator app (TOTP), with recovery codes."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy.orm import Session as DbSession

from app.auth import complete_pending_session, current_user, mfa_pending_session, record_login_event
from app.db import get_db
from app.models import User, UserSession
from app.totp import (
    new_recovery_codes,
    provisioning_uri,
    render_qr_svg,
    start_setup,
    totp_state,
    turn_off,
    turn_on,
    verify_totp_code,
    verify_totp_or_recovery,
)

router = APIRouter(prefix="/auth/totp", tags=["totp"])


@router.post("/setup")
def totp_setup(user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    """Generate a new TOTP secret for the current user and return enrollment
    materials. 2FA only turns on once /enable receives a valid code, so an
    abandoned setup is harmless (see app/totp.py)."""
    if totp_state(user) == "on":
        raise HTTPException(status_code=409, detail="2FA already enabled")
    secret = start_setup(user)
    db.commit()
    uri = provisioning_uri(secret, user.username)
    return {"secret": secret, "uri": uri, "qr_svg": render_qr_svg(uri)}


@router.post("/enable")
def totp_enable(
    code: str = Form(...),
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    state = totp_state(user)
    if state == "on":
        raise HTTPException(status_code=409, detail="2FA already enabled")
    if state != "setting-up" or not verify_totp_code(user.totp_secret, code):
        raise HTTPException(status_code=400, detail="bad code")
    recovery = turn_on(user)
    db.commit()
    # One-time display — these are not stored in plaintext on the server.
    return {"ok": True, "recovery_codes": recovery}


@router.post("/disable")
def totp_disable(
    code: str = Form(...),
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    if totp_state(user) != "on":
        raise HTTPException(status_code=409, detail="2FA not enabled")
    ok, _mode = verify_totp_or_recovery(user, code)
    if not ok:
        raise HTTPException(status_code=400, detail="bad code")
    turn_off(user)
    db.commit()
    return {"ok": True}


@router.post("/recovery-codes")
def totp_regenerate_recovery(
    code: str = Form(...),
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    """Replace the recovery codes (the old ones stop working). Needs a current
    authenticator code, so a borrowed session can't mint fresh ones."""
    if totp_state(user) != "on":
        raise HTTPException(status_code=409, detail="2FA not enabled")
    if not verify_totp_code(user.totp_secret, code):
        raise HTTPException(status_code=400, detail="bad code")
    recovery = new_recovery_codes(user)
    db.commit()
    return {"ok": True, "recovery_codes": recovery}


@router.post("/verify")
def totp_verify(
    request: Request,
    code: str = Form(...),
    sess: UserSession = Depends(mfa_pending_session),
    db: DbSession = Depends(get_db),
):
    """Second factor of login. Promotes a pending session to fully authenticated."""
    user = sess.user
    ip = (request.client.host if request.client else "") or ""
    user_agent = request.headers.get("user-agent", "")
    ok, mode = verify_totp_or_recovery(user, code)
    if not ok:
        record_login_event(
            db,
            username=user.username,
            user_id=user.id,
            success=False,
            reason="bad-totp",
            ip=ip,
            user_agent=user_agent,
        )
        raise HTTPException(status_code=401, detail="bad code")
    user.last_login_at = datetime.now(timezone.utc)
    complete_pending_session(db, sess)
    record_login_event(
        db,
        username=user.username,
        user_id=user.id,
        success=True,
        reason=f"totp-{mode}",
        ip=ip,
        user_agent=user_agent,
    )
    return {"ok": True, "username": user.username}
