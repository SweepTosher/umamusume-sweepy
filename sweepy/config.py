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

CM_ENABLED = False


DEFAULT_TURN_DELAY: dict[str, Any] = {
    "min": 1.6,
    "max": 3.7,
    "restore_min": 1.6,
    "restore_max": 3.7,
    "disabled": False,
}

DEFAULT_CM_CONFIG: dict[str, Any] = {
    "cm_mode": False,
    "cm_preset": "sagittarius",
    "cm_course": "sagittarius",
    "track": "Nakayama",
    "distance": 2500,
    "ground": 1,
    "ground_condition": 1,
    "weather": 1,
    "season": 4,
    "course_id": 10506,
    "inout": 1,
    "cm_role": 0,
    "cm_target": "carry",
    "cm_style": 0,
    "mate_ids": [None, None],
    "mate_roles": ["auto", "auto"],
    "mate_snapshots": [None, None],
}


CM_ROLE_ALIASES: dict[str, int] = {
    "solo": 0,
    "ace1": 0,
    "raw": 0,
    "ace1_raw": 0,
    "ace": 1,
    "ace2": 1,
    "support": 2,
    "debuffer": 2,
    "deb": 2,
    "blocker": 3,
    "blk": 3,
}

CM_STYLE_ALIASES: dict[str, int] = {
    "auto": 0,
    "front": 1,
    "nige": 1,
    "pace": 2,
    "senko": 2,
    "late": 3,
    "sashi": 3,
    "end": 4,
    "oikomi": 4,
    "runaway": 5,
    "oonige": 5,
}


def parse_cm_int_or_alias(val: Any, aliases: dict[str, int], lo: int, hi: int, default: int) -> int:
    if val is None or isinstance(val, bool):
        return default
    if isinstance(val, str):
        key = val.strip().lower()
        if not key:
            return default
        if key in aliases:
            return aliases[key]
        try:
            iv = int(key, 10)
        except ValueError:
            return default
    else:
        try:
            iv = int(val)
        except (TypeError, ValueError):
            return default
    return max(lo, min(hi, iv))


def normalize_cm_role(raw_role: Any, target: Any = None) -> int:
    role = parse_cm_int_or_alias(raw_role, CM_ROLE_ALIASES, 0, 3, 0)
    if role == 1 and str(target or "carry").strip().lower() == "debuffer":
        return 2
    return role


def normalize_cm_style(raw_style: Any) -> int:
    return parse_cm_int_or_alias(raw_style, CM_STYLE_ALIASES, 0, 5, 0)


def apply_turn_delay(client: Any, delay_cfg: dict[str, Any]) -> None:
    timing = getattr(client, "timing", None)
    if timing is None:
        return
    timing.disabled = bool(delay_cfg.get("disabled", False))
    if not timing.disabled:
        timing.turn_min = float(delay_cfg.get("min", 1.6))
        timing.turn_max = float(delay_cfg.get("max", 3.7))


def _normalize_cm_config(raw: Any) -> dict[str, Any]:
    src = raw if isinstance(raw, dict) else {}
    cm_mode = bool(src.get("cm_mode", False))
    raw_course = src.get("cm_course", "sagittarius")
    course_dict = raw_course if isinstance(raw_course, dict) else {}
    if isinstance(raw_course, str):
        cm_course: Any = raw_course.strip() or "sagittarius"
    elif isinstance(raw_course, dict):
        cm_course = dict(raw_course)
    else:
        cm_course = "sagittarius"

    raw_preset = src.get("cm_preset", cm_course if isinstance(cm_course, str) else course_dict.get("slug", "custom"))
    cm_preset = str(raw_preset or "custom").strip() or "custom"

    raw_track = src.get("track", course_dict.get("track", DEFAULT_CM_CONFIG["track"]))
    track = str(raw_track or DEFAULT_CM_CONFIG["track"]).strip() or DEFAULT_CM_CONFIG["track"]
    distance = parse_cm_int_or_alias(
        src.get("distance", course_dict.get("distance")),
        {},
        1000,
        3600,
        int(DEFAULT_CM_CONFIG["distance"]),
    )
    ground = parse_cm_int_or_alias(
        src.get("ground", src.get("surface", course_dict.get("ground", course_dict.get("surface")))),
        {"turf": 1, "grass": 1, "shiba": 1, "dirt": 2, "sand": 2},
        1,
        2,
        int(DEFAULT_CM_CONFIG["ground"]),
    )
    ground_condition = parse_cm_int_or_alias(
        src.get("ground_condition", course_dict.get("ground_condition")),
        {"firm": 1, "good": 2, "soft": 3, "yielding": 3, "heavy": 4, "bad": 4},
        1,
        4,
        int(DEFAULT_CM_CONFIG["ground_condition"]),
    )
    weather = parse_cm_int_or_alias(
        src.get("weather", course_dict.get("weather")),
        {"sunny": 1, "clear": 1, "cloudy": 2, "rainy": 3, "rain": 3, "snowy": 4, "snow": 4},
        1,
        4,
        int(DEFAULT_CM_CONFIG["weather"]),
    )
    season = parse_cm_int_or_alias(
        src.get("season", course_dict.get("season")),
        {"spring": 1, "summer": 2, "autumn": 3, "fall": 3, "winter": 4},
        1,
        4,
        int(DEFAULT_CM_CONFIG["season"]),
    )
    raw_cid = src.get("course_id", course_dict.get("course_id"))
    course_id: int | None = None
    if raw_cid is not None and not isinstance(raw_cid, bool) and str(raw_cid).strip() != "":
        try:
            cid_v = int(raw_cid)
            if cid_v > 0:
                course_id = cid_v
        except (TypeError, ValueError):
            course_id = None
    inout = parse_cm_int_or_alias(
        src.get("inout", course_dict.get("inout")),
        {"inner": 1, "in": 1, "outer": 2, "out": 2},
        1,
        2,
        int(DEFAULT_CM_CONFIG["inout"]),
    )

    cm_role = parse_cm_int_or_alias(src.get("cm_role", 0), CM_ROLE_ALIASES, 0, 3, 0)

    raw_target = str(src.get("cm_target") or "carry").strip().lower()
    cm_target = raw_target if raw_target in ("carry", "debuffer") else "carry"

    cm_style = normalize_cm_style(src.get("cm_style", 0))

    raw_ids = src.get("mate_ids")
    mate_ids: list[int | None] = [None, None]
    if isinstance(raw_ids, (list, tuple)):
        for i in range(min(2, len(raw_ids))):
            v = raw_ids[i]
            if v is not None and str(v).strip() != "" and not isinstance(v, bool):
                try:
                    mate_ids[i] = int(v)
                except (TypeError, ValueError):
                    mate_ids[i] = None

    raw_roles = src.get("mate_roles")
    mate_roles: list[str] = ["auto", "auto"]
    if isinstance(raw_roles, (list, tuple)):
        for i in range(min(2, len(raw_roles))):
            rv = str(raw_roles[i] or "auto").strip().lower()
            mate_roles[i] = rv if rv in ("auto", "ace", "debuffer", "blocker") else "auto"

    raw_snaps = src.get("mate_snapshots")
    mate_snapshots: list[dict[str, Any] | None] = [None, None]
    if isinstance(raw_snaps, (list, tuple)):
        for i in range(min(2, len(raw_snaps))):
            if isinstance(raw_snaps[i], dict):
                mate_snapshots[i] = dict(raw_snaps[i])

    return {
        "cm_mode": cm_mode,
        "cm_preset": cm_preset,
        "cm_course": cm_course,
        "track": track,
        "distance": distance,
        "ground": ground,
        "ground_condition": ground_condition,
        "weather": weather,
        "season": season,
        "course_id": course_id,
        "inout": inout,
        "cm_role": cm_role,
        "cm_target": cm_target,
        "cm_style": cm_style,
        "mate_ids": mate_ids,
        "mate_roles": mate_roles,
        "mate_snapshots": mate_snapshots,
    }


def _disk_payload(settings: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "api_url": settings.get("api_url", ""),
        "turn_delay": settings.get("turn_delay"),
        "burn_clocks": bool(settings.get("burn_clocks", False)),
    }
    if "cm_config" in settings:
        out["cm_config"] = _normalize_cm_config(settings.get("cm_config"))
    return out


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
            "cm_config": _normalize_cm_config(DEFAULT_CM_CONFIG),
        }

    def _ensure_defaults(self) -> None:
        with self._lock:
            if not self.settings_path.is_file():
                atomic_write_json(self.settings_path, _disk_payload(self._default_settings()))
            elif os.name == "posix":
                os.chmod(self.settings_path, 0o600)

    def _backup_corrupt_settings(self, reason: str, defaults: dict[str, Any]) -> dict[str, Any]:
        corrupt = self.settings_path.with_name(self.settings_path.name + ".corrupt")
        try:
            os.replace(self.settings_path, corrupt)
        except OSError:
            corrupt = None
        location = f" (saved as {corrupt})" if corrupt is not None else ""
        print(f"sweepy: settings.json {reason}, using defaults{location}", file=sys.stderr)
        return defaults

    def load_settings(self) -> dict[str, Any]:
        with self._lock:
            defaults = self._default_settings()
            if not self.settings_path.is_file():
                atomic_write_json(self.settings_path, _disk_payload(defaults))
                return defaults
            try:
                raw = json.loads(self.settings_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                return self._backup_corrupt_settings("unreadable", defaults)
            if not isinstance(raw, dict):
                return self._backup_corrupt_settings("is not an object", defaults)
            api_url = str(raw.get("api_url") or defaults["api_url"]).strip().rstrip("/")
            if not api_url:
                api_url = defaults["api_url"]
            return {
                "api_url": api_url,
                "api_key": self._memory_api_key,
                "turn_delay": _normalize_turn_delay(raw.get("turn_delay")),
                "burn_clocks": bool(raw.get("burn_clocks", False)),
                "cm_config": _normalize_cm_config(raw.get("cm_config")),
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
                "cm_config": _normalize_cm_config(settings.get("cm_config")),
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

    def set_cm_config(self, cm_config: dict[str, Any]) -> dict[str, Any]:
        saved = self.update_settings(cm_config=_normalize_cm_config(cm_config))
        return saved["cm_config"]

