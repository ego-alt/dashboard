from concurrent.futures import ThreadPoolExecutor
from functools import cache
from typing import Any, Dict, List

import docker

_STATS_FAN_OUT = 8
_MB = 1024 * 1024


@cache
def _get_client():
    # Lazy: a missing daemon at import time shouldn't crash the worker.
    return docker.from_env()


def _stats_for(container) -> Dict[str, Any]:
    """A single instantaneous stats read for an already-resolved Container.

    ``one_shot=True`` skips the daemon's ~1s CPU-sampling window (which is what
    made the Monitor page take seconds to load) — it returns raw cumulative
    counters with ``precpu_stats`` empty. The client diffs successive polls into
    a CPU% and network rate, so the per-container daemon work stays cheap enough
    to poll on an interval.
    """
    try:
        stats = container.stats(stream=False, one_shot=True)
        cpu = stats.get("cpu_stats") or {}
        cpu_usage = cpu.get("cpu_usage") or {}
        # online_cpus is sometimes absent; fall back to per-CPU array length.
        online_cpus = (
            cpu.get("online_cpus") or len(cpu_usage.get("percpu_usage") or []) or 1
        )

        # Sum every interface — the container's network device isn't always
        # "eth0" (Docker bridge networks often name it otherwise), so hardcoding
        # one interface silently reads zero on a Pi.
        networks = stats.get("networks") or {}
        network_rx = sum(n.get("rx_bytes", 0) for n in networks.values())
        network_tx = sum(n.get("tx_bytes", 0) for n in networks.values())

        # Memory: subtract reclaimable page cache so we report working-set, the
        # way `docker stats` does. cgroup v2 exposes "inactive_file"; v1 calls it
        # "total_inactive_file". Without this the Pi's page cache inflates usage.
        mem = stats.get("memory_stats") or {}
        mem_detail = mem.get("stats") or {}
        inactive = mem_detail.get(
            "inactive_file", mem_detail.get("total_inactive_file", 0)
        )
        mem_used = max(mem.get("usage", 0) - inactive, 0)
        mem_limit = mem.get("limit", 0)
        mem_percent = (mem_used / mem_limit * 100.0) if mem_limit else 0.0

        return {
            "status": "success",
            "stats": {
                # Raw cumulative CPU counters (nanoseconds) + core count; the
                # client computes CPU% from the delta between two polls.
                "cpu_total": cpu_usage.get("total_usage", 0),
                "system_cpu": cpu.get("system_cpu_usage", 0),
                "online_cpus": online_cpus,
                "mem_used_mb": round(mem_used / _MB, 1),
                "mem_limit_mb": round(mem_limit / _MB, 1),
                "mem_percent": round(mem_percent, 1),
                # Cumulative counters since container start; the client diffs
                # successive polls into a per-second rate.
                "network_rx_bytes": network_rx,
                "network_tx_bytes": network_tx,
            },
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def get_container_stats(container_id: str) -> Dict[str, Any]:
    try:
        container = _get_client().containers.get(container_id)
    except Exception as e:
        return {"status": "error", "message": str(e)}
    return _stats_for(container)


def resolve_container_name(id_or_name: str) -> str | None:
    """Canonical container name for an id-or-name, or None if unresolvable.

    Used by the protected-container guard so passing the long Docker id can't
    sneak past a name-based denylist.
    """
    try:
        return _get_client().containers.get(id_or_name).name
    except Exception:
        return None


def list_service_candidates() -> List[Dict[str, Any]]:
    """Lightweight (name, status, labels) for every container — no per-container
    stats. Backs label-based service discovery.
    """
    return [
        {"name": c.name, "status": c.status, "labels": c.labels or {}}
        for c in _get_client().containers.list(all=True)
    ]


def _metadata_row(container) -> Dict[str, Any]:
    """Fields from ``containers.list`` only — no extra inspect/image API calls."""
    attrs = container.attrs or {}
    return {
        "id": container.id,
        "short_id": container.short_id,
        "name": container.name,
        "status": container.status,
        "image": attrs.get("Image", ""),
        "ports": container.ports,
        "created": attrs.get("Created"),
        "command": attrs.get("Command"),
    }


def get_containers(*, include_stats: bool = False) -> List[Dict[str, Any]]:
    """List containers, optionally with a single instantaneous stats read.

    Stats use ``one_shot`` reads (see ``_stats_for``) so no per-container
    sampling block, but they're still an extra daemon round-trip each — fetched
    in parallel and only for running containers.
    """
    containers = _get_client().containers.list(all=True)
    if not containers:
        return []

    rows = [_metadata_row(c) for c in containers]
    if not include_stats:
        return rows

    running = [c for c in containers if c.status == "running"]
    if not running:
        return rows

    with ThreadPoolExecutor(max_workers=_STATS_FAN_OUT) as ex:
        stats_pairs = list(zip(running, ex.map(_stats_for, running)))

    stats_by_id = {c.id: r.get("stats") or {} for c, r in stats_pairs}
    for row in rows:
        if extra := stats_by_id.get(row["id"]):
            row.update(extra)
    return rows


def start_container(container_id: str) -> Dict[str, str]:
    try:
        container = _get_client().containers.get(container_id)
        container.start()
        return {"status": "success", "message": f"Container {container.name} started successfully"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def stop_container(container_id: str) -> Dict[str, str]:
    try:
        container = _get_client().containers.get(container_id)
        container.stop()
        return {"status": "success", "message": f"Container {container.name} stopped successfully"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def restart_container(container_id: str) -> Dict[str, str]:
    try:
        container = _get_client().containers.get(container_id)
        container.restart()
        return {"status": "success", "message": f"Container {container.name} restarted successfully"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def get_container_logs(container_id: str, tail: int = 100) -> Dict[str, Any]:
    try:
        container = _get_client().containers.get(container_id)
        logs = container.logs(tail=tail, timestamps=True).decode("utf-8")
        return {"status": "success", "logs": logs}
    except Exception as e:
        return {"status": "error", "message": str(e)}
