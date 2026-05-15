import docker
from functools import cache
from typing import Dict, List, Any
from .system_stats import get_container_stats


@cache
def _get_client():
    """Lazy Docker client. Imported before the daemon is reachable should not
    crash the FastAPI worker — let endpoints surface the error per-request."""
    return docker.from_env()


def get_containers() -> List[Dict[str, Any]]:
    """Get all running and stopped containers with their details."""
    containers = _get_client().containers.list(all=True)
    result = []
    
    for container in containers:
        container_stats = get_container_stats(container.id).get("stats") or {}
        result.append({
            "id": container.id,
            "short_id": container.short_id,
            "name": container.name,
            "status": container.status,
            "image": container.image.tags[0] if container.image.tags else container.image.id,
            "ports": container.ports,
            "created": container.attrs["Created"],
            "command": container.attrs["Config"]["Cmd"],
            **container_stats,

        })
    
    return result

def start_container(container_id: str) -> Dict[str, str]:
    """Start a container by ID."""
    try:
        container = _get_client().containers.get(container_id)
        container.start()
        return {"status": "success", "message": f"Container {container.name} started successfully"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def stop_container(container_id: str) -> Dict[str, str]:
    """Stop a container by ID."""
    try:
        container = _get_client().containers.get(container_id)
        container.stop()
        return {"status": "success", "message": f"Container {container.name} stopped successfully"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def restart_container(container_id: str) -> Dict[str, str]:
    """Restart a container by ID."""
    try:
        container = _get_client().containers.get(container_id)
        container.restart()
        return {"status": "success", "message": f"Container {container.name} restarted successfully"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def get_container_logs(container_id: str, tail: int = 100) -> Dict[str, Any]:
    """Get logs from a container."""
    try:
        container = _get_client().containers.get(container_id)
        logs = container.logs(tail=tail, timestamps=True).decode('utf-8')
        return {"status": "success", "logs": logs}
    except Exception as e:
        return {"status": "error", "message": str(e)}
