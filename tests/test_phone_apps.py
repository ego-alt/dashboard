"""Phone apps: added in the Deploy tab from a kind = "android" manifest, listed
on Services from their GitHub releases, and checked and downloaded by the app
itself with an API token. GitHub is stubbed out."""
import json

import pytest
from fastapi.testclient import TestClient

import app.deploy as deploy
import app.phone_apps as phone_apps
from app.stack_manifest import ManifestError, parse

ANDROID = 'title = "Scanner"\nkind = "android"\npackage = "com.scanner.app"\ndescription = "Scan documents"\nicon = "icon.svg"\naccent = "#7dd3fc"\n'
RELEASE = {"tag_name": "v12", "name": "1.0.12", "body": "- send the time with calendar uploads",
           "published_at": "2026-10-27T09:00:00Z",
           "assets": [{"name": "doc-scanner-1.0.12.apk", "size": 7, "url": "https://api.github.com/assets/1",
                       "browser_download_url": "https://github.com/ego-alt/doc-scanner/releases/download/v12/x.apk"}]}


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(deploy, "_cache", {})
    monkeypatch.setattr(phone_apps, "APK_DIR", tmp_path / "apks")
    repos = [{"repo": "ego-alt/doc-scanner", "name": "doc-scanner", "description": "", "branch": "main",
              "pushed_at": "2026-10-27T09:00:00Z", "private": False}]
    monkeypatch.setattr(deploy, "owner_repos", lambda: repos)
    files = {("ego-alt/doc-scanner", "homestack.toml"): ANDROID,
             ("ego-alt/doc-scanner", ".github/workflows/ci.yml"): "name: CI",
             ("ego-alt/doc-scanner", "icon.svg"): '<svg viewBox="0 0 24 24"></svg>'}
    monkeypatch.setattr(deploy, "_raw", lambda repo, branch, path: (200, files[(repo, path)])
                        if (repo, path) in files else (404, ""))
    monkeypatch.setattr(deploy, "latest_commit", lambda repo, branch: None)
    monkeypatch.setattr(deploy, "_api", lambda path: RELEASE if path.endswith("/releases/latest") else None)
    fetched = []

    def fake_download(app, release):          # what _download leaves behind, without the network
        path = phone_apps.apk_path(app["name"], release["version_code"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"APK!APK")
        fetched.append(release["version_code"])
        phone_apps._fetching.discard(app["name"])
    monkeypatch.setattr(phone_apps, "_download", fake_download)
    return fetched


def _login(client, make_user, admin=True):
    make_user(username="admin", is_admin=admin)
    assert client.post("/login", data={"username": "admin", "password": "hunter2-secret"}).status_code == 200
    return client


def _add(client):
    r = client.post("/deploy/apps", json={"name": "doc-scanner"})
    assert r.status_code == 201, r.text
    return r.json()["app"]


def _wait_ready(client):
    for _ in range(50):
        if client.get("/phone-apps").json()["apps"][0]["ready"]:
            return
    raise AssertionError("never ready")


def test_the_manifest_says_what_kind_of_app():
    assert parse('title = "X"\n')["kind"] == "web"
    assert parse(ANDROID)["package"] == "com.scanner.app"
    with pytest.raises(ManifestError, match="package"):
        parse('title = "X"\nkind = "android"\n')
    with pytest.raises(ManifestError, match="kind"):
        parse('title = "X"\nkind = "ios"\n')


def test_a_phone_app_needs_no_dockerfile_and_is_listed_not_deployed(client, make_user, state):
    _login(client, make_user)
    check = client.get("/deploy/repos/doc-scanner/check").json()
    assert check["ok"] and [c["label"] for c in check["checks"]][0] == "Listed under Phone apps as doc-scanner"
    assert "Dockerfile" not in [c["label"] for c in check["checks"]]
    app = _add(client)
    assert app["package"] == "com.scanner.app"
    assert (deploy.STATE_DIR / "phone-apps" / "doc-scanner.svg").is_file()
    assert not (deploy.STATE_DIR / "apps").exists()           # the deploy script never sees it
    assert not (deploy.STATE_DIR / "requests").exists()
    rows = client.get("/deploy/apps").json()["apps"]
    assert {"name": "doc-scanner", "kind": "phone"}.items() <= next(r for r in rows if r["name"] == "doc-scanner").items()
    assert client.post("/deploy/apps/doc-scanner/deploy").status_code == 404
    assert client.delete("/deploy/apps/doc-scanner").status_code == 200
    assert client.get("/phone-apps").json()["apps"] == []


def test_services_lists_the_latest_release_and_fetches_its_apk(client, make_user, state):
    _login(client, make_user)
    _add(client)
    _wait_ready(client)
    app = client.get("/phone-apps").json()["apps"][0]
    assert app["latest"]["version_name"] == "1.0.12" and app["installed"] is None
    assert app["icon_url"] == "/phone-apps/doc-scanner/icon.svg"
    assert state == [12]                                        # fetched once
    r = client.get("/phone-apps/doc-scanner/download")
    assert r.status_code == 200 and r.content == b"APK!APK"
    assert r.headers["content-type"] == "application/vnd.android.package-archive"


def test_the_app_checks_with_its_token_and_services_learns_its_version(client, make_user, state):
    _login(client, make_user)
    _add(client)
    _wait_ready(client)
    token = client.post("/auth/tokens", data={"name": "scanner"}).json()["token"]
    phone = TestClient(client.app)                              # no session: only the token
    auth = {"Authorization": f"Bearer {token}"}
    r = phone.get("/phone-apps/doc-scanner/latest?installed=9&installed_name=1.0.9", headers=auth)
    assert r.status_code == 200 and r.json()["update"] is True
    assert phone.get("/phone-apps/doc-scanner/download", headers=auth).status_code == 200
    assert client.get("/phone-apps").json()["apps"][0]["installed"]["version_name"] == "1.0.9"
    assert phone.get("/phone-apps/doc-scanner/latest?installed=12", headers=auth).json()["update"] is False
    # The token reaches only the update check and the download.
    assert phone.get("/phone-apps", headers=auth).status_code == 401
    assert phone.get("/deploy/apps", headers=auth).status_code == 401
    assert phone.get("/phone-apps/doc-scanner/latest").status_code == 401


def test_no_release_yet(client, make_user, state, monkeypatch):
    _login(client, make_user)
    _add(client)
    monkeypatch.setattr(deploy, "_cache", {})
    monkeypatch.setattr(deploy, "_api", lambda path: {"tag_name": "nightly", "assets": []})
    app = client.get("/phone-apps").json()["apps"][0]
    assert app["latest"] is None and app["ready"] is False
    assert client.get("/phone-apps/doc-scanner/download").status_code == 404


def test_only_signed_in_people_see_phone_apps(client, state):
    assert client.get("/phone-apps").status_code == 401
    (deploy.STATE_DIR / "phone-apps").mkdir(parents=True)
    (deploy.STATE_DIR / "phone-apps" / "doc-scanner.json").write_text(json.dumps(
        {"name": "doc-scanner", "repo": "ego-alt/doc-scanner", "branch": "main"}))
    assert client.get("/phone-apps/doc-scanner/download").status_code == 401
