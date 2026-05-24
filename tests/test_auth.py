"""Auth surface: login lifecycle, session expiry, authorization gates."""

from datetime import datetime, timedelta, timezone

from app.auth import SESSION_COOKIE, SESSION_TTL, purge_expired_sessions
from app.main import limiter
from app.models import LoginEvent, UserSession


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
    assert client.post("/containers/abc/start").status_code == 403


def test_non_admin_can_read_containers_endpoint(client, make_user, monkeypatch):
    make_user(username="alice", password="hunter2-pass", is_admin=False)
    client.post("/login", data={"username": "alice", "password": "hunter2-pass"})
    from app import main
    monkeypatch.setattr(main, "get_containers", lambda: [])
    r = client.get("/containers")
    assert r.status_code == 200
    assert r.json() == []


# ---------- cookie attributes ----------


def test_login_cookie_has_secure_attributes(client, make_user):
    make_user(username="alice", password="hunter2-pass")
    r = client.post("/login", data={"username": "alice", "password": "hunter2-pass"})
    set_cookie = r.headers.get("set-cookie", "")
    assert "HttpOnly" in set_cookie
    assert "SameSite=strict" in set_cookie
    assert "Path=/" in set_cookie
    assert SESSION_COOKIE in set_cookie


def test_logout_clears_cookie_with_path(client, make_user):
    make_user(username="alice", password="hunter2-pass")
    client.post("/login", data={"username": "alice", "password": "hunter2-pass"})
    r = client.post("/logout")
    set_cookie = r.headers.get("set-cookie", "")
    assert f"{SESSION_COOKIE}=" in set_cookie
    assert "Max-Age=0" in set_cookie or 'expires=Thu, 01 Jan 1970' in set_cookie.lower()


def test_session_cookie_secure_when_env_set(client, make_user, monkeypatch):
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "1")
    make_user(username="alice", password="hunter2-pass")
    r = client.post("/login", data={"username": "alice", "password": "hunter2-pass"})
    assert "Secure" in r.headers.get("set-cookie", "")


def test_session_cookie_not_secure_over_plain_http(client, make_user, monkeypatch):
    """When env var is unset and the connection is plain http, don't mark Secure
    (otherwise the cookie would never be sent back)."""
    monkeypatch.delenv("SESSION_COOKIE_SECURE", raising=False)
    make_user(username="alice", password="hunter2-pass")
    r = client.post("/login", data={"username": "alice", "password": "hunter2-pass"})
    assert "Secure" not in r.headers.get("set-cookie", "")


def test_session_cookie_secure_when_forwarded_proto_is_https(client, make_user, monkeypatch):
    """Default to Secure when nginx forwards us as HTTPS."""
    monkeypatch.delenv("SESSION_COOKIE_SECURE", raising=False)
    make_user(username="alice", password="hunter2-pass")
    r = client.post(
        "/login",
        data={"username": "alice", "password": "hunter2-pass"},
        headers={"X-Forwarded-Proto": "https"},
    )
    assert "Secure" in r.headers.get("set-cookie", "")


# ---------- session sweeping ----------


def test_purge_expired_sessions_deletes_and_returns_count(client, make_user, TestSession):
    make_user(username="alice", password="hunter2-pass")
    make_user(username="bob", password="hunter2-pass")
    client.post("/login", data={"username": "alice", "password": "hunter2-pass"})
    client.post("/login", data={"username": "bob", "password": "hunter2-pass"})
    db = TestSession()
    try:
        sessions = db.query(UserSession).all()
        assert len(sessions) == 2
        # Expire one of them.
        sessions[0].expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db.commit()
        n = purge_expired_sessions(db)
        assert n == 1
        assert db.query(UserSession).count() == 1
        n_again = purge_expired_sessions(db)
        assert n_again == 0
    finally:
        db.close()


# ---------- audit log ----------


def test_login_records_audit_event_on_success(client, make_user, TestSession):
    user = make_user(username="alice", password="hunter2-pass")
    r = client.post("/login", data={"username": "alice", "password": "hunter2-pass"})
    assert r.status_code == 200

    db = TestSession()
    try:
        events = db.query(LoginEvent).all()
        assert len(events) == 1
        assert events[0].success is True
        assert events[0].username == "alice"
        assert events[0].user_id == user.id
        assert events[0].reason is None
    finally:
        db.close()


def test_login_records_audit_event_on_bad_password(client, make_user, TestSession):
    user = make_user(username="alice", password="hunter2-pass")
    r = client.post("/login", data={"username": "alice", "password": "wrong"})
    assert r.status_code == 401

    db = TestSession()
    try:
        events = db.query(LoginEvent).all()
        assert len(events) == 1
        assert events[0].success is False
        assert events[0].reason == "bad-password"
        assert events[0].user_id == user.id
    finally:
        db.close()


def test_login_records_audit_event_on_unknown_user(client, TestSession):
    r = client.post("/login", data={"username": "ghost", "password": "x"})
    assert r.status_code == 401

    db = TestSession()
    try:
        events = db.query(LoginEvent).all()
        assert len(events) == 1
        assert events[0].success is False
        assert events[0].reason == "unknown-user"
        assert events[0].user_id is None
        assert events[0].username == "ghost"
    finally:
        db.close()


# ---------- sliding session expiry ----------


def test_session_slides_when_past_half_life(client, make_user, TestSession):
    """A session more than half-expired gets extended on the next authenticated
    request — active users don't get logged out mid-use."""
    make_user(username="alice", password="hunter2-pass")
    client.post("/login", data={"username": "alice", "password": "hunter2-pass"})

    db = TestSession()
    try:
        sess = db.query(UserSession).one()
        # Move expiry to ~1/4 of TTL away — well past the half-life threshold.
        sess.expires_at = datetime.now(timezone.utc) + (SESSION_TTL / 4)
        old_expiry = sess.expires_at.replace(tzinfo=timezone.utc) if sess.expires_at.tzinfo is None else sess.expires_at
        db.commit()
    finally:
        db.close()

    r = client.get("/me")
    assert r.status_code == 200

    db = TestSession()
    try:
        sess = db.query(UserSession).one()
        new_expiry = sess.expires_at.replace(tzinfo=timezone.utc) if sess.expires_at.tzinfo is None else sess.expires_at
        assert new_expiry > old_expiry
    finally:
        db.close()


def test_session_does_not_slide_when_fresh(client, make_user, TestSession):
    """A brand-new session isn't re-extended on every request — bounded writes."""
    make_user(username="alice", password="hunter2-pass")
    client.post("/login", data={"username": "alice", "password": "hunter2-pass"})

    db = TestSession()
    try:
        original_expiry = db.query(UserSession).one().expires_at
    finally:
        db.close()

    client.get("/me")

    db = TestSession()
    try:
        assert db.query(UserSession).one().expires_at == original_expiry
    finally:
        db.close()


# ---------- origin check (CSRF surface) ----------


def test_post_with_mismatched_origin_is_rejected(client, make_user):
    make_user(username="alice", password="hunter2-pass")
    client.post("/login", data={"username": "alice", "password": "hunter2-pass"})
    r = client.post("/logout", headers={"Origin": "https://attacker.example"})
    assert r.status_code == 403


def test_post_with_matching_origin_is_accepted(client, make_user):
    make_user(username="alice", password="hunter2-pass")
    client.post("/login", data={"username": "alice", "password": "hunter2-pass"})
    r = client.post("/logout", headers={"Origin": "http://testserver"})
    assert r.status_code == 200


def test_post_without_origin_header_is_accepted(client, make_user):
    """Non-browser clients (cli, curl, our TestClient) don't set Origin."""
    make_user(username="alice", password="hunter2-pass")
    r = client.post("/login", data={"username": "alice", "password": "hunter2-pass"})
    assert r.status_code == 200


def test_get_with_mismatched_origin_is_not_rejected(client, make_user):
    """The origin check only applies to state-changing methods."""
    make_user(username="alice", password="hunter2-pass")
    client.post("/login", data={"username": "alice", "password": "hunter2-pass"})
    r = client.get("/me", headers={"Origin": "https://anywhere.example"})
    assert r.status_code == 200


# ---------- rate limiting ----------


def test_login_rate_limit_triggers_after_burst(client, make_user, monkeypatch):
    """Sixth /login from the same IP within the window should be 429."""
    # The default is "5/minute"; tighten to make the test fast.
    monkeypatch.setattr(limiter, "enabled", True)
    limiter.reset()
    make_user(username="alice", password="hunter2-pass")
    statuses = []
    for _ in range(6):
        r = client.post("/login", data={"username": "alice", "password": "wrong"})
        statuses.append(r.status_code)
    assert statuses[:5] == [401] * 5
    assert statuses[5] == 429
