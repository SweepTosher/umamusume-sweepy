from __future__ import annotations

import json
import math
import os
import secrets
import shutil
from pathlib import Path
import sys
import tempfile
import threading
from typing import Any
from urllib.parse import urlsplit

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


DEFAULT_TURN_DELAY: dict[str, Any] = {
    "min": 1.6,
    "max": 3.7,
    "restore_min": 1.6,
    "restore_max": 3.7,
    "disabled": False,
}

def _disk_payload(settings: dict[str, Any]) -> dict[str, Any]:
    return {
        "api_url": settings.get("api_url", ""),
        "turn_delay": settings.get("turn_delay"),
        "burn_clocks": bool(settings.get("burn_clocks", False)),
    }


def validate_brain_url(api_url: str) -> str:
    cleaned = str(api_url or "").strip().rstrip("/")
    if not cleaned:
        raise ValueError("api_url is empty")
    if any(char.isspace() or ord(char) < 0x20 or ord(char) == 0x7F for char in cleaned):
        raise ValueError("api_url has whitespace or control characters")
    parsed = urlsplit(cleaned)
    if parsed.scheme not in ("https", "http"):
        raise ValueError("api_url must start with https:// or http://")
    if not parsed.hostname:
        raise ValueError("api_url must include a host")
    try:
        port = parsed.port
    except ValueError:
        raise ValueError("api_url port is not 1-65535") from None
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("api_url port is not 1-65535")
    if parsed.username or parsed.password:
        raise ValueError("api_url has embedded credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("api_url has a query or fragment")
    if parsed.scheme == "http" and parsed.hostname.casefold() not in _LOOPBACK_HOSTS:
        raise ValueError("http api_url is only allowed for loopback brains; use https otherwise")
    return cleaned


def ensure_private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "posix":
        os.chmod(path, 0o700)
    return path


def atomic_write_json(path: Path, payload: Any) -> None:
    ensure_private_dir(path.parent)
    encoded = (json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    fd, tmp_name = tempfile.mkstemp(prefix=".tmp_", suffix=".json", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        if os.name == "posix":
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
        if os.name == "posix":
            os.chmod(path, 0o600)
    except BaseException:
        if fd >= 0:
            os.close(fd)
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise


def _as_float(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _normalize_turn_delay(raw: Any) -> dict[str, Any]:
    src = raw if isinstance(raw, dict) else {}
    disabled = bool(src.get("disabled", False))
    restore_min = max(0.0, _as_float(src.get("restore_min", src.get("min", 1.6)), 1.6))
    restore_max = max(restore_min, _as_float(src.get("restore_max", src.get("max", 3.7)), 3.7))
    if disabled:
        cur_min = 0.0
        cur_max = 0.0
    else:
        cur_min = max(0.0, _as_float(src.get("min", restore_min), restore_min))
        cur_max = max(cur_min, _as_float(src.get("max", restore_max), restore_max))
        restore_min = cur_min
        restore_max = cur_max
    return {
        "min": round(cur_min, 3),
        "max": round(cur_max, 3),
        "restore_min": round(restore_min, 3),
        "restore_max": round(restore_max, 3),
        "disabled": disabled,
    }


def default_runtime_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".local" / "share"
    return (root / "sweepy" / "uma_runtime").resolve()


def _migrate_legacy_runtime(target: Path, legacy: Path) -> None:
    if legacy == target or not legacy.is_dir():
        return
    try:
        target.mkdir(parents=True, exist_ok=True)
        for item in legacy.iterdir():
            dest = target / item.name
            if dest.exists():
                continue
            if item.is_dir():
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)
    except OSError:
        return


class RuntimeConfig:
    def __init__(self, runtime_dir: Path | str | None = None) -> None:
        if runtime_dir is None:
            env_dir = os.environ.get("UMA_RUNTIME_DIR")
            if env_dir:
                resolved = Path(env_dir).expanduser().resolve()
            else:
                resolved = default_runtime_dir()
                _migrate_legacy_runtime(
                    resolved, (Path(__file__).resolve().parent.parent / "uma_runtime").resolve()
                )
        else:
            resolved = Path(runtime_dir).expanduser().resolve()
        self.runtime_dir = ensure_private_dir(resolved)
        self.settings_path = self.runtime_dir / "settings.json"
        self.refresh_file = self.runtime_dir / "steam_refresh.token"
        self.device_file = self.runtime_dir / "headless_device.json"
        self.salt_file = self.runtime_dir / "account_salt"
        self._lock = threading.RLock()
        self._memory_api_key = (os.environ.get("SWEEPY_API_KEY") or "").strip()
        self._api_key_seed_pending = False
        self._ensure_defaults()
        self._adopt_disk_api_key()

    def _default_settings(self) -> dict[str, Any]:
        api_url = (os.environ.get("SWEEPY_API_URL") or "https://mayano.top/sweepy").strip().rstrip("/")
        api_key = (os.environ.get("SWEEPY_API_KEY") or "").strip()
        return {
            "api_url": api_url or "https://mayano.top/sweepy",
            "api_key": api_key,
            "turn_delay": dict(DEFAULT_TURN_DELAY),
            "burn_clocks": False,
        }

    def _ensure_defaults(self) -> None:
        with self._lock:
            if not self.settings_path.is_file():
                atomic_write_json(self.settings_path, _disk_payload(self._default_settings()))
            elif os.name == "posix":
                os.chmod(self.settings_path, 0o600)

    def load_settings(self) -> dict[str, Any]:
        with self._lock:
            defaults = self._default_settings()
            if not self.settings_path.is_file():
                atomic_write_json(self.settings_path, _disk_payload(defaults))
                return defaults
            try:
                raw = json.loads(self.settings_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                corrupt = self.settings_path.with_name(self.settings_path.name + ".corrupt")
                try:
                    os.replace(self.settings_path, corrupt)
                except OSError:
                    corrupt = None
                location = f" (saved as {corrupt})" if corrupt is not None else ""
                print(f"sweepy: settings.json unreadable, using defaults{location}", file=sys.stderr)
                return defaults
            if not isinstance(raw, dict):
                corrupt = self.settings_path.with_name(self.settings_path.name + ".corrupt")
                try:
                    os.replace(self.settings_path, corrupt)
                except OSError:
                    corrupt = None
                location = f" (saved as {corrupt})" if corrupt is not None else ""
                print(f"sweepy: settings.json is not an object, using defaults{location}", file=sys.stderr)
                return defaults
            api_url = str(raw.get("api_url") or defaults["api_url"]).strip().rstrip("/")
            if not api_url:
                api_url = defaults["api_url"]
            return {
                "api_url": api_url,
                "api_key": self._memory_api_key,
                "turn_delay": _normalize_turn_delay(raw.get("turn_delay")),
                "burn_clocks": bool(raw.get("burn_clocks", False)),
            }

    def save_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            defaults = self._default_settings()
            api_url = validate_brain_url(settings.get("api_url") or defaults["api_url"])
            normalized = {
                "api_url": api_url,
                "api_key": str(settings.get("api_key") or "").strip(),
                "turn_delay": _normalize_turn_delay(settings.get("turn_delay")),
                "burn_clocks": bool(settings.get("burn_clocks", False)),
            }
            self._memory_api_key = normalized["api_key"]
            self._api_key_seed_pending = False
            atomic_write_json(self.settings_path, _disk_payload(normalized))
            return normalized

    def update_settings(self, **patch: Any) -> dict[str, Any]:
        with self._lock:
            current = self.load_settings()
            current.update(patch)
            return self.save_settings(current)

    def set_brain_config(self, api_url: str, api_key: str | None = None) -> dict[str, Any]:
        with self._lock:
            current = self.load_settings()
            validated = validate_brain_url(api_url)
            current["api_url"] = validated
            if api_key is not None:
                current["api_key"] = str(api_key).strip()
            return self.save_settings(current)

    def _adopt_disk_api_key(self) -> None:
        with self._lock:
            try:
                raw = json.loads(self.settings_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                return
            if not isinstance(raw, dict) or "api_key" not in raw:
                return
            legacy = str(raw.pop("api_key") or "").strip()
            try:
                atomic_write_json(self.settings_path, raw)
            except OSError:
                return
            if legacy and not self._memory_api_key:
                self._memory_api_key = legacy
                self._api_key_seed_pending = True

    def account_salt(self) -> str:
        with self._lock:
            env_salt = (os.environ.get("SWEEPY_ACCOUNT_SALT") or "").strip()
            if len(env_salt) >= 32:
                return env_salt
            for _ in range(2):
                try:
                    stored = self.salt_file.read_text(encoding="utf-8").strip()
                except (OSError, UnicodeDecodeError):
                    stored = ""
                if len(stored) >= 32:
                    return stored
                salt = secrets.token_hex(32)
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
                try:
                    fd = os.open(self.salt_file, flags, 0o600)
                except FileExistsError:
                    continue
                try:
                    os.write(fd, (salt + "\n").encode("ascii"))
                    os.fsync(fd)
                finally:
                    os.close(fd)
                return salt
            raise RuntimeError("account_salt could not be persisted")

    def consume_api_key_seed(self) -> str:
        with self._lock:
            if not self._api_key_seed_pending:
                return ""
            self._api_key_seed_pending = False
            return self._memory_api_key

    def set_api_key(self, api_key: str) -> None:
        with self._lock:
            self._memory_api_key = str(api_key or "").strip()
            self._api_key_seed_pending = False

    def set_turn_delay(self, min_val: float, max_val: float, disabled: bool = False) -> dict[str, Any]:
        with self._lock:
            current = self.load_settings()
            prev = current["turn_delay"]
            if disabled:
                next_delay = _normalize_turn_delay({
                    "min": 0.0,
                    "max": 0.0,
                    "restore_min": prev.get("restore_min", 1.6),
                    "restore_max": prev.get("restore_max", 3.7),
                    "disabled": True,
                })
            else:
                low = max(0.0, _as_float(min_val, 1.6))
                high = max(low, _as_float(max_val, 3.7))
                next_delay = _normalize_turn_delay({
                    "min": low,
                    "max": high,
                    "restore_min": low,
                    "restore_max": high,
                    "disabled": False,
                })
            current["turn_delay"] = next_delay
            saved = self.save_settings(current)
            return saved["turn_delay"]

    def set_burn_clocks(self, burn_clocks: bool) -> dict[str, Any]:
        return self.update_settings(burn_clocks=bool(burn_clocks))

