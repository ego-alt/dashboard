"""docker_control: get_containers wraps live stats; per-container failures
don't bring down the listing; empty results short-circuit."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app import docker_control


@pytest.fixture
def mock_client(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(docker_control, "_get_client", lambda: client)
    return client


def _fake_container(*, cid="abc123", name="library", status="running", with_stats=True):
    c = MagicMock()
    c.id = cid
    c.short_id = cid[:12]
    c.name = name
    c.status = status
    c.image = SimpleNamespace(tags=["library:latest"], id="sha256:deadbeef")
    c.ports = {}
    c.attrs = {
        "Created": "2026-01-01T00:00:00Z",
        "Image": "library:latest",
        "Command": "python",
        "Config": {"Cmd": ["python"]},
    }
    if with_stats:
        c.stats.return_value = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 2_000_000_000},
                "system_cpu_usage": 10_000_000_000,
                "online_cpus": 4,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 1_000_000_000},
                "system_cpu_usage": 9_000_000_000,
            },
            "networks": {"eth0": {"rx_bytes": 2048, "tx_bytes": 1024}},
        }
    else:
        c.stats.side_effect = RuntimeError("daemon failure")
    return c


def test_get_containers_fast_skips_stats(mock_client):
    c = _fake_container()
    mock_client.containers.list.return_value = [c]
    rows = docker_control.get_containers()
    assert len(rows) == 1
    assert rows[0]["name"] == "library"
    c.stats.assert_not_called()


def test_get_containers_returns_metadata_plus_live_stats(mock_client):
    mock_client.containers.list.return_value = [_fake_container()]
    rows = docker_control.get_containers(include_stats=True)
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == "abc123"
    assert row["name"] == "library"
    assert row["status"] == "running"
    assert row["image"] == "library:latest"
    # CPU delta is 1e9 over system delta 1e9, scaled by 4 cores → 400%.
    assert row["cpu_percent"] == 400.0
    assert row["network_rx_kb"] == 2.0
    assert row["network_tx_kb"] == 1.0
    assert row["runtime_seconds"] == 2.0


def test_get_containers_isolates_per_container_stats_failures(mock_client):
    good = _fake_container(cid="good")
    bad = _fake_container(cid="bad", with_stats=False)
    mock_client.containers.list.return_value = [good, bad]
    rows = docker_control.get_containers(include_stats=True)
    assert len(rows) == 2
    by_id = {r["id"]: r for r in rows}
    assert "cpu_percent" in by_id["good"]
    assert "cpu_percent" not in by_id["bad"]


def test_get_containers_skips_stats_for_stopped(mock_client):
    stopped = _fake_container(cid="down", status="exited")
    mock_client.containers.list.return_value = [stopped]
    rows = docker_control.get_containers(include_stats=True)
    assert rows[0]["status"] == "exited"
    stopped.stats.assert_not_called()


def test_get_containers_empty_list_short_circuits(mock_client):
    mock_client.containers.list.return_value = []
    assert docker_control.get_containers() == []


def test_get_container_stats_unknown_id_returns_error(mock_client):
    mock_client.containers.get.side_effect = LookupError("not found")
    result = docker_control.get_container_stats("nonexistent")
    assert result["status"] == "error"
    assert "not found" in result["message"]
