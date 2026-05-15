from typing import Any, Dict

import psutil

_MB = 1024 * 1024
_GB = _MB * 1024


def get_system_stats() -> Dict[str, Any]:
    vm = psutil.virtual_memory()
    du = psutil.disk_usage("/")
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.5),
        "memory_percent": vm.percent,
        "memory_used": vm.used / _MB,
        "memory_total": vm.total / _MB,
        "disk_percent": du.percent,
        "disk_used": du.used / _GB,
        "disk_total": du.total / _GB,
    }
