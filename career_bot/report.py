import json
import re
import traceback
from datetime import datetime
from pathlib import Path


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def new_report(preset=None, scenario_id=0):
    preset = preset or {}
    return {
        "started_at": now_iso(),
        "ended_at": None,
        "preset_name": preset.get("name", ""),
        "scenario_id": scenario_id,
        "status": "running",
        "error": None,
        "final_turn": 0,
        "turns": [],
    }


def safe_int(value, default=0):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def turn_from_event(event):
    data = event.get("data") or {}
    for key in ("payload", "request_payload"):
        payload = data.get(key) or {}
        if payload.get("current_turn") is not None:
            return safe_int(payload.get("current_turn"))
    if event.get("turn") is not None:
        return safe_int(event.get("turn"))
    return 0


def get_turn(report, turn_number):
    turn_number = safe_int(turn_number)
    for turn in report.setdefault("turns", []):
        if safe_int(turn.get("turn")) == turn_number:
            return turn
    turn = {
        "turn": turn_number,
        "api_calls": [],
        "skill_buy_attempts": [],
        "item_buy_attempts": [],
        "item_usage_attempts": [],
    }
    report.setdefault("turns", []).append(turn)
    report["turns"].sort(key=lambda row: safe_int(row.get("turn")))
    return turn


def merge_turn(report, row):
    turn_number = safe_int(row.get("turn"))
    turn = get_turn(report, turn_number)
    preserved = {
        "api_calls": turn.get("api_calls") or [],
        "skill_buy_attempts": turn.get("skill_buy_attempts") or [],
        "item_buy_attempts": turn.get("item_buy_attempts") or [],
        "item_usage_attempts": turn.get("item_usage_attempts") or [],
    }
    turn.update(row)
    for key, value in preserved.items():
        turn[key] = value
    report["final_turn"] = max(safe_int(report.get("final_turn")), turn_number)
    return turn


def add_event(report, row):
    event = row.get("event")
    turn = get_turn(report, row.get("turn"))
    if event == "turn":
        return merge_turn(report, row)
    if event == "skills_attempt":
        turn.setdefault("skill_buy_attempts", []).append(row)
    elif event == "items_buy_attempt":
        turn.setdefault("item_buy_attempts", []).append(row)
    elif event == "items_use_attempt":
        turn.setdefault("item_usage_attempts", []).append(row)
    else:
        turn.setdefault("events", []).append(row)
    report["final_turn"] = max(safe_int(report.get("final_turn")), safe_int(row.get("turn")))
    return turn


def add_api_call(report, event):
    turn = get_turn(report, turn_from_event(event))
    turn.setdefault("api_calls", []).append(event)
    report["final_turn"] = max(safe_int(report.get("final_turn")), safe_int(turn.get("turn")))


def add_decision(report, state, decision):
    data = (state or {}).get("data") or {}
    chara = data.get("chara_info") or {}
    payload = dict(getattr(decision, "payload", {}) or {})
    turn = get_turn(report, payload.get("current_turn") or chara.get("turn") or 0)
    turn["current_command"] = payload
    turn["selected_action"] = getattr(decision, "action", "")
    turn["decision_reason"] = getattr(decision, "reason", "")
    turn["current_action_taken"] = getattr(decision, "action", "")


def set_error(report, exc):
    report["status"] = "error"
    report["error"] = {
        "type": type(exc).__name__,
        "message": str(exc),
        "stack_trace": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
    }


def finish_report(report, status=None):
    if status:
        report["status"] = status
    if report.get("status") == "running":
        report["status"] = "finished"
    report["ended_at"] = now_iso()
    turns = report.get("turns") or []
    if turns:
        report["final_turn"] = max(safe_int(turn.get("turn")) for turn in turns)


def write_report(report, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"career_log_{stamp}.json"
    
    def _json_default(obj):
        if isinstance(obj, bytes):
            return obj.hex()
        return str(obj)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=_json_default)
    
    latest = output_dir / "latest_career_log.json"
    try:
        import shutil
        shutil.copyfile(path, latest)
    except Exception:
        pass
    return path
