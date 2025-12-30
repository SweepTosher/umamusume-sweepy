import json
import os
import threading
import time
from typing import Optional, Dict, Any

_lock = threading.Lock()

_DEFAULT_REPETITIVE_THRESHOLD = 11
_DEFAULT_WATCHDOG_THRESHOLD = 3

_state: Dict[str, Any] = {
    "repetitive_count": 0,
    "repetitive_other_clicks": 0,
    "repetitive_threshold": _DEFAULT_REPETITIVE_THRESHOLD,
    "watchdog_unchanged": 0,
    "watchdog_threshold": _DEFAULT_WATCHDOG_THRESHOLD,
    "last_update_ts": time.time()
}


def get_state() -> Dict[str, Any]:
    with _lock:
        return dict(_state)


def set_thresholds(repetitive_threshold: Optional[int] = None,
                   watchdog_threshold: Optional[int] = None) -> None:
    with _lock:
        if isinstance(repetitive_threshold, int) and repetitive_threshold > 0:
            _state["repetitive_threshold"] = repetitive_threshold
        if isinstance(watchdog_threshold, int) and watchdog_threshold > 0:
            _state["watchdog_threshold"] = watchdog_threshold
        _state["last_update_ts"] = time.time()


def set_counts(repetitive_count: Optional[int] = None,
               repetitive_other_clicks: Optional[int] = None,
               watchdog_unchanged: Optional[int] = None) -> None:
    with _lock:
        if isinstance(repetitive_count, int) and repetitive_count >= 0:
            _state["repetitive_count"] = repetitive_count
        if isinstance(repetitive_other_clicks, int) and repetitive_other_clicks >= 0:
            _state["repetitive_other_clicks"] = repetitive_other_clicks
        if isinstance(watchdog_unchanged, int) and watchdog_unchanged >= 0:
            _state["watchdog_unchanged"] = watchdog_unchanged
        _state["last_update_ts"] = time.time()


def update_repetitive(repetitive_count: int, repetitive_other_clicks: int) -> None:
    with _lock:
        _state["repetitive_count"] = int(max(0, repetitive_count))
        _state["repetitive_other_clicks"] = int(max(0, repetitive_other_clicks))
        _state["last_update_ts"] = time.time()


def update_watchdog(watchdog_unchanged: int) -> None:
    with _lock:
        _state["watchdog_unchanged"] = int(max(0, watchdog_unchanged))
        _state["last_update_ts"] = time.time()


_PERSIST_PATH = os.path.join("userdata", "runtime_settings.json")


def load_persisted(path: Optional[str] = None) -> None:
    p = path or _PERSIST_PATH
    try:
        if os.path.isfile(p):
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            set_thresholds(
                repetitive_threshold=int(data.get("repetitive_threshold", _DEFAULT_REPETITIVE_THRESHOLD)),
                watchdog_threshold=int(data.get("watchdog_threshold", _DEFAULT_WATCHDOG_THRESHOLD)),
            )
    except Exception:
        pass


def save_persisted(path: Optional[str] = None) -> None:
    p = path or _PERSIST_PATH
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with _lock:
            payload = {
                "repetitive_threshold": int(_state.get("repetitive_threshold", _DEFAULT_REPETITIVE_THRESHOLD)),
                "watchdog_threshold": int(_state.get("watchdog_threshold", _DEFAULT_WATCHDOG_THRESHOLD)),
                "saved_at": time.time(),
            }
        with open(p, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def get_repetitive_threshold() -> int:
    with _lock:
        return int(_state.get("repetitive_threshold", _DEFAULT_REPETITIVE_THRESHOLD))


def get_watchdog_threshold() -> int:
    with _lock:
        return int(_state.get("watchdog_threshold", _DEFAULT_WATCHDOG_THRESHOLD))
