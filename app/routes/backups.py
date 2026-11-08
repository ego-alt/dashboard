"""The last backup run, for the Monitor page and the Services status line. The
dashboard holds no restic credentials: it only reads the summary that
scripts/restic-backup.sh writes."""
import json
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from app.auth import current_admin
from app.models import User

router = APIRouter(tags=["backups"])

_BACKUP_STATUS_FILE = os.environ.get(
    "BACKUP_STATUS_FILE", "/var/lib/home-stack-backup/status.json"
)
_BACKUP_STALE_HOURS = float(os.environ.get("BACKUP_STALE_AFTER_HOURS", "36"))
# A run marked running for longer than this was cut off before it could write.
_BACKUP_INTERRUPTED_HOURS = 6


def _seconds_since(stamp) -> float | None:
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))).total_seconds()
    except ValueError:
        return None


def backup_state(data: dict, age_seconds: float | None) -> str:
    """running | interrupted | failed | stale | healthy: the one reading of the
    status file, which the Services line and the Monitor card both show."""
    if data.get("running_since"):
        running = _seconds_since(data["running_since"])
        return "running" if running is not None and running < _BACKUP_INTERRUPTED_HOURS * 3600 else "interrupted"
    if not data.get("ok"):
        return "failed"
    if age_seconds is None or age_seconds > _BACKUP_STALE_HOURS * 3600:
        return "stale"
    return "healthy"


@router.get("/backups/status")
def backup_status_endpoint(_: User = Depends(current_admin)):
    """Last backup run, read from the status file ``restic-backup.sh`` writes.
    The dashboard holds no restic creds — it only reads this summary, and a
    missing file just means no backup has run yet."""
    if not os.path.exists(_BACKUP_STATUS_FILE):
        return {"available": False}
    try:
        with open(_BACKUP_STATUS_FILE) as f:
            data = json.load(f)
    except (OSError, ValueError):
        raise HTTPException(status_code=500, detail="backup status file unreadable")
    age_seconds = _seconds_since(data["finished_at"]) if data.get("finished_at") else None
    return {"available": True, "state": backup_state(data, age_seconds), "age_seconds": age_seconds, **data}
