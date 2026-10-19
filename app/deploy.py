"""The Deploy tab: what's deployed, what's waiting, and adding apps from GitHub.

The dashboard never builds or starts anything itself. It shares a folder with
the Pi's deploy script (scripts/deploy.sh, mounted here at DEPLOY_STATE_DIR):

  status.json          written by the script: the last outcome per repo
  logs/<name>.log      written by the script: each repo's deploy log
  apps/<name>.json     written here: apps enabled in the Deploy tab
  requests/<name>      written here: "deploy now"; a systemd path unit starts
                       the script at once, and the script deletes the file

so every deploy still goes through the same checks: CI must pass, the app
must come up healthy, and a bad commit is rolled back.
"""
import json
import os
import pathlib
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import current_admin
from app.models import User
from app.stack_manifest import ICON_MAX_BYTES, REQUIRED_FILES, ManifestError, app_name, name_problem, parse

router = APIRouter(prefix="/deploy", tags=["deploy"])

STATE_DIR = pathlib.Path(os.environ.get("DEPLOY_STATE_DIR", "/deploy"))
OWNER = os.environ.get("GITHUB_OWNER", "ego-alt")
TOKEN = os.environ.get("DEPLOY_GITHUB_TOKEN", "")

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

_cache: dict[str, tuple[float, Any]] = {}
_lock = threading.Lock()
# Why GitHub last failed to answer, shown on the page ("" when it's fine).
github_problem = ""


def _cached(key: str, ttl: float, fetch):
    """Cache a GitHub answer for `ttl` seconds; a failure (None) for 30."""
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < (ttl if hit[1] is not None else 30):
            return hit[1]
    value = fetch()
    with _lock:
        _cache[key] = (now, value)
    return value


def _get(url: str, *, api: bool = True, timeout: int = 10,
         accept: str = "application/vnd.github+json") -> tuple[int, bytes]:
    headers = {"User-Agent": "home-stack-dashboard"}
    if api:
        headers["Accept"] = accept
        if TOKEN:
            headers["Authorization"] = f"Bearer {TOKEN}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as res:
            return res.status, res.read()
    except urllib.error.HTTPError as e:
        return e.code, b""
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0, b""


def _api(path: str):
    global github_problem
    status, body = _get(f"https://api.github.com{path}")
    if status in (403, 429):
        github_problem = ("GitHub's rate limit is used up for now"
                          + ("." if TOKEN else "; set DEPLOY_GITHUB_TOKEN on the Pi to raise it."))
    elif status == 0:
        github_problem = "GitHub isn't answering."
    elif status == 200:
        github_problem = ""
    if status != 200:
        return None
    try:
        return json.loads(body)
    except ValueError:
        return None


def _raw(repo: str, branch: str, path: str) -> tuple[int, str]:
    if TOKEN:   # through the API, so private repos work too
        status, body = _get(f"https://api.github.com/repos/{repo}/contents/{path}?ref={branch}",
                            accept="application/vnd.github.raw")
    else:       # raw.githubusercontent.com doesn't count against the API's rate limit
        status, body = _get(f"https://raw.githubusercontent.com/{repo}/{branch}/{path}", api=False)
    return status, body.decode("utf-8", "replace") if status == 200 else ""


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


# ---------- GitHub ----------

def latest_commit(repo: str, branch: str) -> dict | None:
    def fetch():
        commit = _api(f"/repos/{repo}/commits/{branch}")
        if not commit:
            return None
        sha = commit["sha"]
        runs = (_api(f"/repos/{repo}/actions/workflows/ci.yml/runs?head_sha={sha}&per_page=5") or {}).get(
            "workflow_runs", [])
        if not runs:
            ci = "none"
        elif any(r["status"] != "completed" for r in runs):
            ci = "running"
        else:
            ci = "passed" if all(r["conclusion"] == "success" for r in runs) else "failed"
        return {"sha": sha, "message": commit["commit"]["message"].splitlines()[0][:120],
                "at": commit["commit"]["committer"]["date"], "ci": ci}
    return _cached(f"commit:{repo}:{branch}", 120, fetch)


def owner_repos() -> list[dict]:
    def fetch():
        # With a token, the owner's private repos too (those it's allowed to read).
        repos = _api("/user/repos?affiliation=owner&per_page=100&sort=pushed" if TOKEN
                     else f"/users/{OWNER}/repos?per_page=100&sort=pushed")
        if repos is None:
            return None
        repos = [r for r in repos if r["full_name"].split("/")[0].lower() == OWNER.lower()]
        return [{"repo": r["full_name"], "name": app_name(r["full_name"]), "description": r.get("description") or "",
                 "branch": r.get("default_branch") or "main", "pushed_at": r.get("pushed_at"),
                 "private": r.get("private", False)}
                for r in repos if not r.get("fork") and not r.get("archived")]
    repos = _cached(f"repos:{OWNER}", 300, fetch)
    if repos is None:
        raise HTTPException(502, github_problem or "Couldn't list your GitHub repos.")
    return repos


def check_repo(repo: str, branch: str) -> dict:
    """Whether a repo can join the stack, as a checklist."""
    name = app_name(repo)
    taken = {a["name"] for a in CORE} | {a["name"] for a in enabled_apps()}
    checks = []
    problem = name_problem(name)
    checks.append({"label": f"Served at /{name}/", "ok": not problem and name not in taken,
                   "detail": problem or ("Already on the stack." if name in taken else "")})
    files = {path: _raw(repo, branch, path) for path in REQUIRED_FILES}
    checks.append({"label": "Dockerfile", "ok": files["Dockerfile"][0] == 200,
                   "detail": "" if files["Dockerfile"][0] == 200 else "Add a Dockerfile at the repo's root."})
    manifest, detail = None, ""
    if files["homestack.toml"][0] != 200:
        detail = "Add homestack.toml (title, port, health path); see the dashboard's docs/APPS.md."
    else:
        try:
            manifest = parse(files["homestack.toml"][1])
        except ManifestError as e:
            detail = str(e)
    checks.append({"label": "homestack.toml", "ok": manifest is not None, "detail": detail})
    if manifest and manifest["icon"]:
        status, text = _raw(repo, branch, manifest["icon"])
        ok = status == 200 and "<svg" in text and len(text.encode()) <= ICON_MAX_BYTES
        checks.append({"label": f"Icon ({manifest['icon']})", "ok": ok,
                       "detail": "" if ok else "homestack.toml names an icon that isn't an SVG in the repo (64 KB at most)."})
    ci = files[".github/workflows/ci.yml"][0] == 200
    checks.append({"label": "CI workflow (.github/workflows/ci.yml)", "ok": ci,
                   "detail": "" if ci else "The Pi deploys only commits whose ci.yml run passed."})
    return {"repo": repo, "name": name, "branch": branch, "ok": all(c["ok"] for c in checks),
            "checks": checks, "manifest": manifest}


# ---------- endpoints ----------

def _row(app: dict, status: dict, containers: dict, queued: set[str], kind: str) -> dict:
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
        "latest": latest_commit(app["repo"], app["branch"]),
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
    return {"apps": rows, "owner": OWNER, "github_problem": github_problem}


@router.get("/repos")
def list_repos(_: User = Depends(current_admin)):
    on_stack = {a["repo"].lower() for a in CORE} | {a["repo"].lower() for a in enabled_apps()}
    repos = [r for r in owner_repos() if r["repo"].lower() not in on_stack]
    return {"owner": OWNER, "repos": repos}


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
    if repo["private"] and not TOKEN:
        raise HTTPException(400, "Private repos need DEPLOY_GITHUB_TOKEN in the dashboard's .env on the Pi.")
    folder = STATE_DIR / "apps"
    folder.mkdir(parents=True, exist_ok=True)
    entry = {"name": result["name"], "repo": repo["repo"], "branch": repo["branch"],
             "title": result["manifest"]["title"],
             "added_by": user.username, "added_at": datetime.now(timezone.utc).isoformat()}
    (folder / f"{result['name']}.json").write_text(json.dumps(entry, indent=2))
    request_deploy(result["name"])
    return {"app": entry}


@router.post("/apps/{name}/deploy", status_code=202)
def deploy_now(name: str, _: User = Depends(current_admin)):
    known = {a["name"]: a for a in CORE} | {a["name"]: a for a in enabled_apps()}
    app = known.get(name)
    if app is None:
        raise HTTPException(404, "No such app.")
    request_deploy(app.get("part_of") or name)
    return {"queued": True}


@router.delete("/apps/{name}")
def remove_app(name: str, _: User = Depends(current_admin)):
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
