ITEM_NAMES = {
    1001: "Speed Notepad",
    1002: "Stamina Notepad",
    1003: "Power Notepad",
    1004: "Guts Notepad",
    1005: "Wit Notepad",
    1101: "Speed Manual",
    1102: "Stamina Manual",
    1103: "Power Manual",
    1104: "Guts Manual",
    1105: "Wit Manual",
    1201: "Speed Scroll",
    1202: "Stamina Scroll",
    1203: "Power Scroll",
    1204: "Guts Scroll",
    1205: "Wit Scroll",
    2001: "Vita 20",
    2002: "Vita 40",
    2003: "Vita 65",
    2101: "Royal Kale Juice",
    2201: "Energy Drink MAX",
    2202: "Energy Drink MAX EX",
    2301: "Plain Cupcake",
    2302: "Berry Sweet Cupcake",
    3001: "Yummy Cat Food",
    3101: "Grilled Carrots",
    4001: "Pretty Mirror",
    4002: "Reporter's Binoculars",
    4003: "Master Practice Guide",
    4004: "Scholar's Hat",
    4101: "Fluffy Pillow",
    4102: "Pocket Planner",
    4103: "Rich Hand Cream",
    4104: "Smart Scale",
    4105: "Aroma Diffuser",
    4106: "Practice Drills DVD",
    4201: "Miracle Cure",
    5001: "Speed Training Application",
    5002: "Stamina Training Application",
    5003: "Power Training Application",
    5004: "Guts Training Application",
    5005: "Wit Training Application",
    7001: "Reset Whistle",
    8001: "Coaching Megaphone",
    8002: "Motivating Megaphone",
    8003: "Empowering Megaphone",
    9001: "Speed Ankle Weights",
    9002: "Stamina Ankle Weights",
    9003: "Power Ankle Weights",
    9004: "Guts Ankle Weights",
    10001: "Good-Luck Charm",
    11001: "Artisan Cleat Hammer",
    11002: "Master Cleat Hammer",
    11003: "Glow Sticks",
}

DISPLAY_TO_ID = {v: k for k, v in ITEM_NAMES.items()}

SLUG_TO_DISPLAY = {name.lower().replace("'", "").replace(" ", "_"): name for name in ITEM_NAMES.values()}

SHOP_ITEM_COSTS = {
    "Speed Notepad": 10, "Stamina Notepad": 10, "Power Notepad": 10, "Guts Notepad": 10, "Wit Notepad": 10,
    "Speed Manual": 15, "Stamina Manual": 15, "Power Manual": 15, "Guts Manual": 15, "Wit Manual": 15,
    "Speed Scroll": 30, "Stamina Scroll": 30, "Power Scroll": 30, "Guts Scroll": 30, "Wit Scroll": 30,
    "Vita 20": 35, "Vita 40": 55, "Vita 65": 75, "Royal Kale Juice": 70,
    "Energy Drink MAX": 30, "Energy Drink MAX EX": 50,
    "Plain Cupcake": 30, "Berry Sweet Cupcake": 55,
    "Yummy Cat Food": 10, "Grilled Carrots": 40,
    "Pretty Mirror": 150, "Reporter's Binoculars": 150, "Master Practice Guide": 150, "Scholar's Hat": 280,
    "Fluffy Pillow": 15, "Pocket Planner": 15, "Rich Hand Cream": 15, "Smart Scale": 15,
    "Aroma Diffuser": 15, "Practice Drills DVD": 15, "Miracle Cure": 40,
    "Speed Training Application": 150, "Stamina Training Application": 150,
    "Power Training Application": 150, "Guts Training Application": 150, "Wit Training Application": 150,
    "Reset Whistle": 20,
    "Coaching Megaphone": 40, "Motivating Megaphone": 55, "Empowering Megaphone": 70,
    "Speed Ankle Weights": 50, "Stamina Ankle Weights": 50, "Power Ankle Weights": 50, "Guts Ankle Weights": 50,
    "Good-Luck Charm": 40,
    "Artisan Cleat Hammer": 25, "Master Cleat Hammer": 40,
    "Glow Sticks": 15,
}

AILMENT_CURE_MAP = {
    "Night Owl": "Fluffy Pillow",
    "Slacker": "Pocket Planner",
    "Skin Outbreak": "Rich Hand Cream",
    "Slow Metabolism": "Smart Scale",
    "Migraine": "Aroma Diffuser",
    "Practice Poor": "Practice Drills DVD",
}

BAD_EFFECT_NAMES = {
    1: "Night Owl",
    2: "Slacker",
    3: "Skin Outbreak",
    4: "Slow Metabolism",
    5: "Migraine",
    6: "Practice Poor",
}

AILMENT_CURE_ALL = "Miracle Cure"

CURE_ITEMS = set(AILMENT_CURE_MAP.values()) | {AILMENT_CURE_ALL}

INSTANT_USE_ITEMS = [
    "Grilled Carrots",
    "Yummy Cat Food",
    "Energy Drink MAX EX",
    "Pretty Mirror",
    "Scholar's Hat",
    "Reporter's Binoculars",
    "Master Practice Guide",
    "Speed Notepad", "Stamina Notepad", "Power Notepad", "Guts Notepad", "Wit Notepad",
    "Speed Manual", "Stamina Manual", "Power Manual", "Guts Manual", "Wit Manual",
    "Speed Scroll", "Stamina Scroll", "Power Scroll", "Guts Scroll", "Wit Scroll",
    "Speed Training Application", "Stamina Training Application",
    "Power Training Application", "Guts Training Application", "Wit Training Application",
]

ONE_TIME_BUFF_ITEMS = {
    "Pretty Mirror",
    "Scholar's Hat",
    "Reporter's Binoculars",
    "Master Practice Guide",
}

ENERGY_ITEMS = {
    "Vita 20": 20,
    "Vita 40": 40,
    "Vita 65": 65,
    "Royal Kale Juice": 100,
}

MEGAPHONE_TIERS = {
    "Coaching Megaphone": (1, 4),
    "Motivating Megaphone": (2, 3),
    "Empowering Megaphone": (3, 2),
}

TRAINING_TYPE_ANKLET = {
    101: "Speed Ankle Weights",
    601: "Speed Ankle Weights",
    105: "Stamina Ankle Weights",
    602: "Stamina Ankle Weights",
    102: "Power Ankle Weights",
    603: "Power Ankle Weights",
    103: "Guts Ankle Weights",
    604: "Guts Ankle Weights",
}

TRAINING_ITEM_DECK_TYPE_INDEX = {
    "Speed Ankle Weights": 0,
    "Stamina Ankle Weights": 1,
    "Power Ankle Weights": 2,
    "Guts Ankle Weights": 3,
    "Speed Training Application": 0,
    "Stamina Training Application": 1,
    "Power Training Application": 2,
    "Guts Training Application": 3,
    "Wit Training Application": 4,
}

DEFAULT_ITEM_TIERS = {
    "speed_notepad": 1,
    "speed_manual": 1,
    "speed_scroll": 1,
    "stamina_notepad": 1,
    "stamina_manual": 1,
    "stamina_scroll": 1,
    "power_notepad": 1,
    "power_manual": 1,
    "power_scroll": 1,
    "guts_notepad": 1,
    "guts_manual": 1,
    "guts_scroll": 1,
    "wit_notepad": 1,
    "wit_manual": 1,
    "wit_scroll": 1,
    "vita_20": 3,
    "vita_40": 2,
    "vita_65": 2,
    "royal_kale_juice": 3,
    "energy_drink_max": 6,
    "energy_drink_max_ex": 7,
    "plain_cupcake": 3,
    "berry_sweet_cupcake": 4,
    "yummy_cat_food": 7,
    "grilled_carrots": 4,
    "pretty_mirror": 7,
    "reporters_binoculars": 8,
    "master_practice_guide": 7,
    "scholars_hat": 8,
    "fluffy_pillow": 7,
    "pocket_planner": 7,
    "rich_hand_cream": 5,
    "smart_scale": 7,
    "aroma_diffuser": 7,
    "practice_drills_dvd": 8,
    "miracle_cure": 5,
    "speed_training_application": 7,
    "stamina_training_application": 7,
    "power_training_application": 7,
    "guts_training_application": 7,
    "wit_training_application": 7,
    "reset_whistle": 1,
    "coaching_megaphone": 999,
    "motivating_megaphone": 3,
    "empowering_megaphone": 3,
    "speed_ankle_weights": 7,
    "stamina_ankle_weights": 7,
    "power_ankle_weights": 7,
    "guts_ankle_weights": 7,
    "good-luck_charm": 3,
    "artisan_cleat_hammer": 1,
    "master_cleat_hammer": 1,
    "glow_sticks": 8,
}


def display_to_slug(name):
    return str(name or "").lower().replace("'", "").replace(" ", "_")


class MantItemManager:
    def __init__(self):
        self.used_buffs = set()
        self.failed_exchange_this_snapshot = set()
        self.failed_use_this_turn = set()
        self.current_turn = None
        self.shop_snapshot_key = None
        self.recover_after_exchange_error = False
        self.recover_after_use_error = False
        self.last_buy_options = []
        self.last_buy_selected = []
        self.last_buy_attempt = []
        self.last_buy_result = {}
        self.last_use_options = []
        self.last_use_selected = []
        self.last_use_attempt = []
        self.last_use_result = {}
        self.last_pre_race_use_selected = []
        self.last_pre_race_use_attempt = []
        self.last_pre_race_use_result = {}
        self.buy_attempt_events = []
        self.use_attempt_events = []

    def reset_scoped_failures(self):
        self.failed_exchange_this_snapshot = set()
        self.failed_use_this_turn = set()
        self.current_turn = None
        self.shop_snapshot_key = None
        self.last_buy_options = []
        self.last_buy_selected = []
        self.last_buy_attempt = []
        self.last_buy_result = {}
        self.last_use_options = []
        self.last_use_selected = []
        self.last_use_attempt = []
        self.last_use_result = {}
        self.buy_attempt_events = []
        self.use_attempt_events = []

    def _set_turn(self, turn):
        turn = int(turn or 0)
        if self.current_turn != turn:
            self.current_turn = turn
            self.failed_use_this_turn = set()

    def _set_shop_snapshot(self, rows):
        key = tuple(
            (
                int(row.get("shop_item_id") or 0),
                int(row.get("item_id") or 0),
                int(row.get("coin_num") or 0),
                int(row.get("item_buy_num") or 0),
                int(row.get("limit_buy_count") or 0),
                int(row.get("limit_turn") or 0),
            )
            for row in rows or []
        )
        if self.shop_snapshot_key != key:
            self.shop_snapshot_key = key
            self.failed_exchange_this_snapshot = set()

    def handle(self, client, state, preset, best_command=None, status=None, race_planner=None):
        current = state
        current, bought = self.buy_shop_items(client, current, preset, race_planner)
        if bought > 0 or self.recover_after_exchange_error:
            current = self._reload_career(client, current, "buy")
        current, used = self.use_items(client, current, preset, best_command, status, race_planner)
        if used > 0 or self.recover_after_use_error:
            current = self._reload_career(client, current, "use")
        return current, bought, used

    def handle_pre_race(self, client, state, preset, payload, status=None, race_planner=None):
        current, bought = self.buy_shop_items(client, state, preset, race_planner)
        if bought > 0 or self.recover_after_exchange_error:
            current = self._reload_career(client, current, "pre_race_buy")

        current, instant_used = self.use_items(client, current, preset, None, status, race_planner)
        if instant_used > 0 or self.recover_after_use_error:
            current = self._reload_career(client, current, "pre_race_use")

        data = current.get("data") or {}
        free = data.get("free_data_set") or {}
        chara = data.get("chara_info") or {}
        owned = self._owned_map(free)
        self.last_pre_race_use_selected = []
        self.last_pre_race_use_attempt = []
        self.last_pre_race_use_result = {}

        turn = int(chara.get("turn") or 0)
        self._set_turn(turn)
        program_id = int((payload or {}).get("program_id") or 0)

        if not owned:
            self.last_pre_race_use_result = {"skip": "no_owned"}
            return current, instant_used

        targets = []
        SUMMER_CAMP_2_START = 60
        CLIMAX_RACE_TURNS = [74, 76, 78]

        vital = int(chara.get("vital") or 0)
        if owned.get("Energy Drink MAX", 0) > 0 and vital <= 1:
            targets.append(("Energy Drink MAX", 1))

        cleat_choice = self._old_ui_cleat_before_race(owned, turn, program_id, race_planner)
        is_climax_race = turn in CLIMAX_RACE_TURNS
        is_g1 = self._is_g1_program(program_id, race_planner)
        use_gear = cleat_choice is not None or is_climax_race or is_g1 or turn > SUMMER_CAMP_2_START
        if use_gear and owned.get("Glow Sticks", 0) > 0:
            targets.append(("Glow Sticks", 1))
        if cleat_choice:
            targets.append((cleat_choice, 1))

        targets = self._merge_targets(targets, owned)
        self.last_pre_race_use_selected = [{"name": name, "item_id": DISPLAY_TO_ID.get(name), "use_num": count} for name, count in targets]
        if not targets:
            self.last_pre_race_use_result = {"skip": "no_targets"}
            return current, instant_used

        use_payload = []
        for name, count in targets:
            item_id = DISPLAY_TO_ID.get(name)
            if not item_id or item_id in self.failed_use_this_turn:
                continue
            item_count = int(owned.get(name) or 0)
            if item_count <= 0:
                continue
            use_payload.append({"item_id": item_id, "use_num": min(count, item_count), "current_num": item_count})

        if use_payload:
            self.last_pre_race_use_attempt = list(use_payload)
            event = {
                "turn": turn,
                "selected": list(self.last_pre_race_use_selected),
                "attempt": list(use_payload),
                "payload": list(use_payload),
                "result": {},
            }
            self.use_attempt_events.append(event)
            try:
                if hasattr(client, "wait_complex_delay"):
                    client.wait_complex_delay()
                self.last_pre_race_use_result = client.use_items(use_payload, turn)
                current = self._reload_career(client, current, "pre_race_gear")
                event["result"] = self.last_pre_race_use_result
                return current, instant_used + len(use_payload)
            except Exception as exc:
                print(f"Pre-Race Item Use Error at turn {turn}: {exc}")
                if "205" in str(exc):
                    for item in use_payload:
                        self.failed_use_this_turn.add(item["item_id"])
                self.last_pre_race_use_result = {"result": "failed", "turn": turn, "error": str(exc), "payload": use_payload}
                event["result"] = self.last_pre_race_use_result
                return current, instant_used

        return current, instant_used

    def buy_shop_items(self, client, state, preset, race_planner=None):
        data = state.get("data") or {}
        free = data.get("free_data_set") or {}
        chara = data.get("chara_info") or {}
        current_turn = int(chara.get("turn") or 0)
        pickups = free.get("pick_up_item_info_array") or []
        self._set_turn(current_turn)
        self._set_shop_snapshot(pickups)
        cfg = self._mant_cfg(preset)
        tiers = cfg.get("item_tiers") or DEFAULT_ITEM_TIERS
        tier_count = int(cfg.get("tier_count") or 8)
        coin_val = free.get("coin_num")
        if coin_val is None:
            coin_val = free.get("gained_coin_num")
        budget = int(coin_val or 0)
        start_budget = budget
        self.last_buy_options = []
        self.last_buy_selected = []
        self.last_buy_attempt = []
        self.last_buy_result = {"mant_coin": budget}
        self.buy_attempt_events = []
        if not pickups:
            self.last_buy_result = {"skip": "no_pickups", "mant_coin": budget}
            return state, 0
        if budget <= 0:
            self.last_buy_result = {"skip": "no_mant_coin", "mant_coin": budget}
            return state, 0

        owned = self._owned_map(free)
        any_sale = any(int(row.get("coin_num") or 0) < int(row.get("original_coin_num") or 0) for row in pickups if int(row.get("original_coin_num") or 0) > 0)
        sale_modifier = 0.9 if any_sale else 1.0
        motivation = int(chara.get("motivation") or 3)
        non_rainbow_count = 0
        for row in chara.get("evaluation_info_array") or []:
            if int(row.get("target_id") or 0) in {1, 2, 3, 4, 5, 6} and int(row.get("evaluation") or 0) < 80:
                non_rainbow_count += 1
        bbq_threshold = int(cfg.get("bbq_unmaxxed_cards") or 3)
        bbq_shift = non_rainbow_count - bbq_threshold
        charm_owned = owned.get("Good-Luck Charm", 0)
        is_senior_or_later = current_turn > 48
        charm_stop_qty = 2 if is_senior_or_later else 3
        charm_stop = charm_owned >= charm_stop_qty
        cupcake_names = {"Plain Cupcake", "Berry Sweet Cupcake"}
        total_cupcakes = sum(owned.get(n, 0) for n in cupcake_names)
        skip_cupcakes = total_cupcakes >= 2 or (is_senior_or_later and total_cupcakes >= 1) or motivation >= 5
        cupcake_shift = total_cupcakes - 1 if skip_cupcakes else 0
        active_ailments = self._active_bad_statuses(data)
        has_miracle = owned.get("Miracle Cure", 0) > 0

        available = []
        for row in pickups:
            shop_item_id = int(row.get("shop_item_id") or 0)
            item_id = int(row.get("item_id") or 0)
            name = ITEM_NAMES.get(item_id)
            if not name:
                continue
            cost = int(row.get("coin_num") or SHOP_ITEM_COSTS.get(name, 9999))
            limit_turn = int(row.get("limit_turn") or 0)
            limit = int(row.get("limit_buy_count") or 1)
            current_num = int(row.get("item_buy_num") or 0)
            skip_reason = None
            if shop_item_id <= 0 or shop_item_id in self.failed_exchange_this_snapshot:
                skip_reason = "failed_snapshot"
            elif limit_turn > 0 and limit_turn < current_turn:
                skip_reason = "expired"
            elif current_num >= limit:
                skip_reason = "limit_reached"
            elif self._skip_buy(name, owned, preset, current_turn, start_budget, data, race_planner):
                skip_reason = "skip_buy"
            self.last_buy_options.append({
                "name": name,
                "item_id": item_id,
                "shop_item_id": shop_item_id,
                "cost": cost,
                "current_num": current_num,
                "limit": limit,
                "limit_turn": limit_turn,
                "turns_left": (limit_turn - current_turn) if limit_turn > 0 else None,
                "skip_reason": skip_reason,
            })
            if not skip_reason:
                available.append((name, row))

        if not available:
            self.last_buy_result = {"skip": "no_available", "mant_coin": budget}
            return state, 0

        effective_rows = []
        for name, row in available:
            slug = display_to_slug(name)
            base_t = int(tiers.get(slug) or 999)
            eff_t = base_t
            for ailment in active_ailments:
                specific_cure = AILMENT_CURE_MAP.get(ailment)
                if specific_cure and name == specific_cure and not has_miracle and owned.get(name, 0) <= 0:
                    eff_t = 1
            if slug == "miracle_cure" and active_ailments and not has_miracle:
                eff_t = 1
            if (slug == "miracle_cure" or slug == "rich_hand_cream") and owned.get(name, 0) <= 0:
                eff_t = 1
            if slug == "grilled_carrots":
                eff_t = min(eff_t, base_t - bbq_shift)
            elif slug == "good-luck_charm":
                eff_t = 999 if charm_stop else min(eff_t, base_t - charm_owned)
            elif slug in {"plain_cupcake", "berry_sweet_cupcake"}:
                eff_t = min(eff_t, base_t - cupcake_shift)
            elif slug in {"artisan_cleat_hammer", "master_cleat_hammer"}:
                eff_t = 999
            effective_rows.append((max(1, eff_t), name, row))

        targets = []
        selected_ids = set()
        cleat_row = self._old_ui_cleat_shop_target(available, owned, budget, current_turn)
        if cleat_row:
            cleat_name = ITEM_NAMES.get(int(cleat_row.get("item_id") or 0), "")
            cleat_cost = int(cleat_row.get("coin_num") or SHOP_ITEM_COSTS.get(cleat_name, 9999))
            if cleat_cost <= budget:
                targets.append(cleat_row)
                selected_ids.add(id(cleat_row))
                budget -= cleat_cost

        for tier in range(1, tier_count + 1):
            tier_rows = [(name, row) for eff_t, name, row in effective_rows if eff_t == tier and id(row) not in selected_ids]
            tier_rows.sort(key=lambda item: (int(item[1].get("limit_turn") or 99), int(item[1].get("coin_num") or SHOP_ITEM_COSTS.get(item[0], 9999))))
            for name, row in tier_rows:
                cost = int(row.get("coin_num") or SHOP_ITEM_COSTS.get(name, 9999))
                remaining = budget - cost
                if remaining < 0:
                    continue
                threshold = 0
                thresholds = cfg.get("tier_thresholds") or {}
                if tier > 1 and current_turn <= 64:
                    raw_threshold = int(thresholds.get(str(tier), thresholds.get(tier, (tier - 1) * 50)) or 0)
                    threshold = int(raw_threshold * sale_modifier)
                floor = self._buy_floor(name, tier, current_turn, start_budget, budget, threshold, cfg)
                if remaining < floor:
                    continue
                targets.append(row)
                selected_ids.add(id(row))
                budget = remaining

        if not targets:
            self.last_buy_result = {"skip": "no_targets", "mant_coin": budget, "start_mant_coin": start_budget}
            return state, 0

        self.last_buy_selected = [{
            "name": ITEM_NAMES.get(int(row.get("item_id") or 0), ""),
            "item_id": int(row.get("item_id") or 0),
            "shop_item_id": int(row.get("shop_item_id") or 0),
            "cost": int(row.get("coin_num") or SHOP_ITEM_COSTS.get(ITEM_NAMES.get(int(row.get("item_id") or 0), ""), 9999)),
            "current_num": int(row.get("item_buy_num") or 0),
            "limit_turn": int(row.get("limit_turn") or 0),
        } for row in targets]

        payload = []
        for row in targets:
            sid = int(row.get("shop_item_id") or 0)
            if sid > 0 and sid not in self.failed_exchange_this_snapshot:
                payload.append({"shop_item_id": sid, "current_num": 0})

        if not payload:
            self.last_buy_result = {"skip": "empty_payload", "mant_coin": budget, "start_mant_coin": start_budget}
            return state, 0

        return self._exchange_batch(client, state, payload, current_turn)

    def _exchange_batch(self, client, state, payload, current_turn):
        if not payload:
            return state, 0

        data = state.get("data") or {}
        chara = data.get("chara_info") or {}
        source_turn = int(chara.get("turn") or 0)

        if source_turn != current_turn:
            self.last_buy_result = {"skip": "stale_turn_detected", "request_current_turn": current_turn, "source_state_turn": source_turn}
            return state, 0

        free = data.get("free_data_set") or {}
        coin_val = free.get("coin_num")
        if coin_val is None:
            coin_val = free.get("gained_coin_num")
        budget = int(coin_val or 0)

        valid_shop_rows = {int(row.get("shop_item_id") or 0): row for row in free.get("pick_up_item_info_array") or []}

        owned_by_id = {}
        for row in free.get("user_item_info_array") or []:
            owned_by_id[int(row.get("item_id") or 0)] = int(row.get("num") or row.get("current_num") or row.get("item_num") or 0)

        valid_payload = []
        attempt_items = []
        total_cost = 0
        for item in payload:
            shop_item_id = int(item.get("shop_item_id") or 0)
            if shop_item_id <= 0:
                continue
            shop_row = valid_shop_rows.get(shop_item_id)
            if not shop_row:
                continue
            cost = int(shop_row.get("coin_num") or SHOP_ITEM_COSTS.get(ITEM_NAMES.get(int(shop_row.get("item_id") or 0), ""), 9999))
            limit_turn = int(shop_row.get("limit_turn") or 0)
            if limit_turn > 0 and limit_turn < current_turn:
                continue
            if int(shop_row.get("item_buy_num") or 0) >= int(shop_row.get("limit_buy_count") or 1):
                continue
            if total_cost + cost > budget:
                continue
            total_cost += cost

            valid_payload.append({
                "shop_item_id": shop_item_id,
                "current_num": owned_by_id.get(int(shop_row.get("item_id") or 0), 0)
            })
            attempt_items.append({
                "shop_item_id": shop_item_id,
                "cost": cost,
                "current_num": owned_by_id.get(int(shop_row.get("item_id") or 0), 0)
            })

        if not valid_payload:
            self.last_buy_result = {"skip": "preflight_failed", "mant_coin": budget}
            return state, 0

        self.last_buy_attempt = list(valid_payload)
        event = {
            "turn": current_turn,
            "selected": list(self.last_buy_selected),
            "attempt": list(attempt_items),
            "payload": list(valid_payload),
            "result": {},
        }
        self.buy_attempt_events.append(event)
        try:
            if hasattr(client, "wait_complex_delay"):
                client.wait_complex_delay()
            result = client.exchange_items(valid_payload, current_turn)
            self.last_buy_result = {"result": "ok", "turn": current_turn, "payload": valid_payload}
            event["result"] = self.last_buy_result
            self.failed_exchange_this_snapshot = set()
            return result, len(valid_payload)
        except Exception as e:
            print(f"Item Exchange Error at turn {current_turn}: {e}")
            if any(code in str(e) for code in ("201", "205", "208")):
                self.recover_after_exchange_error = True
            for item in valid_payload:
                self.failed_exchange_this_snapshot.add(int(item.get("shop_item_id") or 0))
            self.last_buy_result = {"result": "failed", "turn": current_turn, "error": str(e), "payload": valid_payload}
            event["result"] = self.last_buy_result
            return state, 0

    def _is_g1_program(self, program_id, race_planner):
        if not race_planner or not program_id:
            return False
        info = (race_planner.program or {}).get(program_id) or {}
        race_inst = str(info.get("race_instance_id") or "")
        return race_inst.startswith("1")

    def _old_ui_cleat_before_race(self, owned, turn, program_id, race_planner):
        SUMMER_CAMP_2_START = 60
        CLASSIC_YEAR_END = 48
        SENIOR_YEAR_END = 72
        CLIMAX_RACE_TURNS = [74, 76, 78]

        master_qty = owned.get("Master Cleat Hammer", 0)
        artisan_qty = owned.get("Artisan Cleat Hammer", 0)
        if master_qty + artisan_qty <= 0:
            return None

        if turn in CLIMAX_RACE_TURNS:
            if master_qty > 0:
                return "Master Cleat Hammer"
            if artisan_qty > 0:
                return "Artisan Cleat Hammer"
            return None

        if turn > SUMMER_CAMP_2_START:
            total = master_qty + artisan_qty
            if total <= 2:
                return None
            reserve_total = min(2, total)
            reserve_master = min(master_qty, reserve_total)
            spare_master = master_qty - reserve_master
            spare_artisan = artisan_qty - (reserve_total - reserve_master)

            is_senior = turn <= SENIOR_YEAR_END
            if is_senior and master_qty < 3 and spare_artisan > 0:
                return "Artisan Cleat Hammer"
            if spare_master > 0:
                return "Master Cleat Hammer"
            if spare_artisan > 0:
                return "Artisan Cleat Hammer"
            return None

        if not self._is_g1_program(program_id, race_planner):
            return None

        is_senior = CLASSIC_YEAR_END < turn <= SENIOR_YEAR_END
        if is_senior and master_qty < 3:
            if artisan_qty > 0:
                return "Artisan Cleat Hammer"
            if master_qty > 0:
                return "Master Cleat Hammer"
            return None

        if master_qty > 0:
            return "Master Cleat Hammer"
        if artisan_qty > 0:
            return "Artisan Cleat Hammer"
        return None

    def _old_ui_cleat_shop_target(self, available, owned, budget, current_turn):
        CLASSIC_YEAR_END = 48
        SENIOR_YEAR_END = 72

        master_qty = owned.get("Master Cleat Hammer", 0)
        artisan_qty = owned.get("Artisan Cleat Hammer", 0)
        total_cleats = master_qty + artisan_qty
        is_senior = CLASSIC_YEAR_END < current_turn <= SENIOR_YEAR_END
        is_climax = current_turn > SENIOR_YEAR_END
        if not (is_senior or is_climax):
            return None

        available_by_name = {name: row for name, row in available}
        if is_senior:
            if total_cleats >= 2:
                return None
            for candidate in ("Master Cleat Hammer", "Artisan Cleat Hammer"):
                row = available_by_name.get(candidate)
                if not row:
                    continue
                cost = int(row.get("coin_num") or SHOP_ITEM_COSTS.get(candidate, 9999))
                if cost <= budget:
                    return row
            return None

        if total_cleats >= 3:
            return None
        if total_cleats < 2 and budget < 40:
            return None
        for candidate in ("Master Cleat Hammer", "Artisan Cleat Hammer"):
            row = available_by_name.get(candidate)
            if not row:
                continue
            cost = int(row.get("coin_num") or SHOP_ITEM_COSTS.get(candidate, 9999))
            if cost > budget:
                continue
            if total_cleats < 2 and budget - cost < 40:
                continue
            return row
        return None

    def use_items(self, client, state, preset, best_command=None, status=None, race_planner=None):
        data = state.get("data") or {}
        free = data.get("free_data_set") or {}
        chara = data.get("chara_info") or {}
        owned = self._owned_map(free)
        current_turn = int(chara.get("turn") or 0)
        self._set_turn(current_turn)
        self.last_use_options = []
        self.last_use_selected = []
        self.last_use_attempt = []
        self.last_use_result = {}
        self.use_attempt_events = []
        if not owned:
            self.last_use_result = {"skip": "no_owned"}
            return state, 0
        targets = []
        for name in INSTANT_USE_ITEMS:
            qty = owned.get(name, 0)
            if qty <= 0:
                continue
            if DISPLAY_TO_ID.get(name) in self.failed_use_this_turn:
                continue
            if name in ONE_TIME_BUFF_ITEMS:
                if name in self.used_buffs:
                    continue
                targets.append((name, 1))
            else:

                targets.append((name, qty))

        targets.extend(self._energy_targets(chara, owned, preset))
        targets.extend(self._ailment_cure_targets(data, owned))
        mood_target = self._mood_target(chara, owned)
        if mood_target:
            targets.append(mood_target)

        whistle = self._whistle_target(best_command, owned, preset, status, current_turn)
        if whistle:
            targets = [whistle]
        else:
            charm = self._charm_target(best_command, owned, preset, status)
            if charm:
                targets.append(charm)
            mega = self._megaphone_target(state, best_command, owned, preset, status, current_turn, race_planner)
            if mega:
                targets.append(mega)
            anklet = self._anklet_target(state, best_command, owned, preset)
            if anklet:
                targets.append(anklet)

        targets = self._merge_targets(targets, owned)
        selected_names = {name for name, _ in targets}
        for name, count in sorted(owned.items()):
            item_id = DISPLAY_TO_ID.get(name)
            if not item_id or count <= 0:
                continue
            failed = item_id in self.failed_use_this_turn
            selected = name in selected_names and not failed
            reason = None if selected else ("failed_this_turn" if failed else "not_useful_now")
            self.last_use_options.append({
                "name": name,
                "item_id": item_id,
                "current_num": int(count),
                "selected": selected,
                "skip_reason": reason,
                "reason": "selected" if selected else reason,
                "turn": current_turn,
                "context": {
                    "command_type": int((best_command or {}).get("command_type") or 0),
                    "command_id": int((best_command or {}).get("command_id") or 0),
                    "command_group_id": int((best_command or {}).get("command_group_id") or 0),
                },
            })
        if not targets:
            self.last_use_result = {"skip": "no_targets"}
            return state, 0

        payload = []
        valid_targets = []
        for name, count in targets:
            item_id = DISPLAY_TO_ID.get(name)
            if not item_id or item_id in self.failed_use_this_turn:
                continue
            have = int(owned.get(name) or 0)
            if have < count or have <= 0:
                continue

            valid_targets.append((name, count))
            payload.append({
                "item_id": item_id,
                "use_num": count,
                "current_num": have
            })

        if not payload:
            self.last_use_result = {"skip": "empty_payload"}
            return state, 0

        self.last_use_selected = [{"name": name, "item_id": DISPLAY_TO_ID.get(name), "use_num": count} for name, count in valid_targets]
        self.last_use_attempt = list(payload)
        event = {
            "turn": current_turn,
            "selected": list(self.last_use_selected),
            "attempt": list(payload),
            "payload": list(payload),
            "result": {},
        }
        self.use_attempt_events.append(event)
        try:
            if hasattr(client, "wait_complex_delay"):
                client.wait_complex_delay()
            state = client.use_items(payload, current_turn)
            self.failed_use_this_turn = set()
            for name, _ in valid_targets:
                if name in ONE_TIME_BUFF_ITEMS:
                    self.used_buffs.add(name)
            self.last_use_result = {"result": "ok", "turn": current_turn, "payload": payload}
            event["result"] = self.last_use_result
            return state, len(payload)
        except Exception as exc:
            print(f"Item Use Error at turn {current_turn}: {exc}")
            if any(code in str(exc) for code in ("201", "205", "208")):
                self.recover_after_use_error = True
                for item in payload:
                    self.failed_use_this_turn.add(int(item.get("item_id") or 0))
            self.last_use_result = {"result": "failed", "turn": current_turn, "error": str(exc), "payload": payload}
            event["result"] = self.last_use_result
            return state, 0

    def _reload_career(self, client, state, reason):
        try:
            if hasattr(client, "load_career"):
                return client.load_career()
            return client.call("single_mode_free/load", {})
        except Exception as e:
            print(f"Item Manager reload failure after {reason}: {e}")
            return state

    def _is_instant_stat_item(self, name):
        slug = display_to_slug(name)
        return slug.endswith("_notepad") or slug.endswith("_manual") or slug.endswith("_scroll")

    def _coin_reserve(self, turn, budget, cfg):
        if turn <= 20:
            reserve = 160
        elif turn <= 35:
            reserve = 220
        elif turn <= 45:
            reserve = 180
        elif turn <= 55:
            reserve = 120
        elif turn <= 64:
            reserve = 80
        elif turn <= 72:
            reserve = 40
        else:
            reserve = 0
        reserve = int(cfg.get("mant_coin_reserve", reserve) if "mant_coin_reserve" in cfg else reserve)
        cap = self._coin_cap(turn, cfg)
        if cap and budget > cap:
            reserve = min(reserve, max(0, cap // 2))
        if turn >= 73:
            return 0
        if turn >= 65 and budget > 300:
            return min(reserve, 40)
        if turn >= 56 and budget > 220:
            return min(reserve, 60)
        if turn >= 46 and budget > 260:
            return min(reserve, 80)
        if turn >= 36 and budget > 320:
            return min(reserve, 120)
        return reserve

    def _coin_cap(self, turn, cfg):
        if turn <= 20:
            return int(cfg.get("mant_coin_cap_t20", 999999))
        if turn <= 35:
            return int(cfg.get("mant_coin_cap_t35", 300))
        if turn <= 45:
            return int(cfg.get("mant_coin_cap_t45", 260))
        if turn <= 55:
            return int(cfg.get("mant_coin_cap_t55", 200))
        if turn <= 64:
            return int(cfg.get("mant_coin_cap_t64", 140))
        if turn <= 72:
            return int(cfg.get("mant_coin_cap_t72", 80))
        return int(cfg.get("mant_coin_cap_final", 0))

    def _buy_floor(self, name, tier, turn, start_budget, budget, threshold, cfg):
        reserve = self._coin_reserve(turn, start_budget, cfg)
        cap = self._coin_cap(turn, cfg)
        floor = max(int(threshold or 0), reserve) if tier > 1 else 0
        if self._is_instant_stat_item(name):
            if turn >= 46:
                return 0
            if turn >= 36 and start_budget > cap:
                return min(floor, 40)
            if start_budget > cap:
                return min(floor, reserve // 2)
            return min(floor, reserve)
        if turn >= 73:
            return 0
        if start_budget > cap:
            floor = min(floor, max(0, reserve // 2))
        if start_budget >= reserve + 400:
            floor = min(floor, max(0, reserve // 3))
        elif start_budget >= reserve + 250:
            floor = min(floor, max(0, reserve // 2))
        if turn >= 65:
            floor = min(floor, 40)
        elif turn >= 56:
            floor = min(floor, 80)
        elif turn >= 46:
            floor = min(floor, 120)
        return max(0, int(floor))

    def _mant_cfg(self, preset):
        cfg = dict((preset or {}).get("mant_config") or {})
        cfg.setdefault("item_tiers", DEFAULT_ITEM_TIERS)
        cfg.setdefault("tier_count", 8)
        cfg.setdefault("tier_thresholds", {"3": 31, "7": 100, "8": 99999999999})
        cfg.setdefault("charm_failure_rate", 15)
        cfg.setdefault("mega_small_threshold", 11)
        cfg.setdefault("mega_medium_threshold", 21)
        cfg.setdefault("mega_large_threshold", 35)
        cfg.setdefault("mega_late_buy_buffer", 5)
        cfg.setdefault("training_weights_threshold", 40)
        return cfg

    def _owned_map(self, free):
        result = {}
        for row in free.get("user_item_info_array") or []:
            item_id = int(row.get("item_id") or 0)
            name = ITEM_NAMES.get(item_id)
            if name:

                qty = int(row.get("num") or row.get("current_num") or row.get("item_num") or 0)
                result[name] = result.get(name, 0) + qty
        return result

    def _active_bad_statuses(self, data):
        result = []
        for effect_id in (data.get("chara_info") or {}).get("chara_effect_id_array") or []:
            try:
                effect_id = int(effect_id)
            except (TypeError, ValueError):
                continue
            name = BAD_EFFECT_NAMES.get(effect_id)
            if name:
                result.append(name)
        return result

    def _needed_cures(self, data, owned):
        result = []
        if owned.get(AILMENT_CURE_ALL, 0) > 0:
            return result
        for ailment in self._active_bad_statuses(data):
            cure = AILMENT_CURE_MAP.get(ailment)
            if cure and owned.get(cure, 0) <= 0:
                result.append(cure)
        return result

    def _ailment_cure_targets(self, data, owned):
        result = []
        active_ailments = self._active_bad_statuses(data)
        if not active_ailments:
            return result

        unhandled_ailments = []
        for ailment in active_ailments:
            cure = AILMENT_CURE_MAP.get(ailment)
            if cure and owned.get(cure, 0) > 0:
                result.append((cure, 1))
            else:
                unhandled_ailments.append(ailment)

        if unhandled_ailments and owned.get(AILMENT_CURE_ALL, 0) > 0:
            result.append((AILMENT_CURE_ALL, 1))
        return result

    def _energy_targets(self, chara, owned, preset):
        result = []
        hp = int(chara.get("vital") or 0)
        max_hp = int(chara.get("max_vital") or 100)
        gap = max_hp - hp
        if gap < 20:
            return result
        cfg = self._mant_cfg(preset)
        threshold = int(cfg.get("energy_recovery_threshold") or 30)
        if hp > threshold:
            return result

        candidates = []
        for name, value in ENERGY_ITEMS.items():
            qty = owned.get(name, 0)
            if qty > 0:
                candidates.append({"name": name, "value": value, "qty": qty})

        candidates.sort(key=lambda x: x["value"], reverse=True)

        remaining_gap = gap
        for c in candidates:
            if remaining_gap <= 5: break
            num_to_use = min(c["qty"], (remaining_gap + 5) // c["value"])
            if num_to_use > 0:
                result.append((c["name"], num_to_use))
                remaining_gap -= num_to_use * c["value"]

        return result

    def _mood_target(self, chara, owned):
        motivation = int(chara.get("motivation") or 3)
        if motivation >= 5:
            return None

        needed = 5 - motivation

        if owned.get("Berry Sweet Cupcake", 0) > 0:
            return ("Berry Sweet Cupcake", 1)

        if owned.get("Plain Cupcake", 0) > 0:
            use_num = min(owned.get("Plain Cupcake"), needed)
            return ("Plain Cupcake", use_num)

        return None

    def _whistle_target(self, best_command, owned, preset, status, turn):
        if owned.get("Reset Whistle", 0) <= 0:
            return None
        if not best_command or int(best_command.get("command_type") or 0) != 1:
            return None

        score = self._command_stat_gain(best_command)
        cfg = self._mant_cfg(preset)
        threshold = int(cfg.get("whistle_score_threshold") or 35)
        if score < threshold and turn <= 72:
             return ("Reset Whistle", 1)
        return None

    def _charm_target(self, best_command, owned, preset, status):
        if owned.get("Good-Luck Charm", 0) <= 0:
            return None
        if not best_command or int(best_command.get("command_type") or 0) != 1:
            return None
        fail_rate = int(best_command.get("failure_rate") or 0)
        cfg = self._mant_cfg(preset)
        threshold = int(cfg.get("charm_failure_rate") or 15)
        if fail_rate >= threshold:
            return ("Good-Luck Charm", 1)
        return None

    def _megaphone_target(self, state, best_command, owned, preset, status, turn, race_planner):
        if not best_command or int(best_command.get("command_type") or 0) != 1:
            return None

        data = state.get("data") or {}
        free_data = data.get("free_data_set") or {}
        item_effects = free_data.get("item_effect_array") or []
        current_mega_tier = self._active_megaphone_tier(state)

        score = self._command_stat_gain(best_command, sp_weight=0.5)
        cfg = self._mant_cfg(preset)
        small_threshold = float(cfg.get("mega_small_threshold") or 11)
        medium_threshold = float(cfg.get("mega_medium_threshold") or 21)
        large_threshold = float(cfg.get("mega_large_threshold") or 35)
        dump_mode = self._megaphone_dump_mode(data, owned, turn, race_planner, preset)
        slots_left = self._remaining_megaphone_slots(data, turn, race_planner, preset)
        owned_count = self._owned_megaphone_count(owned)
        inventory_pressure = slots_left > 0 and owned_count >= slots_left
        has_upgrade_pair = owned.get("Motivating Megaphone", 0) > 0 and owned.get("Empowering Megaphone", 0) > 0 and slots_left >= 2

        target_tier = 0
        if current_mega_tier <= 0:
            if has_upgrade_pair and score >= medium_threshold:
                return ("Motivating Megaphone", 1)
            if score >= large_threshold and owned.get("Empowering Megaphone", 0) > 0:
                return ("Empowering Megaphone", 1)
            if score >= medium_threshold and owned.get("Motivating Megaphone", 0) > 0:
                return ("Motivating Megaphone", 1)
            if score >= small_threshold and owned.get("Coaching Megaphone", 0) > 0:
                return ("Coaching Megaphone", 1)
            if inventory_pressure or dump_mode:
                if has_upgrade_pair:
                    return ("Motivating Megaphone", 1)
                if owned.get("Empowering Megaphone", 0) > 0:
                    return ("Empowering Megaphone", 1)
                if score >= medium_threshold and owned.get("Motivating Megaphone", 0) > 0:
                    return ("Motivating Megaphone", 1)
                if score >= small_threshold and owned.get("Coaching Megaphone", 0) > 0:
                    return ("Coaching Megaphone", 1)
                if owned.get("Coaching Megaphone", 0) > 0:
                    return ("Coaching Megaphone", 1)
                if owned.get("Motivating Megaphone", 0) > 0:
                    return ("Motivating Megaphone", 1)
                if owned.get("Empowering Megaphone", 0) > 0:
                    return ("Empowering Megaphone", 1)
            else:
                if score >= large_threshold:
                    target_tier = 3
                elif score >= medium_threshold:
                    target_tier = 2
                elif score >= small_threshold:
                    target_tier = 1
        elif current_mega_tier == 1:
            if score >= large_threshold * 1.2:
                target_tier = 3
            elif score >= medium_threshold * 1.1:
                target_tier = 2
        elif current_mega_tier == 2:
            if score >= large_threshold * 1.1:
                target_tier = 3

        if target_tier >= 3 and current_mega_tier < 3 and owned.get("Empowering Megaphone", 0) > 0:
            return ("Empowering Megaphone", 1)
        if target_tier >= 2 and current_mega_tier < 2 and owned.get("Motivating Megaphone", 0) > 0:
            return ("Motivating Megaphone", 1)
        if target_tier >= 1 and current_mega_tier < 1 and owned.get("Coaching Megaphone", 0) > 0:
            return ("Coaching Megaphone", 1)

        return None

    def _megaphone_dump_mode(self, data, owned, turn, race_planner, preset):
        training_turns_left = self._remaining_megaphone_slots(data, turn, race_planner, preset)
        total_duration = 0
        for name, (_, duration) in MEGAPHONE_TIERS.items():
            total_duration += int(owned.get(name, 0) or 0) * duration
        return training_turns_left > 0 and total_duration >= training_turns_left

    def _owned_megaphone_count(self, owned):
        total = 0
        for name in MEGAPHONE_TIERS:
            total += int(owned.get(name, 0) or 0)
        return total

    def _megaphone_buy_surplus(self, data, owned, turn, race_planner, preset):
        slots_left = self._remaining_megaphone_slots(data, turn, race_planner, preset)
        if slots_left <= 0:
            return False
        cfg = self._mant_cfg(preset)
        buffer = int(cfg.get("mega_late_buy_buffer") or 3)
        target = max(0, slots_left - buffer)
        return self._owned_megaphone_count(owned) >= target

    def _remaining_megaphone_slots(self, data, turn, race_planner, preset):
        return self._remaining_training_turns_to_77(data, turn, race_planner, preset)

    def _remaining_training_turns_to_77(self, data, turn, race_planner, preset):
        planned_race_turns = self._planned_race_turns_to_77(data, turn, race_planner, preset)
        race_condition_array = data.get("race_condition_array") or []
        remaining = 0
        for t in range(int(turn or 0), 77):
            if t in (74, 76):
                continue
            if t not in planned_race_turns:
                remaining += 1
        return remaining

    def _planned_race_turns_to_77(self, data, turn, race_planner, preset):
        current_turn = int(turn or 0)
        wanted_pids = set()
        if race_planner and preset:
            wanted_pids = race_planner.wanted_programs(preset)
        result = set()
        for item in data.get("race_condition_array") or []:
            item_turn = int(item.get("turn") or 0)
            program_id = int(item.get("program_id") or 0)
            if item_turn >= current_turn and item_turn < 77 and (not wanted_pids or program_id in wanted_pids):
                result.add(item_turn)
        if race_planner and wanted_pids:
            for program_id in wanted_pids:
                info = (race_planner.program or {}).get(int(program_id or 0)) or {}
                race_turn = self._program_turn_from_month_half(info, current_turn)
                if race_turn >= current_turn and race_turn < 77:
                    result.add(race_turn)
        return result

    def _program_turn_from_month_half(self, program_info, current_turn):
        month = int((program_info or {}).get("month") or 0)
        half = int((program_info or {}).get("half") or 0)
        if month <= 0 or half <= 0:
            return 0
        base_turn = (month - 1) * 2 + half
        candidates = [base_turn + 24 * year for year in range(4)]
        for candidate in candidates:
            if candidate >= int(current_turn or 0):
                return candidate
        return candidates[-1]

    def _anklet_target(self, state, best_command, owned, preset):
        if not best_command or int(best_command.get("command_type") or 0) != 1:
            return None

        cmd_id = int(best_command.get("command_id") or 0)
        anklet = TRAINING_TYPE_ANKLET.get(cmd_id)
        if not anklet or owned.get(anklet, 0) <= 0:
            return None

        data = state.get("data") or {}
        free_data = data.get("free_data_set") or {}
        item_effects = free_data.get("item_effect_array") or []
        for eff in item_effects:
            if eff.get("item_id") in (9001, 9002, 9003, 9004, 9005):
                return None

        score = self._command_stat_gain(best_command, sp_weight=0.5)
        threshold = 30 * (1 - (0.2 * self._active_megaphone_tier(state)))
        if score > threshold:
            return (anklet, 1)
        return None

    def _active_megaphone_tier(self, state):
        current_mega_tier = 0
        for eff in ((state.get("data") or {}).get("free_data_set") or {}).get("item_effect_array") or []:
            item_id = eff.get("item_id")
            if item_id == 8001: current_mega_tier = max(current_mega_tier, 1)
            elif item_id == 8002: current_mega_tier = max(current_mega_tier, 2)
            elif item_id == 8003: current_mega_tier = max(current_mega_tier, 3)
        return current_mega_tier

    def _command_stat_gain(self, cmd, sp_weight=0):
        if not cmd: return 0
        total = 0
        for item in cmd.get("params_inc_dec_info_array") or []:
            tt = item.get("target_type")
            if tt in [1, 2, 3, 4, 5]:
                total += int(item.get("value") or 0)
            elif (tt == 6 or tt == 30) and sp_weight > 0:
                total += int(item.get("value") or 0) * sp_weight
        if total == 0:
            for field in ["speed", "stamina", "power", "guts", "wiz"]:
                total += int(cmd.get(field) or 0)
            if sp_weight > 0:
                total += int(cmd.get("lp") or cmd.get("skill_point") or 0) * sp_weight
        return total

    def _merge_targets(self, targets, owned):
        counts = {}
        for name, count in targets:
            counts[name] = counts.get(name, 0) + count
        result = []
        for name, count in counts.items():
            actual = min(count, owned.get(name, 0))
            if actual > 0:
                result.append((name, actual))
        return result

    def _skip_buy(self, name, owned, preset=None, turn=0, budget=0, data=None, race_planner=None):
        if name in MEGAPHONE_TIERS and self._megaphone_buy_surplus(data or {}, owned, turn, race_planner, preset):
            return True
        if name in CURE_ITEMS:
            if owned.get(name, 0) > 0 or (name != AILMENT_CURE_ALL and owned.get(AILMENT_CURE_ALL, 0) > 0):
                return True
        type_idx = TRAINING_ITEM_DECK_TYPE_INDEX.get(name)
        if type_idx is not None:
            counts = (preset or {}).get("_deck_type_counts") or []
            count = int(counts[type_idx] or 0) if len(counts) > type_idx else 0
            if count >= 1:
                return False
            return not ((turn >= 49 and budget >= 300) or (turn >= 65 and budget >= 150))
        if name in ONE_TIME_BUFF_ITEMS and name in self.used_buffs:
            return True
        return False
