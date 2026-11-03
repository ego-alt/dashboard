"""The power icon: only an admin can ask, and the ask is a file the Pi acts on."""
import pytest

import app.routes.deploy as deploy


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy, "STATE_DIR", tmp_path)
    return tmp_path


def test_only_an_admin_can_shut_down(client, make_user, state):
    make_user(username="bob")
    client.post("/login", data={"username": "bob", "password": "hunter2-secret"})
    assert client.post("/system/shutdown").status_code == 403
    assert not (state / "power" / "shutdown").exists()


def test_shutdown_leaves_a_request(client, make_user, state):
    make_user(username="admin", is_admin=True)
    client.post("/login", data={"username": "admin", "password": "hunter2-secret"})
    assert client.post("/system/shutdown").status_code == 202
    assert "by admin" in (state / "power" / "shutdown").read_text()
