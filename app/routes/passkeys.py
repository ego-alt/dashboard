"""Passkeys (WebAuthn): adding and removing them, and signing in with one."""
import json
from datetime import datetime, timezone

import webauthn as webauthn_lib
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession
from webauthn.helpers import base64url_to_bytes
from webauthn.helpers.cose import COSEAlgorithmIdentifier
from webauthn.helpers.structs import PublicKeyCredentialDescriptor, UserVerificationRequirement

from app.auth import current_user, mint_session, record_login_event, set_session_cookie
from app.db import get_db
from app.models import User, WebauthnCredential
from app.webauthn_helpers import RP_ID, RP_NAME, RP_ORIGIN
from app.webauthn_helpers import challenges as webauthn_challenges

router = APIRouter(prefix="/auth/webauthn", tags=["passkeys"])


class _WebauthnFinishRegistration(BaseModel):
    token: str
    name: str
    credential: dict


class _WebauthnFinishAuthentication(BaseModel):
    token: str
    credential: dict


@router.post("/register/begin")
def webauthn_register_begin(
    user: User = Depends(current_user), db: DbSession = Depends(get_db)
):
    """Issue registration options for the current user. The client passes
    them to ``navigator.credentials.create()`` and posts the response back
    to /register/finish."""
    existing = (
        db.query(WebauthnCredential)
        .filter(WebauthnCredential.user_id == user.id)
        .all()
    )
    exclude = [
        PublicKeyCredentialDescriptor(id=c.credential_id) for c in existing
    ]
    options = webauthn_lib.generate_registration_options(
        rp_id=RP_ID,
        rp_name=RP_NAME,
        user_id=str(user.id).encode(),
        user_name=user.username,
        user_display_name=user.display_name or user.username,
        exclude_credentials=exclude,
        supported_pub_key_algs=[
            COSEAlgorithmIdentifier.ECDSA_SHA_256,
            COSEAlgorithmIdentifier.RSASSA_PKCS1_v1_5_SHA_256,
        ],
    )
    token = webauthn_challenges.issue(options.challenge, user_id=user.id)
    payload = webauthn_lib.options_to_json(options)
    return {"token": token, "options": json.loads(payload)}


@router.post("/register/finish")
def webauthn_register_finish(
    body: _WebauthnFinishRegistration,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    entry = webauthn_challenges.consume(body.token)
    if entry is None:
        raise HTTPException(status_code=400, detail="challenge expired")
    challenge, owner_id = entry
    if owner_id is not None and owner_id != user.id:
        raise HTTPException(status_code=400, detail="challenge owner mismatch")
    try:
        verified = webauthn_lib.verify_registration_response(
            credential=body.credential,
            expected_challenge=challenge,
            expected_rp_id=RP_ID,
            expected_origin=RP_ORIGIN,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"attestation invalid: {exc}")
    raw_transports = (body.credential.get("response") or {}).get("transports") or []
    transports = ",".join(raw_transports) or None
    db.add(
        WebauthnCredential(
            user_id=user.id,
            credential_id=verified.credential_id,
            public_key=verified.credential_public_key,
            sign_count=verified.sign_count,
            transports=transports,
            name=(body.name or "Passkey")[:120],
        )
    )
    db.commit()
    return {"ok": True}


@router.get("/credentials")
def webauthn_list_credentials(
    user: User = Depends(current_user), db: DbSession = Depends(get_db)
):
    creds = (
        db.query(WebauthnCredential)
        .filter(WebauthnCredential.user_id == user.id)
        .order_by(WebauthnCredential.created_at.desc())
        .all()
    )
    return [
        {
            "id": c.id,
            "name": c.name,
            "created_at": c.created_at.isoformat(),
            "last_used_at": c.last_used_at.isoformat() if c.last_used_at else None,
        }
        for c in creds
    ]


@router.delete("/credentials/{cred_id}")
def webauthn_delete_credential(
    cred_id: int,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    cred = (
        db.query(WebauthnCredential)
        .filter(
            WebauthnCredential.id == cred_id,
            WebauthnCredential.user_id == user.id,
        )
        .one_or_none()
    )
    if cred is None:
        raise HTTPException(status_code=404, detail="not found")
    db.delete(cred)
    db.commit()
    return {"ok": True}


@router.post("/login/begin")
def webauthn_login_begin():
    """Issue assertion options for discoverable / resident-key passkeys.
    No username required — the authenticator picks the credential."""
    options = webauthn_lib.generate_authentication_options(
        rp_id=RP_ID,
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    token = webauthn_challenges.issue(options.challenge, user_id=None)
    return {"token": token, "options": json.loads(webauthn_lib.options_to_json(options))}


@router.post("/login/finish")
def webauthn_login_finish(
    body: _WebauthnFinishAuthentication,
    request: Request,
    response: Response,
    db: DbSession = Depends(get_db),
):
    entry = webauthn_challenges.consume(body.token)
    if entry is None:
        raise HTTPException(status_code=400, detail="challenge expired")
    challenge, _ = entry
    raw_id_b64 = body.credential.get("rawId") or body.credential.get("id")
    if not raw_id_b64:
        raise HTTPException(status_code=400, detail="missing rawId")
    try:
        raw_id = base64url_to_bytes(raw_id_b64)
    except Exception:
        raise HTTPException(status_code=400, detail="bad rawId")
    stored = (
        db.query(WebauthnCredential)
        .filter(WebauthnCredential.credential_id == raw_id)
        .one_or_none()
    )
    if stored is None:
        raise HTTPException(status_code=401, detail="unknown credential")
    try:
        verified = webauthn_lib.verify_authentication_response(
            credential=body.credential,
            expected_challenge=challenge,
            expected_rp_id=RP_ID,
            expected_origin=RP_ORIGIN,
            credential_public_key=stored.public_key,
            credential_current_sign_count=stored.sign_count,
        )
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"assertion invalid: {exc}")
    stored.sign_count = verified.new_sign_count
    stored.last_used_at = datetime.now(timezone.utc)
    user = stored.user
    user.last_login_at = datetime.now(timezone.utc)
    # A successful passkey assertion is a strong factor on its own — skip the
    # TOTP gate even if the user has TOTP enrolled.
    ip = (request.client.host if request.client else "") or ""
    user_agent = request.headers.get("user-agent", "")
    token = mint_session(db, user, ip=ip, user_agent=user_agent)
    set_session_cookie(request, response, token)
    record_login_event(
        db,
        username=user.username,
        user_id=user.id,
        success=True,
        reason="passkey",
        ip=ip,
        user_agent=user_agent,
    )
    return {"ok": True, "username": user.username}
