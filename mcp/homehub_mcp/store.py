"""SQLite persistence for OAuth (clients, consents, codes, tokens) and the
tool-call audit log. One small file, ``MCP_DB``. Tokens and codes are stored
as SHA-256 hashes only, the same as the dashboard's API tokens."""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS clients (
    client_id TEXT PRIMARY KEY, info TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS pending (
    req_id TEXT PRIMARY KEY, client_id TEXT NOT NULL, params TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS grants (
    grant_id TEXT PRIMARY KEY, client_id TEXT NOT NULL, client_name TEXT NOT NULL,
    username TEXT NOT NULL, created_at REAL NOT NULL, last_used_at REAL
);
CREATE TABLE IF NOT EXISTS codes (
    code_hash TEXT PRIMARY KEY, grant_id TEXT NOT NULL, client_id TEXT NOT NULL,
    username TEXT NOT NULL, params TEXT NOT NULL, expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS tokens (
    token_hash TEXT PRIMARY KEY, kind TEXT NOT NULL, grant_id TEXT NOT NULL,
    client_id TEXT NOT NULL, username TEXT NOT NULL, scopes TEXT NOT NULL,
    resource TEXT, expires_at REAL
);
CREATE INDEX IF NOT EXISTS tokens_grant ON tokens (grant_id);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL, username TEXT,
    client TEXT, tool TEXT NOT NULL, args TEXT NOT NULL, ok INTEGER NOT NULL,
    error TEXT
);
CREATE INDEX IF NOT EXISTS audit_user_at ON audit (username, at);
"""

AUDIT_KEEP_DAYS = 90
CLIENT_KEEP_DAYS = 7


def digest(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class Store:
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(SCHEMA)

    # --- low level ---

    def execute(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._db.execute(sql, args)

    def one(self, sql: str, args: tuple = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._db.execute(sql, args).fetchone()

    def all(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    # --- meta ---

    def secret(self, key: str) -> str:
        """A random value created on first use and kept (e.g. the CSRF key)."""
        row = self.one("SELECT value FROM meta WHERE key = ?", (key,))
        if row:
            return row["value"]
        value = secrets.token_urlsafe(32)
        self.execute("INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)", (key, value))
        return self.one("SELECT value FROM meta WHERE key = ?", (key,))["value"]

    # --- audit ---

    def audit(self, *, username: str | None, client: str | None, tool: str,
              args: dict[str, Any], ok: bool, error: str | None) -> None:
        self.execute(
            "INSERT INTO audit (at, username, client, tool, args, ok, error) VALUES (?,?,?,?,?,?,?)",
            (time.time(), username, client, tool, json.dumps(_trim(args)), int(ok), error),
        )

    def recent_audit(self, username: str, limit: int = 100) -> list[sqlite3.Row]:
        return self.all(
            "SELECT * FROM audit WHERE username = ? ORDER BY at DESC LIMIT ?", (username, limit)
        )

    def prune(self) -> None:
        now = time.time()
        self.execute("DELETE FROM audit WHERE at < ?", (now - AUDIT_KEEP_DAYS * 86400,))
        self.execute("DELETE FROM codes WHERE expires_at < ?", (now,))
        self.execute("DELETE FROM pending WHERE created_at < ?", (now - 3600,))
        self.execute(
            "DELETE FROM tokens WHERE expires_at IS NOT NULL AND expires_at < ?", (now,)
        )
        # Registrations that never led to a consent (abandoned, or noise).
        self.execute(
            "DELETE FROM clients WHERE created_at < ? AND client_id NOT IN "
            "(SELECT client_id FROM grants)",
            (now - CLIENT_KEEP_DAYS * 86400,),
        )


def _trim(value: Any, limit: int = 200) -> Any:
    """Keep audit rows small and avoid storing whole diary notes."""
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + "…"
    if isinstance(value, dict):
        return {k: _trim(v, limit) for k, v in value.items()}
    if isinstance(value, list):
        return [_trim(v, limit) for v in value[:50]]
    return value
