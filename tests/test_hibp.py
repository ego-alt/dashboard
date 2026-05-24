"""HIBP k-anonymity password check + cli integration."""

import io
import urllib.error
from unittest.mock import patch

import pytest

from app import cli, hibp


# ---------- direct module behavior ----------


def _mock_urlopen_returning(body: str):
    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    return lambda *_args, **_kwargs: _Resp(body.encode("ascii"))


def test_password_breach_count_returns_zero_for_clean(monkeypatch):
    # "abcdef" hash suffix won't match anything we return.
    monkeypatch.setattr(
        hibp.urllib.request, "urlopen", _mock_urlopen_returning("FFFF:1\nEEEE:9")
    )
    assert hibp.password_breach_count("anything") == 0


def test_password_breach_count_matches_known_suffix(monkeypatch):
    """``hunter2`` SHA-1 = F3BBBD66A63D4BF1747940578EC3D0103530E21D, prefix
    F3BBB, suffix D66A63D4BF1747940578EC3D0103530E21D."""
    body = "D66A63D4BF1747940578EC3D0103530E21D:42\n0000:1"
    monkeypatch.setattr(
        hibp.urllib.request, "urlopen", _mock_urlopen_returning(body)
    )
    assert hibp.password_breach_count("hunter2") == 42
    assert hibp.is_password_pwned("hunter2") is True


def test_password_breach_count_returns_zero_on_network_error(monkeypatch):
    def _boom(*_a, **_kw):
        raise urllib.error.URLError("no route to host")

    monkeypatch.setattr(hibp.urllib.request, "urlopen", _boom)
    # Fail-open: legitimate operators on a flaky network shouldn't be blocked.
    assert hibp.password_breach_count("hunter2") == 0


def test_password_breach_count_handles_malformed_lines(monkeypatch):
    body = "garbage\nABC:not-a-number\n"
    monkeypatch.setattr(
        hibp.urllib.request, "urlopen", _mock_urlopen_returning(body)
    )
    assert hibp.password_breach_count("anything") == 0


# ---------- cli integration ----------


def test_cli_create_admin_refuses_pwned_password(monkeypatch, capsys):
    monkeypatch.setattr(cli, "password_breach_count", lambda *_a, **_kw: 100)
    monkeypatch.setattr(cli, "init_db", lambda: None)

    with pytest.raises(SystemExit) as exc:
        cli.main(["create-admin", "alice", "--password", "compromised-pw"])
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "100" in err
    assert "breach" in err.lower()


def test_cli_create_admin_allows_pwned_with_flag(monkeypatch):
    monkeypatch.setattr(cli, "password_breach_count", lambda *_a, **_kw: 100)
    monkeypatch.setattr(cli, "init_db", lambda: None)
    called = {}

    def _fake_add_user(_db, **kwargs):
        called.update(kwargs)
        u = type("U", (), {"id": 1, "is_admin": True})()
        return u

    monkeypatch.setattr(cli, "_add_user", _fake_add_user)

    class _NullCtx:
        def __enter__(self):
            return None

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(cli, "session_scope", lambda: _NullCtx())

    cli.main(
        [
            "create-admin",
            "alice",
            "--password",
            "compromised-pw",
            "--allow-pwned",
        ]
    )
    assert called["username"] == "alice"
    assert called["password"] == "compromised-pw"


def test_cli_create_admin_accepts_clean_password(monkeypatch):
    monkeypatch.setattr(cli, "password_breach_count", lambda *_a, **_kw: 0)
    monkeypatch.setattr(cli, "init_db", lambda: None)
    called = {}

    def _fake_add_user(_db, **kwargs):
        called.update(kwargs)
        u = type("U", (), {"id": 1, "is_admin": True})()
        return u

    monkeypatch.setattr(cli, "_add_user", _fake_add_user)

    class _NullCtx:
        def __enter__(self):
            return None

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(cli, "session_scope", lambda: _NullCtx())

    cli.main(["create-admin", "alice", "--password", "very-strong-pass"])
    assert called["password"] == "very-strong-pass"
