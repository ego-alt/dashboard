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
    age_seconds = None
    stale = True
    finished = data.get("finished_at")
    if finished:
        try:
            ts = datetime.fromisoformat(str(finished).replace("Z", "+00:00"))
            age_seconds = (datetime.now(timezone.utc) - ts).total_seconds()
            stale = age_seconds > _BACKUP_STALE_HOURS * 3600
        except ValueError:
            pass
    return {"available": True, "age_seconds": age_seconds, "stale": stale, **data}
