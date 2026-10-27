"""The Services page: a tile per app, its icon, and the uptime strips."""
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session as DbSession

from app.auth import current_user
from app.db import get_db
from app.models import User
from app.services import DockerUnavailable, app_icon_path, list_services, svg_response
from app.uptime import uptime_summary

router = APIRouter(tags=["services"])


@router.get("/services", response_model=List[Dict[str, Any]])
def list_services_endpoint(_: User = Depends(current_user)):
    try:
        return list_services()
    except DockerUnavailable as e:
        return JSONResponse(
            status_code=503,
            content={"detail": "can't reach Docker", "services": e.last_known},
        )


@router.get("/services/{slug}/icon.svg")
def service_icon(slug: str, _: User = Depends(current_user)):
    """An added app's icon, copied from its repo by the Pi's deploy script."""
    path = app_icon_path(slug)
    if not path:
        raise HTTPException(404, "No icon.")
    return svg_response(path)


@router.get("/uptime")
def uptime_endpoint(
    days: int = 1,
    tz: int = 0,
    _: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    """Uptime strips: ``days=1`` gives 24 hourly buckets, otherwise one bucket
    per day. ``tz`` is the viewer's UTC offset in minutes (east positive)."""
    return uptime_summary(db, days=max(1, min(days, 90)), tz_offset_min=tz)
