from __future__ import annotations

import json
from pathlib import Path
from typing import Any


CM_PRESETS: tuple[dict[str, Any], ...] = (
    {"slug": "capricorn", "name": "Capricorn (Chukyo 1200m Turf)", "course_id": 10701, "distance": 1200, "surface": 1, "distance_type": 1},
    {"slug": "aquarius", "name": "Aquarius (Tokyo 1600m Dirt)", "course_id": 10611, "distance": 1600, "surface": 2, "distance_type": 2},
    {"slug": "cancer", "name": "Cancer (Tokyo 1600m Turf)", "course_id": 10602, "distance": 1600, "surface": 1, "distance_type": 2},
    {"slug": "scorpio", "name": "Scorpio (Tokyo 2000m Turf)", "course_id": 10604, "distance": 2000, "surface": 1, "distance_type": 3},
    {"slug": "aries", "name": "Aries (Nakayama 2000m Turf)", "course_id": 10504, "distance": 2000, "surface": 1, "distance_type": 3},
    {"slug": "taurus", "name": "Taurus (Tokyo 2400m Turf)", "course_id": 10606, "distance": 2400, "surface": 1, "distance_type": 3},
    {"slug": "sagittarius", "name": "Sagittarius (Nakayama 2500m Turf)", "course_id": 10506, "distance": 2500, "surface": 1, "distance_type": 4},
    {"slug": "pisces", "name": "Pisces (Hanshin 3200m Turf)", "course_id": 10914, "distance": 3200, "surface": 1, "distance_type": 4},
)


def _load_json_dict(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    loaded = json.loads(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def _as_int(raw: Any, default: int = 0) -> int:
    if raw is None or isinstance(raw, bool):
        return default
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        if raw != raw or raw in (float("inf"), float("-inf")):
            return default
        return int(raw)
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return default
        try:
            return int(text, 10)
        except ValueError:
            try:
                numeric = float(text)
            except ValueError:
                return default
            if numeric != numeric or numeric in (float("inf"), float("-inf")):
                return default
            return int(numeric)
    return default


def _item_count(items: Any, item_id: int) -> int:
    if not isinstance(items, list):
        return 0
    for row in items:
        if isinstance(row, dict) and _as_int(row.get("item_id")) == item_id:
            return _as_int(row.get("number"))
    return 0


class Catalog:
    def __init__(self, public_dir: Path | str | None = None) -> None:
        if public_dir is None:
            resolved = Path(__file__).resolve().parent.parent / "public"
        else:
            resolved = Path(public_dir).resolve()
        self.public_dir = resolved
        data_dir = self.public_dir / "data"
        self.chara_names: dict[str, str] = {
            str(k): str(v) for k, v in _load_json_dict(data_dir / "chara_names.json").items()
        }

    def chara_name(self, card_id: int | str) -> str:
        cid = str(card_id or "")
        return self.chara_names.get(cid, f"Unknown ({cid})")

    def format_account_status(
        self,
        raw_data: dict[str, Any],
        career_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data = raw_data.get("data") if isinstance(raw_data.get("data"), dict) else raw_data
        user_info = data.get("user_info") if isinstance(data.get("user_info"), dict) else {}
        tp_info = data.get("tp_info") if isinstance(data.get("tp_info"), dict) else {}
        items = data.get("item_list") or data.get("user_item_array") or []

        career_src = data.get("single_mode_chara_light") or data.get("single_mode_chara")
        if isinstance(career_data, dict):
            inner = career_data.get("data") if isinstance(career_data.get("data"), dict) else career_data
            if isinstance(inner.get("chara_info"), dict):
                career_src = inner["chara_info"]

        career_out: dict[str, Any] | None = None
        if isinstance(career_src, dict) and int(career_src.get("card_id") or career_src.get("single_mode_chara_id") or 0) > 0:
            cid = str(career_src.get("card_id") or "")
            career_out = {
                "active": True,
                "single_mode_chara_id": int(career_src.get("single_mode_chara_id") or 0),
                "card_id": cid,
                "name": self.chara_name(cid),
                "turn": int(career_src.get("turn") or 0),
                "scenario_id": int(career_src.get("scenario_id") or 0),
            }

        return {
            "trainer_name": str(user_info.get("name") or ""),
            "tp": {
                "current": int(tp_info.get("current_tp") or 0),
                "max": int(tp_info.get("max_tp") or 100),
            },
            "clocks": _item_count(items, 95),
            "career": career_out,
        }

    def format_veterans(self, raw_data: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not isinstance(raw_data, dict):
            return []
        data = raw_data.get("data") if isinstance(raw_data.get("data"), dict) else raw_data
        raw_vets = data.get("trained_chara_array")
        if not isinstance(raw_vets, list):
            return []
        out: list[dict[str, Any]] = []
        for tc in raw_vets:
            if not isinstance(tc, dict):
                continue
            tid = _as_int(tc.get("trained_chara_id"), 0)
            if tid <= 0:
                continue
            cid = _as_int(tc.get("card_id"), 0)
            stats = [
                _as_int(tc.get("speed"), 0),
                _as_int(tc.get("stamina"), 0),
                _as_int(tc.get("power"), 0),
                _as_int(tc.get("guts"), 0),
                _as_int(tc.get("wiz"), 0),
            ]
            out.append({
                "trained_chara_id": tid,
                "card_id": cid,
                "name": self.chara_name(cid),
                "rank_score": _as_int(tc.get("rank_score"), 0),
                "stats": stats,
                "running_style": _as_int(tc.get("running_style"), 2),
                "proper_distance": [
                    _as_int(tc.get("proper_distance_short"), 1),
                    _as_int(tc.get("proper_distance_mile"), 1),
                    _as_int(tc.get("proper_distance_middle"), 1),
                    _as_int(tc.get("proper_distance_long"), 1),
                ],
                "proper_ground": [
                    _as_int(tc.get("proper_ground_turf"), 1),
                    _as_int(tc.get("proper_ground_dirt"), 1),
                ],
                "skill_count": len(tc.get("skill_array") or []),
            })
        out.sort(key=lambda r: (r["rank_score"], r["trained_chara_id"]), reverse=True)
        return out
