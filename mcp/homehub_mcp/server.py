"""Entry point: build the MCP server and run it over stdio or streamable HTTP.

    homehub-mcp            # stdio (desktop clients launch this)
    homehub-mcp --http     # the mcp container: /mcp + OAuth, behind nginx
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from starlette.responses import PlainTextResponse

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult

from .backend import Backend, ExternalBackend, InternalBackend
from .common import READ, Deps, current_user
from .config import Config
from .oauth import SCOPE, HomeOAuthProvider, register_pages
from .store import Store
from .tools import calendar, library, tapes

log = logging.getLogger("homehub_mcp")

INSTRUCTIONS = """\
Tools for one person's self-hosted home apps: a diary calendar (entries, moments, daily
mood), a music library called Tapes (downloads from links, playlists, podcasts) and an
EPUB library. Everything acts as the signed-in user, on their data only.
Conventions: dates are YYYY-MM-DD, times 24-hour HH:MM in the home's local time zone.
Call homehub_now when you need today's date. There are no delete tools: the user
deletes things in the apps themselves. Things they deleted can be restored for 30 days.
"""


class AuditMiddleware:
    """Record every tool call (who, which client, tool, trimmed arguments,
    success) for the /oauth/connections activity list."""

    def __init__(self, store: Store):
        self.store = store

    async def __call__(self, ctx: ServerRequestContext[Any, Any], call_next: CallNext) -> HandlerResult:
        if ctx.method != "tools/call" or not ctx.params:
            return await call_next(ctx)
        tool = str(ctx.params.get("name", "?"))
        args = ctx.params.get("arguments") or {}
        error = None
        ok = True
        try:
            result = await call_next(ctx)
        except Exception as e:
            ok, error = False, type(e).__name__
            raise
        else:
            match result:
                case CallToolResult(is_error=True) | {"isError": True}:
                    ok = False
                    error = _first_text(result)
                case _:
                    pass
            return result
        finally:
            try:
                self.store.audit(
                    username=current_user(), client=_client_name(self.store), tool=tool,
                    args=dict(args), ok=ok, error=error,
                )
            except Exception:  # never fail a call over the log
                log.exception("audit write failed")


def _first_text(result: Any) -> str | None:
    content = result.content if isinstance(result, CallToolResult) else result.get("content")
    for block in content or []:
        text = getattr(block, "text", None) or (block.get("text") if isinstance(block, dict) else None)
        if text:
            return text[:300]
    return None


def _client_name(store: Store) -> str | None:
    token = get_access_token()
    if token is None:
        return None
    if token.client_id == "api-token":
        return "API token"
    grant = (token.claims or {}).get("grant")
    row = store.one("SELECT client_name FROM grants WHERE grant_id = ?", (grant,)) if grant else None
    return row["client_name"] if row else token.client_id


def build_server(
    config: Config,
    backend: Backend,
    *,
    store: Store | None = None,
    http: httpx.AsyncClient | None = None,
) -> MCPServer:
    """The server with every tool. With ``store`` (http mode) it also serves
    OAuth, the consent/connections pages and the audit log."""
    kwargs: dict[str, Any] = {}
    provider = None
    if store is not None:
        if not config.public_url:
            raise SystemExit("http mode needs MCP_PUBLIC_URL (e.g. https://home.local)")
        provider = HomeOAuthProvider(store, config, http or httpx.AsyncClient(timeout=10))
        kwargs.update(
            auth_server_provider=provider,
            auth=AuthSettings(
                issuer_url=config.public_url,
                resource_server_url=f"{config.public_url}/mcp",
                # Tokens here are only ever minted for this server, and dashboard
                # API tokens carry no resource; the provider is the audience check.
                validate_token_resource=False,
                required_scopes=[SCOPE],
                client_registration_options=ClientRegistrationOptions(
                    enabled=True, valid_scopes=[SCOPE], default_scopes=[SCOPE]
                ),
                revocation_options=RevocationOptions(enabled=True),
            ),
            middleware=[AuditMiddleware(store)],
        )

    server = MCPServer(
        name="homehub",
        title="Home hub",
        instructions=INSTRUCTIONS,
        version="0.1.0",
        **kwargs,
    )
    deps = Deps(backend=backend, config=config)

    @server.tool(
        name="homehub_now",
        annotations=READ,
        description="The current local date, time, weekday and time zone at home.",
    )
    async def homehub_now() -> str:
        try:
            zone = ZoneInfo(config.timezone)
        except Exception:
            zone = None
        now = datetime.now(zone)
        return f"{now:%A %Y-%m-%d %H:%M} ({config.timezone})"

    calendar.register(server, deps)
    tapes.register(server, deps)
    library.register(server, deps)

    if provider is not None:
        register_pages(server, provider)

        @server.custom_route("/healthz", methods=["GET"])
        async def healthz(_request):
            return PlainTextResponse("ok")

    return server


def http_app(
    config: Config,
    store: Store | None = None,
    http: httpx.AsyncClient | None = None,
    backend: Backend | None = None,
):
    """The ASGI app for the container. Tests pass their own store, dashboard
    client and backend."""
    store = store or Store(config.db_path)
    store.prune()
    server = build_server(config, backend or InternalBackend(config), store=store, http=http)
    return server.streamable_http_app(
        streamable_http_path="/mcp",
        # No server-side sessions: survives container restarts and needs no
        # sticky routing. Plain JSON replies suit every client.
        stateless_http=True,
        json_response=True,
        # Every /mcp request needs a bearer token and no cookie is honoured
        # there, so DNS rebinding can't borrow ambient credentials; nginx in
        # front sets Host to the home's own name or LAN IP.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        host=config.host,
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="homehub-mcp", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--http", action="store_true", help="serve streamable HTTP (container mode)")
    args = parser.parse_args(argv)
    config = Config.from_env()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.http:
        import uvicorn

        uvicorn.run(http_app(config), host=config.host, port=config.port,
                    proxy_headers=True, forwarded_allow_ips="*")
    else:
        build_server(config, ExternalBackend(config)).run("stdio")


if __name__ == "__main__":
    main()
