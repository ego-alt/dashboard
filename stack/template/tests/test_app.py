from app import create_app


def test_health_and_home():
    client = create_app({"TESTING": True}).test_client()
    assert client.get("/healthz").get_json() == {"ok": True}
    assert client.get("/").status_code == 200


def test_links_carry_the_stack_prefix():
    client = create_app({"TESTING": True}).test_client()
    page = client.get("/", headers={"X-Forwarded-Prefix": "/__NAME__"})
    assert page.status_code == 200
