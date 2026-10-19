"""The Deploy tab's API, the app manifest, and the Pi-side renderer, with
GitHub and Docker stubbed out."""
import importlib.util
import json
import pathlib

import pytest

import app.deploy as deploy
from app.stack_manifest import ManifestError, name_problem, parse

ROOT = pathlib.Path(__file__).resolve().parent.parent

GOOD_MANIFEST = 'title = "Situation"\ndescription = "World news"\nicon = "icon.svg"\n[env]\nNTFY_TOPIC = "${NTFY_TOPIC}"\n'


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy, "STATE_DIR", tmp_path)
    monkeypatch.setattr(deploy, "_cache", {})
    (tmp_path / "status.json").write_text(json.dumps(
        {"dashboard": {"sha": "abc1234", "result": "deployed", "at": "2026-10-19T04:22:11+0100"}}))
    repos = [
        {"repo": "ego-alt/situation", "name": "situation", "description": "World news", "branch": "main",
         "pushed_at": "2026-10-19T10:00:00Z", "private": False},
        {"repo": "ego-alt/half-done", "name": "half-done", "description": "", "branch": "main",
         "pushed_at": "2026-10-18T10:00:00Z", "private": False},
        {"repo": "ego-alt/library", "name": "library", "description": "", "branch": "master",
         "pushed_at": None, "private": False},
    ]
    monkeypatch.setattr(deploy, "owner_repos", lambda: repos)
    files = {
        ("ego-alt/situation", "Dockerfile"): "FROM python:3.11-slim",
        ("ego-alt/situation", "homestack.toml"): GOOD_MANIFEST,
        ("ego-alt/situation", ".github/workflows/ci.yml"): "name: CI",
        ("ego-alt/situation", "icon.svg"): '<svg viewBox="0 0 24 24"></svg>',
        ("ego-alt/half-done", "Dockerfile"): "FROM node:22",
    }
    monkeypatch.setattr(deploy, "_raw", lambda repo, branch, path: (200, files[(repo, path)])
                        if (repo, path) in files else (404, ""))
    monkeypatch.setattr(deploy, "latest_commit", lambda repo, branch: {
        "sha": "def5678", "message": "small/fix", "at": "2026-10-19T10:00:00Z", "ci": "passed"})
    import app.docker_control as dc
    monkeypatch.setattr(dc, "get_containers", lambda: [{"name": "dashboard", "state": "up", "status": "running"}])
    return tmp_path


def _admin(client, make_user):
    make_user(username="admin", is_admin=True)
    assert client.post("/login", data={"username": "admin", "password": "hunter2-secret"}).status_code == 200
    return client


def test_admins_only(client, make_user, state):
    make_user(username="bob")
    client.post("/login", data={"username": "bob", "password": "hunter2-secret"})
    assert client.get("/deploy/apps").status_code == 403


def test_lists_the_stack_with_deployed_and_latest(client, make_user, state):
    apps = _admin(client, make_user).get("/deploy/apps").json()["apps"]
    assert [a["name"] for a in apps] == ["dashboard", "mcp", "library", "calendar", "tapes"]
    dash = apps[0]
    assert dash["deployed"]["sha"] == "abc1234" and dash["latest"]["ci"] == "passed"
    assert dash["container"]["state"] == "up" and dash["queued"] is False


def test_repos_on_offer_exclude_the_stack(client, make_user, state):
    body = _admin(client, make_user).get("/deploy/repos").json()
    assert [r["name"] for r in body["repos"]] == ["situation", "half-done"] and body["private_hidden"] is True


def test_checklist(client, make_user, state):
    c = _admin(client, make_user)
    ready = c.get("/deploy/repos/situation/check").json()
    assert ready["ok"] and ready["manifest"]["title"] == "Situation" and ready["manifest"]["port"] == 8000
    assert "Icon (icon.svg)" in {x["label"] for x in ready["checks"]}
    half = c.get("/deploy/repos/half-done/check").json()
    assert not half["ok"]
    missing = {x["label"] for x in half["checks"] if not x["ok"]}
    assert missing == {"homestack.toml", "CI workflow (.github/workflows/ci.yml)"}


def test_add_deploy_and_remove(client, make_user, state):
    c = _admin(client, make_user)
    assert c.post("/deploy/apps", json={"name": "half-done"}).status_code == 400   # not ready
    r = c.post("/deploy/apps", json={"name": "situation"})
    assert r.status_code == 201
    entry = json.loads((state / "apps" / "situation.json").read_text())
    assert entry["repo"] == "ego-alt/situation" and entry["title"] == "Situation" and entry["added_by"] == "admin"
    assert (state / "requests" / "situation").exists()                             # deploys at once
    assert "situation" in [a["name"] for a in c.get("/deploy/apps").json()["apps"]]
    assert "situation" not in [r["name"] for r in c.get("/deploy/repos").json()["repos"]]

    (state / "requests" / "situation").unlink()
    assert c.post("/deploy/apps/mcp/deploy").status_code == 202
    assert (state / "requests" / "dashboard").exists()                             # mcp ships with the dashboard

    assert c.delete("/deploy/apps/library").status_code == 404                     # core apps stay
    assert c.delete("/deploy/apps/situation").status_code == 200
    assert not (state / "apps" / "situation.json").exists() and (state / "requests" / "situation").exists()


def test_log_tail(client, make_user, state):
    (state / "logs").mkdir()
    (state / "logs" / "tapes.log").write_text("\n".join(f"line {i}" for i in range(500)))
    lines = _admin(client, make_user).get("/deploy/apps/tapes/log?tail=3").json()["lines"]
    assert lines == ["line 497", "line 498", "line 499"]


def test_manifest_rules():
    m = parse(GOOD_MANIFEST)
    assert (m["port"], m["health"], m["data"], m["env"]) == (8000, "/healthz", None, {"NTFY_TOPIC": "${NTFY_TOPIC}"})
    for bad in ('description = "no title"', 'title = "x"\nport = 70000', 'title = "x"\nhealth = "healthz"',
                'title = "x"\ndata = "relative"', 'title = "x"\nicon = "globe"', 'title = "x"\naccent = "gold"', 'title = "x"\naccent = "#1a2030"', 'title = "x"\nicon = "../x.svg"', 'title = "x"\n[env]\nlower = "1"', "not toml ["):
        with pytest.raises(ManifestError):
            parse(bad)
    assert parse('title = "x"\naccent = "#FFB020"')["accent"] == "#ffb020"
    assert name_problem("situation") is None
    assert name_problem("library") and name_problem("Bad_Name") and name_problem("login")


# ---------- the Pi-side renderer ----------

def _renderer():
    spec = importlib.util.spec_from_file_location("stack_render", ROOT / "scripts" / "stack_render.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_render_compose_and_routes(tmp_path):
    r = _renderer()
    stack, state_dir = tmp_path / "stack", tmp_path / "state"
    (stack / "situation").mkdir(parents=True)
    (stack / "situation" / "homestack.toml").write_text('title = "Situation"\nport = 5000\ndata = "/app/instance"\nicon = "icon.svg"\naccent = "#ffb020"\n')
    (stack / "situation" / "icon.svg").write_text('<svg viewBox="0 0 24 24"><circle r="9"/></svg>')
    (state_dir / "apps").mkdir(parents=True)
    (state_dir / "apps" / "situation.json").write_text(json.dumps({"name": "situation", "repo": "ego-alt/situation"}))
    (state_dir / "apps" / "broken.json").write_text("{not json")

    assert r.render(state_dir, stack) is True
    compose = (state_dir / "generated" / "compose.apps.yml").read_text()
    assert f'build: "{stack / "situation"}"' in compose and 'APPLICATION_ROOT: "/situation"' in compose
    assert f'"{stack / "situation" / "instance"}:/app/instance"' in compose and '"5000"' in compose
    assert 'homehub.accent: "#ffb020"' in compose
    route = (state_dir / "generated" / "nginx" / "situation.locations").read_text()
    assert "set                $app_situation http://situation:5000;" in route and "auth_request" in route
    assert (state_dir / "generated" / "icons" / "situation.svg").read_text().startswith("<svg")
    assert r.render(state_dir, stack) is False                       # nothing changed: no nginx reload

    (state_dir / "apps" / "situation.json").unlink()                 # removed in the Deploy tab
    assert r.render(state_dir, stack) is True
    assert not list((state_dir / "generated" / "nginx").glob("*.locations"))
    assert not list((state_dir / "generated" / "icons").glob("*.svg"))
    assert "services: {}" in (state_dir / "generated" / "compose.apps.yml").read_text()


def test_an_app_without_a_manifest_gets_no_route_yet(tmp_path):
    r = _renderer()
    (tmp_path / "state" / "apps").mkdir(parents=True)
    (tmp_path / "state" / "apps" / "new.json").write_text(json.dumps({"name": "new-app", "repo": "ego-alt/new-app"}))
    r.render(tmp_path / "state", tmp_path / "stack")                 # not cloned yet
    assert not list((tmp_path / "state" / "generated" / "nginx").glob("*.locations"))


def test_github_trouble_is_said_not_hidden(client, make_user, state, monkeypatch):
    monkeypatch.undo()                                       # the real owner_repos, with GitHub refusing
    monkeypatch.setattr(deploy, "STATE_DIR", state)
    monkeypatch.setattr(deploy, "_cache", {})
    monkeypatch.setattr(deploy, "_get", lambda url, api=True, timeout=10: (403, b""))
    r = _admin(client, make_user).get("/deploy/repos")
    assert r.status_code == 502 and "rate limit" in r.json()["detail"]
    monkeypatch.setattr(deploy, "_cache", {})
    monkeypatch.setattr(deploy, "_get", lambda url, api=True, timeout=10: (401, b""))
    assert "expired" in client.get("/deploy/repos").json()["detail"]


def test_running_is_what_the_pi_has_checked_out(client, make_user, state):
    data = json.loads((state / "status.json").read_text())
    data["_heads"] = {"dashboard": "abc1234", "library": "0ff1ce0"}
    (state / "status.json").write_text(json.dumps(data))
    apps = {a["name"]: a for a in _admin(client, make_user).get("/deploy/apps").json()["apps"]}
    assert apps["dashboard"]["deployed"]["result"] == "deployed"           # head matches the last deploy
    assert apps["library"]["deployed"] == {"sha": "0ff1ce0", "result": None, "at": None}
    assert apps["mcp"]["deployed"]["sha"] == "abc1234"                      # mcp runs the dashboard's commit


def test_an_added_app_brings_its_own_icon(client, make_user, state, monkeypatch):
    import app.services as services
    monkeypatch.setattr(services, "ICON_DIR", state / "icons")
    (state / "icons").mkdir()
    (state / "icons" / "situation.svg").write_text('<svg viewBox="0 0 24 24"></svg>')
    monkeypatch.setattr(services, "list_service_candidates", lambda: [
        {"name": n, "status": "running", "labels": {"homehub.enable": "true", "homehub.route": f"/{n}/"}}
        for n in ("situation", "library")])
    c = _admin(client, make_user)
    tiles = {s["slug"]: s for s in c.get("/services").json()}
    assert tiles["situation"]["icon_url"] == "/services/situation/icon.svg" and tiles["library"]["icon_url"] is None
    r = c.get("/services/situation/icon.svg")
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml")
    assert "sandbox" in r.headers["content-security-policy"]
    assert c.get("/services/library/icon.svg").status_code == 404
    assert c.get("/services/..%2Fstatus/icon.svg").status_code == 404


def test_private_repos_need_the_dashboards_token(client, make_user, state, monkeypatch):
    repos = deploy.owner_repos()
    repos[0]["private"] = True
    c = _admin(client, make_user)
    r = c.post("/deploy/apps", json={"name": "situation"})
    assert r.status_code == 400 and "DEPLOY_GITHUB_TOKEN" in r.json()["detail"]
    monkeypatch.setattr(deploy, "TOKEN", "github_pat_test")
    assert c.post("/deploy/apps", json={"name": "situation"}).status_code == 201


def test_with_a_token_files_come_through_the_api(monkeypatch):
    calls = []
    monkeypatch.setattr(deploy, "TOKEN", "github_pat_test")
    monkeypatch.setattr(deploy, "_get", lambda url, **kw: calls.append((url, kw)) or (200, b"title = 'x'"))
    assert deploy._raw("ego-alt/situation", "main", "homestack.toml") == (200, "title = 'x'")
    assert calls[0][0] == "https://api.github.com/repos/ego-alt/situation/contents/homestack.toml?ref=main"
    assert calls[0][1]["accept"] == "application/vnd.github.raw"
