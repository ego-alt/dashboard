"""Dashboard API: Docker monitor + auth provider for the home stack."""

import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session as DbSession

from app.auth import (
    clear_session_cookie,
    complete_pending_session,
    current_admin,
    current_user,
    current_user_cookie_or_token,
    current_user_optional,
    mfa_pending_session,
    mint_api_token,
    mint_pending_session,
    mint_session,
    record_login_event,
    revoke_session,
    set_session_cookie,
    timing_safe_no_such_user,
    verify_password,
    SESSION_COOKIE,
)
from app.db import get_db, init_db
from app.docker_control import (
    get_container_logs,
    get_container_stats,
    get_containers,
    resolve_container_name,
    restart_container,
    start_container,
    stop_container,
)
from app.models import ApiToken, User, UserSession, WebauthnCredential
from app.services import list_services
from app.spa import register_spa
from app.system_stats import get_system_stats
from app.totp import (
    generate_recovery_codes,
    generate_secret,
    hash_recovery_codes,
    provisioning_uri,
    render_qr_svg,
    verify_totp_code,
    verify_totp_or_recovery,
)
from app.webauthn_helpers import (
    RP_ID,
    RP_NAME,
    RP_ORIGIN,
    challenges as webauthn_challenges,
)
import webauthn as webauthn_lib
from webauthn.helpers.structs import (
    PublicKeyCredentialDescriptor,
    UserVerificationRequirement,
)
from webauthn.helpers.cose import COSEAlgorithmIdentifier
from webauthn.helpers import base64url_to_bytes
from pydantic import BaseModel

# Gateway containers that must never be stopped/restarted from the dashboard —
# doing so would sever the very session/route serving this request. UI also
# hides the controls; this is the server-side backstop.
PROTECTED_CONTAINERS = frozenset(
    c.strip()
    for c in os.environ.get("PROTECTED_CONTAINERS", "dashboard,home-nginx").split(",")
    if c.strip()
)


def _reject_if_protected(container_id: str, action: str) -> None:
    name = resolve_container_name(container_id)
    if name in PROTECTED_CONTAINERS:
        raise HTTPException(
            status_code=409,
            detail=f"refusing to {action} {name!r}: protected gateway container",
        )


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="Dashboard API", lifespan=lifespan)

# Per-IP rate limiter. Tunable via env so the home-stack operator can relax it
# for shared-NAT households or tighten it if abuse shows up in login_events.
_LOGIN_RATE_LIMIT = os.environ.get("LOGIN_RATE_LIMIT", "5/minute")
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
def _rate_limit_handler(_request: Request, _exc: RateLimitExceeded) -> Response:
    return Response(
        content='{"detail":"too many requests"}',
        status_code=429,
        media_type="application/json",
    )


def _allowed_origins() -> set[str]:
    """Origins permitted to make state-changing requests. Override in
    production via ``ALLOWED_ORIGINS`` (comma-separated). Defaults cover the
    Vite dev server, direct uvicorn, and the FastAPI TestClient."""
    raw = os.environ.get("ALLOWED_ORIGINS")
    if raw is not None:
        return {o.strip() for o in raw.split(",") if o.strip()}
    return {
        "http://localhost:5173",
        "http://localhost:8000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8000",
        "http://testserver",
    }


_ALLOWED_ORIGINS = _allowed_origins()


@app.middleware("http")
async def origin_check_middleware(request: Request, call_next):
    """Reject browser-originated state-changing requests from foreign origins.
    CORS already blocks cross-origin *reads*; this stops cross-origin *writes*
    (form POST) that don't trigger a preflight.

    An incoming Origin is accepted if it's in ``ALLOWED_ORIGINS`` OR its host
    matches the request's Host header. The latter covers production behind a
    proxy that preserves Host (nginx default) without requiring config; the
    allowlist covers dev where a proxy rewrites Host (Vite with changeOrigin).

    Permissive when ``Origin`` is absent (CLI clients, server-to-server) —
    those paths aren't a CSRF vector.
    """
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        origin = request.headers.get("origin")
        if origin and origin not in _ALLOWED_ORIGINS:
            origin_host = urlparse(origin).netloc
            request_host = request.headers.get("host", "")
            if not origin_host or origin_host != request_host:
                return Response(content="origin mismatch", status_code=403)
    return await call_next(request)


def _unwrap(result: Dict[str, Any]) -> Dict[str, Any]:
    """Convert the docker_control ``{status, message}`` shape into an HTTP 400
    when status is error. Leaves the success body unchanged."""
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("message", "unknown error"))
    return result


# ---------- public endpoints ----------


@app.get("/ping")
def ping():
    return {"message": "pong"}


@app.post("/login")
@limiter.limit(_LOGIN_RATE_LIMIT)
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


@app.post("/logout")
def logout(request: Request, response: Response, db: DbSession = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        revoke_session(db, token)
    clear_session_cookie(response)
    return {"ok": True}


# ---------- auth-state endpoints ----------


@app.get("/me")
def me(user: User = Depends(current_user)):
    return {
        "username": user.username,
        "display_name": user.display_name,
        "is_admin": bool(user.is_admin),
        "totp_enabled": bool(user.totp_enabled),
    }


@app.get("/auth/verify")
def auth_verify(user: Optional[User] = Depends(current_user_cookie_or_token)):
    if user is None:
        return Response(status_code=401)
    return Response(status_code=200, headers={"X-User": user.username})


# ---------- TOTP 2FA ----------


@app.post("/auth/totp/setup")
def totp_setup(user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    """Generate a new TOTP secret for the current user and return enrollment
    materials. The secret is stored immediately but ``totp_enabled`` only flips
    once /enable receives a valid code, so an abandoned setup is harmless."""
    if user.totp_enabled:
        raise HTTPException(status_code=409, detail="2FA already enabled")
    secret = generate_secret()
    user.totp_secret = secret
    db.commit()
    uri = provisioning_uri(secret, user.username)
    return {"secret": secret, "uri": uri, "qr_svg": render_qr_svg(uri)}


@app.post("/auth/totp/enable")
def totp_enable(
    code: str = Form(...),
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    if user.totp_enabled:
        raise HTTPException(status_code=409, detail="2FA already enabled")
    if not user.totp_secret or not verify_totp_code(user.totp_secret, code):
        raise HTTPException(status_code=400, detail="bad code")
    recovery = generate_recovery_codes()
    user.totp_recovery_codes = hash_recovery_codes(recovery)
    user.totp_enabled = True
    db.commit()
    # One-time display — these are not stored in plaintext on the server.
    return {"ok": True, "recovery_codes": recovery}


@app.post("/auth/totp/disable")
def totp_disable(
    code: str = Form(...),
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    if not user.totp_enabled:
        raise HTTPException(status_code=409, detail="2FA not enabled")
    ok, _mode = verify_totp_or_recovery(user, code)
    if not ok:
        raise HTTPException(status_code=400, detail="bad code")
    user.totp_enabled = False
    user.totp_secret = None
    user.totp_recovery_codes = None
    db.commit()
    return {"ok": True}


@app.post("/auth/totp/verify")
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


# ---------- WebAuthn / passkeys ----------


class _WebauthnFinishRegistration(BaseModel):
    token: str
    name: str
    credential: dict


class _WebauthnFinishAuthentication(BaseModel):
    token: str
    credential: dict


@app.post("/auth/webauthn/register/begin")
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
    import json

    return {"token": token, "options": json.loads(payload)}


@app.post("/auth/webauthn/register/finish")
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


@app.get("/auth/webauthn/credentials")
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


@app.delete("/auth/webauthn/credentials/{cred_id}")
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


@app.post("/auth/webauthn/login/begin")
def webauthn_login_begin():
    """Issue assertion options for discoverable / resident-key passkeys.
    No username required — the authenticator picks the credential."""
    options = webauthn_lib.generate_authentication_options(
        rp_id=RP_ID,
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    token = webauthn_challenges.issue(options.challenge, user_id=None)
    import json

    return {"token": token, "options": json.loads(webauthn_lib.options_to_json(options))}


@app.post("/auth/webauthn/login/finish")
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


# ---------- API tokens (programmatic auth for native apps) ----------


@app.get("/auth/tokens")
def list_api_tokens(user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    toks = (
        db.query(ApiToken)
        .filter(ApiToken.user_id == user.id)
        .order_by(ApiToken.created_at.desc())
        .all()
    )
    return [
        {
            "id": t.id,
            "name": t.name,
            "prefix": t.prefix,
            "created_at": t.created_at.isoformat(),
            "last_used_at": t.last_used_at.isoformat() if t.last_used_at else None,
        }
        for t in toks
    ]


@app.post("/auth/tokens")
def create_api_token(
    name: str = Form(...),
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    """Mint a token for the current user. The raw value is returned exactly
    once (only its hash is persisted) — the client must store it now."""
    raw = mint_api_token(db, user, name=name)
    return {"ok": True, "token": raw}


@app.delete("/auth/tokens/{token_id}")
def delete_api_token(
    token_id: int,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    tok = (
        db.query(ApiToken)
        .filter(ApiToken.id == token_id, ApiToken.user_id == user.id)
        .one_or_none()
    )
    if tok is None:
        raise HTTPException(status_code=404, detail="not found")
    db.delete(tok)
    db.commit()
    return {"ok": True}


# ---------- Service registry (home hub) ----------


@app.get("/services", response_model=List[Dict[str, Any]])
def list_services_endpoint(_: User = Depends(current_user)):
    return list_services()


# ---------- Docker monitor (auth-gated) ----------


@app.get("/containers", response_model=List[Dict[str, Any]])
def list_containers(stats: bool = False, _: User = Depends(current_user)):
    return get_containers(include_stats=stats)


@app.post("/containers/{container_id}/start", response_model=Dict[str, str])
def start_container_endpoint(container_id: str, _: User = Depends(current_admin)):
    _reject_if_protected(container_id, "start")
    return _unwrap(start_container(container_id))


@app.post("/containers/{container_id}/stop", response_model=Dict[str, str])
def stop_container_endpoint(container_id: str, _: User = Depends(current_admin)):
    _reject_if_protected(container_id, "stop")
    return _unwrap(stop_container(container_id))


@app.post("/containers/{container_id}/restart", response_model=Dict[str, str])
def restart_container_endpoint(container_id: str, _: User = Depends(current_admin)):
    _reject_if_protected(container_id, "restart")
    return _unwrap(restart_container(container_id))


@app.get("/containers/{container_id}/logs", response_model=Dict[str, Any])
def get_logs_endpoint(
    container_id: str,
    tail: Optional[int] = 50,
    _: User = Depends(current_user),
):
    return _unwrap(get_container_logs(container_id, tail))


# ---------- System stats (auth-gated) ----------


@app.get("/stats/system", response_model=Dict[str, Any])
def system_stats_endpoint(_: User = Depends(current_user)):
    return get_system_stats()


@app.get("/stats/containers/{container_id}", response_model=Dict[str, Any])
def container_stats_endpoint(container_id: str, _: User = Depends(current_user)):
    return _unwrap(get_container_stats(container_id))


# ---------- React SPA (built into app/static by Docker / manual npm run build) ----------

register_spa(app)
