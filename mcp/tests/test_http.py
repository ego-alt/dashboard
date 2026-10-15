"""The container app end to end: discovery, registration, consent, tokens,
refresh, revocation, API-token fallback, audit, all over HTTP."""

import base64
import hashlib
import re
import secrets
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from starlette.testclient import TestClient

from homehub_mcp.backend import InternalBackend
from homehub_mcp.server import http_app
from homehub_mcp.store import Store

REDIRECT = "http://localhost:9999/cb"
ACCEPT = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def dashboard(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/auth/verify":
        if "session=grey-cookie" in request.headers.get("cookie", ""):
            return httpx.Response(200, headers={"X-User": "grey"})
        if request.headers.get("authorization") == "Bearer pat-sam":
            return httpx.Response(200, headers={"X-User": "sam"})
    return httpx.Response(401)


@pytest.fixture
def store():
    return Store(":memory:")


@pytest.fixture
def client(config, fake, store):
    fake.on("GET", "tapes", r"/api/tracks")(lambda r, m: httpx.Response(200, json=[
        {"id": 1, "title": "Pink Moon", "artist": "Nick Drake", "album": "", "duration": 125}]))
    app = http_app(
        config, store=store,
        http=httpx.AsyncClient(transport=httpx.MockTransport(dashboard)),
        backend=InternalBackend(config, transport=httpx.MockTransport(fake)),
    )
    with TestClient(app, base_url="http://localhost:8100", follow_redirects=False) as c:
        yield c


def register(c, **extra):
    return c.post("/register", json={
        "redirect_uris": [REDIRECT], "client_name": "Test Assistant",
        "token_endpoint_auth_method": "none", "grant_types": ["authorization_code", "refresh_token"],
        **extra,
    })


def authorize(c):
    """Register, consent as grey, return (client_id, tokens)."""
    cid = register(c).json()["client_id"]
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    r = c.get("/authorize", params={
        "response_type": "code", "client_id": cid, "redirect_uri": REDIRECT, "state": "xyz",
        "code_challenge": challenge, "code_challenge_method": "S256", "scope": "homehub",
        "resource": "http://localhost:8100/mcp",
    })
    consent = urlparse(r.headers["location"])
    c.cookies.set("session", "grey-cookie")
    page = c.get(f"{consent.path}?{consent.query}&b=1")
    csrf = re.search(r'name=csrf value="([0-9a-f]+)"', page.text).group(1)
    req = parse_qs(consent.query)["req"][0]
    r = c.post("/oauth/consent", data={"req": req, "csrf": csrf, "decision": "allow"})
    code = parse_qs(urlparse(r.headers["location"]).query)["code"][0]
    c.cookies.clear()
    tokens = c.post("/token", data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT,
        "client_id": cid, "code_verifier": verifier,
    }).json()
    return cid, tokens


def rpc(c, token, method, params=None):
    return c.post("/mcp", headers={**ACCEPT, "Authorization": f"Bearer {token}",
                                   "mcp-protocol-version": "2025-11-25"},
                  json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})


def test_discovery(client):
    r = client.post("/mcp", json={})
    assert r.status_code == 401
    assert "/.well-known/oauth-protected-resource/mcp" in r.headers["www-authenticate"]
    prm = client.get("/.well-known/oauth-protected-resource/mcp").json()
    assert prm["resource"] == "http://localhost:8100/mcp"
    asm = client.get("/.well-known/oauth-authorization-server").json()
    assert asm["issuer"].rstrip("/") == "http://localhost:8100"
    assert asm["code_challenge_methods_supported"] == ["S256"]
    assert client.get("/healthz").text == "ok"


@pytest.mark.parametrize("uri", ["http://evil.example/cb", "javascript:alert(1)"])
def test_registration_refuses_unsafe_redirects(client, uri):
    assert register(client, redirect_uris=[uri]).status_code == 400


def test_custom_scheme_and_loopback_redirects_allowed(client):
    assert register(client, redirect_uris=["cursor://anysphere/cb", "http://127.0.0.1:3000/cb"]).status_code == 201


def test_consent_requires_sign_in_and_csrf(client):
    cid = register(client).json()["client_id"]
    r = client.get("/authorize", params={
        "response_type": "code", "client_id": cid, "redirect_uri": REDIRECT,
        "code_challenge": "x" * 43, "code_challenge_method": "S256",
    })
    loc = urlparse(r.headers["location"])
    assert loc.path == "/oauth/consent"
    path = f"{loc.path}?{loc.query}"
    assert 'http-equiv="refresh"' in client.get(path).text  # one same-site bounce
    r = client.get(path + "&b=1")
    assert r.status_code == 303 and r.headers["location"].startswith("/login?next=%2Foauth%2Fconsent")
    client.cookies.set("session", "grey-cookie")
    page = client.get(path + "&b=1")
    assert "Allow Test Assistant" in page.text and page.headers["x-frame-options"] == "DENY"
    req = parse_qs(loc.query)["req"][0]
    assert client.post("/oauth/consent", data={"req": req, "csrf": "0", "decision": "allow"}).status_code == 403
    csrf = re.search(r'name=csrf value="([0-9a-f]+)"', page.text).group(1)
    r = client.post("/oauth/consent", data={"req": req, "csrf": csrf, "decision": "deny"})
    assert parse_qs(urlparse(r.headers["location"]).query)["error"] == ["access_denied"]


def test_tools_run_as_the_consenting_user(client, fake):
    _, tok = authorize(client)
    assert rpc(client, tok["access_token"], "tools/list").json()["result"]["tools"]
    r = rpc(client, tok["access_token"], "tools/call",
            {"name": "tapes_search_tracks", "arguments": {"query": "moon"}}).json()["result"]
    assert "Pink Moon" in r["content"][0]["text"]
    sent = fake.last()
    assert sent.headers["x-forwarded-user"] == "grey"
    assert sent.headers["x-internal-auth"] == "s3cret"
    assert "authorization" not in sent.headers  # the client's token never reaches the apps


def test_dashboard_api_token_works_as_bearer(client, fake):
    r = rpc(client, "pat-sam", "tools/call", {"name": "tapes_search_tracks", "arguments": {"query": "x"}})
    assert r.status_code == 200
    assert fake.last().headers["x-forwarded-user"] == "sam"
    assert rpc(client, "not-a-token", "tools/list").status_code == 401


def test_refresh_rotates_and_disconnect_revokes(client, store):
    cid, tok = authorize(client)
    new = client.post("/token", data={"grant_type": "refresh_token", "refresh_token": tok["refresh_token"],
                                      "client_id": cid})
    assert new.status_code == 200
    new = new.json()
    assert rpc(client, tok["access_token"], "tools/list").status_code == 401
    assert rpc(client, new["access_token"], "tools/list").status_code == 200
    reuse = client.post("/token", data={"grant_type": "refresh_token", "refresh_token": tok["refresh_token"],
                                        "client_id": cid})
    assert reuse.status_code == 400

    client.cookies.set("session", "grey-cookie")
    page = client.get("/oauth/connections")
    assert "Test Assistant" in page.text
    gid = store.one("SELECT grant_id FROM grants")["grant_id"]
    csrf = re.search(r"name=csrf value='([0-9a-f]+)'", page.text).group(1)
    client.post("/oauth/connections/revoke", data={"grant": gid, "csrf": csrf})
    assert rpc(client, new["access_token"], "tools/list").status_code == 401


def test_codes_are_single_use(client):
    cid = register(client).json()["client_id"]
    verifier = "v" * 50
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    r = client.get("/authorize", params={"response_type": "code", "client_id": cid, "redirect_uri": REDIRECT,
                                         "code_challenge": challenge, "code_challenge_method": "S256"})
    loc = urlparse(r.headers["location"])
    client.cookies.set("session", "grey-cookie")
    page = client.get(f"{loc.path}?{loc.query}&b=1")
    csrf = re.search(r'name=csrf value="([0-9a-f]+)"', page.text).group(1)
    r = client.post("/oauth/consent", data={"req": parse_qs(loc.query)["req"][0], "csrf": csrf,
                                            "decision": "allow"})
    code = parse_qs(urlparse(r.headers["location"]).query)["code"][0]
    form = {"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT, "client_id": cid}
    assert client.post("/token", data={**form, "code_verifier": "w" * 50}).status_code == 400
    assert client.post("/token", data={**form, "code_verifier": verifier}).status_code == 200
    assert client.post("/token", data={**form, "code_verifier": verifier}).status_code == 400


def test_tool_calls_are_audited(client, store):
    rpc(client, "pat-sam", "tools/call", {"name": "tapes_search_tracks", "arguments": {"query": "moon"}})
    rpc(client, "pat-sam", "tools/call", {"name": "calendar_get_day", "arguments": {"date": "nope"}})
    rows = store.recent_audit("sam")
    assert [(r["tool"], r["ok"], r["client"]) for r in rows] == [
        ("calendar_get_day", 0, "API token"), ("tapes_search_tracks", 1, "API token"),
    ]
    assert "YYYY-MM-DD" in rows[0]["error"]


def test_audit_trims_long_arguments(store):
    store.audit(username="u", client="c", tool="t", args={"notes": "x" * 5000}, ok=True, error=None)
    assert len(store.recent_audit("u")[0]["args"]) < 300


def test_prune_drops_abandoned_registrations(client, store):
    import time

    cid = register(client).json()["client_id"]
    _, _ = authorize(client)  # a second client that does get consent
    store.execute("UPDATE clients SET created_at = ?", (time.time() - 30 * 86400,))
    store.prune()
    left = {r["client_id"] for r in store.all("SELECT client_id FROM clients")}
    assert cid not in left and len(left) == 1
