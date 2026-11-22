from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Mapping

REQUIRED_NUMBER_FIELDS = (
    "card_id",
    "speed",
    "stamina",
    "power",
    "guts",
    "wiz",
    "motivation",
    "skill_point",
    "race_running_style",
    "proper_distance_short",
    "proper_distance_mile",
    "proper_distance_middle",
    "proper_distance_long",
    "proper_running_style_nige",
    "proper_running_style_senko",
    "proper_running_style_sashi",
    "proper_running_style_oikomi",
    "proper_ground_turf",
    "proper_ground_dirt",
)

OPTIONAL_NUMBER_FIELDS = (
    "fans",
    "talent_level",
    "turn",
    "single_mode_chara_id",
    "scenario_id",
)

SKILL_FIELDS = ("skill_id", "level")
HINT_FIELDS = ("group_id", "rarity", "level")
FINAL_CAREER_TURN = 78
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_SPACE = re.compile(r"\s+")


def _int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _rows(values: Any, fields: tuple[str, ...]) -> list[dict[str, int]] | None:
    if not isinstance(values, (list, tuple)):
        return None
    rows: list[dict[str, int]] = []
    for value in values:
        if not isinstance(value, Mapping):
            return None
        row: dict[str, int] = {}
        for field in fields:
            number = _int(value.get(field))
            if number is None:
                return None
            row[field] = number
        rows.append(row)
    return rows


def is_final_turn(chara: Mapping[str, Any] | None) -> bool:
    turn = _int((chara or {}).get("turn"))
    return turn is not None and turn >= FINAL_CAREER_TURN


def build_final_turn_payload(state: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(state, Mapping):
        return None
    chara = state.get("chara_info")
    if not isinstance(chara, Mapping):
        return None

    info: dict[str, Any] = {}
    for field in REQUIRED_NUMBER_FIELDS:
        number = _int(chara.get(field))
        if number is None:
            return None
        info[field] = number

    skills = _rows(chara.get("skill_array"), SKILL_FIELDS)
    if skills is None:
        return None
    info["skill_array"] = skills

    tips = _rows(chara.get("skill_tips_array") or [], HINT_FIELDS)
    if tips is None:
        return None
    info["skill_tips_array"] = tips

    for field in OPTIONAL_NUMBER_FIELDS:
        number = _int(chara.get(field))
        if number is not None:
            info[field] = number

    return {"chara_info": info}


def _slug(text: Any, fallback: str) -> str:
    cleaned = _SPACE.sub("_", _UNSAFE.sub("", str(text or "")).strip())
    return cleaned.strip("._")[:80] or fallback


def export_filename(
    chara: Mapping[str, Any] | None,
    name: str | None = None,
    moment: datetime | None = None,
) -> str:
    chara = chara or {}
    label = name or chara.get("name")
    card_id = _int(chara.get("card_id"))
    fallback = f"card_{card_id}" if card_id is not None else "umadump"
    when = moment or datetime.now()
    return f"{_slug(label, fallback)}_{when:%Y%m%d-%H%M%S}.json"
