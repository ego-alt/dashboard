"""Dashboard API: the auth provider for the home stack, its Docker monitor, and
the Services, Deploy and phone-app pages. This file is the app itself:
startup, the rate limit, the origin check. The endpoints are in app/routes/,
one module per area."""

import os
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI, Request, Response
from slowapi.errors import RateLimitExceeded

from app.db import SessionLocal, init_db
from app.ratelimit import limiter
from app.routes import (
    account,
    backups,
    containers,
    deploy,
    passkeys,
    phone_apps,
    services,
    tokens,
    totp,
    users,
)
from app.spa import register_spa
from app.uptime import start_sampler

@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    # One sampler per process; the dashboard runs a single uvicorn worker.
    stop = None
    if os.environ.get("UPTIME_SAMPLER", "1") != "0":
        stop = start_sampler(SessionLocal)
    yield
    if stop is not None:
        stop.set()


app = FastAPI(title="Dashboard API", lifespan=lifespan)

# The per-IP limit on password guesses (app/ratelimit.py).
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
def _rate_limit_handler(_request: Request, _exc: RateLimitExceeded) -> Response:
    return Response(
        content='{"detail":"too many requests"}',
        status_code=429,
        media_type="application/json",
    )


def _allowed_origins() -> set[str]:
    """Origins permitted to make state-changing requests. Override in
    production via ``ALLOWED_ORIGINS`` (comma-separated). Defaults cover the
    Vite dev server, direct uvicorn, and the FastAPI TestClient."""
    raw = os.environ.get("ALLOWED_ORIGINS")
    if raw is not None:
        return {o.strip() for o in raw.split(",") if o.strip()}
    return {
        "http://localhost:5173",
        "http://localhost:8000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8000",
        "http://testserver",
    }


_ALLOWED_ORIGINS = _allowed_origins()


@app.middleware("http")
async def origin_check_middleware(request: Request, call_next):
    """Reject browser-originated state-changing requests from foreign origins.
    CORS already blocks cross-origin *reads*; this stops cross-origin *writes*
    (form POST) that don't trigger a preflight.

    An incoming Origin is accepted if it's in ``ALLOWED_ORIGINS`` OR its host
    matches the request's Host header. The latter covers production behind a
    proxy that preserves Host (nginx default) without requiring config; the
    allowlist covers dev where a proxy rewrites Host (Vite with changeOrigin).

    Permissive when ``Origin`` is absent (CLI clients, server-to-server) —
    those paths aren't a CSRF vector.
    """
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        origin = request.headers.get("origin")
        if origin and origin not in _ALLOWED_ORIGINS:
            origin_host = urlparse(origin).netloc
            request_host = request.headers.get("host", "")
            if not origin_host or origin_host != request_host:
                return Response(content="origin mismatch", status_code=403)
    return await call_next(request)


# ---------- public endpoints ----------


@app.get("/ping")
def ping():
    return {"message": "pong"}


# ---------- everything else, by area (app/routes/) ----------

for _router in (account.router, totp.router, passkeys.router, tokens.router, users.router,
                services.router, containers.router, backups.router, deploy.router, phone_apps.router):
    app.include_router(_router)

# The React SPA (built into app/static by Docker or `npm run build`) answers the rest.
register_spa(app)
