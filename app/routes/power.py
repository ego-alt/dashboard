"""Shut the Pi down from the dashboard (the power icon by Sign out, admins only).

The dashboard can't power off the machine it runs on. It leaves power/shutdown in
the folder it shares with the deploy script, and a systemd path unit on the Pi
(scripts/install-deploy-timer.sh) runs scripts/power.sh, which clears the request
and powers off. Docker stops every container on the way down, so the databases
close cleanly and the backup disk is unmounted.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

import app.routes.deploy as deploy
from app.auth import current_admin
from app.models import User

router = APIRouter(prefix="/system", tags=["system"])


@router.post("/shutdown", status_code=202)
def shutdown(admin: User = Depends(current_admin)):
    folder = deploy.STATE_DIR / "power"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "shutdown").write_text(f"{datetime.now(timezone.utc).isoformat()} by {admin.username}\n")
    return {"ok": True}
