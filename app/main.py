"""Dashboard API: Docker monitor + auth provider for the home stack.

Two layers of access:
- ``Depends(current_user)`` for read endpoints (anyone logged in can see what's
  running).
- ``Depends(current_admin)`` for destructive Docker actions
  (start/stop/restart).

``/login``, ``/logout``, ``/ping`` are intentionally unauthenticated. The
``/auth/verify`` endpoint is the one nginx ``auth_request`` hits per backend
request — it returns 200 + ``X-User`` header for valid sessions, 401 otherwise.
"""

import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session as DbSession

from app.auth import (
    SESSION_COOKIE,
    SESSION_TTL,
    current_admin,
    current_user,
    current_user_optional,
    mint_session,
    revoke_session,
    verify_password,
)
from app.db import get_db, init_db
from app.docker_control import (
    get_container_logs,
    get_containers,
    restart_container,
    start_container,
    stop_container,
)
from app.models import User
from app.system_stats import get_container_stats, get_system_stats


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="Dashboard API", lifespan=lifespan)


# CORS — needed for `npm run dev` where the SPA runs on a different origin.
# In production behind nginx, frontend + API are same-origin, so this becomes
# a no-op. Pass an empty value to disable entirely.
_cors_origins = [
    o.strip()
    for o in os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",")
    if o.strip()
]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# ---------- public endpoints ----------


@app.get("/ping")
def ping():
    """Public healthcheck. Used by Docker HEALTHCHECK and the operator."""
    return {"message": "pong"}


@app.post("/login")
def login(
    request: Request,
    response: Response,
    username: str = Form(...),
    password: str = Form(...),
    db: DbSession = Depends(get_db),
):
    user = db.query(User).filter(User.username == username).one_or_none()
    if user is None or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="bad credentials")
    token = mint_session(
        db,
        user,
        ip=(request.client.host if request.client else "") or "",
        user_agent=request.headers.get("user-agent", ""),
    )
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True,
        secure=False,  # set True once nginx-TLS is in front; envify in §3 of PLAN
        samesite="lax",
        path="/",
    )
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True, "username": user.username}


@app.post("/logout")
def logout(request: Request, response: Response, db: DbSession = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        revoke_session(db, token)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


# ---------- auth-state endpoints ----------


@app.get("/me")
def me(user: User = Depends(current_user)):
    """Returns the current user. SPA bootstraps from this on mount."""
    return {
        "username": user.username,
        "display_name": user.display_name,
        "is_admin": bool(user.is_admin),
    }


@app.get("/auth/verify")
def auth_verify(user: Optional[User] = Depends(current_user_optional)):
    """Called by nginx auth_request. 200 + X-User on valid session, else 401."""
    if user is None:
        return Response(status_code=401)
    return Response(status_code=200, headers={"X-User": user.username})


# ---------- Docker monitor (auth-gated) ----------


@app.get("/containers", response_model=List[Dict[str, Any]])
def list_containers(_: User = Depends(current_user)):
    return get_containers()


@app.post("/containers/{container_id}/start", response_model=Dict[str, str])
def start_container_endpoint(container_id: str, _: User = Depends(current_admin)):
    result = start_container(container_id)
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@app.post("/containers/{container_id}/stop", response_model=Dict[str, str])
def stop_container_endpoint(container_id: str, _: User = Depends(current_admin)):
    result = stop_container(container_id)
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@app.post("/containers/{container_id}/restart", response_model=Dict[str, str])
def restart_container_endpoint(container_id: str, _: User = Depends(current_admin)):
    result = restart_container(container_id)
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@app.get("/containers/{container_id}/logs", response_model=Dict[str, Any])
def get_logs_endpoint(
    container_id: str,
    tail: Optional[int] = 50,
    _: User = Depends(current_user),
):
    result = get_container_logs(container_id, tail)
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])
    return result


# ---------- System stats (auth-gated) ----------


@app.get("/stats/system", response_model=Dict[str, Any])
def system_stats_endpoint(_: User = Depends(current_user)):
    return get_system_stats()


@app.get("/stats/containers/{container_id}", response_model=Dict[str, Any])
def container_stats_endpoint(container_id: str, _: User = Depends(current_user)):
    result = get_container_stats(container_id)
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])
    return result
