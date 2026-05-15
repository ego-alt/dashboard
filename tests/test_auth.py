"""Auth surface: login lifecycle, session expiry, authorization gates."""

from datetime import datetime, timedelta, timezone

from app.auth import SESSION_COOKIE
from app.models import UserSession


# ---------- public endpoints ----------


def test_ping_is_public(client):
    r = client.get("/ping")
    assert r.status_code == 200
    assert r.json() == {"message": "pong"}


# ---------- unauthenticated rejection ----------


def test_me_requires_auth(client):
    assert client.get("/me").status_code == 401


def test_verify_requires_auth(client):
    assert client.get("/auth/verify").status_code == 401


def test_containers_requires_auth(client):
    assert client.get("/containers").status_code == 401


def test_stats_requires_auth(client):
    assert client.get("/stats/system").status_code == 401


# ---------- login ----------


def test_login_bad_password(client, make_user):
    make_user(username="alice", password="hunter2")
    r = client.post("/login", data={"username": "alice", "password": "wrong"})
    assert r.status_code == 401


def test_login_unknown_user(client):
    r = client.post("/login", data={"username": "ghost", "password": "x"})
    assert r.status_code == 401


def test_login_success_sets_cookie_and_returns_user(client, make_user):
    make_user(username="alice", password="hunter2-pass")
    r = client.post("/login", data={"username": "alice", "password": "hunter2-pass"})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "username": "alice"}
    assert SESSION_COOKIE in r.cookies


# ---------- authenticated state ----------


def test_me_after_login_returns_user(client, make_user):
    make_user(username="alice", password="hunter2-pass", is_admin=False)
    client.post("/login", data={"username": "alice", "password": "hunter2-pass"})
    r = client.get("/me")
    assert r.status_code == 200
    body = r.json()
    assert body["username"] == "alice"
    assert body["is_admin"] is False


def test_verify_after_login_returns_xuser_header(client, make_user):
    make_user(username="alice", password="hunter2-pass")
    client.post("/login", data={"username": "alice", "password": "hunter2-pass"})
    r = client.get("/auth/verify")
    assert r.status_code == 200
    assert r.headers.get("x-user") == "alice"


def test_logout_clears_session(client, make_user):
    make_user(username="alice", password="hunter2-pass")
    client.post("/login", data={"username": "alice", "password": "hunter2-pass"})
    assert client.get("/me").status_code == 200
    assert client.post("/logout").status_code == 200
    assert client.get("/me").status_code == 401


def test_expired_session_is_rejected(client, make_user, TestSession):
    make_user(username="alice", password="hunter2-pass")
    client.post("/login", data={"username": "alice", "password": "hunter2-pass"})
    db = TestSession()
    try:
        sess = db.query(UserSession).one()
        sess.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    finally:
        db.close()
    assert client.get("/me").status_code == 401
    assert client.get("/auth/verify").status_code == 401


# ---------- authorization ----------


def test_non_admin_cannot_start_container(client, make_user):
    make_user(username="alice", password="hunter2-pass", is_admin=False)
    client.post("/login", data={"username": "alice", "password": "hunter2-pass"})
    # Auth dependency should 403 before the Docker call is reached.
    assert client.post("/containers/abc/start").status_code == 403


def test_non_admin_can_read_containers_endpoint_shape(client, make_user, monkeypatch):
    """Non-admin should pass the auth gate on read endpoints; the Docker call
    itself can fail, but the auth dependency must not be the blocker."""
    make_user(username="alice", password="hunter2-pass", is_admin=False)
    client.post("/login", data={"username": "alice", "password": "hunter2-pass"})
    # Stub the docker call so we test only the auth gate.
    from app import main
    monkeypatch.setattr(main, "get_containers", lambda: [])
    r = client.get("/containers")
    assert r.status_code == 200
    assert r.json() == []
