from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from sweepy.stripper import unwrap_data


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


def item_count(items: Any, item_id: int) -> int:
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
        cm_raw = _load_json_dict(data_dir / "cm_courses.json")
        raw_presets = cm_raw.get("presets")
        raw_courses = cm_raw.get("courses")
        self.cm_presets: list[dict[str, Any]] = (
            [dict(p) for p in raw_presets if isinstance(p, dict)]
            if isinstance(raw_presets, list) and raw_presets
            else [
                {
                    "slug": str(p["slug"]),
                    "name": str(p["name"]),
                    "course_id": int(p["course_id"]),
                    "track": str(p["name"]).split("(")[1].split()[0] if "(" in str(p["name"]) else "Tokyo",
                    "distance": int(p["distance"]),
                    "ground": int(p["surface"]),
                    "distance_type": int(p["distance_type"]),
                    "turn": 1,
                    "inout": 1,
                    "ground_condition": 1,
                    "weather": 1,
                    "season": 1,
                }
                for p in CM_PRESETS
            ]
        )
        self.cm_courses: list[dict[str, Any]] = (
            [dict(c) for c in raw_courses if isinstance(c, dict)]
            if isinstance(raw_courses, list) and raw_courses
            else list(self.cm_presets)
        )
        self._hydrate_master_pack()

    def _hydrate_master_pack(self) -> None:
        pack_env = os.environ.get("UMA_MASTER_PACK_DIR", "").strip()
        if not pack_env:
            return
        pack_dir = Path(pack_env).expanduser()
        if not pack_dir.is_dir():
            return
        try:
            cn_path = pack_dir / "chara_names.json"
            if cn_path.is_file():
                for k, v in _load_json_dict(cn_path).items():
                    self.chara_names.setdefault(str(k), str(v))
            cr_path = pack_dir / "courses.json"
            if cr_path.is_file():
                p_courses = _load_json_dict(cr_path).get("courses")
                if isinstance(p_courses, list):
                    existing = {int(c["course_id"]) for c in self.cm_courses if c.get("course_id") is not None}
                    for crow in p_courses:
                        if isinstance(crow, dict) and crow.get("course_id") is not None:
                            cid = int(crow["course_id"])
                            if cid not in existing:
                                self.cm_courses.append(dict(crow))
                                existing.add(cid)
        except (OSError, ValueError, TypeError, KeyError):
            return

    def cm_metadata(self) -> dict[str, Any]:
        tracks = sorted({str(c.get("track") or "") for c in self.cm_courses if c.get("track")})
        return {
            "presets": list(self.cm_presets),
            "courses": list(self.cm_courses),
            "tracks": tracks,
            "ground_conditions": [
                {"id": 1, "label": "Firm"},
                {"id": 2, "label": "Good"},
                {"id": 3, "label": "Soft"},
                {"id": 4, "label": "Heavy"},
            ],
            "weathers": [
                {"id": 1, "label": "Sunny"},
                {"id": 2, "label": "Cloudy"},
                {"id": 3, "label": "Rainy"},
                {"id": 4, "label": "Snowy"},
            ],
            "seasons": [
                {"id": 1, "label": "Spring"},
                {"id": 2, "label": "Summer"},
                {"id": 3, "label": "Autumn"},
                {"id": 4, "label": "Winter"},
            ],
            "styles": [
                {"id": 0, "label": "Auto"},
                {"id": 1, "label": "Front"},
                {"id": 2, "label": "Pace"},
                {"id": 3, "label": "Late"},
                {"id": 4, "label": "End"},
                {"id": 5, "label": "Runaway"},
            ],
            "modes": [
                {"id": 0, "slug": "solo", "label": "Solo", "mates_required": 0, "mates_max": 0},
                {"id": 1, "slug": "ace", "label": "Ace", "mates_required": 0, "mates_max": 2},
                {"id": 2, "slug": "support", "label": "Support (Debuffer)", "mates_required": 2, "mates_max": 2},
                {"id": 3, "slug": "blocker", "label": "Support (Blocker)", "mates_required": 2, "mates_max": 2},
            ],
            "ace_targets": [
                {"id": "carry", "label": "Carry"},
                {"id": "debuffer", "label": "Debuffer"},
            ],
            "support_subroles": [
                {"id": 2, "label": "Debuffer"},
                {"id": 3, "label": "Blocker"},
            ],
        }

    def chara_name(self, card_id: int | str) -> str:
        cid = str(card_id or "")
        return self.chara_names.get(cid, f"Unknown ({cid})")

    def format_account_status(
        self,
        raw_data: dict[str, Any],
        career_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data = unwrap_data(raw_data)
        user_info = data.get("user_info") if isinstance(data.get("user_info"), dict) else {}
        tp_info = data.get("tp_info") if isinstance(data.get("tp_info"), dict) else {}
        items = data.get("item_list") or data.get("user_item_array") or []

        career_src = data.get("single_mode_chara_light") or data.get("single_mode_chara")
        if isinstance(career_data, dict):
            inner = unwrap_data(career_data)
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
            "clocks": item_count(items, 95),
            "career": career_out,
        }

    def format_veterans(self, raw_data: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not isinstance(raw_data, dict):
            return []
        data = unwrap_data(raw_data)
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
