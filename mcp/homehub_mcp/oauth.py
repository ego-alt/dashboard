"""OAuth 2.1 for remote MCP clients, with the dashboard as the identity source.

The SDK serves the protocol endpoints (metadata, /register, /authorize,
/token, /revoke) and checks PKCE, redirect URIs and client secrets. This module
supplies storage and the human step:

1. ``/authorize`` parks the request and sends the browser to ``/oauth/consent``.
2. The consent page asks the dashboard who the browser is signed in as. It
   forwards the session cookie to ``/auth/verify``, and sends the user to the
   dashboard login (with TOTP or a passkey) if needed. Then it shows
   "Allow <client> to use your calendar, music and library?".
3. Approving mints a single-use code bound to that user. The client swaps it at
   ``/token`` for a 1-hour access token and a rotating 30-day refresh token.

Bearer tokens on /mcp are either these access tokens or a dashboard API token
(a personal access token, for clients that only take a static header). Those
are checked against the dashboard's own ``/auth/verify``.

``/oauth/connections`` lists the user's connected clients and what they did,
with a Revoke button.
"""

from __future__ import annotations

import hmac
import html
import json
import secrets
import time
from datetime import datetime
from urllib.parse import quote, urlparse

import httpx
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    RefreshToken,
    RegistrationError,
    TokenError,
    construct_redirect_uri,
)
from mcp.server.mcpserver import MCPServer
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from .config import Config
from .store import Store, digest

SCOPE = "homehub"
ACCESS_TTL = 3600
REFRESH_TTL = 30 * 86400
CODE_TTL = 300
PENDING_TTL = 900
PAT_CACHE_TTL = 60  # a revoked dashboard API token stops working within this
LOOPBACK = {"localhost", "127.0.0.1", "[::1]", "::1"}


class HomeOAuthProvider:
    """OAuthAuthorizationServerProvider backed by ``Store``."""

    def __init__(self, store: Store, config: Config, http: httpx.AsyncClient):
        self.store = store
        self.config = config
        self.http = http
        self._pat_cache: dict[str, tuple[float, str | None]] = {}

    # ---- clients (dynamic registration) ----

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        row = self.store.one("SELECT info FROM clients WHERE client_id = ?", (client_id,))
        return OAuthClientInformationFull.model_validate_json(row["info"]) if row else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        self.store.prune()  # registrations are rare; a good moment to tidy
        for uri in client_info.redirect_uris or []:
            parsed = urlparse(str(uri))
            # Plain http only to the user's own machine; https or an app's
            # custom scheme (cursor://, vscode://…) otherwise.
            if parsed.scheme == "http" and parsed.hostname not in LOOPBACK:
                raise RegistrationError(
                    error="invalid_redirect_uri",
                    error_description="http redirect URIs must point at localhost",
                )
            if parsed.scheme in ("javascript", "data", "file"):
                raise RegistrationError(error="invalid_redirect_uri")
        self.store.execute(
            "INSERT OR REPLACE INTO clients (client_id, info, created_at) VALUES (?, ?, ?)",
            (client_info.client_id, client_info.model_dump_json(), time.time()),
        )

    # ---- authorize → consent ----

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        req_id = secrets.token_urlsafe(24)
        self.store.execute(
            "INSERT INTO pending (req_id, client_id, params, created_at) VALUES (?, ?, ?, ?)",
            (req_id, client.client_id, params.model_dump_json(), time.time()),
        )
        return f"{self.config.public_url}/oauth/consent?req={req_id}"

    def pending(self, req_id: str) -> tuple[OAuthClientInformationFull, AuthorizationParams] | None:
        row = self.store.one(
            "SELECT * FROM pending WHERE req_id = ? AND created_at > ?",
            (req_id, time.time() - PENDING_TTL),
        )
        if not row:
            return None
        info = self.store.one("SELECT info FROM clients WHERE client_id = ?", (row["client_id"],))
        if not info:
            return None
        return (
            OAuthClientInformationFull.model_validate_json(info["info"]),
            AuthorizationParams.model_validate_json(row["params"]),
        )

    def approve(self, req_id: str, username: str) -> str:
        """Turn a parked request into a code for ``username``; returns the
        client redirect URL."""
        found = self.pending(req_id)
        if not found:
            raise LookupError("expired")
        client, params = found
        self.store.execute("DELETE FROM pending WHERE req_id = ?", (req_id,))
        grant_id = secrets.token_urlsafe(16)
        self.store.execute(
            "INSERT INTO grants (grant_id, client_id, client_name, username, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (grant_id, client.client_id, client_label(client), username, time.time()),
        )
        code = secrets.token_urlsafe(32)
        self.store.execute(
            "INSERT INTO codes (code_hash, grant_id, client_id, username, params, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (digest(code), grant_id, client.client_id, username, params.model_dump_json(),
             time.time() + CODE_TTL),
        )
        return construct_redirect_uri(str(params.redirect_uri), code=code, state=params.state)

    def deny(self, req_id: str) -> str | None:
        found = self.pending(req_id)
        self.store.execute("DELETE FROM pending WHERE req_id = ?", (req_id,))
        if not found:
            return None
        _, params = found
        return construct_redirect_uri(
            str(params.redirect_uri), error="access_denied", state=params.state
        )

    # ---- codes ----

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        row = self.store.one(
            "SELECT * FROM codes WHERE code_hash = ? AND client_id = ? AND expires_at > ?",
            (digest(authorization_code), client.client_id, time.time()),
        )
        if not row:
            return None
        p = AuthorizationParams.model_validate_json(row["params"])
        return AuthorizationCode(
            code=authorization_code,
            scopes=p.scopes or [SCOPE],
            expires_at=row["expires_at"],
            client_id=client.client_id,
            code_challenge=p.code_challenge,
            redirect_uri=p.redirect_uri,
            redirect_uri_provided_explicitly=p.redirect_uri_provided_explicitly,
            resource=p.resource,
            subject=row["username"],
        )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        row = self.store.one(
            "SELECT grant_id FROM codes WHERE code_hash = ?", (digest(authorization_code.code),)
        )
        self.store.execute(  # single use
            "DELETE FROM codes WHERE code_hash = ?", (digest(authorization_code.code),)
        )
        if not row:
            raise TokenError(error="invalid_grant", error_description="code already used")
        return self._issue(
            row["grant_id"], client.client_id, authorization_code.subject or "",
            authorization_code.scopes, authorization_code.resource,
        )

    # ---- tokens ----

    def _issue(self, grant_id: str, client_id: str, username: str, scopes: list[str],
               resource: str | None) -> OAuthToken:
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        now = time.time()
        for raw, kind, ttl in ((access, "access", ACCESS_TTL), (refresh, "refresh", REFRESH_TTL)):
            self.store.execute(
                "INSERT INTO tokens (token_hash, kind, grant_id, client_id, username, scopes, "
                "resource, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (digest(raw), kind, grant_id, client_id, username, " ".join(scopes), resource,
                 now + ttl),
            )
        return OAuthToken(
            access_token=access, token_type="Bearer", expires_in=ACCESS_TTL,
            refresh_token=refresh, scope=" ".join(scopes),
        )

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        row = self.store.one(
            "SELECT * FROM tokens WHERE token_hash = ? AND kind = 'refresh' AND client_id = ? "
            "AND expires_at > ?",
            (digest(refresh_token), client.client_id, time.time()),
        )
        if not row:
            return None
        return RefreshToken(
            token=refresh_token, client_id=row["client_id"], scopes=row["scopes"].split(),
            expires_at=int(row["expires_at"]), resource=row["resource"], subject=row["username"],
        )

    async def exchange_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]
    ) -> OAuthToken:
        row = self.store.one(
            "SELECT grant_id FROM tokens WHERE token_hash = ?", (digest(refresh_token.token),)
        )
        # Rotate: the old refresh token and the grant's live access tokens go.
        self.store.execute(
            "DELETE FROM tokens WHERE grant_id = ?", (row["grant_id"],)
        )
        return self._issue(
            row["grant_id"], client.client_id, refresh_token.subject or "",
            scopes or refresh_token.scopes, refresh_token.resource,
        )

    async def load_access_token(self, token: str) -> AccessToken | None:
        row = self.store.one(
            "SELECT t.*, g.last_used_at FROM tokens t JOIN grants g ON g.grant_id = t.grant_id "
            "WHERE t.token_hash = ? AND t.kind = 'access' AND t.expires_at > ?",
            (digest(token), time.time()),
        )
        if row:
            if not row["last_used_at"] or row["last_used_at"] < time.time() - 60:
                self.store.execute(
                    "UPDATE grants SET last_used_at = ? WHERE grant_id = ?",
                    (time.time(), row["grant_id"]),
                )
            return AccessToken(
                token=token, client_id=row["client_id"], scopes=row["scopes"].split(),
                expires_at=int(row["expires_at"]), resource=row["resource"],
                subject=row["username"], claims={"grant": row["grant_id"]},
            )
        username = await self._dashboard_token_user(token)
        if username:
            return AccessToken(token=token, client_id="api-token", scopes=[SCOPE], subject=username)
        return None

    async def _dashboard_token_user(self, token: str) -> str | None:
        """A dashboard API token → its username, via the dashboard itself."""
        key = digest(token)
        hit = self._pat_cache.get(key)
        if hit and hit[0] > time.time():
            return hit[1]
        try:
            res = await self.http.get(
                f"{self.config.dashboard_url}/auth/verify",
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.HTTPError:
            return None  # dashboard down: refuse, and don't cache
        user = res.headers.get("x-user") if res.status_code == 200 else None
        self._pat_cache[key] = (time.time() + (PAT_CACHE_TTL if user else 5), user)
        if len(self._pat_cache) > 1000:
            self._pat_cache.clear()
        return user

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        row = self.store.one("SELECT grant_id FROM tokens WHERE token_hash = ?", (digest(token.token),))
        if row:
            self.store.execute("DELETE FROM tokens WHERE grant_id = ?", (row["grant_id"],))

    def revoke_grant(self, grant_id: str, username: str) -> None:
        self.store.execute(
            "DELETE FROM tokens WHERE grant_id IN "
            "(SELECT grant_id FROM grants WHERE grant_id = ? AND username = ?)",
            (grant_id, username),
        )
        self.store.execute(
            "DELETE FROM grants WHERE grant_id = ? AND username = ?", (grant_id, username)
        )


def client_label(client: OAuthClientInformationFull) -> str:
    name = (client.client_name or "").strip()
    if not name and client.redirect_uris:
        name = urlparse(str(client.redirect_uris[0])).hostname or ""
    return (name or "An unnamed app")[:80]


# ---------------------------------------------------------------------------
# Browser pages: consent + connections. Served by this container under /oauth/.
# ---------------------------------------------------------------------------

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>{title}</title>
<style>
:root {{ --bg:#f5f5f4; --card:#fff; --ink:#1c1917; --muted:#78716c; --line:#e7e5e4;
        --accent:#1c1917; --accent-ink:#fff; --bad:#b91c1c; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg:#0c0a09; --card:#1c1917; --ink:#f5f5f4; --muted:#a8a29e; --line:#292524;
          --accent:#f5f5f4; --accent-ink:#1c1917; --bad:#f87171; }} }}
* {{ box-sizing:border-box }}
body {{ margin:0; background:var(--bg); color:var(--ink);
       font:15px/1.5 Inter, system-ui, -apple-system, sans-serif; }}
main {{ max-width:560px; margin:8vh auto; padding:0 16px }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:24px }}
h1 {{ font-size:20px; margin:0 0 8px }}
p, li {{ color:var(--muted) }}
strong {{ color:var(--ink) }}
.row {{ display:flex; gap:8px; margin-top:20px; flex-wrap:wrap }}
button {{ font:inherit; padding:9px 16px; border-radius:8px; border:1px solid var(--line);
         background:transparent; color:var(--ink); cursor:pointer }}
button.primary {{ background:var(--accent); color:var(--accent-ink); border-color:var(--accent) }}
button.danger {{ color:var(--bad) }}
table {{ width:100%; border-collapse:collapse; font-size:13px }}
td, th {{ text-align:left; padding:6px 4px; border-top:1px solid var(--line); vertical-align:top }}
code {{ font:12px ui-monospace, Menlo, monospace }}
.bad {{ color:var(--bad) }}
section + section {{ margin-top:24px }}
</style></head><body><main>{body}</main></body></html>"""


def page(title: str, body: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(
        PAGE.format(title=html.escape(title), body=body),
        status_code=status,
        headers={
            "Cache-Control": "no-store",
            "X-Frame-Options": "DENY",  # no clickjacking the Allow button
            # No form-action: Chrome applies it to the redirect after Allow, which
            # may go to an app's own scheme (cursor://…).
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; "
                                       "frame-ancestors 'none'",
        },
    )


def register_pages(server: MCPServer, provider: HomeOAuthProvider) -> None:
    store = provider.store
    config = provider.config
    csrf_key = store.secret("csrf").encode()

    def csrf(purpose: str, username: str) -> str:
        return hmac.new(csrf_key, f"{purpose}:{username}".encode(), "sha256").hexdigest()

    async def signed_in_user(request: Request) -> str | None:
        cookie = request.headers.get("cookie")
        if not cookie:
            return None
        try:
            res = await provider.http.get(
                f"{config.dashboard_url}/auth/verify", headers={"Cookie": cookie}
            )
        except httpx.HTTPError:
            return None
        return res.headers.get("x-user") if res.status_code == 200 else None

    def to_login(request: Request) -> Response:
        here = request.url.path + ("?" + request.url.query if request.url.query else "")
        return RedirectResponse(f"/login?next={quote(here, safe='')}", status_code=303)

    def bounce(request: Request) -> Response:
        """Arriving from another site, the browser holds back the dashboard's
        SameSite=strict session cookie. One same-site reload brings it."""
        sep = "&" if request.url.query else "?"
        target = html.escape(request.url.path + "?" + request.url.query + sep + "b=1")
        return page("Continue", f'<meta http-equiv="refresh" content="0;url={target}">'
                    f'<p><a href="{target}">Continue</a></p>')

    @server.custom_route("/oauth/consent", methods=["GET"])
    async def consent_page(request: Request) -> Response:
        req_id = request.query_params.get("req", "")
        found = provider.pending(req_id)
        if not found:
            return page("Link expired", "<div class=card><h1>This link has expired</h1>"
                        "<p>Start connecting again from the app.</p></div>", 400)
        user = await signed_in_user(request)
        if not user:
            if not request.query_params.get("b"):
                return bounce(request)
            return to_login(request)
        client, params = found
        redirect_host = urlparse(str(params.redirect_uri)).netloc or str(params.redirect_uri)
        name = html.escape(client_label(client))
        body = f"""<div class=card>
<h1>Allow {name} to use your home apps?</h1>
<p>Signed in as <strong>{html.escape(user)}</strong>. {name} will be able to read and change
your <strong>calendar</strong> (entries and moods), <strong>music</strong> (downloads,
playlists, podcasts) and <strong>library</strong> (books, tags, reading status), including
deleting things. Your diary notes will be visible to it and to the AI model it uses.</p>
<p>You can disconnect it any time at <a href="/oauth/connections">/oauth/connections</a>.
After you choose, you'll be returned to <code>{html.escape(redirect_host)}</code>.</p>
<form method=post action="/oauth/consent" class=row>
<input type=hidden name=req value="{html.escape(req_id)}">
<input type=hidden name=csrf value="{csrf('consent:' + req_id, user)}">
<button class=primary name=decision value=allow>Allow</button>
<button name=decision value=deny>Cancel</button>
</form></div>"""
        return page(f"Allow {client_label(client)}", body)

    @server.custom_route("/oauth/consent", methods=["POST"])
    async def consent_submit(request: Request) -> Response:
        form = await request.form()
        req_id = str(form.get("req", ""))
        user = await signed_in_user(request)
        if not user:
            return to_login(request)
        if not hmac.compare_digest(str(form.get("csrf", "")), csrf("consent:" + req_id, user)):
            return page("Try again", "<div class=card><h1>That didn't work</h1>"
                        "<p>Reload the page and try again.</p></div>", 403)
        if form.get("decision") == "allow":
            try:
                target = provider.approve(req_id, user)
            except LookupError:
                return page("Link expired", "<div class=card><h1>This link has expired</h1>"
                            "<p>Start connecting again from the app.</p></div>", 400)
        else:
            target = provider.deny(req_id)
            if target is None:
                return page("Cancelled", "<div class=card><h1>Cancelled</h1></div>")
        return RedirectResponse(target, status_code=303)

    @server.custom_route("/oauth/connections", methods=["GET"])
    async def connections_page(request: Request) -> Response:
        user = await signed_in_user(request)
        if not user:
            return to_login(request)
        grants = store.all(
            "SELECT * FROM grants WHERE username = ? ORDER BY created_at DESC", (user,)
        )
        token = csrf("revoke", user)
        rows = "".join(
            f"<tr><td><strong>{html.escape(g['client_name'])}</strong></td>"
            f"<td>{_when(g['created_at'])}</td><td>{_when(g['last_used_at'])}</td>"
            f"<td><form method=post action='/oauth/connections/revoke'>"
            f"<input type=hidden name=grant value='{html.escape(g['grant_id'])}'>"
            f"<input type=hidden name=csrf value='{token}'>"
            f"<button class=danger>Disconnect</button></form></td></tr>"
            for g in grants
        ) or "<tr><td colspan=4>No apps connected.</td></tr>"
        audit = "".join(
            f"<tr><td>{_when(a['at'])}</td><td>{html.escape(a['client'] or '')}</td>"
            f"<td><code>{html.escape(a['tool'])}</code></td>"
            f"<td><code>{html.escape(_args(a['args']))}</code>"
            + (f"<div class=bad>{html.escape(a['error'] or 'failed')}</div>" if not a["ok"] else "")
            + "</td></tr>"
            for a in store.recent_audit(user)
        ) or "<tr><td colspan=4>Nothing yet.</td></tr>"
        body = f"""<div class=card><section><h1>Connected apps</h1>
<p>AI assistants that can use your calendar, music and library as
<strong>{html.escape(user)}</strong>. Dashboard API tokens are managed in Settings.</p>
<table><tr><th>App</th><th>Connected</th><th>Last used</th><th></th></tr>{rows}</table>
</section><section><h1>Recent activity</h1>
<table><tr><th>When</th><th>App</th><th>Tool</th><th>Arguments</th></tr>{audit}</table>
</section></div>"""
        return page("Connected apps", body)

    @server.custom_route("/oauth/connections/revoke", methods=["POST"])
    async def connections_revoke(request: Request) -> Response:
        user = await signed_in_user(request)
        if not user:
            return to_login(request)
        form = await request.form()
        if hmac.compare_digest(str(form.get("csrf", "")), csrf("revoke", user)):
            provider.revoke_grant(str(form.get("grant", "")), user)
        return RedirectResponse("/oauth/connections", status_code=303)


def _when(ts: float | None) -> str:
    return datetime.fromtimestamp(ts).strftime("%-d %b %Y %H:%M") if ts else "never"


def _args(raw: str) -> str:
    try:
        args = json.loads(raw)
    except ValueError:
        return raw
    return ", ".join(f"{k}={v!r}" for k, v in args.items() if v not in ("", [], None, 0))[:300]
