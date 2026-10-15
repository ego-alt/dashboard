"""Fakes for the three apps and the dashboard, wired through httpx.MockTransport,
so the server's tests need no running services."""

from __future__ import annotations

import json
import re
from collections.abc import Callable

import httpx
import pytest

from homehub_mcp.backend import InternalBackend
from homehub_mcp.config import Config

APP_HOSTS = {"calendar": "calendar.test", "tapes": "tapes.test", "library": "library.test"}


class FakeApps:
    """Route table: (method, host app, path regex) → handler(request, match).
    Records every request for assertions."""

    def __init__(self):
        self.routes: list[tuple[str, str, re.Pattern, Callable]] = []
        self.requests: list[httpx.Request] = []

    def on(self, method: str, app: str, path: str):
        def deco(fn):
            self.routes.append((method, APP_HOSTS[app], re.compile(path + "$"), fn))
            return fn
        return deco

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        for method, host, pattern, fn in self.routes:
            m = pattern.match(request.url.path)
            if method == request.method and host == request.url.host and m:
                return fn(request, m)
        return httpx.Response(404, json={"error": "no fake route"})

    def last(self, method: str | None = None) -> httpx.Request:
        reqs = [r for r in self.requests if method is None or r.method == method]
        return reqs[-1]


def body(request: httpx.Request):
    return json.loads(request.content or b"null")


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def config():
    return Config(
        public_url="http://localhost:8100",
        dashboard_url="http://dash.test",
        app_urls={app: f"http://{host}" for app, host in APP_HOSTS.items()},
        internal_secret="s3cret",
        db_path=":memory:",
    )


@pytest.fixture
def fake():
    return FakeApps()


class UserBackend(InternalBackend):
    """InternalBackend that acts as a fixed user, for in-process tool tests
    (which carry no access token)."""

    def __init__(self, config, user="grey", **kw):
        super().__init__(config, **kw)
        self.user = user

    def _headers(self, user):
        return super()._headers(user or self.user)


@pytest.fixture
def backend(config, fake):
    return UserBackend(config, transport=httpx.MockTransport(fake))
