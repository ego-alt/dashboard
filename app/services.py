"""Service-registry view: the ``Service`` table (human-facing metadata) married
to live Docker state. The table never stores status — that always comes from
the daemon, and the hub must still render if the daemon is unreachable.
"""

from typing import Any, Dict, List

from sqlalchemy.orm import Session as DbSession

from app.docker_control import get_containers
from app.models import Service


def list_services(db: DbSession) -> List[Dict[str, Any]]:
    rows = (
        db.query(Service)
        .filter(Service.is_enabled.is_(True))
        .order_by(Service.display_name)
        .all()
    )
    if not rows:
        return []

    try:
        by_name = {c["name"]: c for c in get_containers()}
        docker_ok = True
    except Exception:
        # Daemon down / socket missing — show tiles with unknown status rather
        # than 500 the whole hub.
        by_name = {}
        docker_ok = False

    out: List[Dict[str, Any]] = []
    for s in rows:
        if not docker_ok:
            status = "unknown"
        else:
            container = by_name.get(s.container_name)
            if container is None:
                status = "absent"
            elif container.get("status") == "running":
                status = "running"
            else:
                status = "stopped"
        out.append(
            {
                "slug": s.slug,
                "display_name": s.display_name,
                "route_prefix": s.route_prefix,
                "icon": s.icon,
                "description": s.description,
                "container_name": s.container_name,
                "status": status,
            }
        )
    return out
