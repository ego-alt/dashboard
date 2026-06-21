"""Admin user management: CRUD, password policy, anti-lockout guards, 2FA
reset, and the delete path that must purge a user's tokens/sessions so no live
credential outlives the account."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import ApiToken, User, UserSession


@pytest.fixture(autouse=True)
def _no_hibp(monkeypatch):
    # Never hit the HaveIBeenPwned network API in tests; treat all as un-breached.
    monkeypatch.setattr("app.main.password_breach_count", lambda pw: 0)


def _login(client, username, password="hunter2-secret"):
    r = client.post("/login", data={"username": username, "password": password})
    assert r.status_code == 200


def _admin(client, make_user):
    make_user(username="admin", is_admin=True)
    _login(client, "admin")


def _id_of(client, username):
    return next(u["id"] for u in client.get("/users").json() if u["username"] == username)


def test_list_requires_admin(client, make_user):
    assert client.get("/users").status_code == 401  # unauthenticated
    make_user(username="bob", is_admin=False)
    _login(client, "bob")
    assert client.get("/users").status_code == 403  # non-admin


def test_create_and_list(client, make_user):
    _admin(client, make_user)
    r = client.post("/users", data={"username": "carol", "password": "longenough1"})
    assert r.status_code == 200 and r.json()["username"] == "carol"
    assert {"admin", "carol"} <= {u["username"] for u in client.get("/users").json()}


def test_create_rejects_short_password(client, make_user):
    _admin(client, make_user)
    assert client.post("/users", data={"username": "x", "password": "short"}).status_code == 400


def test_create_rejects_duplicate(client, make_user):
    _admin(client, make_user)
    client.post("/users", data={"username": "carol", "password": "longenough1"})
    r = client.post("/users", data={"username": "carol", "password": "longenough2"})
    assert r.status_code == 409


def test_cannot_demote_or_delete_self(client, make_user):
    _admin(client, make_user)
    me = _id_of(client, "admin")
    assert client.post(f"/users/{me}/admin", data={"is_admin": "false"}).status_code == 400
    assert client.delete(f"/users/{me}").status_code == 400


def test_set_password_lets_user_login(client, make_user):
    _admin(client, make_user)
    bob = client.post("/users", data={"username": "bob", "password": "oldpassword1"}).json()
    assert client.post(f"/users/{bob['id']}/password", data={"password": "newpassword1"}).status_code == 200
    fresh = TestClient(app)
    assert fresh.post("/login", data={"username": "bob", "password": "newpassword1"}).status_code == 200


def test_delete_purges_tokens_and_sessions(client, make_user, TestSession):
    _admin(client, make_user)
    bob = client.post("/users", data={"username": "bob", "password": "longenough1"}).json()

    bob_client = TestClient(app)
    bob_client.post("/login", data={"username": "bob", "password": "longenough1"})
    token = bob_client.post("/auth/tokens", data={"name": "scanner"}).json()["token"]
    assert TestClient(app).get(
        "/auth/verify", headers={"Authorization": f"Bearer {token}"}
    ).status_code == 200

    assert client.delete(f"/users/{bob['id']}").status_code == 200

    # token no longer authorizes, and no token/session rows survive
    assert TestClient(app).get(
        "/auth/verify", headers={"Authorization": f"Bearer {token}"}
    ).status_code == 401
    db = TestSession()
    try:
        assert db.query(ApiToken).filter(ApiToken.user_id == bob["id"]).count() == 0
        assert db.query(UserSession).filter(UserSession.user_id == bob["id"]).count() == 0
    finally:
        db.close()


def test_reset_2fa_clears_enrollment(client, make_user, TestSession):
    _admin(client, make_user)
    bob = client.post("/users", data={"username": "bob", "password": "longenough1"}).json()
    db = TestSession()
    try:
        u = db.get(User, bob["id"])
        u.totp_enabled, u.totp_secret = True, "SECRET"
        db.commit()
    finally:
        db.close()

    assert client.post(f"/users/{bob['id']}/reset-2fa").status_code == 200
    db = TestSession()
    try:
        u = db.get(User, bob["id"])
        assert u.totp_enabled is False and u.totp_secret is None
    finally:
        db.close()
