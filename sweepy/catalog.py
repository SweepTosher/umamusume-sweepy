from __future__ import annotations

import json
from pathlib import Path
from typing import Any



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
