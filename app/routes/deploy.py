"""The Deploy tab: what's deployed, what's waiting, and adding apps from GitHub.

The dashboard never builds or starts anything itself. It shares a folder with
the Pi's deploy script (scripts/deploy.sh, mounted here at DEPLOY_STATE_DIR):

  status.json          written by the script: the last outcome per repo
  logs/<name>.log      written by the script: each repo's deploy log
  apps/<name>.json     written here: apps enabled in the Deploy tab
  phone-apps/<name>.*  written here: phone apps, which the script never sees
                       (nothing to run; see app/routes/phone_apps.py)
  requests/<name>      written here: "deploy now"; a systemd path unit starts
                       the script at once, and the script deletes the file

so every deploy still goes through the same checks: CI must pass, the app
must come up healthy, and a bad commit is rolled back.
"""
import json
import os
import pathlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import github
from app.auth import current_admin
from app.models import User
from app.stack_manifest import ICON_MAX_BYTES, ManifestError, app_name, name_problem, parse, required_files

router = APIRouter(prefix="/deploy", tags=["deploy"])

STATE_DIR = pathlib.Path(os.environ.get("DEPLOY_STATE_DIR", "/deploy"))
OWNER = github.OWNER

# The stack's own repos: deployed by the same script, listed first.
CORE = [
    {"name": "dashboard", "repo": f"{OWNER}/dashboard", "branch": "master", "container": "dashboard",
     "title": "Dashboard"},
    {"name": "mcp", "repo": f"{OWNER}/dashboard", "branch": "master", "container": "mcp",
     "title": "MCP server", "part_of": "dashboard"},
    {"name": "library", "repo": f"{OWNER}/library", "branch": "master", "container": "library", "title": "Shelves"},
    {"name": "calendar", "repo": f"{OWNER}/calendar", "branch": "master", "container": "calendar",
     "title": "Calendar"},
    {"name": "tapes", "repo": f"{OWNER}/tapes", "branch": "main", "container": "music", "title": "Tapes"},
]

# ---------- the shared folder ----------

def _status() -> dict:
    try:
        return json.loads((STATE_DIR / "status.json").read_text())
    except (OSError, ValueError):
        return {}


def enabled_apps() -> list[dict]:
    apps = []
    for path in sorted((STATE_DIR / "apps").glob("*.json")):
        try:
            apps.append(json.loads(path.read_text()))
        except (OSError, ValueError):
            continue
    return apps


def _queued() -> set[str]:
    folder = STATE_DIR / "requests"
    return {p.name for p in folder.iterdir()} if folder.exists() else set()


def request_deploy(name: str):
    folder = STATE_DIR / "requests"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(datetime.now(timezone.utc).isoformat())


def owner_repos() -> list[dict]:
    repos = github.owner_repos()
    if repos is None:
        raise HTTPException(502, github.problem or "Couldn't list your GitHub repos.")
    return repos


def phone_apps() -> list[dict]:
    from app.routes.phone_apps import registered
    return registered()


def check_repo(repo: str, branch: str) -> dict:
    """Whether a repo can join the stack, as a checklist. A phone app
    (kind = "android") needs no Dockerfile: it's listed, not served."""
    name = app_name(repo)
    taken = {a["name"] for a in CORE} | {a["name"] for a in enabled_apps()} | {a["name"] for a in phone_apps()}
    status, text = github.raw(repo, branch, "homestack.toml")
    manifest, detail = None, ""
    if status != 200:
        detail = "Add homestack.toml (title, port, health path); see the dashboard's docs/APPS.md."
    else:
        try:
            manifest = parse(text)
        except ManifestError as e:
            detail = str(e)
    kind = manifest["kind"] if manifest else "web"
    files = {path: github.raw(repo, branch, path) for path in required_files(kind) if path != "homestack.toml"}
    checks = []
    problem = name_problem(name)
    checks.append({"label": f"Served at /{name}/" if kind == "web" else f"Listed under Phone apps as {name}",
                   "ok": not problem and name not in taken,
                   "detail": problem or ("Already on the stack." if name in taken else "")})
    if kind == "web":
        checks.append({"label": "Dockerfile", "ok": files["Dockerfile"][0] == 200,
                       "detail": "" if files["Dockerfile"][0] == 200 else "Add a Dockerfile at the repo's root."})
    checks.append({"label": "homestack.toml", "ok": manifest is not None, "detail": detail})
    if manifest and manifest["icon"]:
        status, text = github.raw(repo, branch, manifest["icon"])
        ok = status == 200 and "<svg" in text and len(text.encode()) <= ICON_MAX_BYTES
        checks.append({"label": f"Icon ({manifest['icon']})", "ok": ok,
                       "detail": "" if ok else "homestack.toml names an icon that isn't an SVG in the repo (64 KB at most)."})
    ci = files[".github/workflows/ci.yml"][0] == 200
    checks.append({"label": "CI workflow (.github/workflows/ci.yml)", "ok": ci, "detail": "" if ci else (
        "The Pi deploys only commits whose ci.yml run passed." if kind == "web"
        else "Its CI builds the signed APK and publishes it as a release (tag v<versionCode>).")})
    return {"repo": repo, "name": name, "branch": branch, "ok": all(c["ok"] for c in checks),
            "checks": checks, "manifest": manifest}


# ---------- endpoints ----------

def _row(app: dict, status: dict, containers: dict, queued: set[str], kind: str) -> dict:
    """An app as the Pi sees it. "Latest on GitHub" only if it's already cached:
    asking GitHub takes seconds, so the page gets it from /deploy/apps/latest."""
    # What the Pi has checked out (written every run), with the last deploy's
    # outcome when it was for that same commit.
    head = status.get("_heads", {}).get(app.get("part_of") or app["name"])
    last = status.get(app["name"])
    if head:
        deployed = {"sha": head, "result": last["result"], "at": last["at"]} if last and last.get("sha") == head \
            else {"sha": head, "result": None, "at": None}
    else:
        deployed = last
    container = containers.get(app.get("container") or app["name"])
    return {
        "name": app["name"], "kind": kind, "repo": app["repo"], "branch": app["branch"],
        "title": app.get("title") or app["name"], "part_of": app.get("part_of"),
        "deployed": deployed,
        "latest": github.cached_latest(app["repo"], app["branch"]),
        "container": {"state": container["state"], "status": container.get("status")} if container else None,
        "queued": app.get("part_of", app["name"]) in queued,
    }


@router.get("/apps")
def list_apps(_: User = Depends(current_admin)):
    from app.docker_control import get_containers
    try:
        containers = {c["name"]: c for c in get_containers()}
    except Exception:  # noqa: BLE001 — Docker unreachable: show what we know
        containers = {}
    status, queued = _status(), _queued()
    rows = [_row(a, status, containers, queued, "core") for a in CORE]
    for app in enabled_apps():
        rows.append(_row({**app, "container": app["name"]}, status, containers, queued, "app"))
    from app.routes.phone_apps import latest_release
    for app in phone_apps():      # nothing deployed: what matters is the newest release
        release = latest_release(app)
        rows.append({"name": app["name"], "kind": "phone", "repo": app["repo"], "branch": app["branch"],
                     "title": app.get("title") or app["name"], "part_of": None, "deployed": None,
                     "latest": github.cached_latest(app["repo"], app["branch"]), "container": None, "queued": False,
                     "release": {"version_code": release["version_code"], "version_name": release["version_name"],
                                 "published_at": release["published_at"]} if release else None})
    return {"apps": rows, "owner": OWNER, "github_problem": github.problem}


def _stack() -> list[dict]:
    return CORE + enabled_apps() + phone_apps()


@router.get("/apps/latest")
def list_latest(_: User = Depends(current_admin)):
    """Each app's latest commit on GitHub with its CI result, every repo asked
    at once (one after another took several seconds)."""
    apps = _stack()
    repos = sorted({(a["repo"], a.get("branch", "main")) for a in apps})
    with ThreadPoolExecutor(max_workers=8) as pool:
        found = dict(zip(repos, pool.map(lambda r: github.latest_commit(*r), repos), strict=True))
    return {"latest": {a["name"]: found[(a["repo"], a.get("branch", "main"))] for a in apps},
            "github_problem": github.problem}


@router.get("/repos")
def list_repos(_: User = Depends(current_admin)):
    on_stack = {a["repo"].lower() for a in _stack()}
    repos = [r for r in owner_repos() if r["repo"].lower() not in on_stack]
    # Without a token GitHub lists only public repos.
    return {"owner": OWNER, "repos": repos, "private_hidden": not github.TOKEN}


@router.get("/repos/{name}/check")
def check(name: str, _: User = Depends(current_admin)):
    repo = next((r for r in owner_repos() if r["name"] == name.lower()), None)
    if repo is None:
        raise HTTPException(404, f"No repo called {name} under {OWNER}.")
    return check_repo(repo["repo"], repo["branch"])


class AddApp(BaseModel):
    name: str


@router.post("/apps", status_code=201)
def add_app(body: AddApp, user: User = Depends(current_admin)):
    repo = next((r for r in owner_repos() if r["name"] == body.name.lower()), None)
    if repo is None:
        raise HTTPException(404, f"No repo called {body.name} under {OWNER}.")
    result = check_repo(repo["repo"], repo["branch"])
    if not result["ok"]:
        raise HTTPException(400, "This repo isn't ready yet: " + "; ".join(
            c["detail"] or c["label"] for c in result["checks"] if not c["ok"]))
    if repo["private"] and not github.TOKEN:
        raise HTTPException(400, "Private repos need DEPLOY_GITHUB_TOKEN in the dashboard's .env on the Pi.")
    manifest = result["manifest"]
    if manifest["kind"] == "android":
        return {"app": _add_phone_app(result, repo, manifest, user)}
    folder = STATE_DIR / "apps"
    folder.mkdir(parents=True, exist_ok=True)
    entry = {"name": result["name"], "repo": repo["repo"], "branch": repo["branch"],
             "title": result["manifest"]["title"],
             "added_by": user.username, "added_at": datetime.now(timezone.utc).isoformat()}
    (folder / f"{result['name']}.json").write_text(json.dumps(entry, indent=2))
    request_deploy(result["name"])
    return {"app": entry}


def _add_phone_app(result: dict, repo: dict, manifest: dict, user: User) -> dict:
    """A phone app is listed, not deployed: its details and icon go where
    Services reads them, and the deploy script never sees it."""
    folder = STATE_DIR / "phone-apps"
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        raise HTTPException(500, "The dashboard can't write to phone-apps/ in the deploy folder; run "
                            "scripts/install-deploy-timer.sh on the Pi again to set its permissions.") from None
    entry = {"name": result["name"], "repo": repo["repo"], "branch": repo["branch"], "kind": "android",
             "title": manifest["title"], "description": manifest["description"], "accent": manifest["accent"],
             "package": manifest["package"], "private": repo["private"],
             "added_by": user.username, "added_at": datetime.now(timezone.utc).isoformat()}
    if manifest["icon"]:
        status, text = github.raw(repo["repo"], repo["branch"], manifest["icon"])
        if status == 200 and "<svg" in text and len(text.encode()) <= ICON_MAX_BYTES:
            (folder / f"{result['name']}.svg").write_text(text)
    (folder / f"{result['name']}.json").write_text(json.dumps(entry, indent=2))
    return entry


@router.post("/apps/{name}/deploy", status_code=202)
def deploy_now(name: str, _: User = Depends(current_admin)):
    known = {a["name"]: a for a in CORE} | {a["name"]: a for a in enabled_apps()}
    app = known.get(name)
    if app is None:
        raise HTTPException(404, "No such app." if name not in {a["name"] for a in phone_apps()}
                            else "A phone app ships when its CI publishes a release.")
    request_deploy(app.get("part_of") or name)
    return {"queued": True}


@router.delete("/apps/{name}")
def remove_app(name: str, _: User = Depends(current_admin)):
    phone = STATE_DIR / "phone-apps" / f"{name}.json"
    if phone.exists():          # nothing running to stop; installed copies stay on phones
        phone.unlink()
        (STATE_DIR / "phone-apps" / f"{name}.svg").unlink(missing_ok=True)
        return {"removed": name}
    path = STATE_DIR / "apps" / f"{name}.json"
    if not path.exists():
        raise HTTPException(404, "Only apps added here can be removed.")
    path.unlink()
    request_deploy(name)        # the script stops it on its next run, which this starts
    return {"removed": name}


@router.get("/apps/{name}/log")
def app_log(name: str, tail: int = 300, _: User = Depends(current_admin)):
    known = {a["name"] for a in CORE} | {a["name"] for a in enabled_apps()}
    if name not in known:
        raise HTTPException(404, "No such app.")
    path = STATE_DIR / "logs" / f"{'dashboard' if name == 'mcp' else name}.log"
    try:
        lines = path.read_text(errors="replace").splitlines()[-max(1, min(tail, 2000)):]
    except OSError:
        lines = []
    return {"lines": lines}
