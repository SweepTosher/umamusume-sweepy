import json
import re
from pathlib import Path

# Skill Markers
MARK_WHITE_CIRCLE = "○"  # U+25CB
MARK_DOUBLE_CIRCLE = "◎" # U+25CE
MARK_X = "×"             # U+00D7
MARK_LARGE_CIRCLE = "◯"  # U+25EF

# Mojibake variants found in logs/source
MOJI_WHITE_CIRCLE = "â—‹"
MOJI_LARGE_CIRCLE = "â—¯"
MOJI_DOUBLE_CIRCLE = "â—Ž"
MOJI_X = "Ã—"

SKILL_LEARN_PRIORITY_LIST = [
    [
        'Corner Acceleration ○', 'Corner Adept ○', 'Slipstream', 'Tail Held High',
        'Straightaway Spurt', 'Ramp Up', 'Inside Scoop', 'Passing Pro', 'Homestretch Haste',
        'Fast-Paced', 'Outer Swell', 'Sprinting Gear', 'Slick Surge', 'Corner Recovery ○',
        'Hydrate', 'After-School Stroll', 'Clean Heart', 'Dominator', 'All-Seeing Eyes', 'Mystifying Murmur'
    ],
    [
        'Acceleration', 'Focus', 'Go with the Flow', 'I Can See Right Through You',
        'Nimble Navigator', 'Straightaway Recovery', 'Deep Breaths', 'Preferred Position',
        'Groundwork', 'Up-Tempo', 'Unyielding Spirit', 'Pressure', 'Strategist', 'Triple 7s',
        'Shake It Out', 'Intimidate', 'Stamina Eater', 'Intense Gaze', 'Speed Star',
        'Staggering Lead', 'Blinding Flash', 'Restless', 'Trackblazer', 'Meticulous Measures',
        'Keeping the Lead', 'Leader\'s Pride', 'Wait-and-See', 'A Small Breather'
    ],
    [
        'Levelheaded', 'Stop Right There!', 'Super Lucky Seven', 'Maverick ○', 'Sympathy',
        'Long Shot ○', 'Inner Post Proficiency ○', 'Outer Post Proficiency ○', 'Right-Handed ○',
        'Left-Handed ○', 'Firm Conditions ○', 'Wet Conditions ○', 'Standard Distance ○',
        'Non-Standard Distance ○', 'Competitive Spirit ○', 'Target in Sight ○', 'Lone Wolf'
    ]
]


def norm(text):
    return re.sub(r'[^a-z0-9]+', '', str(text or '').lower())


def strip_mark(text):
    if not text:
        return ""
    for m in [MARK_WHITE_CIRCLE, MARK_DOUBLE_CIRCLE, MARK_X, MARK_LARGE_CIRCLE,
              MOJI_WHITE_CIRCLE, MOJI_DOUBLE_CIRCLE, MOJI_X, MOJI_LARGE_CIRCLE]:
        text = text.replace(m, "")
    return text.strip()


class SkillBuyer:
    def __init__(self, base_dir):
        self.base_dir = Path(base_dir)
        self.skill_names = {}
        self.skill_rarities = {}
        self.skill_costs = {}
        self.skill_grade_values = {}
        self.skill_id_exists = set()
        self.group_to_skill_ids = {}
        self.skill_to_group_id = {}
        self.failed_this_turn = {}
        self.current_turn = None
        self.last_candidates = []
        self.last_selected = []
        self.last_attempt = []
        self.last_result = {}
        self.recover_after_error = False
        self.attempt_events = []
        self._load()

    def _load(self):
        path = self.base_dir / "data" / "skill_data.json"
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self.skill_names = {}
            self.skill_rarities = {}
            self.skill_costs = {}
            self.skill_grade_values = {}
            self.skill_to_group_id = {}
            for raw_id, raw_info in data.items():
                skill_id = int(raw_id)
                if isinstance(raw_info, dict):
                    self.skill_names[skill_id] = raw_info.get("name") or str(skill_id)
                    self.skill_rarities[skill_id] = int(raw_info.get("rarity") or 0)
                    self.skill_costs[skill_id] = int(raw_info.get("need_skill_point") or 0)
                    self.skill_grade_values[skill_id] = int(raw_info.get("grade_value") or 0)
                    group_id = int(raw_info.get("group_id") or 0)
                    if group_id:
                        self.skill_to_group_id[skill_id] = group_id
                else:
                    self.skill_names[skill_id] = raw_info
        except Exception:
            return
        self.skill_id_exists = set(self.skill_names)
        self.group_to_skill_ids = {}
        for skill_id in self.skill_names:
            group_id = self.skill_to_group_id.get(skill_id) or (skill_id if skill_id < 100000 else skill_id // 10)
            self.skill_to_group_id[skill_id] = group_id
            self.group_to_skill_ids.setdefault(group_id, []).append(skill_id)
        
        for group_id, ids in self.group_to_skill_ids.items():
            children = [sid for sid in ids if sid >= 100000]
            if children:
                # Exclude the 5-digit parent group ID if 6-digit children exist
                self.group_to_skill_ids[group_id] = sorted(children, key=self._tier_sort_key)
            else:
                self.group_to_skill_ids[group_id] = sorted(ids, key=self._tier_sort_key)

    def _tier_sort_key(self, skill_id):
        grade_value = int(self.skill_grade_values.get(skill_id) or 0)
        return (
            int(self.skill_rarities.get(skill_id) or 99),
            1 if grade_value <= 0 else 0,
            grade_value if grade_value > 0 else 999999,
            int(skill_id),
        )

    def _tier_ids(self, group_id, rarity):
        ids = [
            sid for sid in self.group_to_skill_ids.get(group_id, [])
            if self.skill_rarities.get(sid, 0) == rarity and self.skill_grade_values.get(sid, 0) > 0
        ]
        return sorted(ids, key=self._tier_sort_key)

    def _resolve_buyable_tier(self, group_id, rarity, owned_skill_ids):
        tiers = self._tier_ids(group_id, rarity)
        if not tiers:
            candidates = [
                sid for sid in self.group_to_skill_ids.get(group_id, [])
                if self.skill_rarities.get(sid, 0) == rarity and sid not in owned_skill_ids
            ]
            return sorted(candidates, key=self._tier_sort_key)[0] if candidates else 0
        for index, sid in enumerate(tiers):
            if sid in owned_skill_ids:
                continue
            if index == 0 or tiers[index - 1] in owned_skill_ids:
                return sid
            return 0
        return 0

    def _unowned_white_tiers(self, group_id, owned_skill_ids):
        return [sid for sid in self._tier_ids(group_id, 1) if sid not in owned_skill_ids]

    def reset_scoped_failures(self):
        self.failed_this_turn = {}
        self.current_turn = None
        self.last_candidates = []
        self.last_selected = []
        self.last_attempt = []
        self.last_result = {}

    def _set_turn(self, turn):
        turn = int(turn or 0)
        if self.current_turn != turn:
            self.current_turn = turn
            self.failed_this_turn = {turn: set()}
        self.failed_this_turn.setdefault(turn, set())

    def _failed_for_turn(self, turn=None):
        turn = int(turn if turn is not None else self.current_turn or 0)
        return self.failed_this_turn.setdefault(turn, set())

    def buy(self, client, state, preset, force=False):
        data = state.get("data") or {}
        chara = data.get("chara_info") or data.get("single_mode_chara_light") or {}
        self.recover_after_error = False
        self.attempt_events = []
        if not chara:
            return state, 0

        points = int(chara.get("skill_point") or 0)
        turn = int(chara.get("turn") or 0)
        self._set_turn(turn)
        
        # Increase aggression if SP is very high
        is_hoarding = points > 1500
        threshold = int(preset.get("learn_skill_threshold") or 444)
        if not force and not is_hoarding and points <= threshold:
            self.last_candidates = []
            self.last_selected = []
            self.last_attempt = []
            self.last_result = {"skip": "threshold", "points": points, "threshold": threshold}
            return state, 0

        if preset.get("manual_purchase_at_end") and not force:
            self.last_candidates = []
            self.last_selected = []
            self.last_attempt = []
            self.last_result = {"skip": "manual_purchase_at_end"}
            return state, 0

        candidates = self._candidates(chara, preset)
        if force and not candidates:
            # At the end, try to buy ANY unknown skill if we have points
            candidates = self._candidates(chara, {**preset, "learn_skill_only_user_provided": False})

        self.last_candidates = [dict(item) for item in candidates]
        if not candidates:
            self.last_selected = []
            self.last_attempt = []
            self.last_result = {"skip": "no_candidates", "points": points}
            return state, 0

        selected = []
        spent = 0
        for candidate in candidates:
            cost = int(candidate.get("cost") or self._estimate_cost(candidate))
            if spent + cost > points:
                continue
            selected.append(candidate)
            spent += cost

        if not selected:
            self.last_selected = []
            self.last_attempt = []
            self.last_result = {"skip": "not_enough_points", "points": points}
            return state, 0

        self.last_selected = [dict(item) for item in selected]
        
        current_state, total_bought = self._buy_batch(client, state, selected, turn)
            
        return current_state, total_bought

    def preview(self, state, preset, force=False):
        data = state.get("data") or {}
        chara = data.get("chara_info") or data.get("single_mode_chara_light") or {}
        if not chara:
            self.last_candidates = []
            self.last_selected = []
            return
        turn = int(chara.get("turn") or 0)
        self._set_turn(turn)
        points = int(chara.get("skill_point") or 0)
        threshold = int(preset.get("learn_skill_threshold") or 444)
        if not force and points <= threshold:
            self.last_candidates = []
            self.last_selected = []
            return
        if preset.get("manual_purchase_at_end") and not force:
            self.last_candidates = []
            self.last_selected = []
            return
        candidates = self._candidates(chara, preset)
        selected = []
        spent = 0
        for candidate in candidates:
            cost = int(candidate.get("cost") or self._estimate_cost(candidate))
            if spent + cost > points:
                continue
            selected.append(candidate)
            spent += cost
        self.last_candidates = [dict(item) for item in candidates]
        self.last_selected = [dict(item) for item in selected]

    def _priority(self, rows):
        result = {}
        for index, row in enumerate(rows):
            for name in row:
                key = norm(name)
                result[key] = min(index, result.get(key, index))
        return result

    def _priority_value(self, skill_id, name, base_name, priority):
        values = [priority.get(str(skill_id)), priority.get(norm(name)), priority.get(norm(base_name))]
        values = [v for v in values if v is not None]
        return min(values) if values else 999

    def _priority_context(self, preset):
        raw_priority = preset.get("learn_skill_list") or []
        if not raw_priority and not preset.get("learn_skill_only_user_provided"):
            raw_priority = SKILL_LEARN_PRIORITY_LIST
        return self._priority(raw_priority)

    def _blacklist(self, preset):
        return {norm(item) for item in preset.get("learn_skill_blacklist") or []}

    def _candidates(self, chara, preset):
        owned = {int(item.get("skill_id") or 0) for item in chara.get("skill_array") or []}
        owned_groups = {self.skill_to_group_id.get(skill_id, skill_id // 10) for skill_id in owned}
        priority = self._priority_context(preset)
        blacklist = self._blacklist(preset)
        result = []
        for tip in chara.get("skill_tips_array") or []:
            resolved = self.resolve_skill_tip(tip, owned, owned_groups, priority, blacklist, preset)
            if not resolved or resolved.get("skip_reason"):
                continue
            result.append({
                "skill_id": resolved["resolved_skill_id"],
                "group_id": resolved["group_id"],
                "tip_rarity": resolved["tip_rarity"],
                "hint_level": resolved["hint_level"],
                "name": resolved["resolved_name"],
                "priority": resolved["priority"],
                "cost": resolved["cost"],
                "bundled_skill_ids": resolved.get("bundled_skill_ids") or [],
                "resolution_reason": resolved["resolution_reason"],
                "failed_scope": resolved["failed_scope"],
                "candidate_skill_ids": resolved["candidate_skill_ids"],
            })
        result.sort(key=lambda item: (item["priority"], -item["hint_level"], item["cost"], item["skill_id"]))
        
        deduped = []
        seen = set()
        for item in result:
            if item["skill_id"] not in seen:
                seen.add(item["skill_id"])
                deduped.append(item)
        result = deduped
        
        if preset.get("learn_skill_only_user_provided"):
            if not any(row for row in (preset.get("learn_skill_list") or [])):
                return []
            return [item for item in result if item["priority"] < 999]
        return result

    def resolve_skill_tip(self, tip, owned_skill_ids, owned_groups, priority, blacklist, preset):
        group_id = int(tip.get("group_id") or 0)
        tip_rarity = int(tip.get("rarity") or 0)
        hint_level = int(tip.get("level") or 0)
        failed = self._failed_for_turn()
        if tip_rarity:
            buyable_tier = self._resolve_buyable_tier(group_id, tip_rarity, owned_skill_ids)
            candidate_skill_ids = [buyable_tier] if buyable_tier else []
        else:
            candidate_skill_ids = [
                sid for sid in self.group_to_skill_ids.get(group_id, [])
                if sid not in owned_skill_ids
            ]
        
        row = {
            "group_id": group_id,
            "tip_rarity": tip_rarity,
            "hint_level": hint_level,
            "candidate_skill_ids": list(candidate_skill_ids),
            "resolved_skill_id": 0,
            "resolved_name": "",
            "cost": 0,
            "priority": 999,
            "resolution_reason": "",
            "master_exists": False,
            "skip_reason": None,
            "failed_scope": None,
        }
        if not candidate_skill_ids:
            row["skip_reason"] = "unknown_master"
            return row

        usable = [sid for sid in candidate_skill_ids if sid not in failed]
        if not usable:
            row["skip_reason"] = "failed_this_turn"
            row["failed_scope"] = "this_turn"
            return row

        normal = [sid for sid in usable if not (self.skill_names.get(sid, "").endswith(MARK_X) or self.skill_names.get(sid, "").endswith(MOJI_X))]
        if not normal:
            row["skip_reason"] = "no_normal_skills"
            return row

        normal.sort(key=self._tier_sort_key)
        resolved = normal[0]
        name = self.skill_names.get(resolved, "")
        
        best_priority = 999
        reason = "first_valid_variant"
        
        for sid in normal:
            s_name = self.skill_names.get(sid, "")
            base_name = strip_mark(s_name)
            if norm(s_name) in blacklist or norm(base_name) in blacklist:
                row["skip_reason"] = "blacklist"
                return row
            p_val = self._priority_value(sid, s_name, base_name, priority)
            if p_val < best_priority:
                best_priority = p_val
                reason = "priority_match"
                
        if best_priority == 999:
            for sid in normal:
                s_name = self.skill_names.get(sid, "")
                if any(s_name.endswith(m) for m in [MARK_WHITE_CIRCLE, MARK_LARGE_CIRCLE, MOJI_WHITE_CIRCLE, MOJI_LARGE_CIRCLE]):
                    best_priority = 500
                    reason = "circle_variant"
                    break

        if not name:
            row["skip_reason"] = "unknown_master"
            return row
            
        # Double circle rule
        is_double = name.endswith(MARK_DOUBLE_CIRCLE) or name.endswith(MOJI_DOUBLE_CIRCLE)
        if preset.get("skip_double_circle_unless_high_hint", False) and is_double and hint_level < 4:
            row["skip_reason"] = "rule_rejected"
            return row

        row["resolved_skill_id"] = resolved
        row["resolved_name"] = name
        bundled_skill_ids = []
        cost = self._estimate_cost({"skill_id": resolved, "hint_level": hint_level, "name": name})
        if self.skill_rarities.get(resolved, 0) == 2:
            bundled_skill_ids = self._unowned_white_tiers(group_id, owned_skill_ids)
            for bundled_id in bundled_skill_ids:
                cost += self._estimate_cost({
                    "skill_id": bundled_id,
                    "hint_level": 0,
                    "name": self.skill_names.get(bundled_id, ""),
                })

        row["priority"] = best_priority
        row["cost"] = cost
        row["bundled_skill_ids"] = bundled_skill_ids
        row["resolution_reason"] = reason
        row["master_exists"] = resolved in self.skill_id_exists
        if resolved in failed:
            row["failed_scope"] = "this_turn"

        return row

    def _buy_batch(self, client, state, candidates, turn):
        if not candidates:
            return state, 0

        data = state.get("data") or {}
        chara = data.get("chara_info") or data.get("single_mode_chara_light") or {}
        current_turn = int(chara.get("turn") or 0)
        
        if current_turn != turn:
            self.last_result = {"skip": "stale_turn_detected", "request_current_turn": turn, "source_state_turn": current_turn}
            return state, 0

        valid_tips = set()
        for tip in chara.get("skill_tips_array") or []:
            group_id = int(tip.get("group_id") or 0)
            valid_tips.update(self.group_to_skill_ids.get(group_id, []))

        points = int(chara.get("skill_point") or 0)
        selected_total_cost = 0
        valid_candidates = []

        for item in candidates:
            skill_id = item["skill_id"]
            cost = int(item.get("cost") or 0)
            if skill_id <= 0 or item.get("skip_reason"):
                item["preflight_error"] = "invalid_skill"
                continue
            if skill_id not in valid_tips:
                item["preflight_error"] = "not_in_tips"
                continue
            if selected_total_cost + cost > points:
                item["preflight_error"] = "unaffordable"
                continue
            item["preflight_passed"] = True
            selected_total_cost += cost
            valid_candidates.append(item)

        if not valid_candidates:
            self.last_result = {"skip": "preflight_failed", "turn": turn, "points": points}
            return state, 0

        payload = []
        payload_ids = set()
        for item in valid_candidates:
            for skill_id in [item["skill_id"], *(item.get("bundled_skill_ids") or [])]:
                skill_id = int(skill_id or 0)
                if skill_id > 0 and skill_id not in payload_ids:
                    payload.append({"skill_id": skill_id, "level": 1})
                    payload_ids.add(skill_id)
        self.last_attempt = [dict(item) for item in valid_candidates]
        event = {
            "turn": turn,
            "selected": [dict(item) for item in candidates],
            "attempt": [dict(item) for item in valid_candidates],
            "payload": payload,
            "result": {},
        }
        self.attempt_events.append(event)

        print(f"DEBUG: Sending gain_skills payload at turn {turn}: {json.dumps(payload)}")
        try:
            if hasattr(client, "wait_complex_delay"):
                client.wait_complex_delay()
            result = client.gain_skills(payload, turn)
            self.last_result = {"result": "ok", "turn": turn, "count": len(valid_candidates), "payload": payload}
            event["result"] = self.last_result
            self._failed_for_turn(turn).clear()
            return result, len(valid_candidates)
        except Exception as exc:
            print(f"Skill Purchase Error at turn {turn}: {exc}")
            if any(code in str(exc) for code in ("201", "205", "208")):
                self.recover_after_error = True
                # Refresh state immediately to get true SP count
                try:
                    fresh_state = client.load_career()
                    if fresh_state:
                        state = fresh_state
                except Exception:
                    pass
            self._failed_for_turn(turn).update(int(item["skill_id"]) for item in valid_candidates)
            self.last_result = {"result": "failed", "turn": turn, "error": str(exc), "payload": payload}
            event["result"] = self.last_result
            return state, 0


    def _select_skill_id(self, group_id, priority, owned, rarity=0):
        owned_groups = {self.skill_to_group_id.get(sid, sid // 10) for sid in owned}
        resolved = self.resolve_skill_tip({"group_id": group_id, "rarity": rarity, "level": 0}, set(owned), owned_groups, priority, set(), {})
        return int((resolved or {}).get("resolved_skill_id") or 0)

    def _estimate_cost(self, candidate):
        name = candidate.get("name") or ""
        skill_id = candidate.get("skill_id") or 0
        level = candidate.get("hint_level") or 0
        
        is_circle = any(m in name for m in [MARK_WHITE_CIRCLE, MARK_LARGE_CIRCLE, MOJI_WHITE_CIRCLE, MOJI_LARGE_CIRCLE])
        
        if is_circle:
            base = 130
        elif skill_id >= 900000:
            base = 200
        else:
            base = self.skill_costs.get(skill_id)
            if not base:
                base = 200 if self.skill_rarities.get(skill_id, 0) >= 2 else 160
        return max(1, int(base * (100 - min(level, 5) * 10) / 100))
