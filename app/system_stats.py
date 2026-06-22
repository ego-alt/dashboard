import os
from typing import Any, Dict, Optional

import psutil

_MB = 1024 * 1024
_GB = _MB * 1024

# Pi exposes CPU temperature in millidegrees here; absent on macOS/dev.
_THERMAL = "/sys/class/thermal/thermal_zone0/temp"
# Where the stack's data actually lives (books/music/DBs). Root "/" usually
# isn't what fills up — the backup mount is. Reported only when distinct.
_DATA_MOUNT = os.getenv("DATA_MOUNT", "/mnt/backup")


def _cpu_temp_c() -> Optional[float]:
    try:
        with open(_THERMAL) as f:
            return round(int(f.read().strip()) / 1000, 1)
    except (OSError, ValueError):
        return None


def _disk(path: str) -> Optional[Dict[str, float]]:
    try:
        du = psutil.disk_usage(path)
        return {
            "percent": du.percent,
            "used_gb": round(du.used / _GB, 1),
            "total_gb": round(du.total / _GB, 1),
        }
    except OSError:
        return None


def get_system_stats() -> Dict[str, Any]:
    vm = psutil.virtual_memory()
    root = _disk("/") or {}
    stats: Dict[str, Any] = {
        "cpu_percent": psutil.cpu_percent(interval=0.5),
        "memory_percent": vm.percent,
        "memory_used": vm.used / _MB,
        "memory_total": vm.total / _MB,
        "disk_percent": root.get("percent"),
        "disk_used": root.get("used_gb"),
        "disk_total": root.get("total_gb"),
        "cpu_temp_c": _cpu_temp_c(),
    }

    # Only surface the data mount when it's a real, separate mountpoint — on dev
    # boxes it won't exist, so the card just omits it.
    if _DATA_MOUNT and os.path.ismount(_DATA_MOUNT):
        if data := _disk(_DATA_MOUNT):
            stats["data_mount"] = _DATA_MOUNT
            stats["data_disk_percent"] = data["percent"]
            stats["data_disk_used"] = data["used_gb"]
            stats["data_disk_total"] = data["total_gb"]

    return stats
