"""Service discovery from Docker labels.

The home stack's compose file is the single source of truth: a container opts
into the hub with ``homehub.enable=true`` and carries its tile metadata as
labels. No DB, no registration step — adding a service means adding labels
where you already define the container.

Recognized labels (all under the ``homehub.`` prefix):
  enable       "true"/"1"/"yes" — opt in (required)
  route        nginx path to link the tile to, e.g. "/library/" (required)
  name         display name (defaults to the container name)
  icon         icon key, e.g. book or calendar (optional; UI picks by slug or monogram).
               Apps added in the Deploy tab bring their own SVG instead (icon_url).
  description  one-line blurb (optional)
  accent       the icon's colour as #rrggbb (optional; otherwise picked from the name)
"""

import os
import pathlib
import re
from typing import Any, Dict, List

from app.docker_control import list_service_candidates

LABEL_PREFIX = "homehub."

_TRUTHY = {"1", "true", "yes", "on"}

# Icons of apps added in the Deploy tab, copied out of their repos on the Pi.
ICON_DIR = pathlib.Path(os.environ.get("DEPLOY_STATE_DIR", "/deploy")) / "generated" / "icons"
_SLUG = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def app_icon_path(slug: str) -> pathlib.Path | None:
    path = ICON_DIR / f"{slug}.svg"
    return path if _SLUG.match(slug) and path.is_file() else None


class DockerUnavailable(Exception):
    """The daemon couldn't be reached. ``last_known`` is the most recent
    successful listing (states marked unknown), so the hub can still link to
    the apps."""

    def __init__(self, last_known: List[Dict[str, Any]]):
        super().__init__("can't reach Docker")
        self.last_known = last_known


_last_known: List[Dict[str, Any]] = []


def _label(labels: Dict[str, str], key: str) -> str | None:
    v = labels.get(f"{LABEL_PREFIX}{key}")
    v = v.strip() if isinstance(v, str) else v
    return v or None


def list_services() -> List[Dict[str, Any]]:
    """Discovered, hub-enabled services sorted by display name.

    Raises ``DockerUnavailable`` (carrying the last good listing) when the
    daemon can't be reached, so the hub can say so instead of "no services".
    """
    global _last_known
    try:
        candidates = list_service_candidates()
    except Exception:
        raise DockerUnavailable(
            [{**s, "state": "unknown", "since": None} for s in _last_known]
        )

    out: List[Dict[str, Any]] = []
    for c in candidates:
        labels = c.get("labels") or {}
        enabled = (labels.get(f"{LABEL_PREFIX}enable") or "").strip().lower()
        if enabled not in _TRUTHY:
            continue
        route = _label(labels, "route")
        if not route:
            continue  # nothing to link the tile to
        out.append(
            {
                "slug": c["name"],
                "display_name": _label(labels, "name") or c["name"],
                "route_prefix": route,
                "icon": _label(labels, "icon"),
                "icon_url": f"/services/{c['name']}/icon.svg" if app_icon_path(c["name"]) else None,
                "description": _label(labels, "description"),
                "accent": a if (a := _label(labels, "accent")) and _HEX.match(a) else None,
                "container_name": c["name"],
                "status": "running" if c.get("status") == "running" else "stopped",
                # up / degraded (running but unhealthy) / down — see container_state.
                "health": c.get("health"),
                "state": c.get("state") or ("up" if c.get("status") == "running" else "down"),
                "since": c.get("started_at") if c.get("status") == "running" else c.get("finished_at"),
            }
        )
    out.sort(key=lambda s: s["display_name"].lower())
    _last_known = out
    return out
