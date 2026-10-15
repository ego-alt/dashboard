"""HTTP calls from the tools to the three apps.

Two transports behind one interface:

- ``InternalBackend``: straight to each app on the compose network, as the
  user, with ``X-Forwarded-User``. This is the same trust nginx's
  ``auth_request`` hands the apps. Used by the ``mcp`` container.
- ``ExternalBackend``: through the public nginx with the user's own
  ``Authorization: Bearer`` API token, which ``/auth/verify`` already accepts.
  Used for stdio on a laptop, where the compose network isn't reachable.

Either way, an app's own error message ("The end is before the start.")
reaches the model unchanged, so it can correct itself.
"""

from __future__ import annotations

from typing import Any

import httpx

from mcp.server.mcpserver.exceptions import ToolError

from .config import Config

APPS = ("calendar", "tapes", "library")

# Where nginx mounts each app on the public host.
PUBLIC_PREFIX = {"calendar": "/calendar", "tapes": "/music", "library": "/library"}

TIMEOUT = httpx.Timeout(30.0, connect=5.0)


class AppError(ToolError):
    """An app refused or failed a request; the message is fit for the model."""


def _error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        for key in ("message", "error", "detail"):
            text = body.get(key)
            # Flask's stock abort() text names a URL, which means nothing to a model.
            if isinstance(text, str) and text and not text.startswith("The requested URL"):
                return text
    if response.status_code == 404:
        return "Not found."
    if response.status_code == 403:
        return "You don't have permission to do that."
    return f"The app answered {response.status_code}."


class Backend:
    """Base: subclasses supply the base URL and auth headers."""

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None, verify: Any = True):
        self._client = httpx.AsyncClient(
            timeout=TIMEOUT, follow_redirects=False, transport=transport, verify=verify
        )

    def _base(self, app: str) -> str:
        raise NotImplementedError

    def _headers(self, user: str | None) -> dict[str, str]:
        raise NotImplementedError

    async def request(
        self,
        app: str,
        method: str,
        path: str,
        *,
        user: str | None,
        json: Any = None,
        params: dict[str, Any] | None = None,
        with_headers: bool = False,
    ) -> Any:
        """Call ``app`` and return its decoded JSON (or None for an empty body),
        or ``(json, headers)`` with ``with_headers``. Raises AppError with a
        readable message on any failure."""
        if app not in APPS:
            raise ValueError(f"unknown app {app!r}")
        if params:
            params = {k: v for k, v in params.items() if v is not None}
        try:
            response = await self._client.request(
                method,
                self._base(app) + path,
                json=json,
                params=params,
                headers=self._headers(user),
            )
        except httpx.HTTPError as e:
            raise AppError(f"Couldn't reach {app} ({type(e).__name__}). Is it running?") from e

        if response.is_redirect or response.status_code == 401:
            # nginx turns a failed auth_request into a 302 to /login.
            raise AppError(
                f"{app} didn't accept these credentials. The access token may have been revoked."
            )
        if response.is_error:
            raise AppError(_error_message(response))
        body = None
        if response.content:
            try:
                body = response.json()
            except ValueError:
                raise AppError(f"{app} sent back something that isn't JSON.") from None
        return (body, response.headers) if with_headers else body

    async def aclose(self) -> None:
        await self._client.aclose()


class InternalBackend(Backend):
    def __init__(self, config: Config, **kwargs: Any):
        super().__init__(**kwargs)
        self._urls = config.app_urls
        self._secret = config.internal_secret

    def _base(self, app: str) -> str:
        return self._urls[app]

    def _headers(self, user: str | None) -> dict[str, str]:
        if not user:
            # Never call an app anonymously: in proxy mode that would be refused
            # anyway, and in standalone mode it could act as the local user.
            raise AppError("Not signed in.")
        headers = {"X-Forwarded-User": user, "Accept": "application/json"}
        if self._secret:
            headers["X-Internal-Auth"] = self._secret
        return headers


class ExternalBackend(Backend):
    def __init__(self, config: Config, **kwargs: Any):
        verify: Any = True
        if config.homehub_ca == "0":
            verify = False
        elif config.homehub_ca:
            verify = config.homehub_ca
        kwargs.setdefault("verify", verify)
        super().__init__(**kwargs)
        if not config.homehub_url or not config.homehub_token:
            raise SystemExit(
                "stdio mode needs HOMEHUB_URL (e.g. https://home.local) and HOMEHUB_TOKEN "
                "(create one in the dashboard under API tokens)."
            )
        self._url = config.homehub_url
        self._token = config.homehub_token

    def _base(self, app: str) -> str:
        return self._url + PUBLIC_PREFIX[app]

    def _headers(self, user: str | None) -> dict[str, str]:
        # The token *is* the identity; ``user`` is ignored.
        return {"Authorization": f"Bearer {self._token}", "Accept": "application/json"}
