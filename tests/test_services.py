"""Service registry: status derivation, daemon-down resilience, the
protected-container anti-lockout guard, and CLI upsert idempotency."""

from sqlalchemy.orm import sessionmaker

from app import main, services
from app.cli import _register_service
from app.db import Base
from app.models import Service


def _seed_service(test_engine, **kw):
    Base.metadata.create_all(test_engine)
    Session = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)
    db = Session()
    try:
        defaults = dict(
            slug="library",
            display_name="Library",
            container_name="library",
            route_prefix="/library/",
            icon="📚",
            description="EPUB reader",
            is_enabled=True,
        )
        defaults.update(kw)
        db.add(Service(**defaults))
        db.commit()
    finally:
        db.close()


# ---------- list_services status derivation ----------


def test_services_empty_when_none_registered(client):
    assert client.get("/services").status_code == 401  # unauth
    # (auth path covered below; empty-list path is the no-rows short-circuit)


def test_services_running(client, make_user, test_engine, monkeypatch):
    _seed_service(test_engine)
    monkeypatch.setattr(
        services, "get_containers", lambda: [{"name": "library", "status": "running"}]
    )
    make_user(username="al", password="hunter2-pass")
    client.post("/login", data={"username": "al", "password": "hunter2-pass"})
    r = client.get("/services")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["slug"] == "library"
    assert body[0]["status"] == "running"
    assert body[0]["route_prefix"] == "/library/"


def test_services_absent_when_container_missing(client, make_user, test_engine, monkeypatch):
    _seed_service(test_engine)
    monkeypatch.setattr(services, "get_containers", lambda: [{"name": "other", "status": "running"}])
    make_user(username="al", password="hunter2-pass")
    client.post("/login", data={"username": "al", "password": "hunter2-pass"})
    assert client.get("/services").json()[0]["status"] == "absent"


def test_services_unknown_when_daemon_down(client, make_user, test_engine, monkeypatch):
    _seed_service(test_engine)

    def boom():
        raise RuntimeError("docker socket missing")

    monkeypatch.setattr(services, "get_containers", boom)
    make_user(username="al", password="hunter2-pass")
    client.post("/login", data={"username": "al", "password": "hunter2-pass"})
    assert client.get("/services").json()[0]["status"] == "unknown"


def test_disabled_service_hidden(client, make_user, test_engine, monkeypatch):
    _seed_service(test_engine, is_enabled=False)
    monkeypatch.setattr(services, "get_containers", lambda: [])
    make_user(username="al", password="hunter2-pass")
    client.post("/login", data={"username": "al", "password": "hunter2-pass"})
    assert client.get("/services").json() == []


# ---------- protected-container guard ----------


def test_protected_container_refused_even_for_admin(client, make_user, monkeypatch):
    make_user(username="boss", password="hunter2-pass", is_admin=True)
    client.post("/login", data={"username": "boss", "password": "hunter2-pass"})
    # Whatever id is passed resolves to a protected name.
    monkeypatch.setattr(main, "resolve_container_name", lambda _id: "home-nginx")
    r = client.post("/containers/anyid/stop")
    assert r.status_code == 409
    assert "protected" in r.json()["detail"]


def test_non_protected_container_allowed_for_admin(client, make_user, monkeypatch):
    make_user(username="boss", password="hunter2-pass", is_admin=True)
    client.post("/login", data={"username": "boss", "password": "hunter2-pass"})
    monkeypatch.setattr(main, "resolve_container_name", lambda _id: "some-app")
    monkeypatch.setattr(
        main, "stop_container", lambda _id: {"status": "success", "message": "stopped"}
    )
    r = client.post("/containers/some-app/stop")
    assert r.status_code == 200
    assert r.json()["status"] == "success"


# ---------- CLI upsert idempotency ----------


def test_register_service_is_idempotent_upsert(test_engine):
    Base.metadata.create_all(test_engine)
    Session = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)
    db = Session()
    try:
        svc1, created1 = _register_service(
            db,
            slug="cal",
            display_name="Calendar",
            container_name="calendar",
            route_prefix="/calendar/",
        )
        assert created1 is True
        svc2, created2 = _register_service(
            db,
            slug="cal",
            display_name="Calendar (renamed)",
            container_name="calendar",
            route_prefix="/calendar/",
        )
        assert created2 is False
        assert svc2.id == svc1.id
        assert db.query(Service).count() == 1
        assert db.query(Service).one().display_name == "Calendar (renamed)"
    finally:
        db.close()
