from concurrent.futures import ThreadPoolExecutor
from functools import cache
from typing import Any, Dict, List

import docker

_STATS_FAN_OUT = 8


@cache
def _get_client():
    # Lazy: a missing daemon at import time shouldn't crash the worker.
    return docker.from_env()


def _stats_for(container) -> Dict[str, Any]:
    """Stats for an already-resolved Container — avoids a second daemon round-trip."""
    try:
        stats = container.stats(stream=False)
        cpu_delta = (
            stats["cpu_stats"]["cpu_usage"]["total_usage"]
            - stats["precpu_stats"]["cpu_usage"]["total_usage"]
        )
        system_delta = (
            stats["cpu_stats"]["system_cpu_usage"]
            - stats["precpu_stats"]["system_cpu_usage"]
        )
        cpu_percent = 0.0
        if system_delta > 0 and cpu_delta > 0:
            cpu_count = stats["cpu_stats"].get("online_cpus", 1)
            cpu_percent = (cpu_delta / system_delta) * cpu_count * 100.0

        networks = stats.get("networks") or {}
        network_rx = networks.get("eth0", {}).get("rx_bytes", 0)
        network_tx = networks.get("eth0", {}).get("tx_bytes", 0)

        return {
            "status": "success",
            "stats": {
                "cpu_percent": round(cpu_percent, 2),
                "network_rx_kb": round(network_rx / 1024, 2),
                "network_tx_kb": round(network_tx / 1024, 2),
                "runtime_seconds": round(
                    stats["cpu_stats"]["cpu_usage"]["total_usage"] / 1_000_000_000, 2
                ),
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


def get_containers() -> List[Dict[str, Any]]:
    """List every container with its per-container live stats.

    Each ``container.stats(stream=False)`` call blocks ~1s sampling CPU, so we
    fan them out across a thread pool — the SDK releases the GIL on socket I/O.
    """
    containers = _get_client().containers.list(all=True)
    if not containers:
        return []
    with ThreadPoolExecutor(max_workers=_STATS_FAN_OUT) as ex:
        stats_results = list(ex.map(_stats_for, containers))
    result = []
    for container, stats_result in zip(containers, stats_results):
        stats = stats_result.get("stats") or {}
        result.append(
            {
                "id": container.id,
                "short_id": container.short_id,
                "name": container.name,
                "status": container.status,
                "image": container.image.tags[0] if container.image.tags else container.image.id,
                "ports": container.ports,
                "created": container.attrs["Created"],
                "command": container.attrs["Config"]["Cmd"],
                **stats,
            }
        )
    return result


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
