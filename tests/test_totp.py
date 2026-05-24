"""TOTP 2FA: setup / enable / verify / disable, plus the two-step login flow."""

import json

import pyotp

from app.auth import SESSION_COOKIE
from app.models import LoginEvent, User, UserSession


def _login_first_factor(client, username="alice", password="hunter2-pass"):
    return client.post("/login", data={"username": username, "password": password})


def _current_code(secret: str) -> str:
    return pyotp.TOTP(secret).now()


def _user_row(TestSession, username: str = "alice") -> User:
    db = TestSession()
    try:
        return db.query(User).filter(User.username == username).one()
    finally:
        db.close()


# ---------- setup ----------


def test_totp_setup_requires_auth(client):
    assert client.post("/auth/totp/setup").status_code == 401


def test_totp_setup_returns_secret_and_qr(client, make_user, TestSession):
    make_user(username="alice", password="hunter2-pass")
    _login_first_factor(client)

    r = client.post("/auth/totp/setup")
    assert r.status_code == 200
    body = r.json()
    assert body["secret"]
    assert body["uri"].startswith("otpauth://totp/")
    assert body["qr_svg"].startswith("<?xml") or body["qr_svg"].startswith("<svg")

    # Secret is persisted; enabled flag is NOT — abandoned setup is harmless.
    user = _user_row(TestSession)
    assert user.totp_secret == body["secret"]
    assert user.totp_enabled is False


def test_totp_setup_rejected_when_already_enabled(client, make_user, TestSession):
    make_user(username="alice", password="hunter2-pass")
    _login_first_factor(client)
    client.post("/auth/totp/setup")
    secret = _user_row(TestSession).totp_secret
    client.post("/auth/totp/enable", data={"code": _current_code(secret)})

    r = client.post("/auth/totp/setup")
    assert r.status_code == 409


# ---------- enable ----------


def test_totp_enable_with_correct_code_returns_recovery_codes(
    client, make_user, TestSession
):
    make_user(username="alice", password="hunter2-pass")
    _login_first_factor(client)
    client.post("/auth/totp/setup")
    secret = _user_row(TestSession).totp_secret

    r = client.post("/auth/totp/enable", data={"code": _current_code(secret)})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert len(body["recovery_codes"]) == 10
    # Codes look like ``abcde-fghij`` (hex, 5+5).
    assert all("-" in c and len(c) == 11 for c in body["recovery_codes"])

    user = _user_row(TestSession)
    assert user.totp_enabled is True
    # Recovery codes are stored as a JSON list of argon2 hashes, not plaintext.
    stored = json.loads(user.totp_recovery_codes)
    assert len(stored) == 10
    assert all(h.startswith("$argon2id$") for h in stored)
    assert not any(c in user.totp_recovery_codes for c in body["recovery_codes"])


def test_totp_enable_with_wrong_code_fails(client, make_user):
    make_user(username="alice", password="hunter2-pass")
    _login_first_factor(client)
    client.post("/auth/totp/setup")

    r = client.post("/auth/totp/enable", data={"code": "000000"})
    assert r.status_code == 400


# ---------- login flow with 2FA ----------


def _enrolled_user(client, make_user, TestSession):
    make_user(username="alice", password="hunter2-pass")
    _login_first_factor(client)
    client.post("/auth/totp/setup")
    secret = _user_row(TestSession).totp_secret
    client.post("/auth/totp/enable", data={"code": _current_code(secret)})
    client.post("/logout")
    return secret


def test_login_with_2fa_user_returns_needs_2fa(client, make_user, TestSession):
    _enrolled_user(client, make_user, TestSession)
    r = _login_first_factor(client)
    assert r.status_code == 200
    body = r.json()
    assert body == {"ok": True, "needs_2fa": True}
    # Cookie is set, but it's a pending session.
    assert SESSION_COOKIE in r.cookies


def test_pending_session_cannot_access_protected_routes(client, make_user, TestSession):
    _enrolled_user(client, make_user, TestSession)
    _login_first_factor(client)
    assert client.get("/me").status_code == 401
    assert client.get("/auth/verify").status_code == 401
    assert client.get("/containers").status_code == 401


def test_totp_verify_with_correct_code_promotes_session(
    client, make_user, TestSession
):
    secret = _enrolled_user(client, make_user, TestSession)
    _login_first_factor(client)

    r = client.post("/auth/totp/verify", data={"code": _current_code(secret)})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "username": "alice"}

    # Now /me works again.
    assert client.get("/me").status_code == 200

    # Session row was promoted, not replaced.
    db = TestSession()
    try:
        sess = db.query(UserSession).filter(UserSession.user_id != None).one()  # noqa: E711
        assert sess.mfa_pending is False
    finally:
        db.close()


def test_totp_verify_with_wrong_code_rejects_and_audits(
    client, make_user, TestSession
):
    _enrolled_user(client, make_user, TestSession)
    _login_first_factor(client)

    r = client.post("/auth/totp/verify", data={"code": "000000"})
    assert r.status_code == 401

    db = TestSession()
    try:
        bad = (
            db.query(LoginEvent)
            .filter(LoginEvent.reason == "bad-totp")
            .all()
        )
        assert len(bad) == 1
        assert bad[0].success is False
    finally:
        db.close()


def test_totp_verify_without_pending_session_is_401(client):
    """No pending cookie → can't even attempt /verify."""
    r = client.post("/auth/totp/verify", data={"code": "000000"})
    assert r.status_code == 401


def test_full_session_cannot_be_used_for_totp_verify(client, make_user):
    """A user without 2FA enrolled still has a full session — /verify rejects it."""
    make_user(username="alice", password="hunter2-pass")
    _login_first_factor(client)
    r = client.post("/auth/totp/verify", data={"code": "000000"})
    assert r.status_code == 401


# ---------- recovery codes ----------


def test_recovery_code_works_once(client, make_user, TestSession):
    _enrolled_user(client, make_user, TestSession)
    # Re-enroll to recover the plaintext recovery codes.
    _login_first_factor(client)
    # We're enrolled, so login returns needs_2fa — finish with TOTP first.
    db = TestSession()
    try:
        secret = db.query(User).one().totp_secret
    finally:
        db.close()
    client.post("/auth/totp/verify", data={"code": _current_code(secret)})

    # Reset and re-enroll so we have plaintext codes returned to us.
    client.post("/auth/totp/disable", data={"code": _current_code(secret)})
    client.post("/auth/totp/setup")
    new_secret = _user_row(TestSession).totp_secret
    enable = client.post("/auth/totp/enable", data={"code": _current_code(new_secret)})
    recovery_codes = enable.json()["recovery_codes"]

    # Log out, log back in via first factor, then verify with a recovery code.
    client.post("/logout")
    _login_first_factor(client)
    r = client.post("/auth/totp/verify", data={"code": recovery_codes[0]})
    assert r.status_code == 200

    # Second use of the same recovery code must fail (one-time).
    client.post("/logout")
    _login_first_factor(client)
    r = client.post("/auth/totp/verify", data={"code": recovery_codes[0]})
    assert r.status_code == 401


# ---------- disable ----------


def test_totp_disable_with_correct_code_clears_state(client, make_user, TestSession):
    secret = _enrolled_user(client, make_user, TestSession)
    _login_first_factor(client)
    client.post("/auth/totp/verify", data={"code": _current_code(secret)})

    r = client.post("/auth/totp/disable", data={"code": _current_code(secret)})
    assert r.status_code == 200

    user = _user_row(TestSession)
    assert user.totp_enabled is False
    assert user.totp_secret is None
    assert user.totp_recovery_codes is None


def test_totp_disable_with_wrong_code_fails(client, make_user, TestSession):
    secret = _enrolled_user(client, make_user, TestSession)
    _login_first_factor(client)
    client.post("/auth/totp/verify", data={"code": _current_code(secret)})

    r = client.post("/auth/totp/disable", data={"code": "000000"})
    assert r.status_code == 400

    user = _user_row(TestSession)
    assert user.totp_enabled is True


# ---------- /me exposure ----------


def test_me_includes_totp_enabled_flag(client, make_user, TestSession):
    make_user(username="alice", password="hunter2-pass")
    _login_first_factor(client)
    r = client.get("/me")
    assert r.json()["totp_enabled"] is False

    client.post("/auth/totp/setup")
    secret = _user_row(TestSession).totp_secret
    client.post("/auth/totp/enable", data={"code": _current_code(secret)})

    # After enabling, must re-verify with 2FA next login — but /me still works
    # on the existing pre-2FA session (sessions issued before enrollment stay
    # valid; the gate is at /login).
    r = client.get("/me")
    assert r.json()["totp_enabled"] is True
