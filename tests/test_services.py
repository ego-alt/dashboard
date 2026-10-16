"""Label-based service discovery + the protected-container anti-lockout guard."""

from app import main, services


def _candidate(name, status="running", **labels):
    return {"name": name, "status": status, "labels": labels}


# ---------- discovery from Docker labels ----------


def test_unauthenticated_services_is_401(client):
    assert client.get("/services").status_code == 401


def test_enabled_service_discovered(client, make_user, monkeypatch):
    monkeypatch.setattr(
        services,
        "list_service_candidates",
        lambda: [
            _candidate(
                "library",
                status="running",
                **{
                    "homehub.enable": "true",
                    "homehub.name": "Library",
                    "homehub.route": "/library/",
                    "homehub.icon": "book",
                },
            )
        ],
    )
    make_user(username="al", password="hunter2-pass")
    client.post("/login", data={"username": "al", "password": "hunter2-pass"})
    body = client.get("/services").json()
    assert len(body) == 1
    assert body[0] == {
        "slug": "library",
        "display_name": "Library",
        "route_prefix": "/library/",
        "icon": "book",
        "description": None,
        "container_name": "library",
        "status": "running",
        "health": None,
        "state": "up",
        "since": None,
    }


def test_container_without_enable_label_excluded(client, make_user, monkeypatch):
    monkeypatch.setattr(
        services,
        "list_service_candidates",
        lambda: [
            _candidate("dashboard", **{"homehub.route": "/"}),  # no enable
            _candidate("randomdb"),  # no labels at all
        ],
    )
    make_user(username="al", password="hunter2-pass")
    client.post("/login", data={"username": "al", "password": "hunter2-pass"})
    assert client.get("/services").json() == []


def test_enabled_but_no_route_skipped(client, make_user, monkeypatch):
    monkeypatch.setattr(
        services,
        "list_service_candidates",
        lambda: [_candidate("x", **{"homehub.enable": "true"})],
    )
    make_user(username="al", password="hunter2-pass")
    client.post("/login", data={"username": "al", "password": "hunter2-pass"})
    assert client.get("/services").json() == []


def test_stopped_container_reported_stopped_and_name_default(client, make_user, monkeypatch):
    monkeypatch.setattr(
        services,
        "list_service_candidates",
        lambda: [
            _candidate(
                "calendar",
                status="exited",
                **{"homehub.enable": "1", "homehub.route": "/calendar/"},
            )
        ],
    )
    make_user(username="al", password="hunter2-pass")
    client.post("/login", data={"username": "al", "password": "hunter2-pass"})
    svc = client.get("/services").json()[0]
    assert svc["status"] == "stopped"
    assert svc["display_name"] == "calendar"  # falls back to container name
    assert svc["icon"] is None


def test_unhealthy_running_container_is_degraded(client, make_user, monkeypatch):
    monkeypatch.setattr(
        services,
        "list_service_candidates",
        lambda: [
            {
                **_candidate(
                    "music", **{"homehub.enable": "true", "homehub.route": "/music/"}
                ),
                "state": "degraded",
                "started_at": "2026-10-16T01:00:00Z",
            }
        ],
    )
    make_user(username="al", password="hunter2-pass")
    client.post("/login", data={"username": "al", "password": "hunter2-pass"})
    svc = client.get("/services").json()[0]
    assert svc["state"] == "degraded"
    assert svc["since"] == "2026-10-16T01:00:00Z"


def test_daemon_down_is_503_with_last_known_services(client, make_user, monkeypatch):
    monkeypatch.setattr(
        services,
        "list_service_candidates",
        lambda: [_candidate("library", **{"homehub.enable": "1", "homehub.route": "/library/"})],
    )
    make_user(username="al", password="hunter2-pass")
    client.post("/login", data={"username": "al", "password": "hunter2-pass"})
    assert client.get("/services").status_code == 200

    def boom():
        raise RuntimeError("docker socket missing")

    monkeypatch.setattr(services, "list_service_candidates", boom)
    r = client.get("/services")
    assert r.status_code == 503
    body = r.json()
    assert body["detail"] == "can't reach Docker"
    assert [s["slug"] for s in body["services"]] == ["library"]
    assert body["services"][0]["state"] == "unknown"


def test_results_sorted_by_display_name(client, make_user, monkeypatch):
    monkeypatch.setattr(
        services,
        "list_service_candidates",
        lambda: [
            _candidate("z", **{"homehub.enable": "true", "homehub.route": "/z/", "homehub.name": "Zeta"}),
            _candidate("a", **{"homehub.enable": "true", "homehub.route": "/a/", "homehub.name": "Alpha"}),
        ],
    )
    make_user(username="al", password="hunter2-pass")
    client.post("/login", data={"username": "al", "password": "hunter2-pass"})
    names = [s["display_name"] for s in client.get("/services").json()]
    assert names == ["Alpha", "Zeta"]


# ---------- protected-container anti-lockout guard ----------


def test_protected_container_refused_even_for_admin(client, make_user, monkeypatch):
    make_user(username="boss", password="hunter2-pass", is_admin=True)
    client.post("/login", data={"username": "boss", "password": "hunter2-pass"})
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
