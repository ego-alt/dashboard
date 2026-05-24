"""WebAuthn / passkey support: registration + assertion challenge plumbing.

Wraps ``py_webauthn`` with the small amount of state we need on top — an
in-memory challenge cache (TTL'd) so that /begin and /finish can prove the
client really echoed the random value we issued.

The cache is a single dict; it's process-local, which is fine while the
dashboard runs as a single uvicorn process. If we ever scale to multiple
workers, swap it for a small SQLite table.
"""

import os
import secrets
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

CHALLENGE_TTL = timedelta(minutes=5)

# Relying Party config. Override via env in production.
RP_ID = os.environ.get("WEBAUTHN_RP_ID", "localhost")
RP_NAME = os.environ.get("WEBAUTHN_RP_NAME", "Home Dashboard")
RP_ORIGIN = os.environ.get("WEBAUTHN_ORIGIN", "http://localhost:8000")


class _ChallengeCache:
    """Process-local TTL store. Threadsafe so uvicorn's threads don't race."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[bytes, datetime, Optional[int]]] = {}
        self._lock = threading.Lock()

    def issue(self, challenge: bytes, *, user_id: Optional[int] = None) -> str:
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + CHALLENGE_TTL
        with self._lock:
            self._data[token] = (challenge, expires_at, user_id)
            self._purge_expired_locked()
        return token

    def consume(self, token: str) -> Optional[tuple[bytes, Optional[int]]]:
        with self._lock:
            entry = self._data.pop(token, None)
        if entry is None:
            return None
        challenge, expires_at, user_id = entry
        if datetime.now(timezone.utc) > expires_at:
            return None
        return challenge, user_id

    def _purge_expired_locked(self) -> None:
        now = datetime.now(timezone.utc)
        for k, (_, exp, _) in list(self._data.items()):
            if exp <= now:
                del self._data[k]

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


challenges = _ChallengeCache()
