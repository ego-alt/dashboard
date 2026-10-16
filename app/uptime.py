"""Uptime history.

A background thread samples every container's state once a minute (up,
degraded or down; see ``docker_control.container_state``) and adds that minute
to the container's row for the current UTC hour in ``uptime_hours``. Hourly
rows keep it small: 30 days of six containers is ~4k rows. ``uptime_summary``
turns the rows into the strips the UI draws.
"""

import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import delete
from sqlalchemy.orm import Session as DbSession

from app.docker_control import list_service_candidates
from app.models import UptimeHour

log = logging.getLogger("dashboard.uptime")

SAMPLE_SECONDS = 60
RETAIN_DAYS = 90
STATES = ("up", "degraded", "down")


def _utc_naive(now: datetime) -> datetime:
    # SQLite hands back naive datetimes, so store naive UTC throughout.
    return now.astimezone(timezone.utc).replace(tzinfo=None) if now.tzinfo else now


def record_sample(db: DbSession, rows: List[Dict[str, Any]], now: datetime) -> None:
    """Count one minute for each container (``rows`` as from
    ``list_service_candidates``)."""
    hour = _utc_naive(now).replace(minute=0, second=0, microsecond=0)
    for r in rows:
        state = r.get("state")
        if state not in STATES:
            continue
        row = db.get(UptimeHour, (r["name"], hour))
        if row is None:
            row = UptimeHour(name=r["name"], hour=hour, up=0, degraded=0, down=0)
            db.add(row)
        setattr(row, state, getattr(row, state) + 1)
    db.commit()


def prune(db: DbSession, now: datetime) -> None:
    cutoff = _utc_naive(now) - timedelta(days=RETAIN_DAYS)
    db.execute(delete(UptimeHour).where(UptimeHour.hour < cutoff))
    db.commit()


def uptime_summary(
    db: DbSession, *, days: int, tz_offset_min: int = 0, now: Optional[datetime] = None
) -> Dict[str, Any]:
    """Per container: uptime % over the window and one bucket per hour
    (``days == 1``, the last 24 hours) or per local day (otherwise, the last
    ``days`` days including today). A bucket is ``[up, degraded, down]``
    minutes, or None when nothing was sampled.

    ``tz_offset_min`` is the viewer's offset from UTC in minutes (east
    positive), so days break at the viewer's midnight.
    """
    now = _utc_naive(now or datetime.now(timezone.utc))
    offset = timedelta(minutes=tz_offset_min)
    if days <= 1:
        size = timedelta(hours=1)
        end = now.replace(minute=0, second=0, microsecond=0) + size
        count = 24
    else:
        size = timedelta(days=1)
        local_midnight = (now + offset).replace(hour=0, minute=0, second=0, microsecond=0)
        end = local_midnight - offset + size
        count = days
    start = end - size * count

    out: Dict[str, Dict[str, Any]] = {}
    rows = db.query(UptimeHour).filter(UptimeHour.hour >= start, UptimeHour.hour < end)
    for r in rows:
        entry = out.setdefault(r.name, {"buckets": [None] * count})
        i = int((r.hour - start) / size)
        b = entry["buckets"][i] or [0, 0, 0]
        entry["buckets"][i] = [b[0] + r.up, b[1] + r.degraded, b[2] + r.down]
    for entry in out.values():
        totals = [sum(b[k] for b in entry["buckets"] if b) for k in range(3)]
        sampled = sum(totals)
        entry["pct"] = round(100 * totals[0] / sampled, 2) if sampled else None
    return {
        "start": start.replace(tzinfo=timezone.utc).isoformat(),
        "bucket": "hour" if days <= 1 else "day",
        "services": out,
    }


def _sample_once(session_factory, now: datetime) -> None:
    db = session_factory()
    try:
        record_sample(db, list_service_candidates(), now)
        if now.minute == 0:
            prune(db, now)
    finally:
        db.close()


def start_sampler(session_factory) -> threading.Event:
    """Sample now and then every minute in a daemon thread. Set the returned
    event to stop it. Docker being unreachable records nothing (a gap)."""
    stop = threading.Event()

    def loop():
        while True:
            try:
                _sample_once(session_factory, datetime.now(timezone.utc))
            except Exception as e:  # noqa: BLE001 — never kill the loop
                log.warning("uptime sample failed: %s", e)
            if stop.wait(SAMPLE_SECONDS):
                return

    threading.Thread(target=loop, name="uptime-sampler", daemon=True).start()
    return stop
