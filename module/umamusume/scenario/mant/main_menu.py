import cv2
import re

from bot.recog.image_matcher import image_match
from bot.recog.ocr import ocr_line
from module.umamusume.asset.template import REF_MANT_ON_SALE
from module.umamusume.define import TurnOperationType
import bot.base.log as logger

log = logger.get_logger(__name__)

COIN_ROI_NORMAL = (1172, 1197, 402, 500)
COIN_ROI_SUMMER = (1172, 1199, 321, 417)
COIN_ROI_CLIMAX = (1125, 1148, 565, 654)

RIVAL_COLOR_1 = (0x4E, 0xFF, 0xFF)
RIVAL_COLOR_2 = (0x30, 0xAD, 0xEB)
RIVAL_TOLERANCE = 5


def read_shop_coins(img, is_summer, is_climax):
    if is_climax:
        y1, y2, x1, x2 = COIN_ROI_CLIMAX
    elif is_summer:
        y1, y2, x1, x2 = COIN_ROI_SUMMER
    else:
        y1, y2, x1, x2 = COIN_ROI_NORMAL
    roi = img[y1:y2, x1:x2]
    text = ocr_line(roi, lang="en")
    digits = re.sub(r'[^0-9]', '', text)
    if digits:
        return int(digits)
    return -1


def handle_mant_inventory_scan(ctx, current_date):
    if ctx.cultivate_detail.mant_inventory_scanned:
        return False
    if current_date < 13:
        return False

    from module.umamusume.scenario.mant.inventory import scan_inventory, open_items_panel, close_items_panel
    from module.umamusume.context import log_detected_items

    opened = open_items_panel(ctx)
    if not opened:
        ctx.ctrl.trigger_decision_reset = True
        return True

    owned = scan_inventory(ctx)
    ctx.cultivate_detail.mant_owned_items = owned
    ctx.cultivate_detail.mant_inventory_scanned = True
    log_detected_items(owned)

    close_items_panel(ctx)
    ctx.cultivate_detail.turn_info.parse_main_menu_finish = False
    return True


def handle_mant_inventory_rescan_if_pending(ctx, current_date):
    pending = getattr(ctx.cultivate_detail, 'mant_inventory_rescan_pending', False)
    if not pending:
        return False

    from module.umamusume.scenario.mant.inventory import scan_inventory, open_items_panel, close_items_panel
    from module.umamusume.context import log_detected_items

    opened = open_items_panel(ctx)
    if not opened:
        ctx.ctrl.trigger_decision_reset = True
        return True

    owned = scan_inventory(ctx)
    ctx.cultivate_detail.mant_owned_items = owned
    ctx.cultivate_detail.mant_inventory_scanned = True
    ctx.cultivate_detail.mant_inventory_rescan_pending = False
    log_detected_items(owned)
    close_items_panel(ctx)
    ctx.cultivate_detail.turn_info.parse_main_menu_finish = False
    return True


def handle_mant_turn_start(ctx, current_date):
    from module.umamusume.scenario.mant.shop import is_shop_scan_turn, current_shop_chunk
    if not is_shop_scan_turn(current_date):
        return

    chunk = current_shop_chunk(current_date)
    last_chunk = getattr(ctx.cultivate_detail, 'mant_shop_last_chunk', -1)

    if chunk != last_chunk:
        ctx.cultivate_detail.mant_shop_items = []
    else:
        updated = []
        for name, conf, gy, turns, bought in ctx.cultivate_detail.mant_shop_items:
            if turns == 99:
                updated.append((name, conf, gy, turns, bought))
            elif turns > 1:
                updated.append((name, conf, gy, turns - 1, bought))
        ctx.cultivate_detail.mant_shop_items = updated

        from module.umamusume.context import log_detected_shop_items
        log_detected_shop_items([(name, turns, bought) for name, _, _, turns, bought in updated])


def handle_mant_shop_scan(ctx, current_date):
    if ctx.cultivate_detail.mant_shop_scanned_this_turn:
        return False
    from module.umamusume.scenario.mant.shop import (
        is_shop_scan_turn, scan_mant_shop, buy_shop_items,
        SHOP_ITEM_COSTS, SLUG_TO_DISPLAY, display_to_slug,
        current_shop_chunk
    )
    from module.umamusume.scenario.mant.constants import AILMENT_CURE_MAP, AILMENT_CURE_ALL
    if not is_shop_scan_turn(current_date):
        return False
    chunk = current_shop_chunk(current_date)
    last_chunk = getattr(ctx.cultivate_detail, 'mant_shop_last_chunk', -1)
    if chunk == last_chunk:
        return False

    scan_result = scan_mant_shop(ctx)
    if scan_result is None:
        ctx.ctrl.trigger_decision_reset = True
        return True

    items_list, ratio, drag_ratio, first_item_gy = scan_result
    ctx.cultivate_detail.mant_shop_items = items_list
    ctx.cultivate_detail.mant_shop_ratio = ratio
    ctx.cultivate_detail.mant_shop_drag_ratio = drag_ratio
    ctx.cultivate_detail.mant_shop_first_gy = first_item_gy
    ctx.cultivate_detail.mant_shop_scanned_this_turn = True
    ctx.cultivate_detail.mant_shop_last_chunk = chunk

    from module.umamusume.context import log_detected_shop_items
    log_detected_shop_items([(name, turns, purchased) for name, _, _, turns, purchased in items_list])

    bought = False
    mant_cfg = getattr(ctx.task.detail.scenario_config, 'mant_config', None)
    if mant_cfg and mant_cfg.item_tiers:
        budget = ctx.cultivate_detail.mant_coins
        shop_available = {name for name, _, _, _, purchased in items_list if not purchased}
        shop_slugs = {display_to_slug(n) for n in shop_available}
        shop_copy_counts = {}
        for name, _, _, _, purchased in items_list:
            if not purchased:
                shop_copy_counts[name] = shop_copy_counts.get(name, 0) + 1

        img = ctx.ctrl.get_screen()
        any_sale = handle_mant_on_sale(img) if img is not None else False
        sale_modifier = 0.9 if any_sale else 1.0

        from module.umamusume.persistence import get_used_buffs, get_ignore_cat_food, get_ignore_grilled_carrots
        from module.umamusume.scenario.mant.inventory import ONE_TIME_BUFF_ITEMS
        used_buffs = get_used_buffs()
        ignore_cat = get_ignore_cat_food()
        ignore_carrots = get_ignore_grilled_carrots()

        active_ailments = getattr(ctx.cultivate_detail, 'mant_afflictions', [])
        owned = getattr(ctx.cultivate_detail, 'mant_owned_items', [])
        owned_map = {n: q for n, q in owned}
        has_miracle_cure = owned_map.get(AILMENT_CURE_ALL, 0) > 0

        from module.umamusume.context import detected_portraits_log
        non_rainbow_count = 0
        for info in detected_portraits_log.values():
            if not info.get('is_npc', False):
                if info.get('favor', 0) < 4:
                    non_rainbow_count += 1
        bbq_threshold = mant_cfg.bbq_unmaxxed_cards
        bbq_base_tier = mant_cfg.item_tiers.get("grilled_carrots")
        bbq_shift = non_rainbow_count - bbq_threshold if detected_portraits_log else 0
        bbq_effective_tier = None
        if bbq_base_tier is not None:
            bbq_effective_tier = bbq_base_tier - bbq_shift

        charm_owned = owned_map.get("Good-Luck Charm", 0)
        charm_base_tier = mant_cfg.item_tiers.get("good-luck_charm")
        charm_shift = charm_owned
        charm_effective_tier = 0
        if charm_base_tier is not None:
            charm_effective_tier = charm_base_tier - charm_shift

        from module.umamusume.constants.game_constants import CLASSIC_YEAR_END
        is_senior_or_later_for_charm = current_date > CLASSIC_YEAR_END
        charm_stop_qty = 2 if is_senior_or_later_for_charm else 3
        charm_stop = charm_owned >= charm_stop_qty

        bought_cures = set()
        priority_targets = []
        if active_ailments and not has_miracle_cure:
            needed_cures = set()
            for ailment, cure in AILMENT_CURE_MAP.items():
                for active in active_ailments:
                    if ailment.lower() in active.lower():
                        needed_cures.add(cure)
            for cure in needed_cures:
                if cure in bought_cures:
                    continue
                if owned_map.get(cure, 0) <= 0 and cure in shop_available:
                    cost = SHOP_ITEM_COSTS.get(cure, 9999)
                    if cost <= budget:
                        priority_targets.append(cure)
                        bought_cures.add(cure)
                        budget -= cost
            if not bought_cures.intersection(needed_cures) and AILMENT_CURE_ALL in shop_available and owned_map.get(AILMENT_CURE_ALL, 0) <= 0:
                cost = SHOP_ITEM_COSTS.get(AILMENT_CURE_ALL, 9999)
                if cost <= budget:
                    priority_targets.append(AILMENT_CURE_ALL)
                    bought_cures.add(AILMENT_CURE_ALL)
                    budget -= cost
        if bought_cures:
            ctx.cultivate_detail._mant_bought_cures_this_cycle = bought_cures

        priority_set = set(priority_targets)

        all_cures = set(AILMENT_CURE_MAP.values())

        def should_skip(display_name):
            if display_name in priority_set:
                return True
            if display_name in ONE_TIME_BUFF_ITEMS and display_name in used_buffs:
                return True
            if ignore_cat and display_name == "Yummy Cat Food":
                return True
            if ignore_carrots:
                bbq_slug = display_to_slug(display_name)
                if bbq_slug == "grilled_carrots":
                    return True
            if display_name in all_cures:
                if has_miracle_cure:
                    return True
                if owned_map.get(display_name, 0) > 0:
                    return True
            if display_name == AILMENT_CURE_ALL and has_miracle_cure:
                return True
            if display_name == "Energy Drink MAX" and owned_map.get("Energy Drink MAX", 0) > 0:
                return True
            return False

        from module.umamusume.constants.game_constants import CLASSIC_YEAR_END, SENIOR_YEAR_END, SUMMER_CAMP_2_END

        cupcake_names = {'Plain Cupcake', 'Berry Sweet Cupcake'}
        skip_cupcakes = False
        total_cupcakes = sum(owned_map.get(n, 0) for n in cupcake_names)
        is_senior_or_later = current_date > CLASSIC_YEAR_END

        from module.umamusume.scenario.mant.constants import get_incoming_mood
        cached_mood = getattr(ctx.cultivate_detail.turn_info, 'cached_mood', None)
        if cached_mood is not None:
            current_mood = cached_mood
        else:
            from bot.conn.fetch import read_mood
            current_mood = read_mood(ctx.current_screen)

        if total_cupcakes >= 2:
            skip_cupcakes = True
        elif is_senior_or_later and (total_cupcakes >= 1 or current_mood is None or current_mood >= 5):
            skip_cupcakes = True
        elif current_mood is None or current_mood >= 5:
            skip_cupcakes = True
        else:
            incoming = get_incoming_mood(current_date, 3)
            if current_mood + 1 + incoming >= 5:
                skip_cupcakes = True
        post_senior_summer = current_date > SUMMER_CAMP_2_END

        cleat_reserve = 0
        if CLASSIC_YEAR_END < current_date <= SENIOR_YEAR_END:
            owned_total = owned_map.get('Master Cleat Hammer', 0) + owned_map.get('Artisan Cleat Hammer', 0)
            if owned_total < 3:
                cleat_reserve = 40

        tier_targets = []

        if bbq_effective_tier is not None and bbq_effective_tier <= 0:
            bbq_display = "Grilled Carrots"
            bbq_slug = "grilled_carrots"
            if bbq_slug in shop_slugs and not should_skip(bbq_display):
                cost = SHOP_ITEM_COSTS.get(bbq_display, 9999)
                copies = shop_copy_counts.get(bbq_display, 0)
                for _ in range(copies):
                    if budget - cost < 0:
                        break
                    tier_targets.append(bbq_display)
                    budget -= cost

        for tier in range(1, mant_cfg.tier_count + 1):
            for slug, t in mant_cfg.item_tiers.items():
                if slug == "grilled_carrots" and bbq_effective_tier is not None:
                    if bbq_effective_tier <= 0 or bbq_effective_tier > mant_cfg.tier_count:
                        continue
                    effective_tier = bbq_effective_tier
                elif slug == "good-luck_charm" and charm_effective_tier is not None:
                    if charm_stop or charm_effective_tier <= 0 or charm_effective_tier > mant_cfg.tier_count:
                        continue
                    effective_tier = charm_effective_tier
                else:
                    effective_tier = t
                if effective_tier != tier or slug not in shop_slugs:
                    continue
                display = SLUG_TO_DISPLAY.get(slug)
                if not display:
                    continue
                if should_skip(display):
                    continue
                if skip_cupcakes and display in cupcake_names:
                    continue

                cost = SHOP_ITEM_COSTS.get(display, 9999)
                copies = shop_copy_counts.get(display, 0)
                if copies <= 0:
                    continue

                actual_copies = 1 if display in all_cures or display == AILMENT_CURE_ALL else copies
                for i in range(actual_copies):
                    remaining_after = budget - cost
                    if remaining_after < 0:
                        break
                    threshold = 0
                    if tier > 1 and not post_senior_summer:
                        raw_threshold = mant_cfg.tier_thresholds.get(tier, (tier - 1) * 50)
                        threshold = raw_threshold * sale_modifier
                    if threshold > 0 and remaining_after < threshold:
                        break
                    tier_targets.append(display)
                    budget -= cost

        targets = priority_targets + tier_targets
        if targets:
            bought, held_items = buy_shop_items(ctx, targets, items_list, ratio, drag_ratio, first_item_gy)
            if bought:
                ctx.cultivate_detail.mant_inventory_rescan_pending = True
                total_spent = sum(SHOP_ITEM_COSTS.get(t, 0) for t in targets)
                ctx.cultivate_detail.mant_coins = max(0, ctx.cultivate_detail.mant_coins - total_spent)
                bought_set = set(targets)
                ctx.cultivate_detail.mant_shop_items = [
                    (name, conf, gy, turns, purchased or (name in bought_set))
                    for name, conf, gy, turns, purchased in items_list
                ]
                remaining = [(name, turns, False) for name, _, _, turns, purchased in items_list
                             if not purchased and name not in bought_set]
                log_detected_shop_items(remaining)

    if not bought:
        from module.umamusume.scenario.mant.shop import BACK_BTN_X, BACK_BTN_Y
        import time as t
        ctx.ctrl.click(BACK_BTN_X, BACK_BTN_Y)
        t.sleep(1)

    ctx.cultivate_detail.turn_info.parse_main_menu_finish = False
    return True


def handle_mant_emergency_shop_buys(ctx, current_date):
    if getattr(ctx.cultivate_detail.turn_info, 'mant_emergency_shop_done', False):
        return False

    from module.umamusume.scenario.mant.shop import (
        is_shop_scan_turn, scan_mant_shop, buy_shop_items,
        SHOP_ITEM_COSTS, SLUG_TO_DISPLAY, display_to_slug,
        BACK_BTN_X, BACK_BTN_Y,
    )
    from module.umamusume.scenario.mant.constants import AILMENT_CURE_MAP, AILMENT_CURE_ALL
    import time as _t

    if not is_shop_scan_turn(current_date):
        return False

    shop_items = getattr(ctx.cultivate_detail, 'mant_shop_items', [])
    if not shop_items:
        return False

    budget = ctx.cultivate_detail.mant_coins
    emergency_targets = []

    mant_cfg = getattr(ctx.task.detail.scenario_config, 'mant_config', None)
    if mant_cfg and mant_cfg.item_tiers:
        expiring = {name for name, _, _, turns, purchased in shop_items
                    if turns == 1 and not purchased}
        if expiring:
            shop_slugs = {display_to_slug(n) for n, _, _, _, purchased in shop_items
                          if not purchased}
            expiring_counts = {}
            for name, _, _, turns, purchased in shop_items:
                if name in expiring and not purchased:
                    expiring_counts[name] = expiring_counts.get(name, 0) + 1
            from module.umamusume.constants.game_constants import SUMMER_CAMP_2_END
            post_senior_summer = current_date > SUMMER_CAMP_2_END

            tmp_budget = budget
            from module.umamusume.persistence import get_ignore_grilled_carrots as _get_ig_grilled
            ignore_grilled_carrots_em = _get_ig_grilled()
            bbq_base_tier_em = mant_cfg.item_tiers.get("grilled_carrots")
            from module.umamusume.context import detected_portraits_log
            non_rainbow_count_em = 0
            for info_em in detected_portraits_log.values():
                if not info_em.get('is_npc', False):
                    if info_em.get('favor', 0) < 4:
                        non_rainbow_count_em += 1
            bbq_threshold_em = mant_cfg.bbq_unmaxxed_cards
            bbq_shift_em = non_rainbow_count_em - bbq_threshold_em if detected_portraits_log else 0
            bbq_eff_em = None
            if bbq_base_tier_em is not None:
                bbq_eff_em = bbq_base_tier_em - bbq_shift_em

        
            if bbq_eff_em is not None and bbq_eff_em <= 0 and not ignore_grilled_carrots_em:
                bbq_display_em = SLUG_TO_DISPLAY.get("grilled_carrots")
                if bbq_display_em and bbq_display_em in expiring and bbq_display_em in shop_slugs:
                    cost_em = SHOP_ITEM_COSTS.get(bbq_display_em, 9999)
                    copies_em = expiring_counts.get(bbq_display_em, 0)
                    for _ in range(copies_em):
                        if tmp_budget - cost_em < 0:
                            break
                        emergency_targets.append(bbq_display_em)
                        tmp_budget -= cost_em
                        budget = tmp_budget

            for tier in range(1, mant_cfg.tier_count + 1):
                for slug, t in mant_cfg.item_tiers.items():
                    if slug == "grilled_carrots" and bbq_eff_em is not None and ignore_grilled_carrots_em:
                        continue
                    if slug == "grilled_carrots" and bbq_eff_em is not None:
                        if bbq_eff_em <= 0 or bbq_eff_em > mant_cfg.tier_count:
                            continue
                        effective_tier_em = bbq_eff_em
                    else:
                        effective_tier_em = t
                    if effective_tier_em != tier or slug not in shop_slugs:
                        continue
                    display = SLUG_TO_DISPLAY.get(slug)
                    if not display or display not in expiring:
                        continue
                    if display in set(AILMENT_CURE_MAP.values()) or display == AILMENT_CURE_ALL:
                        continue
                    from module.umamusume.persistence import get_used_buffs
                    from module.umamusume.scenario.mant.inventory import ONE_TIME_BUFF_ITEMS
                    if display in ONE_TIME_BUFF_ITEMS and display in get_used_buffs():
                        continue
                    if display == "Energy Drink MAX":
                        owned_em = {n: q for n, q in getattr(ctx.cultivate_detail, 'mant_owned_items', [])}
                        if owned_em.get("Energy Drink MAX", 0) > 0:
                            continue

                    cost = SHOP_ITEM_COSTS.get(display, 9999)
                    copies = expiring_counts.get(display, 0)
                    if copies <= 0:
                        continue

                    threshold = 0
                    if tier > 1 and not post_senior_summer:
                        threshold = mant_cfg.tier_thresholds.get(tier, (tier - 1) * 50)

                    for _ in range(copies):
                        remaining_after = tmp_budget - cost
                        if remaining_after < 0:
                            break
                        if threshold > 0 and remaining_after < threshold:
                            break
                        emergency_targets.append(display)
                        tmp_budget -= cost
                        budget = tmp_budget

    active_ailments = getattr(ctx.cultivate_detail, 'mant_afflictions', [])
    if active_ailments:
        owned_map = {n: q for n, q in getattr(ctx.cultivate_detail, 'mant_owned_items', [])}
        shop_available = {name for name, _, _, _, p in shop_items if not p}
        bought_this_cycle = getattr(ctx.cultivate_detail, '_mant_bought_cures_this_cycle', set())

        if not owned_map.get(AILMENT_CURE_ALL, 0):
            any_uncovered = False
            for ailment in active_ailments:
                covered = False
                for ailment_name, cure_name in AILMENT_CURE_MAP.items():
                    if ailment_name.lower() not in ailment.lower():
                        continue
                    if owned_map.get(cure_name, 0) > 0 or cure_name in emergency_targets or cure_name in bought_this_cycle:
                        covered = True
                        break
                    if cure_name in shop_available:
                        cost = SHOP_ITEM_COSTS.get(cure_name, 9999)
                        if cost <= budget:
                            emergency_targets.append(cure_name)
                            bought_this_cycle.add(cure_name)
                            budget -= cost
                            covered = True
                    break
                if not covered:
                    any_uncovered = True

            if (any_uncovered
                    and AILMENT_CURE_ALL in shop_available
                    and AILMENT_CURE_ALL not in emergency_targets
                    and AILMENT_CURE_ALL not in bought_this_cycle
                    and owned_map.get(AILMENT_CURE_ALL, 0) <= 0):
                cost = SHOP_ITEM_COSTS.get(AILMENT_CURE_ALL, 9999)
                if cost <= budget:
                    emergency_targets.append(AILMENT_CURE_ALL)
                    budget -= cost

    if not emergency_targets:
        return False

    scan_result = scan_mant_shop(ctx)
    if scan_result is None:
        ctx.ctrl.trigger_decision_reset = True
        return True

    ctx.cultivate_detail.turn_info.mant_emergency_shop_done = True
    items_list, ratio, drag_ratio, first_item_gy = scan_result
    ctx.cultivate_detail.mant_shop_items = items_list

    fresh_available = {name for name, _, _, _, purchased in items_list if not purchased}
    final_targets = [tgt for tgt in emergency_targets if tgt in fresh_available]

    if not final_targets:
        ctx.ctrl.click(BACK_BTN_X, BACK_BTN_Y)
        _t.sleep(1)
        return True

    bought, _ = buy_shop_items(ctx, final_targets, items_list, ratio, drag_ratio, first_item_gy)
    if bought:
        ctx.cultivate_detail.mant_inventory_rescan_pending = True
        spent = sum(SHOP_ITEM_COSTS.get(tgt, 0) for tgt in final_targets)
        ctx.cultivate_detail.mant_coins = max(0, ctx.cultivate_detail.mant_coins - spent)
        bought_set = set(final_targets)
        ctx.cultivate_detail.mant_shop_items = [
            (name, conf, gy, turns, purchased or (name in bought_set))
            for name, conf, gy, turns, purchased in items_list
        ]
        from module.umamusume.context import log_detected_shop_items
        remaining = [(name, turns, purchased)
                     for name, _, _, turns, purchased in items_list
                     if not purchased and name not in bought_set]
        log_detected_shop_items(remaining)
    else:
        ctx.ctrl.click(BACK_BTN_X, BACK_BTN_Y)
        _t.sleep(1)

    return True


CLIMAX_MASTER_RESERVE = 40


def _would_cleat_be_used(cleat_name, race_id, current_date, owned_map):
    from module.umamusume.scenario.mant.inventory import MANT_CLIMAX_RACE_TURNS, remaining_climax_races
    from module.umamusume.asset.race_data import is_g1_race

    sim = dict(owned_map)
    sim[cleat_name] = sim.get(cleat_name, 0) + 1

    master_qty = sim.get('Master Cleat Hammer', 0)
    artisan_qty = sim.get('Artisan Cleat Hammer', 0)
    is_climax_race = current_date in MANT_CLIMAX_RACE_TURNS

    if is_climax_race:
        if cleat_name == 'Master Cleat Hammer':
            return master_qty > 0
        return artisan_qty > 0 and master_qty == 0

    races_left = remaining_climax_races(current_date)
    master_reserve = min(races_left, master_qty)
    artisan_reserve = max(0, races_left - master_reserve)
    master_spare = master_qty - master_reserve
    artisan_spare = artisan_qty - artisan_reserve

    if master_qty + artisan_qty <= 2:
        return False

    if is_g1_race(race_id):
        return master_spare > 0 or artisan_spare > 0
    else:
        return artisan_spare > 0


def handle_mant_cleat_shop_buy(ctx, current_date):
    from module.umamusume.constants.game_constants import CLASSIC_YEAR_END, SENIOR_YEAR_END
    from module.umamusume.scenario.mant.shop import (
        SHOP_ITEM_COSTS, scan_mant_shop, buy_shop_items, BACK_BTN_X, BACK_BTN_Y
    )
    import time as _t

    if getattr(ctx.cultivate_detail.turn_info, 'mant_cleat_shop_done', False):
        return False

    owned = dict(getattr(ctx.cultivate_detail, 'mant_owned_items', {}))
    master_qty = owned.get('Master Cleat Hammer', 0)
    artisan_qty = owned.get('Artisan Cleat Hammer', 0)
    total_cleats = master_qty + artisan_qty
    budget = ctx.cultivate_detail.mant_coins

    shop_items = getattr(ctx.cultivate_detail, 'mant_shop_items', [])
    if not shop_items:
        return False
    shop_available = {name for name, _, _, _, purchased in shop_items if not purchased}

    is_senior = CLASSIC_YEAR_END < current_date <= SENIOR_YEAR_END
    is_climax = current_date > SENIOR_YEAR_END

    if not (is_senior or is_climax):
        return False


    if is_senior:
        if total_cleats >= 2:
            return False
        for candidate in ('Master Cleat Hammer', 'Artisan Cleat Hammer'):
            if candidate not in shop_available:
                continue
            cost = SHOP_ITEM_COSTS.get(candidate, 9999)
            if cost > budget:
                continue
            return _execute_cleat_buy(ctx, candidate, cost)
        return False


    if is_climax:
        if total_cleats >= 3:
            return False
        if total_cleats < 2 and budget < 40:
            return False
        for candidate in ('Master Cleat Hammer', 'Artisan Cleat Hammer'):
            if candidate not in shop_available:
                continue
            cost = SHOP_ITEM_COSTS.get(candidate, 9999)
            if cost > budget:
                continue
            if total_cleats < 2 and budget - cost < 40:
                continue
            return _execute_cleat_buy(ctx, candidate, cost)
        return False

    return False


def _execute_cleat_buy(ctx, cleat_name, cost):
    from module.umamusume.scenario.mant.shop import (
        scan_mant_shop, buy_shop_items, BACK_BTN_X, BACK_BTN_Y
    )
    import time as _t

    scan_result = scan_mant_shop(ctx)
    if scan_result is None:
        ctx.ctrl.trigger_decision_reset = True
        return True

    ctx.cultivate_detail.turn_info.mant_cleat_shop_done = True
    items_list, ratio, drag_ratio, first_item_gy = scan_result
    ctx.cultivate_detail.mant_shop_items = items_list

    fresh_available = {n for n, _, _, _, p in items_list if not p}
    if cleat_name not in fresh_available:
        ctx.ctrl.click(BACK_BTN_X, BACK_BTN_Y)
        _t.sleep(1)
        return True

    bought, _ = buy_shop_items(ctx, [cleat_name], items_list, ratio, drag_ratio, first_item_gy)
    if bought:
        ctx.cultivate_detail.mant_inventory_rescan_pending = True
        ctx.cultivate_detail.mant_coins = max(0, ctx.cultivate_detail.mant_coins - cost)
        owned = dict(getattr(ctx.cultivate_detail, 'mant_owned_items', {}))
        owned[cleat_name] = owned.get(cleat_name, 0) + 1
        ctx.cultivate_detail.mant_owned_items = list(owned.items())
        ctx.cultivate_detail.mant_shop_items = [
            (n, c, g, t, p or (n == cleat_name))
            for n, c, g, t, p in items_list
        ]
        from module.umamusume.context import log_detected_shop_items
        log_detected_shop_items(
            [(n, t, p) for n, _, _, t, p in items_list if not p and n != cleat_name]
        )
    else:
        ctx.ctrl.click(BACK_BTN_X, BACK_BTN_Y)
        _t.sleep(1)

    return True


def handle_mant_main_menu(ctx, img, current_date):
    from module.umamusume.constants.game_constants import is_summer_camp_period

    if handle_mant_inventory_rescan_if_pending(ctx, current_date):
        return True

    if handle_mant_inventory_scan(ctx, current_date):
        return True

    from module.umamusume.scenario.mant.inventory import (
        has_instant_use_items, handle_instant_use_items, handle_cupcake_use
    )
    if has_instant_use_items(ctx):
        handle_instant_use_items(ctx)
        ctx.cultivate_detail.turn_info.parse_main_menu_finish = False
        return True

    if not getattr(ctx.cultivate_detail.turn_info, 'mant_cupcake_checked', False):
        ctx.cultivate_detail.turn_info.mant_cupcake_checked = True
        if handle_cupcake_use(ctx):
            return True

    if not getattr(ctx.cultivate_detail.turn_info, 'mant_main_menu_coins_read', False):
        is_summer = is_summer_camp_period(current_date)
        is_climax = current_date > 72 or current_date < -72
        coins = read_shop_coins(img, is_summer, is_climax)
        if coins == -1:
            coins = 0
        ctx.cultivate_detail.turn_info.mant_main_menu_coins_read = True
        ctx.cultivate_detail.mant_coins = coins

    if handle_mant_shop_scan(ctx, current_date):
        return True

    if handle_mant_emergency_shop_buys(ctx, current_date):
        return True

    handle_mant_on_sale(img)

    if handle_mant_afflictions(ctx, img):
        return True

    if handle_mant_cleat_shop_buy(ctx, current_date):
        return True

    return False


def handle_mant_on_sale(img):
    img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    sale_result = image_match(img_gray, REF_MANT_ON_SALE)
    if sale_result.find_match:
        log.info("shop on sale")
        return True
    return False


def try_use_cure_items(ctx):
    from module.umamusume.scenario.mant.constants import AILMENT_CURE_MAP, AILMENT_CURE_ALL
    from module.umamusume.scenario.mant.inventory import use_item_and_update_inventory

    afflictions = getattr(ctx.cultivate_detail, 'mant_afflictions', [])
    if not afflictions:
        return False

    owned = getattr(ctx.cultivate_detail, 'mant_owned_items', [])
    owned_map = {n: q for n, q in owned}

    if owned_map.get(AILMENT_CURE_ALL, 0) > 0:
        log.info(f"using {AILMENT_CURE_ALL} for {afflictions}")
        if use_item_and_update_inventory(ctx, AILMENT_CURE_ALL):
            ctx.cultivate_detail.mant_afflictions = []
            return True

    used_any = False
    for ailment in list(afflictions):
        for ailment_name, cure_name in AILMENT_CURE_MAP.items():
            if ailment_name.lower() not in ailment.lower():
                continue
            if owned_map.get(cure_name, 0) > 0:
                log.info(f"using {cure_name} for {ailment}")
                if use_item_and_update_inventory(ctx, cure_name):
                    owned_map[cure_name] = max(0, owned_map.get(cure_name, 0) - 1)
                    afflictions.remove(ailment)
                    used_any = True
            break

    ctx.cultivate_detail.mant_afflictions = afflictions
    return used_any


def handle_mant_afflictions(ctx, img):
    from module.umamusume.constants.game_constants import is_summer_camp_period
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    current_date = getattr(ctx.cultivate_detail.turn_info, 'date', 0)
    if is_summer_camp_period(current_date):
        medic_px = img_rgb[1118, 100]
    else:
        medic_px = img_rgb[1125, 40]
    medic_lit = medic_px[0] > 200 and medic_px[1] > 200 and medic_px[2] > 200
    if not medic_lit:
        ctx.cultivate_detail.mant_afflictions = []
        return False
    if medic_lit and not ctx.cultivate_detail.mant_afflictions:
        from module.umamusume.scenario.mant.afflictions import detect_afflictions
        afflictions = detect_afflictions(ctx)
        ctx.cultivate_detail.mant_afflictions = afflictions
        ctx.cultivate_detail.turn_info.parse_main_menu_finish = False
        return True
    if ctx.cultivate_detail.mant_afflictions:
        if try_use_cure_items(ctx):
            ctx.cultivate_detail.turn_info.parse_main_menu_finish = False
            return True
    return False


def color_match(px, target, tol):
    return (abs(int(px[0]) - target[0]) <= tol and
            abs(int(px[1]) - target[1]) <= tol and
            abs(int(px[2]) - target[2]) <= tol)


def handle_mant_rival_race(ctx, img):
    if getattr(ctx.cultivate_detail.turn_info, 'mant_rival_checked', False):
        return
    from module.umamusume.constants.game_constants import is_summer_camp_period
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    current_date = getattr(ctx.cultivate_detail.turn_info, 'date', 0)
    rival_x = 497 if is_summer_camp_period(current_date) else 565
    px = img_rgb[1089, rival_x]
    if color_match(px, RIVAL_COLOR_1, RIVAL_TOLERANCE) or color_match(px, RIVAL_COLOR_2, RIVAL_TOLERANCE):
        log.info("rival race detected")
        ctx.cultivate_detail.turn_info.turn_operation = None
        ctx.cultivate_detail.turn_info.parse_train_info_finish = False
    ctx.cultivate_detail.turn_info.mant_rival_checked = True
