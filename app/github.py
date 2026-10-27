"""Reading GitHub for the Deploy tab and the phone apps: the owner's repos,
each repo's latest commit with its CI result, files and releases.

Answers are cached (a failure briefly), and `problem` says why GitHub last
failed to answer, for the pages to show ("" when it's fine). A token
(DEPLOY_GITHUB_TOKEN, read-only) raises the rate limit and reaches private repos.
"""
import json
import os
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from app.stack_manifest import app_name

OWNER = os.environ.get("GITHUB_OWNER", "ego-alt")
TOKEN = os.environ.get("DEPLOY_GITHUB_TOKEN", "")
LATEST_TTL = 120          # seconds a repo's latest commit stays cached

_cache: dict[str, tuple[float, Any]] = {}
_lock = threading.Lock()
problem = ""


def cached(key: str, ttl: float, fetch):
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


def get(url: str, *, api: bool = True, timeout: int = 10,
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


def api(path: str):
    """GET a GitHub API path as JSON, or None; notes why in `problem`."""
    global problem
    status, body = get(f"https://api.github.com{path}")
    if status in (403, 429):
        problem = ("GitHub's rate limit is used up for now"
                   + ("." if TOKEN else "; set DEPLOY_GITHUB_TOKEN on the Pi to raise it."))
    elif status == 401:
        problem = "GitHub refused DEPLOY_GITHUB_TOKEN; it may have expired."
    elif status == 0:
        problem = "GitHub isn't answering."
    elif status == 200:
        problem = ""
    if status != 200:
        return None
    try:
        return json.loads(body)
    except ValueError:
        return None


def raw(repo: str, branch: str, path: str) -> tuple[int, str]:
    """A file from a repo: (HTTP status, text)."""
    if TOKEN:   # through the API, so private repos work too
        status, body = get(f"https://api.github.com/repos/{repo}/contents/{path}?ref={branch}",
                           accept="application/vnd.github.raw")
    else:       # raw.githubusercontent.com doesn't count against the API's rate limit
        status, body = get(f"https://raw.githubusercontent.com/{repo}/{branch}/{path}", api=False)
    return status, body.decode("utf-8", "replace") if status == 200 else ""


def cached_latest(repo: str, branch: str) -> dict | None:
    """The latest commit if it's already cached and fresh; never asks GitHub."""
    hit = _cache.get(f"commit:{repo}:{branch}")
    return hit[1] if hit and time.monotonic() - hit[0] < LATEST_TTL else None


def latest_commit(repo: str, branch: str) -> dict | None:
    """A branch's newest commit and its CI result (passed, failed, running, none)."""
    def fetch():
        commit = api(f"/repos/{repo}/commits/{branch}")
        if not commit:
            return None
        sha = commit["sha"]
        runs = (api(f"/repos/{repo}/actions/workflows/ci.yml/runs?head_sha={sha}&per_page=5") or {}).get(
            "workflow_runs", [])
        if not runs:
            ci = "none"
        elif any(r["status"] != "completed" for r in runs):
            ci = "running"
        else:
            ci = "passed" if all(r["conclusion"] == "success" for r in runs) else "failed"
        return {"sha": sha, "message": commit["commit"]["message"].splitlines()[0][:120],
                "at": commit["commit"]["committer"]["date"], "ci": ci}
    return cached(f"commit:{repo}:{branch}", LATEST_TTL, fetch)


def owner_repos() -> list[dict] | None:
    """The owner's own repos (not forks or archived), newest push first; None if GitHub didn't answer."""
    def fetch():
        # With a token, the owner's private repos too (those it's allowed to read).
        repos = api("/user/repos?affiliation=owner&per_page=100&sort=pushed" if TOKEN
                    else f"/users/{OWNER}/repos?per_page=100&sort=pushed")
        if repos is None:
            return None
        repos = [r for r in repos if r["full_name"].split("/")[0].lower() == OWNER.lower()]
        return [{"repo": r["full_name"], "name": app_name(r["full_name"]), "description": r.get("description") or "",
                 "branch": r.get("default_branch") or "main", "pushed_at": r.get("pushed_at"),
                 "private": r.get("private", False)}
                for r in repos if not r.get("fork") and not r.get("archived")]
    return cached(f"repos:{OWNER}", 300, fetch)


def latest_release(repo: str, ttl: float = 120) -> dict | None:
    """A repo's newest release, as GitHub gives it, or None."""
    return cached(f"release:{repo}", ttl, lambda: api(f"/repos/{repo}/releases/latest"))
