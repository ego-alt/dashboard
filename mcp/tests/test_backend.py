import httpx
import pytest

from homehub_mcp.backend import AppError, ExternalBackend, InternalBackend
from homehub_mcp.config import Config

pytestmark = pytest.mark.anyio


async def test_internal_sends_user_and_secret(config, fake):
    fake.on("GET", "calendar", "/x")(lambda r, m: httpx.Response(200, json={"ok": 1}))
    b = InternalBackend(config, transport=httpx.MockTransport(fake))
    assert await b.request("calendar", "GET", "/x", user="grey") == {"ok": 1}
    req = fake.last()
    assert req.headers["x-forwarded-user"] == "grey"
    assert req.headers["x-internal-auth"] == "s3cret"
    assert "authorization" not in req.headers


async def test_internal_refuses_without_a_user(config, fake):
    b = InternalBackend(config, transport=httpx.MockTransport(fake))
    with pytest.raises(AppError, match="Not signed in"):
        await b.request("calendar", "GET", "/x", user=None)
    assert fake.requests == []


async def test_external_uses_bearer_and_public_prefix(fake):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(204)

    cfg = Config(homehub_url="https://home.test", homehub_token="tok")
    b = ExternalBackend(cfg, transport=httpx.MockTransport(handler))
    assert await b.request("tapes", "DELETE", "/api/x", user="ignored") is None
    assert str(seen[0].url) == "https://home.test/music/api/x"
    assert seen[0].headers["authorization"] == "Bearer tok"
    assert "x-forwarded-user" not in seen[0].headers


def test_external_needs_url_and_token():
    with pytest.raises(SystemExit):
        ExternalBackend(Config())


@pytest.mark.parametrize("response,message", [
    (httpx.Response(400, json={"status": "error", "message": "The end is before the start."}),
     "The end is before the start."),
    (httpx.Response(400, json={"error": "Give the tape a name."}), "Give the tape a name."),
    (httpx.Response(404, json={"error": "The requested URL was not found on the server."}), "Not found."),
    (httpx.Response(403, text="nope"), "permission"),
    (httpx.Response(302, headers={"location": "/login"}), "didn't accept these credentials"),
    (httpx.Response(401, json={}), "didn't accept these credentials"),
    (httpx.Response(200, text="<html>"), "isn't JSON"),
])
async def test_errors_reach_the_model_readably(config, response, message):
    b = InternalBackend(config, transport=httpx.MockTransport(lambda r: response))
    with pytest.raises(AppError, match=message):
        await b.request("calendar", "GET", "/x", user="grey")


async def test_unreachable_app(config):
    def boom(request):
        raise httpx.ConnectError("refused")

    b = InternalBackend(config, transport=httpx.MockTransport(boom))
    with pytest.raises(AppError, match="Couldn't reach calendar"):
        await b.request("calendar", "GET", "/x", user="grey")
