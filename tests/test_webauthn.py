"""WebAuthn / passkey endpoints.

The crypto verification done by py_webauthn requires a real authenticator,
so we mock the verify_*_response calls. The rest of the flow (challenge
issuance, credential storage, credential listing, the login-mints-a-session
path) is exercised end-to-end against the in-memory test SQLite.
"""

from types import SimpleNamespace
from unittest.mock import patch

from app.auth import SESSION_COOKIE
from app.models import LoginEvent, WebauthnCredential
from app.webauthn_helpers import challenges


def _login(client, username="alice", password="hunter2-pass"):
    return client.post("/login", data={"username": username, "password": password})


def _seed_pending_challenge(user_id):
    """Pretend the /begin endpoint already ran and the cache has a token."""
    return challenges.issue(b"fake-challenge", user_id=user_id)


# ---------- list / delete ----------


def test_credentials_list_empty_when_none(client, make_user):
    make_user(username="alice", password="hunter2-pass")
    _login(client)
    r = client.get("/auth/webauthn/credentials")
    assert r.status_code == 200
    assert r.json() == []


def test_credentials_list_returns_user_credentials_only(client, make_user, TestSession):
    alice = make_user(username="alice", password="hunter2-pass")
    bob = make_user(username="bob", password="hunter2-pass")
    db = TestSession()
    try:
        db.add(WebauthnCredential(
            user_id=alice.id,
            credential_id=b"\x01",
            public_key=b"pk1",
            sign_count=0,
            name="Alice's phone",
        ))
        db.add(WebauthnCredential(
            user_id=bob.id,
            credential_id=b"\x02",
            public_key=b"pk2",
            sign_count=0,
            name="Bob's laptop",
        ))
        db.commit()
    finally:
        db.close()

    _login(client, username="alice")
    r = client.get("/auth/webauthn/credentials")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["name"] == "Alice's phone"


def test_delete_credential_removes_only_own(client, make_user, TestSession):
    make_user(username="alice", password="hunter2-pass")
    bob = make_user(username="bob", password="hunter2-pass")
    db = TestSession()
    try:
        db.add(WebauthnCredential(
            user_id=bob.id, credential_id=b"\xff", public_key=b"pk",
            sign_count=0, name="Bob's key",
        ))
        db.commit()
        bob_cred_id = db.query(WebauthnCredential).filter(WebauthnCredential.user_id == bob.id).one().id
    finally:
        db.close()

    _login(client, username="alice")
    # Alice can't delete Bob's credential.
    r = client.delete(f"/auth/webauthn/credentials/{bob_cred_id}")
    assert r.status_code == 404

    db = TestSession()
    try:
        assert db.query(WebauthnCredential).count() == 1
    finally:
        db.close()


# ---------- registration ----------


def test_register_begin_returns_options_and_token(client, make_user):
    make_user(username="alice", password="hunter2-pass")
    _login(client)
    r = client.post("/auth/webauthn/register/begin")
    assert r.status_code == 200
    body = r.json()
    assert body["token"]
    opts = body["options"]
    assert opts["rp"]["id"]
    assert opts["challenge"]
    assert opts["user"]["name"] == "alice"


def test_register_finish_stores_credential(client, make_user, TestSession):
    alice = make_user(username="alice", password="hunter2-pass")
    _login(client)

    # Pretend /begin already ran.
    token = _seed_pending_challenge(alice.id)

    fake_verified = SimpleNamespace(
        credential_id=b"\xaa\xbb\xcc",
        credential_public_key=b"\xde\xad\xbe\xef",
        sign_count=0,
    )
    cred_dict = {"id": "abc", "response": {"transports": ["usb"]}}
    with patch(
        "app.main.webauthn_lib.verify_registration_response",
        return_value=fake_verified,
    ):
        r = client.post(
            "/auth/webauthn/register/finish",
            json={"token": token, "name": "Alice's phone", "credential": cred_dict},
        )
    assert r.status_code == 200, r.text

    db = TestSession()
    try:
        cred = db.query(WebauthnCredential).one()
        assert cred.user_id == alice.id
        assert cred.credential_id == b"\xaa\xbb\xcc"
        assert cred.public_key == b"\xde\xad\xbe\xef"
        assert cred.name == "Alice's phone"
        assert cred.transports == "usb"
    finally:
        db.close()


def test_register_finish_rejects_unknown_token(client, make_user):
    make_user(username="alice", password="hunter2-pass")
    _login(client)
    r = client.post(
        "/auth/webauthn/register/finish",
        json={"token": "no-such-token", "name": "x", "credential": {}},
    )
    assert r.status_code == 400


# ---------- assertion / login ----------


def test_login_begin_returns_options_without_auth(client):
    """Passkey login is the entry point — no session yet."""
    r = client.post("/auth/webauthn/login/begin")
    assert r.status_code == 200
    body = r.json()
    assert body["token"]
    assert body["options"]["challenge"]


def test_login_finish_mints_session_and_skips_2fa(client, make_user, TestSession):
    alice = make_user(username="alice", password="hunter2-pass")
    # Pre-existing passkey credential.
    db = TestSession()
    try:
        db.add(WebauthnCredential(
            user_id=alice.id,
            credential_id=b"\x11\x22\x33",
            public_key=b"\xaa",
            sign_count=0,
            name="key",
        ))
        # Even with TOTP enrolled, a passkey login is its own MFA.
        u = db.query(type(alice)).filter_by(id=alice.id).one()
        u.totp_enabled = True
        u.totp_secret = "JBSWY3DPEHPK3PXP"
        db.commit()
    finally:
        db.close()

    token = challenges.issue(b"fake", user_id=None)
    # "ESIz" is base64url for the bytes 11 22 33.
    cred_dict = {"id": "ESIz", "rawId": "ESIz", "response": {}}
    fake_verified = SimpleNamespace(new_sign_count=1)
    with patch(
        "app.main.webauthn_lib.verify_authentication_response",
        return_value=fake_verified,
    ):
        r = client.post(
            "/auth/webauthn/login/finish",
            json={"token": token, "credential": cred_dict},
        )
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "username": "alice"}
    assert SESSION_COOKIE in r.cookies

    # Session is fully authenticated (skipped TOTP), so /me works.
    assert client.get("/me").status_code == 200

    # Audit row recorded with reason=passkey.
    db = TestSession()
    try:
        events = db.query(LoginEvent).all()
        assert any(e.reason == "passkey" and e.success for e in events)
    finally:
        db.close()


def test_login_finish_rejects_unknown_credential_id(client, make_user):
    make_user(username="alice", password="hunter2-pass")
    token = challenges.issue(b"fake", user_id=None)
    # rawId points at a credential that doesn't exist.
    cred_dict = {"id": "3q0", "rawId": "3q0", "response": {}}
    r = client.post(
        "/auth/webauthn/login/finish",
        json={"token": token, "credential": cred_dict},
    )
    assert r.status_code == 401


def test_login_finish_rejects_expired_challenge(client):
    r = client.post(
        "/auth/webauthn/login/finish",
        json={"token": "no-such-token", "credential": {}},
    )
    assert r.status_code == 400
