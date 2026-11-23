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


_CM_MATE_INT_FIELDS = (
    "card_id",
    "speed",
    "stamina",
    "power",
    "guts",
    "wiz",
    "running_style",
    "proper_distance_short",
    "proper_distance_mile",
    "proper_distance_middle",
    "proper_distance_long",
    "proper_ground_turf",
    "proper_ground_dirt",
    "proper_running_style_nige",
    "proper_running_style_senko",
    "proper_running_style_sashi",
    "proper_running_style_oikomi",
)


def strip_cm_mate(
    raw_mate: dict[str, Any],
    *,
    role_override: str | None = None,
    style_override: int | None = None,
) -> dict[str, Any]:
    if not isinstance(raw_mate, dict):
        raise TypeError("raw_mate must be a dict")
    cleaned: dict[str, Any] = {}
    for field in _CM_MATE_INT_FIELDS:
        val = raw_mate.get(field)
        if val is not None and not isinstance(val, bool):
            try:
                cleaned[field] = int(val)
            except (TypeError, ValueError):
                continue

    if "power" not in cleaned and raw_mate.get("pow") is not None:
        cleaned["power"] = int(raw_mate["pow"])
    if "wiz" not in cleaned and raw_mate.get("wisdom") is not None:
        cleaned["wiz"] = int(raw_mate["wisdom"])
    if isinstance(raw_mate.get("stats"), (list, tuple)) and len(raw_mate["stats"]) >= 5:
        cleaned["stats"] = [int(x) for x in raw_mate["stats"][:5]]

    if style_override is not None and 1 <= int(style_override) <= 5:
        cleaned["running_style"] = int(style_override)
    elif "running_style" not in cleaned:
        alt_style = raw_mate.get("racingStyle") or raw_mate.get("style")
        if alt_style is not None and not isinstance(alt_style, bool):
            st_i = int(alt_style)
            cleaned["running_style"] = st_i if 1 <= st_i <= 5 else 2

    if isinstance(raw_mate.get("aptitudes"), (list, tuple)):
        cleaned["aptitudes"] = [str(x) for x in raw_mate["aptitudes"][:3]]

    raw_skills = raw_mate.get("skills")
    if raw_skills is None:
        raw_skills = raw_mate.get("skill_array")
    skill_array: list[dict[str, int]] = []
    if isinstance(raw_skills, (list, tuple)):
        for item in raw_skills[:64]:
            if isinstance(item, dict) and item.get("skill_id") is not None:
                skill_array.append({"skill_id": int(item["skill_id"])})
            elif isinstance(item, (list, tuple)) and len(item) >= 1:
                skill_array.append({"skill_id": int(item[0])})
            elif isinstance(item, int) and not isinstance(item, bool):
                skill_array.append({"skill_id": int(item)})
    cleaned["skill_array"] = skill_array

    role_str = str(role_override if role_override is not None else (raw_mate.get("role") or "")).strip().lower()
    if role_str and role_str != "auto":
        cleaned["role"] = role_str
        if "deb" in role_str:
            cleaned["is_debuffer"] = True
        elif "block" in role_str:
            cleaned["is_blocker"] = True
    else:
        if bool(raw_mate.get("is_debuffer")) or (
            raw_mate.get("style") == 6 and "racingStyle" in raw_mate
        ):
            cleaned["is_debuffer"] = True
        if bool(raw_mate.get("is_blocker")):
            cleaned["is_blocker"] = True

    return _scrub_private(cleaned)


def resolve_cm_options_for_account(
    cm_cfg: dict[str, Any] | None,
    raw_account_data: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not isinstance(cm_cfg, dict) or not bool(cm_cfg.get("cm_mode")):
        return None

    data = (
        raw_account_data.get("data")
        if isinstance(raw_account_data, dict) and isinstance(raw_account_data.get("data"), dict)
        else raw_account_data
    )
    by_tid: dict[int, dict[str, Any]] = {}
    if isinstance(data, dict):
        for tc in data.get("trained_chara_array") or []:
            if isinstance(tc, dict) and tc.get("trained_chara_id") is not None:
                try:
                    by_tid[int(tc["trained_chara_id"])] = tc
                except (TypeError, ValueError):
                    continue

    raw_explicit = cm_cfg.get("cm_mates")
    resolved_mates: list[dict[str, Any]] = []
    if isinstance(raw_explicit, (list, tuple)):
        if len(raw_explicit) > 2:
            raise ValueError(f"Expected at most 2 teammates, got {len(raw_explicit)}")
        mate_roles = cm_cfg.get("mate_roles") if isinstance(cm_cfg.get("mate_roles"), (list, tuple)) else []
        for idx, item in enumerate(raw_explicit):
            if item is None:
                continue
            r_ov = str(mate_roles[idx]) if idx < len(mate_roles) and mate_roles[idx] else None
            resolved_mates.append(strip_cm_mate(item, role_override=r_ov))
    else:
        mate_ids = cm_cfg.get("mate_ids") if isinstance(cm_cfg.get("mate_ids"), (list, tuple)) else []
        mate_roles = cm_cfg.get("mate_roles") if isinstance(cm_cfg.get("mate_roles"), (list, tuple)) else []
        mate_snaps = cm_cfg.get("mate_snapshots") if isinstance(cm_cfg.get("mate_snapshots"), (list, tuple)) else []
        for idx in range(min(2, max(len(mate_ids), len(mate_snaps)))):
            raw_tid = mate_ids[idx] if idx < len(mate_ids) else None
            r_ov = str(mate_roles[idx]) if idx < len(mate_roles) and mate_roles[idx] else None
            snap = mate_snaps[idx] if idx < len(mate_snaps) else None
            if raw_tid is not None and not isinstance(raw_tid, bool):
                tid = int(raw_tid)
                if tid in by_tid:
                    resolved_mates.append(strip_cm_mate(by_tid[tid], role_override=r_ov))
                elif isinstance(snap, dict) and int(snap.get("_snap_tid") or 0) == tid:
                    resolved_mates.append(strip_cm_mate(snap, role_override=r_ov))
                else:
                    raise ValueError(f"Selected teammate veteran {tid} not found in account veterans")

    raw_role = cm_cfg.get("cm_role", 0)
    if isinstance(raw_role, str):
        role_map = {
            "solo": 0, "ace1": 0, "raw": 0, "ace1_raw": 0,
            "ace": 1, "ace2": 1,
            "support": 2, "debuffer": 2, "deb": 2,
            "blocker": 3, "blk": 3,
        }
        cm_role = role_map.get(raw_role.strip().lower(), 0)
    else:
        cm_role = max(0, min(3, int(raw_role or 0)))

    cm_style = max(0, min(5, int(cm_cfg.get("cm_style", 0) or 0)))
    cm_course = cm_cfg.get("cm_course") or "sagittarius"
    return {
        "cm_mode": True,
        "cm_course": cm_course,
        "cm_role": cm_role,
        "cm_style": cm_style,
        "cm_mates": resolved_mates,
    }
