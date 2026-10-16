"""Uptime: container state from inspect data, the per-minute sampler's hourly
buckets, and the strips /uptime returns."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app import docker_control
from app.models import UptimeHour
from app.uptime import prune, record_sample, uptime_summary


def _c(status="running", health=None, **state):
    st = {"StartedAt": "2026-10-16T01:00:00.123Z", "FinishedAt": "0001-01-01T00:00:00Z", **state}
    if health:
        st["Health"] = {"Status": health}
    return SimpleNamespace(status=status, attrs={"State": st, "RestartCount": 3}, labels={})


def test_container_state():
    assert docker_control.container_state(_c()) == {
        "state": "up",
        "health": None,
        "started_at": "2026-10-16T01:00:00.123Z",
        "finished_at": None,
        "restart_count": 3,
    }
    assert docker_control.container_state(_c(health="healthy"))["state"] == "up"
    assert docker_control.container_state(_c(health="unhealthy"))["state"] == "degraded"
    assert docker_control.container_state(_c(health="starting"))["state"] == "degraded"
    down = docker_control.container_state(_c("exited", FinishedAt="2026-10-16T02:14:00Z"))
    assert down["state"] == "down"
    assert down["started_at"] is None and down["finished_at"] == "2026-10-16T02:14:00Z"


def test_never_stopped_has_no_finished_at():
    assert docker_control.container_state(_c("created"))["finished_at"] is None


NOW = datetime(2026, 10, 16, 12, 30, tzinfo=timezone.utc)


def test_samples_add_up_per_hour(TestSession):
    db = TestSession()
    for minute in range(3):
        record_sample(
            db,
            [{"name": "music", "state": "up"}, {"name": "library", "state": "down"}],
            NOW + timedelta(minutes=minute),
        )
    record_sample(db, [{"name": "music", "state": "degraded"}], NOW)
    record_sample(db, [{"name": "music", "state": "nonsense"}], NOW)
    rows = {r.name: r for r in db.query(UptimeHour)}
    assert (rows["music"].up, rows["music"].degraded, rows["music"].down) == (3, 1, 0)
    assert rows["library"].down == 3
    assert rows["music"].hour == datetime(2026, 10, 16, 12)


def _hours(db, name, start, states):
    for i, (up, deg, down) in enumerate(states):
        db.add(UptimeHour(name=name, hour=start + timedelta(hours=i), up=up, degraded=deg, down=down))
    db.commit()


def test_last_24_hours(TestSession):
    db = TestSession()
    _hours(db, "music", datetime(2026, 10, 16, 11), [(60, 0, 0), (20, 0, 10)])
    _hours(db, "music", datetime(2026, 10, 15, 12), [(60, 0, 0)])  # just outside
    s = uptime_summary(db, days=1, now=NOW)
    assert s["bucket"] == "hour"
    assert s["start"] == "2026-10-15T13:00:00+00:00"
    b = s["services"]["music"]["buckets"]
    assert len(b) == 24 and b[-2:] == [[60, 0, 0], [20, 0, 10]] and b[0] is None
    assert s["services"]["music"]["pct"] == round(100 * 80 / 90, 2)


def test_days_break_at_the_viewers_midnight(TestSession):
    db = TestSession()
    # 22:00 and 23:00 UTC on the 15th are already the 16th at UTC+2.
    _hours(db, "music", datetime(2026, 10, 15, 21), [(60, 0, 0), (0, 0, 60), (0, 60, 0)])
    utc = uptime_summary(db, days=2, now=NOW)["services"]["music"]["buckets"]
    assert utc == [[60, 60, 60], None]
    east = uptime_summary(db, days=2, tz_offset_min=120, now=NOW)
    assert east["start"] == "2026-10-14T22:00:00+00:00"
    assert east["services"]["music"]["buckets"] == [[60, 0, 0], [0, 60, 60]]


def test_prune_keeps_90_days(TestSession):
    db = TestSession()
    _hours(db, "music", datetime(2026, 7, 1), [(60, 0, 0)])
    _hours(db, "music", datetime(2026, 10, 1), [(60, 0, 0)])
    prune(db, NOW)
    assert [r.hour.month for r in db.query(UptimeHour)] == [10]


def test_uptime_endpoint_needs_sign_in(client, make_user):
    assert client.get("/uptime").status_code == 401
    make_user()
    client.post("/login", data={"username": "alice", "password": "hunter2-secret"})
    body = client.get("/uptime?days=30&tz=60").json()
    assert body["bucket"] == "day" and body["services"] == {}
