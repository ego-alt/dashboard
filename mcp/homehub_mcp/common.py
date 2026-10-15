"""Bits every tool module shares: who is calling, annotations, small formatters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.types import ToolAnnotations

from .backend import AppError, Backend
from .config import Config


@dataclass
class Deps:
    backend: Backend
    config: Config


def current_user() -> str | None:
    """The dashboard username behind this call (http mode). In stdio mode
    there's no per-call identity; the backend's token speaks for the user."""
    token = get_access_token()
    return token.subject if token else None


READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)
WRITE = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False
)
IDEMPOTENT = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)
DESTRUCTIVE = ToolAnnotations(
    read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=False
)
# Reaches the wider internet (fetches a link the caller gave).
FETCH = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True
)


def parse_date(value: str, field: str) -> date:
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except (ValueError, AttributeError):
        raise AppError(f"{field} must be a date like 2026-03-14 (YYYY-MM-DD).") from None


def parse_time(value: str, field: str) -> str:
    try:
        return datetime.strptime(value.strip(), "%H:%M").strftime("%H:%M")
    except (ValueError, AttributeError):
        raise AppError(f"{field} must be a 24-hour time like 19:30 (HH:MM).") from None


def duration(seconds: float | int | None) -> str:
    s = int(seconds or 0)
    if s <= 0:
        return "?"
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def capped(lines: list[str], limit: int, hint: str) -> str:
    """Join ``lines``; past ``limit`` show the first ones and say how to narrow."""
    if len(lines) <= limit:
        return "\n".join(lines)
    return "\n".join(lines[:limit] + [f"… {len(lines) - limit} more. {hint}"])
