from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

HINT_DISCOUNT = (0, 10, 20, 30, 35, 40)
BRANCH_TOKEN = re.compile(r"(distance_type|running_style)==([1-4])")
APTITUDE_DEFAULTS = (
    ("proper_ground_turf", 7),
    ("proper_ground_dirt", 1),
    ("proper_distance_short", 4),
    ("proper_distance_mile", 6),
    ("proper_distance_middle", 7),
    ("proper_distance_long", 6),
    ("proper_running_style_nige", 6),
    ("proper_running_style_senko", 7),
    ("proper_running_style_sashi", 7),
    ("proper_running_style_oikomi", 4),
)
CATALOG_ENV = "SWEEPY_SKILL_CATALOG"
CATALOG_PATH = Path(__file__).resolve().parent / "data" / "skill_catalog.json"


def _apt_nd(rank: int) -> tuple[int, int]:
    value = max(1, min(8, int(rank)))
    if value == 1:
        return 7, 10
    if value <= 4:
        return 8, 10
    if value <= 6:
        return 9, 10
    return 11, 10


def _branches(condition_1: Any, condition_2: Any) -> tuple[tuple[int, int], ...]:
    branches: list[tuple[int, int]] = []
    for condition in (condition_1 or "", condition_2 or ""):
        if not condition:
            continue
        unconditional = False
        for chunk in str(condition).split("@"):
            distance = 0
            style = 0
            has_predicate = False
            for token in chunk.split("&"):
                match = BRANCH_TOKEN.fullmatch(token.strip())
                if not match:
                    continue
                has_predicate = True
                if match.group(1) == "distance_type" and distance == 0:
                    distance = int(match.group(2))
                elif match.group(1) == "running_style" and style == 0:
                    style = int(match.group(2))
            if not has_predicate:
                unconditional = True
                break
            branches.append((distance, style))
        if unconditional:
            return ()
    return tuple(branches)


def _aptitudes(chara: Mapping[str, Any]) -> list[int]:
    return [
        int(chara[key]) if chara.get(key) is not None else default
        for key, default in APTITUDE_DEFAULTS
    ]


def _score(entry: Mapping[str, Any], apts: list[int]) -> int:
    grade = int(entry["grade_value"])
    branches = entry["branches"]
    if not branches:
        return grade
    best_n = 0
    best_d = 1
    for distance, style in branches:
        n, d = 1, 1
        if 1 <= distance <= 4:
            fn, fd = _apt_nd(apts[1 + distance])
            n *= fn
            d *= fd
        if 1 <= style <= 4:
            fn, fd = _apt_nd(apts[5 + style])
            n *= fn
            d *= fd
        if best_n == 0 or n * best_d > best_n * d:
            best_n, best_d = n, d
    if grade >= 0:
        return (2 * grade * best_n + best_d) // (2 * best_d)
    return -((2 * (-grade) * best_n + best_d) // (2 * best_d))


class SkillShop:
    def __init__(self, payload: Mapping[str, Any]) -> None:
        self.skills: dict[int, dict[str, Any]] = {}
        self.groups: dict[int, list[dict[str, Any]]] = {}
        self.innate: dict[int, set[int]] = {
            int(card_id): {int(skill_id) for skill_id in skill_ids}
            for card_id, skill_ids in (payload.get("innate") or {}).items()
        }
        self.awakening: dict[int, list[tuple[int, int]]] = {
            int(card_id): [(int(pair[0]), int(pair[1])) for pair in pairs]
            for card_id, pairs in (payload.get("awakening") or {}).items()
        }
        rows = [row for row in (payload.get("skills") or []) if isinstance(row, (list, tuple))]
        for row in rows:
            skill_id = int(row[0])
            group_id = int(row[2])
            group_rate = int(row[3])
            entry = {
                "skill_id": skill_id,
                "rarity": int(row[1]),
                "group_id": group_id,
                "group_rate": group_rate,
                "grade_value": int(row[4]),
                "base_cost": int(row[5]),
                "branches": _branches(row[6], row[7]),
            }
            self.skills[skill_id] = entry
            if entry["grade_value"] > 0 and group_rate >= 1:
                self.groups.setdefault(group_id, []).append(entry)
        for entries in self.groups.values():
            entries.sort(key=lambda item: item["group_rate"])

    def _hints(
        self, chara: Mapping[str, Any]
    ) -> tuple[dict[tuple[int, int], int], dict[int, int]]:
        by_group: dict[tuple[int, int], int] = {}
        by_skill: dict[int, int] = {}
        for tip in chara.get("skill_tips_array") or []:
            if not isinstance(tip, Mapping):
                continue
            level = int(tip.get("level", tip.get("skill_level", tip.get("tips_level", 0))) or 0)
            if "group_id" in tip and "rarity" in tip:
                key = (int(tip["group_id"]), int(tip["rarity"]))
                by_group[key] = max(by_group.get(key, 0), level)
            elif "group_id" in tip:
                key = (int(tip["group_id"]), 1)
                by_group[key] = max(by_group.get(key, 0), level)
            if "skill_id" in tip:
                skill_id = int(tip["skill_id"])
                by_skill[skill_id] = max(by_skill.get(skill_id, 0), level)
        return by_group, by_skill

    def _unlocked_card_skills(self, chara: Mapping[str, Any]) -> set[int]:
        card_id = int(chara.get("card_id") or 0)
        talent_level = int(chara.get("talent_level") or 1)
        unlocked = set(self.innate.get(card_id, ()))
        for need_rank, skill_id in self.awakening.get(card_id, ()):
            if talent_level >= need_rank and skill_id > 0:
                unlocked.add(skill_id)
        return unlocked

    def optimal(self, chara: Mapping[str, Any]) -> list[int]:
        budget = int(chara.get("skill_point") or 0)
        if budget <= 0:
            return []
        apts = _aptitudes(chara)
        owned_by_group: dict[int, dict[str, Any]] = {}
        for item in chara.get("skill_array") or []:
            if not isinstance(item, Mapping):
                continue
            entry = self.skills.get(int(item.get("skill_id") or 0))
            if entry:
                prev = owned_by_group.get(entry["group_id"])
                if prev is None or entry["group_rate"] > prev["group_rate"]:
                    owned_by_group[entry["group_id"]] = entry
        hint_group, hint_skill = self._hints(chara)
        effects = {int(value) for value in (chara.get("chara_effect_id_array") or [])}
        fast_learner = (7 in effects) or bool(chara.get("fast_learner", False))
        innate = self._unlocked_card_skills(chara)

        def hint_level(entry: Mapping[str, Any]) -> int:
            own = hint_skill.get(int(entry["skill_id"]), 0)
            grouped = hint_group.get((int(entry["group_id"]), int(entry["rarity"])), 0)
            return min(5, max(0, max(own, grouped)))

        def tier_cost(entry: Mapping[str, Any]) -> int:
            discount = min(100, HINT_DISCOUNT[hint_level(entry)] + (10 if fast_learner else 0))
            return max(10, (int(entry["base_cost"]) * (100 - discount)) // 100)

        options: list[list[tuple[int, int, tuple[int, ...]]]] = []
        for entries in self.groups.values():
            owned = owned_by_group.get(entries[0]["group_id"])
            owned_rate = owned["group_rate"] if owned else 0
            any_hint = any(hint_level(item) > 0 for item in entries)
            any_innate = any(item["skill_id"] in innate for item in entries)
            if not any_hint and not any_innate:
                continue
            old_score = _score(owned, apts) if owned else 0
            group_options: list[tuple[int, int, tuple[int, ...]]] = []
            cumulative = 0
            chain: list[int] = []
            for entry in entries:
                if entry["group_rate"] <= owned_rate:
                    continue
                cumulative += tier_cost(entry)
                chain.append(int(entry["skill_id"]))
                if entry["rarity"] == 1:
                    legal = any_hint or any_innate
                else:
                    legal = hint_level(entry) > 0 or entry["skill_id"] in innate
                if not legal:
                    continue
                net = _score(entry, apts) - old_score
                if net > 0 and cumulative <= budget:
                    group_options.append((cumulative, net, tuple(chain)))
            if group_options:
                options.append(group_options)
        if not options:
            return []
        best = [-1] * (budget + 1)
        best[0] = 0
        parents: list[dict[int, tuple[int, tuple[int, ...]]]] = []
        for group_options in options:
            nxt = list(best)
            choices: dict[int, tuple[int, tuple[int, ...]]] = {}
            for spent in range(budget + 1):
                base = best[spent]
                if base < 0:
                    continue
                for cost, value, sids in group_options:
                    total = spent + cost
                    if total <= budget and base + value > nxt[total]:
                        nxt[total] = base + value
                        choices[total] = (spent, sids)
            best = nxt
            parents.append(choices)
        best_spent = 0
        best_value = 0
        for spent in range(budget + 1):
            if best[spent] > best_value:
                best_value = best[spent]
                best_spent = spent
        if best_value <= 0:
            return []
        chosen: list[int] = []
        current = best_spent
        for index in range(len(options) - 1, -1, -1):
            choice = parents[index].get(current)
            if choice is None:
                continue
            previous, sids = choice
            chosen.extend(reversed(sids))
            current = previous
        chosen.reverse()
        return chosen


_shop_cache: dict[str, SkillShop | None] = {}


def catalog_path() -> Path:
    override = (os.environ.get(CATALOG_ENV) or "").strip()
    if override:
        return Path(os.path.expanduser(override))
    return CATALOG_PATH


def terminal_skill_shop() -> SkillShop | None:
    path = catalog_path()
    key = str(path)
    if key in _shop_cache:
        return _shop_cache[key]
    shop: SkillShop | None = None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, Mapping):
            shop = SkillShop(payload)
    except (OSError, ValueError, TypeError):
        shop = None
    _shop_cache[key] = shop
    return shop


def terminal_skill_bundle(chara: Mapping[str, Any] | None) -> list[dict[str, int]]:
    if not isinstance(chara, Mapping):
        return []
    shop = terminal_skill_shop()
    if shop is None:
        return []
    try:
        chosen = shop.optimal(chara)
    except (KeyError, ValueError, TypeError):
        return []
    return [{"skill_id": int(skill_id), "level": 1} for skill_id in chosen]
