"""Settings, read once from the environment.

Two ways to run (see README):

- **stdio** (a desktop client launches the server): calls the apps through the
  public nginx with the user's personal access token. Needs ``HOMEHUB_URL`` and
  ``HOMEHUB_TOKEN``.
- **http** (the ``mcp`` container): calls the apps directly on the compose
  network as the authenticated user, and answers OAuth for remote clients.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass(frozen=True)
class Config:
    # --- stdio / external ---
    homehub_url: str = ""  # e.g. https://home.local
    homehub_token: str = ""  # a dashboard API token
    # Path to a CA bundle for a self-signed home cert; "0" disables checks (dev only).
    homehub_ca: str = ""

    # --- http / internal ---
    public_url: str = ""  # how clients reach nginx, e.g. https://home.local
    dashboard_url: str = "http://dashboard:8000"
    app_urls: dict[str, str] = field(
        default_factory=lambda: {
            "calendar": "http://calendar:5002",
            "tapes": "http://music:5003",
            "library": "http://library:5001",
        }
    )
    # Sent as X-Internal-Auth with X-Forwarded-User when set (apps may require it).
    internal_secret: str = ""
    db_path: str = "/data/mcp.db"
    host: str = "0.0.0.0"
    port: int = 8100

    # Calendar times are naive local times; tool descriptions name this zone.
    timezone: str = "Europe/London"

    @classmethod
    def from_env(cls) -> Config:
        return cls(
            homehub_url=_env("HOMEHUB_URL").rstrip("/"),
            homehub_token=_env("HOMEHUB_TOKEN"),
            homehub_ca=_env("HOMEHUB_CA"),
            public_url=_env("MCP_PUBLIC_URL").rstrip("/"),
            dashboard_url=_env("DASHBOARD_URL", "http://dashboard:8000").rstrip("/"),
            app_urls={
                "calendar": _env("CALENDAR_URL", "http://calendar:5002").rstrip("/"),
                "tapes": _env("TAPES_URL", "http://music:5003").rstrip("/"),
                "library": _env("LIBRARY_URL", "http://library:5001").rstrip("/"),
            },
            internal_secret=_env("INTERNAL_AUTH_SECRET"),
            db_path=_env("MCP_DB", "/data/mcp.db"),
            host=_env("MCP_HOST", "0.0.0.0"),
            port=int(_env("MCP_PORT", "8100")),
            timezone=_env("TZ", "Europe/London") or "Europe/London",
        )
