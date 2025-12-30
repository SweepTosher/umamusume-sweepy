import time
from typing import Optional, Dict, Any

events_load_info: Optional[Dict[str, Any]] = None


def update_events_load_info(count: int) -> None:
    global events_load_info
    events_load_info = {
        "loaded": True,
        "count": int(count),
        "timestamp": time.time(),
    }


def get_events_load_info() -> Dict[str, Any]:
    global events_load_info
    return events_load_info or {
        "loaded": False,
        "count": 0,
        "timestamp": 0,
    }
