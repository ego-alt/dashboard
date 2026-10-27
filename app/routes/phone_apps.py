"""Phone apps: Android apps from the owner's repos, installed and updated from
the dashboard.

A repo joins in the Deploy tab like any app, with kind = "android" and its
package name in homestack.toml (app/stack_manifest.py). Nothing runs on the Pi:
the app's CI builds a signed APK and publishes it as a GitHub release, tagged
v<versionCode> and named after its versionName, with the APK attached. A
release exists only once CI has passed, as a deploy waits for CI.

  phone-apps/<name>.json   in the deploy state folder: the apps added (written
                           by app/routes/deploy.py), with their title and colour
  phone-apps/<name>.svg    their icon
  <PHONE_APPS_DIR>/<name>/ the APKs, fetched from GitHub once and kept here, so
                           phones install over the tailnet, not from GitHub

Services lists them with Install, Update or Up to date. A web page can't see
what a phone has installed, so the app says so itself: when it checks for an
update (GET /phone-apps/<name>/latest?installed=<versionCode>) the version is
recorded for whoever's signed in. That check and the download also take an API
token (the app holds one already, for the calendar), unlike the rest of the
dashboard: a token here can read releases and fetch an APK, nothing more.
"""
import json
import os
import pathlib
import re
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session as DbSession

from app import github
from app.auth import current_user, current_user_cookie_or_token
from app.db import get_db
from app.models import InstalledApp, User
from app.routes import deploy
from app.services import svg_response

router = APIRouter(prefix="/phone-apps", tags=["phone-apps"])

APK_DIR = pathlib.Path(os.environ.get("PHONE_APPS_DIR", "data/phone-apps"))
RELEASE_TTL = 120          # seconds a release stays cached
KEEP = 2                   # APKs kept per app: the latest and the one before
_TAG = re.compile(r"^v?(\d+)$")
_fetching: set[str] = set()
_fetch_lock = threading.Lock()


def folder() -> pathlib.Path:
    return deploy.STATE_DIR / "phone-apps"


def registered() -> list[dict]:
    apps = []
    for path in sorted(folder().glob("*.json")):
        try:
            apps.append(json.loads(path.read_text()))
        except (OSError, ValueError):
            continue
    return apps


def find(name: str) -> dict:
    app = next((a for a in registered() if a["name"] == name), None)
    if app is None:
        raise HTTPException(404, "No such phone app.")
    return app


# ---------- releases on GitHub ----------

def latest_release(app: dict) -> Optional[dict]:
    """The newest release with an APK, or None (none yet, or GitHub not answering)."""
    release = github.latest_release(app["repo"], RELEASE_TTL)
    if not release:
        return None
    tag = _TAG.match(release.get("tag_name") or "")
    apk = next((a for a in release.get("assets") or [] if a.get("name", "").endswith(".apk")), None)
    if not tag or not apk:
        return None
    return {
        "version_code": int(tag.group(1)),
        "version_name": (release.get("name") or release["tag_name"]).strip(),
        "notes": (release.get("body") or "").strip(),
        "published_at": release.get("published_at"),
        "size": apk.get("size"),
        "asset_url": apk.get("url"),                       # the API's: works for private repos
        "download_url": apk.get("browser_download_url"),
    }


def apk_path(name: str, version_code: int) -> pathlib.Path:
    return APK_DIR / name / f"{name}-{version_code}.apk"


class _NoAuthOnRedirect(urllib.request.HTTPRedirectHandler):
    """GitHub sends asset downloads on to storage that rejects our token."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None:
            new.remove_header("Authorization")
        return new


def _download(app: dict, release: dict) -> None:
    target = apk_path(app["name"], release["version_code"])
    target.parent.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": "home-stack-dashboard", "Accept": "application/octet-stream"}
    if github.TOKEN:
        headers["Authorization"] = f"Bearer {github.TOKEN}"
    url = release["asset_url"] if github.TOKEN else release["download_url"]
    tmp = target.with_suffix(".part")
    try:
        opener = urllib.request.build_opener(_NoAuthOnRedirect)
        with opener.open(urllib.request.Request(url, headers=headers), timeout=120) as res, tmp.open("wb") as out:
            while chunk := res.read(1 << 16):
                out.write(chunk)
        if release.get("size") and tmp.stat().st_size != release["size"]:
            raise OSError("size doesn't match the release")
        tmp.replace(target)
        older = sorted(target.parent.glob("*.apk"), key=lambda p: p.stat().st_mtime, reverse=True)[KEEP:]
        for old in older:
            old.unlink(missing_ok=True)
    except (urllib.error.URLError, OSError):
        tmp.unlink(missing_ok=True)
    finally:
        with _fetch_lock:
            _fetching.discard(app["name"])


def ready(app: dict, release: Optional[dict]) -> bool:
    """Whether the release's APK is here to install; if not, start fetching it."""
    if not release:
        return False
    if apk_path(app["name"], release["version_code"]).is_file():
        return True
    with _fetch_lock:
        if app["name"] in _fetching:
            return False
        _fetching.add(app["name"])
    threading.Thread(target=_download, args=(app, release), daemon=True).start()
    return False


# ---------- endpoints ----------

def phone_user(user: Optional[User] = Depends(current_user_cookie_or_token)) -> User:
    """Signed in, or holding an API token (the phone app itself)."""
    if user is None:
        raise HTTPException(401, "not authenticated")
    return user


def _public(release: Optional[dict]) -> Optional[dict]:
    if not release:
        return None
    return {k: release[k] for k in ("version_code", "version_name", "notes", "published_at", "size")}


def _installed(db: DbSession, user: User) -> dict[str, InstalledApp]:
    return {i.app: i for i in db.query(InstalledApp).filter(InstalledApp.user_id == user.id)}


@router.get("")
def list_phone_apps(user: User = Depends(current_user), db: DbSession = Depends(get_db)) -> dict[str, Any]:
    installed = _installed(db, user)
    apps = []
    for app in registered():
        release = latest_release(app)
        mine = installed.get(app["name"])
        apps.append({
            "name": app["name"], "title": app.get("title") or app["name"],
            "description": app.get("description", ""), "accent": app.get("accent") or None,
            "package": app.get("package"),
            "icon_url": f"/phone-apps/{app['name']}/icon.svg" if (folder() / f"{app['name']}.svg").is_file() else None,
            "latest": _public(release), "ready": ready(app, release),
            "installed": {"version_code": mine.version_code, "version_name": mine.version_name,
                          "seen_at": mine.seen_at.isoformat()} if mine else None,
        })
    return {"apps": apps, "github_problem": github.problem}


@router.get("/{name}/latest")
def latest(name: str, installed: Optional[int] = None, installed_name: str = "",
           user: User = Depends(phone_user), db: DbSession = Depends(get_db)) -> dict[str, Any]:
    """What the app asks on launch: the newest release, and whether to offer it.
    The version it reports is remembered for Services."""
    app = find(name)
    if installed is not None and installed >= 0:
        row = db.query(InstalledApp).filter(InstalledApp.user_id == user.id, InstalledApp.app == name).first()
        if row is None:
            row = InstalledApp(user_id=user.id, app=name, version_code=installed)
            db.add(row)
        row.version_code, row.version_name = installed, installed_name[:40]
        row.seen_at = datetime.now(timezone.utc)
        db.commit()
    release = latest_release(app)
    return {"latest": _public(release), "ready": ready(app, release),
            "update": bool(release and installed is not None and release["version_code"] > installed),
            "download": f"/phone-apps/{name}/download"}


@router.get("/{name}/download")
def download(name: str, _: User = Depends(phone_user)):
    app = find(name)
    release = latest_release(app)
    if not release:
        raise HTTPException(404, "No release of this app yet.")
    if not ready(app, release):
        raise HTTPException(503, "The Pi is still fetching this version from GitHub; try again in a minute.")
    return FileResponse(apk_path(name, release["version_code"]), media_type="application/vnd.android.package-archive",
                        filename=f"{name}-{release['version_name']}.apk")


@router.get("/{name}/icon.svg")
def icon(name: str, _: User = Depends(current_user)):
    find(name)
    path = folder() / f"{name}.svg"
    if not path.is_file():
        raise HTTPException(404, "No icon.")
    return svg_response(path)
