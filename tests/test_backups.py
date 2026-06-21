"""Backup status endpoint: admin-gated, tolerates a missing file, and computes
freshness (stale vs healthy) from the status file's finished_at timestamp."""

import json
from datetime import datetime, timedelta, timezone


def _utc(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _login(client, username, password="hunter2-secret"):
    assert client.post(
        "/login", data={"username": username, "password": password}
    ).status_code == 200


def _admin(client, make_user):
    make_user(username="admin", is_admin=True)
    _login(client, "admin")


def test_requires_admin(client, make_user):
    assert client.get("/backups/status").status_code == 401  # unauthenticated
    make_user(username="bob", is_admin=False)
    _login(client, "bob")
    assert client.get("/backups/status").status_code == 403  # non-admin


def test_missing_file_is_not_an_error(client, make_user, monkeypatch, tmp_path):
    monkeypatch.setattr("app.main._BACKUP_STATUS_FILE", str(tmp_path / "absent.json"))
    _admin(client, make_user)
    assert client.get("/backups/status").json() == {"available": False}


def test_fresh_run_is_healthy(client, make_user, monkeypatch, tmp_path):
    p = tmp_path / "status.json"
    p.write_text(json.dumps({
        "ok": True,
        "finished_at": _utc(datetime.now(timezone.utc)),
        "snapshot_count": 5,
        "databases": [{"app": "calendar", "ok": True}],
    }))
    monkeypatch.setattr("app.main._BACKUP_STATUS_FILE", str(p))
    _admin(client, make_user)
    r = client.get("/backups/status").json()
    assert r["available"] is True
    assert r["stale"] is False
    assert r["snapshot_count"] == 5
    assert r["age_seconds"] is not None


def test_old_run_is_stale(client, make_user, monkeypatch, tmp_path):
    p = tmp_path / "status.json"
    p.write_text(json.dumps({
        "ok": True,
        "finished_at": _utc(datetime.now(timezone.utc) - timedelta(days=3)),
    }))
    monkeypatch.setattr("app.main._BACKUP_STATUS_FILE", str(p))
    _admin(client, make_user)
    r = client.get("/backups/status").json()
    assert r["available"] is True and r["stale"] is True
