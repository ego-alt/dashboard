"""Backup status endpoint: admin-gated, tolerates a missing file, and computes
its state (running, interrupted, failed, stale or healthy) from the status file."""

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
    monkeypatch.setattr("app.routes.backups._BACKUP_STATUS_FILE", str(tmp_path / "absent.json"))
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
    monkeypatch.setattr("app.routes.backups._BACKUP_STATUS_FILE", str(p))
    _admin(client, make_user)
    r = client.get("/backups/status").json()
    assert r["available"] is True
    assert r["state"] == "healthy"
    assert r["snapshot_count"] == 5
    assert r["age_seconds"] is not None


def test_old_run_is_stale(client, make_user, monkeypatch, tmp_path):
    p = tmp_path / "status.json"
    p.write_text(json.dumps({
        "ok": True,
        "finished_at": _utc(datetime.now(timezone.utc) - timedelta(days=3)),
    }))
    monkeypatch.setattr("app.routes.backups._BACKUP_STATUS_FILE", str(p))
    _admin(client, make_user)
    r = client.get("/backups/status").json()
    assert r["available"] is True and r["state"] == "stale"


def _state(client, make_user, monkeypatch, tmp_path, data):
    p = tmp_path / "status.json"
    p.write_text(json.dumps(data))
    monkeypatch.setattr("app.routes.backups._BACKUP_STATUS_FILE", str(p))
    _admin(client, make_user)
    return client.get("/backups/status").json()["state"]


def test_failed_run(client, make_user, monkeypatch, tmp_path):
    data = {"ok": False, "finished_at": _utc(datetime.now(timezone.utc)), "error": "failed during: pruning"}
    assert _state(client, make_user, monkeypatch, tmp_path, data) == "failed"


def test_a_run_going_now_is_running(client, make_user, monkeypatch, tmp_path):
    now = datetime.now(timezone.utc)
    data = {"ok": False, "finished_at": _utc(now - timedelta(days=1)), "running_since": _utc(now - timedelta(minutes=2))}
    assert _state(client, make_user, monkeypatch, tmp_path, data) == "running"


def test_a_run_that_never_finished_is_interrupted(client, make_user, monkeypatch, tmp_path):
    now = datetime.now(timezone.utc)
    data = {"ok": True, "finished_at": _utc(now - timedelta(days=1)), "running_since": _utc(now - timedelta(hours=7))}
    assert _state(client, make_user, monkeypatch, tmp_path, data) == "interrupted"
