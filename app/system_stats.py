import psutil
import docker
import datetime
from typing import Dict, List, Any

# Initialize Docker client
client = docker.from_env()

def get_system_stats() -> Dict[str, Any]:
    """Get overall system statistics."""
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.5),
        "memory_percent": psutil.virtual_memory().percent,
        "memory_used": psutil.virtual_memory().used / (1024 * 1024),  # MB
        "memory_total": psutil.virtual_memory().total / (1024 * 1024),  # MB
        "disk_percent": psutil.disk_usage('/').percent,
        "disk_used": psutil.disk_usage('/').used / (1024 * 1024 * 1024),  # GB
        "disk_total": psutil.disk_usage('/').total / (1024 * 1024 * 1024),  # GB
    }

def get_container_stats(container_id: str) -> Dict[str, Any]:
    """Get statistics for a specific container."""
    try:
        container = client.containers.get(container_id)
        stats = container.stats(stream=False)
        
        # Calculate CPU usage percentage
        cpu_delta = stats["cpu_stats"]["cpu_usage"]["total_usage"] - stats["precpu_stats"]["cpu_usage"]["total_usage"]
        system_delta = stats["cpu_stats"]["system_cpu_usage"] - stats["precpu_stats"]["system_cpu_usage"]
        cpu_percent = 0.0
        
        if system_delta > 0 and cpu_delta > 0:
            cpu_count = stats["cpu_stats"].get("online_cpus", 1)
            cpu_percent = (cpu_delta / system_delta) * cpu_count * 100.0
        
        # Access network stats
        networks = stats.get("networks", {})
        network_rx = networks.get("eth0", {}).get("rx_bytes", 0) if networks else 0
        network_tx = networks.get("eth0", {}).get("tx_bytes", 0) if networks else 0
        
        return {
            "status": "success",
            "stats": {
                "cpu_percent": round(cpu_percent, 2),
                "network_rx_kb": round(network_rx / 1024, 2),
                "network_tx_kb": round(network_tx / 1024, 2),
                "runtime_seconds": round(stats["cpu_stats"]["cpu_usage"]["total_usage"] / 1_000_000_000, 2),
            }
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

