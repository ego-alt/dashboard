"""Your own account: /me, changing your password, sessions, sign-in history,
fresh recovery codes, and an admin password reset ending the user's sessions."""

import pyotp
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(autouse=True)
def _no_hibp(monkeypatch):
    monkeypatch.setattr("app.main.password_breach_count", lambda pw: 0)


def _login(client, username="alice", password="hunter2-secret"):
    r = client.post("/login", data={"username": username, "password": password})
    assert r.status_code == 200
    return r


def test_me_has_id_for_self_checks(client, make_user):
    u = make_user()
    _login(client)
    body = client.get("/me").json()
    assert body["id"] == u.id
    assert body["totp_recovery_left"] is None


def test_change_password_needs_current_and_ends_other_sessions(client, make_user):
    make_user()
    _login(client)
    other = TestClient(app)
    _login(other)
    r = client.post(
        "/me/password",
        data={"current_password": "wrong-one-entirely", "new_password": "a-new-passphrase"},
    )
    assert r.status_code == 400  # not 401: the session is fine
    r = client.post(
        "/me/password",
        data={"current_password": "hunter2-secret", "new_password": "a-new-passphrase"},
    )
    assert r.json() == {"ok": True, "sessions_ended": 1}
    assert client.get("/me").status_code == 200  # this device stays signed in
    assert other.get("/me").status_code == 401
    _login(TestClient(app), password="a-new-passphrase")


def test_change_password_applies_the_policy(client, make_user):
    make_user()
    _login(client)
    r = client.post(
        "/me/password", data={"current_password": "hunter2-secret", "new_password": "short"}
    )
    assert r.status_code == 400


def test_sessions_list_marks_current_and_revokes_others(client, make_user):
    make_user()
    _login(client)
    other = TestClient(app)
    _login(other)
    rows = client.get("/auth/sessions").json()
    assert len(rows) == 2
    assert rows[0]["current"] is True and rows[1]["current"] is False
    assert all(len(r["id"]) == 16 for r in rows)
    assert "token" not in rows[0]
    # Can't end the current one here; can end the other.
    assert client.delete(f"/auth/sessions/{rows[0]['id']}").status_code == 400
    assert client.delete(f"/auth/sessions/{rows[1]['id']}").json() == {"ok": True}
    assert other.get("/me").status_code == 401
    assert client.delete("/auth/sessions/0000000000000000").status_code == 404


def test_cannot_revoke_someone_elses_session(client, make_user):
    make_user()
    make_user(username="bob")
    bob = TestClient(app)
    _login(bob, "bob")
    bob_id = bob.get("/auth/sessions").json()[0]["id"]
    _login(client)
    assert client.delete(f"/auth/sessions/{bob_id}").status_code == 404
    assert bob.get("/me").status_code == 200


def test_revoke_others(client, make_user):
    make_user()
    _login(client)
    for _ in range(2):
        _login(TestClient(app))
    assert client.post("/auth/sessions/revoke-others").json()["sessions_ended"] == 2
    assert len(client.get("/auth/sessions").json()) == 1


def test_login_events_are_your_own(client, make_user):
    make_user()
    make_user(username="bob")
    client.post("/login", data={"username": "alice", "password": "nope-nope-nope"})
    _login(TestClient(app), "bob")
    _login(client)
    events = client.get("/auth/login-events").json()
    assert [e["success"] for e in events] == [True, False]
    assert events[1]["reason"] == "bad-password"


def test_regenerate_recovery_codes_needs_a_current_code(client, make_user, TestSession):
    make_user()
    _login(client)
    secret = client.post("/auth/totp/setup").json()["secret"]
    first = client.post("/auth/totp/enable", data={"code": pyotp.TOTP(secret).now()}).json()
    assert client.get("/me").json()["totp_recovery_left"] == len(first["recovery_codes"])
    assert client.post("/auth/totp/recovery-codes", data={"code": "000000"}).status_code == 400
    r = client.post("/auth/totp/recovery-codes", data={"code": pyotp.TOTP(secret).now()})
    fresh = r.json()["recovery_codes"]
    assert set(fresh).isdisjoint(first["recovery_codes"])
    # An old code no longer turns 2FA off; a new one does.
    assert client.post("/auth/totp/disable", data={"code": first["recovery_codes"][0]}).status_code == 400
    assert client.post("/auth/totp/disable", data={"code": fresh[0]}).status_code == 200


def test_admin_password_reset_ends_the_users_sessions(client, make_user):
    make_user(username="admin", is_admin=True)
    make_user(username="bob")
    bob = TestClient(app)
    _login(bob, "bob")
    _login(client, "admin")
    bob_id = next(u["id"] for u in client.get("/users").json() if u["username"] == "bob")
    r = client.post(f"/users/{bob_id}/password", data={"password": "brand-new-pass"})
    assert r.json() == {"ok": True, "sessions_ended": 1}
    assert bob.get("/me").status_code == 401


def test_admin_resetting_own_password_stays_signed_in(client, make_user):
    admin = make_user(username="admin", is_admin=True)
    _login(client, "admin")
    client.post(f"/users/{admin.id}/password", data={"password": "brand-new-pass"})
    assert client.get("/me").status_code == 200


def test_browser_opening_users_gets_the_page(client, make_user):
    r = client.get("/users", headers={"accept": "text/html,application/xhtml+xml"},
                   follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/admin/users"
    # fetch() from the SPA still gets JSON (and the auth checks).
    assert client.get("/users").status_code == 401
