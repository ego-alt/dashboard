"""API tokens: mint via session, authorize /auth/verify via Bearer, revoke,
and the least-privilege guarantee that a token can't drive dashboard endpoints."""


def _login(client, username="alice", password="hunter2-secret"):
    r = client.post("/login", data={"username": username, "password": password})
    assert r.status_code == 200
    return r


def _mint(client, name="scanner app"):
    r = client.post("/auth/tokens", data={"name": name})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    return body["token"]


def _bare_client():
    """A TestClient with no session cookie — so only the Bearer token can auth."""
    from app.main import app
    from fastapi.testclient import TestClient

    return TestClient(app)


def test_mint_requires_auth(client):
    assert client.post("/auth/tokens", data={"name": "x"}).status_code == 401


def test_token_authorizes_verify_with_bearer(client, make_user):
    make_user()
    _login(client)
    token = _mint(client)

    # A fresh client (no session cookie) authenticates with just the Bearer token.
    bare = _bare_client()
    r = bare.get("/auth/verify", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.headers.get("x-user") == "alice"


def test_invalid_bearer_is_rejected(client):
    r = client.get("/auth/verify", headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 401


def test_listing_never_exposes_raw_token(client, make_user):
    make_user()
    _login(client)
    token = _mint(client, name="scanner app")

    listed = client.get("/auth/tokens").json()
    assert len(listed) == 1
    entry = listed[0]
    assert entry["name"] == "scanner app"
    assert entry["prefix"] == token[:8]
    # The raw token must never come back from the list endpoint.
    assert "token" not in entry


def test_delete_revokes_token(client, make_user):
    make_user()
    _login(client)
    token = _mint(client)

    token_id = client.get("/auth/tokens").json()[0]["id"]
    assert client.delete(f"/auth/tokens/{token_id}").status_code == 200

    # Bearer no longer authorizes after revocation. Use a cookie-less client so
    # the still-valid session cookie can't mask the revoked token.
    bare = _bare_client()
    assert bare.get(
        "/auth/verify", headers={"Authorization": f"Bearer {token}"}
    ).status_code == 401


def test_token_does_not_grant_dashboard_access(client, make_user):
    """A token authorizes downstream apps via /auth/verify, but must NOT unlock
    dashboard-native endpoints (those stay cookie-only)."""
    make_user(is_admin=True)
    _login(client)
    token = _mint(client)

    bare = _bare_client()
    headers = {"Authorization": f"Bearer {token}"}
    assert bare.get("/containers", headers=headers).status_code == 401
    assert bare.get("/me", headers=headers).status_code == 401
    assert bare.get("/auth/tokens", headers=headers).status_code == 401


def test_tokens_are_scoped_to_owner(client, make_user):
    make_user(username="alice")
    make_user(username="mallory")
    _login(client, "alice")
    _mint(client)

    # Mallory's session sees none of alice's tokens and can't delete them.
    other_id = client.get("/auth/tokens").json()[0]["id"]
    mallory = client  # reuse client but switch session
    mallory.post("/logout")
    _login(mallory, "mallory")
    assert mallory.get("/auth/tokens").json() == []
    assert mallory.delete(f"/auth/tokens/{other_id}").status_code == 404
