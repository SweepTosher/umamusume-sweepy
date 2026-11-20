from __future__ import annotations

from typing import Any


_ALLOWED_TOP_KEYS = frozenset({
    "chara_info",
    "home_info",
    "live_data_set",
    "race_start_info",
    "race_condition_array",
    "race_history",
    "unchecked_event_array",
    "single_mode_finish_common",
    "race_reward_info",
    "command_result",
})

_PRIVATE_KEY_MARKERS = ("viewerid", "steamid", "authkey", "sessionticket", "deviceid", "udid")

_PRIVATE_EXACT_KEYS = frozenset({"friendcode", "trainername", "ownername", "ownertrainername"})


def _norm_key(value: Any) -> str:
    return "".join(ch for ch in str(value).lower() if ch.isalnum())

_LIFT_START_KEYS = (
    "chara_info",
    "home_info",
    "unchecked_event_array",
    "race_condition_array",
    "race_start_info",
    "race_history",
    "single_mode_finish_common",
)


def _scrub_private(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[Any, Any] = {}
        for key, item in value.items():
            norm = _norm_key(key)
            if norm in _PRIVATE_EXACT_KEYS:
                continue
            if any(marker in norm for marker in _PRIVATE_KEY_MARKERS):
                continue
            cleaned[key] = _scrub_private(item)
        return cleaned
    if isinstance(value, list):
        return [_scrub_private(item) for item in value]
    return value


def strip_career_state(raw_data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw_data, dict):
        raise TypeError("raw_data is not a dict")

    source = dict(raw_data.get("data")) if isinstance(raw_data.get("data"), dict) and "chara_info" not in raw_data and "single_mode_start_common" not in raw_data and "live_data_set" not in raw_data else dict(raw_data)

    start_common = source.get("single_mode_start_common")
    if isinstance(start_common, dict):
        for key in _LIFT_START_KEYS:
            if source.get(key) is None and key in start_common:
                source[key] = start_common[key]

    load_common = source.get("single_mode_load_common")
    if isinstance(load_common, dict):
        for key in _LIFT_START_KEYS:
            if source.get(key) is None and key in load_common:
                source[key] = load_common[key]

    out: dict[str, Any] = {}
    for key, value in source.items():
        if key not in _ALLOWED_TOP_KEYS:
            continue
        if key == "live_data_set" and isinstance(value, dict):
            lds_copy = {
                lds_key: lds_val
                for lds_key, lds_val in value.items()
                if lds_key not in ("evaluation_info_array", "not_up_parameter_info", "not_down_parameter_info")
            }
            out["live_data_set"] = lds_copy
            continue
        if key == "race_start_info":
            if isinstance(value, dict):
                pid = value.get("program_id")
                out["race_start_info"] = {"program_id": pid} if pid is not None else {}
            else:
                out["race_start_info"] = None
            continue
        if key == "race_condition_array":
            if isinstance(value, list):
                compacted: list[dict[str, int]] = []
                for row in value:
                    if isinstance(row, dict) and row.get("program_id") is not None:
                        compacted.append({"program_id": int(row["program_id"])})
                out["race_condition_array"] = compacted
            else:
                out["race_condition_array"] = []
            continue
        out[key] = value

    return _scrub_private(out)
