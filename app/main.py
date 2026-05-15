"""Dashboard API: Docker monitor + auth provider for the home stack."""

import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session as DbSession

from app.auth import (
    clear_session_cookie,
    current_admin,
    current_user,
    current_user_optional,
    mint_session,
    revoke_session,
    set_session_cookie,
    verify_password,
    SESSION_COOKIE,
)
from app.db import get_db, init_db
from app.docker_control import (
    get_container_logs,
    get_container_stats,
    get_containers,
    restart_container,
    start_container,
    stop_container,
)
from app.models import User
from app.system_stats import get_system_stats


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="Dashboard API", lifespan=lifespan)


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
    user.last_login_at = datetime.now(timezone.utc)
    token = mint_session(
        db,
        user,
        ip=(request.client.host if request.client else "") or "",
        user_agent=request.headers.get("user-agent", ""),
    )
    set_session_cookie(response, token)
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
    }


@app.get("/auth/verify")
def auth_verify(user: Optional[User] = Depends(current_user_optional)):
    if user is None:
        return Response(status_code=401)
    return Response(status_code=200, headers={"X-User": user.username})


# ---------- Docker monitor (auth-gated) ----------


@app.get("/containers", response_model=List[Dict[str, Any]])
def list_containers(_: User = Depends(current_user)):
    return get_containers()


@app.post("/containers/{container_id}/start", response_model=Dict[str, str])
def start_container_endpoint(container_id: str, _: User = Depends(current_admin)):
    return _unwrap(start_container(container_id))


@app.post("/containers/{container_id}/stop", response_model=Dict[str, str])
def stop_container_endpoint(container_id: str, _: User = Depends(current_admin)):
    return _unwrap(stop_container(container_id))


@app.post("/containers/{container_id}/restart", response_model=Dict[str, str])
def restart_container_endpoint(container_id: str, _: User = Depends(current_admin)):
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
