"""The Monitor page: containers (state, logs, start/stop/restart for admins)
and the host's CPU, memory, disk and temperature."""
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

from app.auth import current_admin, current_user
from app.docker_control import (
    get_container_logs,
    get_container_stats,
    get_containers,
    resolve_container_name,
    restart_container,
    start_container,
    stop_container,
)
from app.models import User
from app.system_stats import get_system_stats

router = APIRouter(tags=["containers"])

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


def _unwrap(result: Dict[str, Any]) -> Dict[str, Any]:
    """Convert the docker_control ``{status, message}`` shape into an HTTP 400
    when status is error. Leaves the success body unchanged."""
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("message", "unknown error"))
    return result


@router.get("/containers", response_model=List[Dict[str, Any]])
def list_containers(stats: bool = False, _: User = Depends(current_user)):
    try:
        return get_containers(include_stats=stats)
    except Exception:
        raise HTTPException(status_code=503, detail="can't reach Docker")


@router.post("/containers/{container_id}/start", response_model=Dict[str, str])
def start_container_endpoint(container_id: str, _: User = Depends(current_admin)):
    _reject_if_protected(container_id, "start")
    return _unwrap(start_container(container_id))


@router.post("/containers/{container_id}/stop", response_model=Dict[str, str])
def stop_container_endpoint(container_id: str, _: User = Depends(current_admin)):
    _reject_if_protected(container_id, "stop")
    return _unwrap(stop_container(container_id))


@router.post("/containers/{container_id}/restart", response_model=Dict[str, str])
def restart_container_endpoint(container_id: str, _: User = Depends(current_admin)):
    _reject_if_protected(container_id, "restart")
    return _unwrap(restart_container(container_id))


@router.get("/containers/{container_id}/logs", response_model=Dict[str, Any])
def get_logs_endpoint(
    container_id: str,
    tail: Optional[int] = 50,
    _: User = Depends(current_user),
):
    return _unwrap(get_container_logs(container_id, tail))


@router.get("/stats/system", response_model=Dict[str, Any])
def system_stats_endpoint(_: User = Depends(current_user)):
    return get_system_stats()


@router.get("/stats/containers/{container_id}", response_model=Dict[str, Any])
def container_stats_endpoint(container_id: str, _: User = Depends(current_user)):
    return _unwrap(get_container_stats(container_id))
