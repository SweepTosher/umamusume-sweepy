import time
import threading

import numpy as np
import cv2

import bot.base.log as logger
from bot.recog.image_matcher import image_match
from module.umamusume.context import UmamusumeContext
from module.umamusume.types import TurnOperation
from module.umamusume.define import TrainingType, TurnOperationType, ScenarioType, SupportCardType, SupportCardFavorLevel
from module.umamusume.asset.point import (
    TRAINING_POINT_LIST, RETURN_TO_CULTIVATE_MAIN_MENU
)
from module.umamusume.constants.game_constants import (
    is_summer_camp_period, JUNIOR_YEAR_END, CLASSIC_YEAR_END, get_date_period_index
)
from module.umamusume.constants.scoring_constants import (
    DEFAULT_BASE_SCORES, DEFAULT_SCORE_VALUE, DEFAULT_SPIRIT_EXPLOSION,
    DEFAULT_SPECIAL_WEIGHTS, DEFAULT_REST_THRESHOLD,
    DEFAULT_STAT_VALUE_MULTIPLIER, DEFAULT_NPC_SCORE_VALUE
)
from module.umamusume.constants.timing_constants import (
    TRAINING_CLICK_DELAY, TRAINING_WAIT_DELAY, TRAINING_RETRY_DELAY,
    TRAINING_DETECTION_DELAY, ENERGY_READ_RETRY_DELAY,
    MAX_TRAINING_RETRY, MAX_DETECTION_ATTEMPTS
)
from module.umamusume.constants.game_constants import get_date_period_index
from module.umamusume.script.cultivate_task.parse import parse_train_type, parse_failure_rates
from module.umamusume.script.cultivate_task.helpers import should_use_pal_outing_simple
from bot.recog.training_stat_scanner import scan_facility_stats
from bot.recog.energy_scanner import scan_training_energy_change

log = logger.get_logger(__name__)


def script_cultivate_training_select(ctx: UmamusumeContext):
    if ctx.cultivate_detail.turn_info is None:
        log.warning("Turn information not initialized")
        ctx.ctrl.click_by_point(RETURN_TO_CULTIVATE_MAIN_MENU)
        return

    turn_op = ctx.cultivate_detail.turn_info.turn_operation

    if turn_op is not None:
        if turn_op.turn_operation_type == TurnOperationType.TURN_OPERATION_TYPE_TRAINING:
            training_type = turn_op.training_type
            ctx.ctrl.click_by_point(TRAINING_POINT_LIST[training_type.value - 1])
            time.sleep(TRAINING_CLICK_DELAY)
            ctx.ctrl.click_by_point(TRAINING_POINT_LIST[training_type.value - 1])
            time.sleep(TRAINING_WAIT_DELAY)
            return

        else:
            ctx.ctrl.click_by_point(RETURN_TO_CULTIVATE_MAIN_MENU)
            return

    limit = int(getattr(ctx.cultivate_detail, 'rest_threshold', getattr(ctx.cultivate_detail, 'rest_treshold', getattr(ctx.cultivate_detail, 'fast_path_energy_limit', DEFAULT_REST_THRESHOLD))))
    if limit == 0:
        energy = 100
    else:
        from bot.conn.fetch import read_energy
        energy = read_energy()
        if energy == 0:
            time.sleep(ENERGY_READ_RETRY_DELAY)
            energy = read_energy()
    if energy <= limit:
        op = TurnOperation()
        if should_use_pal_outing_simple(ctx):
            op.turn_operation_type = TurnOperationType.TURN_OPERATION_TYPE_TRIP
        else:
            log.info(f"rest threshold: energy={energy}, threshold={limit} - prioritizing rest")
            op.turn_operation_type = TurnOperationType.TURN_OPERATION_TYPE_REST
        ctx.cultivate_detail.turn_info.turn_operation = op
        ctx.ctrl.click_by_point(RETURN_TO_CULTIVATE_MAIN_MENU)
        return

    if not ctx.cultivate_detail.turn_info.parse_train_info_finish:

        class TrainingDetectionResult:
            def __init__(self):
                self.support_card_info_list = []
                self.has_hint = False
                self.failure_rate = -1
                self.speed_incr = 0
                self.stamina_incr = 0
                self.power_incr = 0
                self.will_incr = 0
                self.intelligence_incr = 0
                self.skill_point_incr = 0
                self.energy_change = 0.0

        def detect_training_once(ctx, img, train_type, energy_change=None):
            result = TrainingDetectionResult()
            facility_map = {
                TrainingType.TRAINING_TYPE_SPEED: "speed",
                TrainingType.TRAINING_TYPE_STAMINA: "stamina",
                TrainingType.TRAINING_TYPE_POWER: "power",
                TrainingType.TRAINING_TYPE_WILL: "guts",
                TrainingType.TRAINING_TYPE_INTELLIGENCE: "wits",
            }
            result.facility_name = facility_map.get(train_type)
            result.scenario_name = "ura" if ctx.cultivate_detail.scenario.scenario_type() == ScenarioType.SCENARIO_TYPE_URA else "aoharuhai"
            result.stat_results = {}
            result.energy_change = energy_change if energy_change is not None else 0.0
            try:
                if result.facility_name:
                    result.stat_results = scan_facility_stats(img, result.facility_name, result.scenario_name)
                train_incr = ctx.cultivate_detail.scenario.parse_training_result(img)
                result.speed_incr = train_incr[0]
                result.stamina_incr = train_incr[1]
                result.power_incr = train_incr[2]
                result.will_incr = train_incr[3]
                result.intelligence_incr = train_incr[4]
                result.skill_point_incr = train_incr[5]
            except Exception:
                pass
            try:
                parse_failure_rates(ctx, img, train_type)
                til = ctx.cultivate_detail.turn_info.training_info_list[train_type.value - 1]
                result.failure_rate = getattr(til, 'failure_rate', -1)
            except Exception:
                pass
            try:
                result.support_card_info_list = ctx.cultivate_detail.scenario.parse_training_support_card(img)
            except Exception:
                pass
            try:
                from module.umamusume.asset.template import REF_TRAINING_HINT
                import cv2 as cv2_local
                roi = img[181:769, 666:690]
                roi_gray = cv2_local.cvtColor(roi, cv2_local.COLOR_BGR2GRAY)
                result.has_hint = image_match(roi_gray, REF_TRAINING_HINT).find_match
            except Exception:
                pass
            return result

        def compare_detection_results(result1, result2):
            if len(result1.support_card_info_list) != len(result2.support_card_info_list):
                return False
            for sc1, sc2 in zip(result1.support_card_info_list, result2.support_card_info_list):
                if getattr(sc1, "card_type", None) != getattr(sc2, "card_type", None):
                    return False
                if getattr(sc1, "favor", None) != getattr(sc2, "favor", None):
                    return False
            if result1.has_hint != result2.has_hint:
                return False
            if result1.failure_rate != result2.failure_rate:
                return False
            if result1.speed_incr != result2.speed_incr:
                return False
            if result1.stamina_incr != result2.stamina_incr:
                return False
            if result1.power_incr != result2.power_incr:
                return False
            if result1.will_incr != result2.will_incr:
                return False
            if result1.intelligence_incr != result2.intelligence_incr:
                return False
            if result1.skill_point_incr != result2.skill_point_incr:
                return False
            return True

        def apply_detection_result(ctx, train_type, result):
            til = ctx.cultivate_detail.turn_info.training_info_list[train_type.value - 1]
            til.support_card_info_list = result.support_card_info_list
            til.has_hint = result.has_hint
            til.failure_rate = result.failure_rate
            til.speed_incr = result.speed_incr
            til.stamina_incr = result.stamina_incr
            til.power_incr = result.power_incr
            til.will_incr = result.will_incr
            til.intelligence_incr = result.intelligence_incr
            til.skill_point_incr = result.skill_point_incr
            til.stat_results = getattr(result, 'stat_results', {})
            til.energy_change = getattr(result, 'energy_change', 0.0)
            tt_map = {
                TrainingType.TRAINING_TYPE_SPEED: SupportCardType.SUPPORT_CARD_TYPE_SPEED,
                TrainingType.TRAINING_TYPE_STAMINA: SupportCardType.SUPPORT_CARD_TYPE_STAMINA,
                TrainingType.TRAINING_TYPE_POWER: SupportCardType.SUPPORT_CARD_TYPE_POWER,
                TrainingType.TRAINING_TYPE_WILL: SupportCardType.SUPPORT_CARD_TYPE_WILL,
                TrainingType.TRAINING_TYPE_INTELLIGENCE: SupportCardType.SUPPORT_CARD_TYPE_INTELLIGENCE,
            }
            target = tt_map.get(train_type)
            relevant_count = 0
            for sc in result.support_card_info_list:
                if getattr(sc, "card_type", None) == target:
                    relevant_count += 1
            til.relevant_count = relevant_count

        def parse_training_with_retry(ctx, img, train_type, energy_change=None):
            for attempt in range(MAX_DETECTION_ATTEMPTS):
                result1 = detect_training_once(ctx, img, train_type, energy_change)
                time.sleep(TRAINING_DETECTION_DELAY)
                result2 = detect_training_once(ctx, img, train_type, energy_change)
                if compare_detection_results(result1, result2):
                    apply_detection_result(ctx, train_type, result1)
                    return
                time.sleep(TRAINING_DETECTION_DELAY)
            apply_detection_result(ctx, train_type, result2)

        def clear_training(ctx: UmamusumeContext, train_type: 'TrainingType'):
            til = ctx.cultivate_detail.turn_info.training_info_list[train_type.value - 1]
            til.speed_incr = 0
            til.stamina_incr = 0
            til.power_incr = 0
            til.will_incr = 0
            til.intelligence_incr = 0
            til.skill_point_incr = 0
            til.support_card_info_list = []
            til.stat_results = {}

        threads: list[threading.Thread] = []
        blocked_trainings = [False] * 5
        energy_changes: list[tuple[int, float]] = []

        date = ctx.cultivate_detail.turn_info.date
        if date == 0:
            extra_weight = [0, 0, 0, 0, 0]
        elif date <= JUNIOR_YEAR_END:
            extra_weight = ctx.cultivate_detail.extra_weight[0]
        elif date <= CLASSIC_YEAR_END:
            extra_weight = ctx.cultivate_detail.extra_weight[1]
        else:
            extra_weight = ctx.cultivate_detail.extra_weight[2]

        try:
            if is_summer_camp_period(date) and isinstance(ctx.cultivate_detail.extra_weight, (list, tuple)) and len(ctx.cultivate_detail.extra_weight) >= 4:
                extra_weight = ctx.cultivate_detail.extra_weight[3]
        except Exception:
            pass

        img = ctx.current_screen
        train_type = parse_train_type(ctx, img)
        if train_type == TrainingType.TRAINING_TYPE_UNKNOWN:
            return
        viewed = train_type.value

   

        if extra_weight[viewed - 1] > -1:
           
            facility_map = {
                TrainingType.TRAINING_TYPE_SPEED: "speed",
                TrainingType.TRAINING_TYPE_STAMINA: "stamina",
                TrainingType.TRAINING_TYPE_POWER: "power",
                TrainingType.TRAINING_TYPE_WILL: "guts",
                TrainingType.TRAINING_TYPE_INTELLIGENCE: "wits",
            }
            facility_name = facility_map.get(train_type)
            immediate_img = ctx.ctrl.get_screen()
            thread = threading.Thread(target=parse_training_with_retry, args=(ctx, immediate_img, train_type, None))
            threads.append(thread)
            thread.start()
            energy_change, _ = scan_training_energy_change(ctx.ctrl, facility_name, initial_img=immediate_img)
            energy_changes.append((viewed - 1, energy_change))
        else:
            clear_training(ctx, train_type)

        facility_map = {
            TrainingType.TRAINING_TYPE_SPEED: "speed",
            TrainingType.TRAINING_TYPE_STAMINA: "stamina",
            TrainingType.TRAINING_TYPE_POWER: "power",
            TrainingType.TRAINING_TYPE_WILL: "guts",
            TrainingType.TRAINING_TYPE_INTELLIGENCE: "wits",
        }
        
        for i in range(5):
            if i != (viewed - 1):
                if extra_weight[i] > -1:
                    retry = 0
                    ctx.ctrl.click_by_point(TRAINING_POINT_LIST[i])
                    img = ctx.ctrl.get_screen()
                    while parse_train_type(ctx, img) != TrainingType(i + 1) and retry < MAX_TRAINING_RETRY:
                        if retry > 2:
                            ctx.ctrl.click_by_point(TRAINING_POINT_LIST[i])
                        time.sleep(TRAINING_RETRY_DELAY)
                        img = ctx.ctrl.get_screen()
                        retry += 1
                    if retry == MAX_TRAINING_RETRY:
                        log.info(f"Training {TrainingType(i + 1).name} is restricted by game - skipping")
                        blocked_trainings[i] = True
                        clear_training(ctx, TrainingType(i + 1))
                        continue

                    train_type_i = TrainingType(i + 1)
                    facility_name = facility_map.get(train_type_i)
                    thread = threading.Thread(target=parse_training_with_retry, args=(ctx, img, train_type_i, None))
                    threads.append(thread)
                    thread.start()
                    energy_change, _ = scan_training_energy_change(ctx.ctrl, facility_name, initial_img=img)
                    energy_changes.append((i, energy_change))
                else:
                    clear_training(ctx, TrainingType(i + 1))

        for thread in threads:
            thread.join()

        for idx, energy_val in energy_changes:
            ctx.cultivate_detail.turn_info.training_info_list[idx].energy_change = energy_val

        date = ctx.cultivate_detail.turn_info.date
        sv = getattr(ctx.cultivate_detail, 'score_value', DEFAULT_SCORE_VALUE)
        def resolve_weights(sv_list, idx):
            try:
                arr = sv_list[idx]
            except Exception:
                arr = [0.11, 0.10, 0.006, 0.09]
            if not isinstance(arr, (list, tuple)):
                arr = [0.11, 0.10, 0.006, 0.09]
            base = list(arr[:4])
            if len(base) < 4:
                base += [0.09] * (4 - len(base))
            special_defaults = DEFAULT_SPECIAL_WEIGHTS
            try:
                special = arr[4]
            except Exception:
                special = special_defaults[idx if 0 <= idx < len(special_defaults) else 0]
            return base + [special]
        period_idx = get_date_period_index(date)
        w_lv1, w_lv2, w_energy_change, w_hint, w_special = resolve_weights(sv, period_idx)
        try:
            se_config = getattr(ctx.cultivate_detail, 'spirit_explosion', DEFAULT_SPIRIT_EXPLOSION)
            if isinstance(se_config, list) and len(se_config) > 0 and isinstance(se_config[0], list):
                se_weights = se_config[period_idx]
            else:
                se_weights = se_config
        except Exception:
            se_weights = DEFAULT_SPIRIT_EXPLOSION

        type_map = [
            SupportCardType.SUPPORT_CARD_TYPE_SPEED,
            SupportCardType.SUPPORT_CARD_TYPE_STAMINA,
            SupportCardType.SUPPORT_CARD_TYPE_POWER,
            SupportCardType.SUPPORT_CARD_TYPE_WILL,
            SupportCardType.SUPPORT_CARD_TYPE_INTELLIGENCE,
        ]
        names = ["Speed", "Stamina", "Power", "Guts", "Wit"]
        stat_keys = ["speed", "stamina", "power", "guts", "wits", "sp"]
        computed_scores = [0.0, 0.0, 0.0, 0.0, 0.0]
        special_counts = [0, 0, 0, 0, 0]
        spirit_counts = [0, 0, 0, 0, 0]
        stat_contributions = [[0.0] * 6 for _ in range(5)]

        pre_highest_stat_idx = None
        try:
            d_pre = int(ctx.cultivate_detail.turn_info.date)
            if isinstance(d_pre, int) and d_pre > 48 and d_pre <= 72:
                uma_pre = ctx.cultivate_detail.turn_info.uma_attribute
                stats_pre = [uma_pre.speed, uma_pre.stamina, uma_pre.power, uma_pre.will, uma_pre.intelligence]
                pre_highest_stat_idx = int(np.argmax(stats_pre)) if len(stats_pre) == 5 else None
        except Exception:
            pass

        stat_mult = getattr(ctx.cultivate_detail, 'stat_value_multiplier', DEFAULT_STAT_VALUE_MULTIPLIER)
        if not isinstance(stat_mult, (list, tuple)) or len(stat_mult) < 6:
            stat_mult = DEFAULT_STAT_VALUE_MULTIPLIER



        from bot.conn.fetch import read_energy
        try:
            current_energy = int(read_energy())
            if current_energy == 0:
                time.sleep(ENERGY_READ_RETRY_DELAY)
                current_energy = int(read_energy())
        except Exception:
            current_energy = None
        try:
            rest_threshold = int(getattr(ctx.cultivate_detail, 'rest_threshold', getattr(ctx.cultivate_detail, 'rest_treshold', getattr(ctx.cultivate_detail, 'fast_path_energy_limit', DEFAULT_REST_THRESHOLD))))
        except Exception:
            rest_threshold = DEFAULT_REST_THRESHOLD
        
        base_scores = getattr(ctx.cultivate_detail, 'base_score', DEFAULT_BASE_SCORES)

        base_energy = getattr(ctx.cultivate_detail.turn_info, 'base_energy', None)
        if base_energy is not None:
            log.info(f"Base Energy: {base_energy:.1f}%{' (high energy)' if base_energy >= 80 else ''}")

        for idx in range(5):
            til = ctx.cultivate_detail.turn_info.training_info_list[idx]
            target_type = type_map[idx]
            lv1c = 0
            lv2c = 0
            npc = 0
            npc_total_contrib = 0.0
            pal_count = 0
            score = base_scores[idx] if isinstance(base_scores, (list, tuple)) and len(base_scores) > idx else 0.0
            for sc in (getattr(til, "support_card_info_list", []) or []):
                favor = getattr(sc, "favor", SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_UNKNOWN)
                ctype = getattr(sc, "card_type", SupportCardType.SUPPORT_CARD_TYPE_UNKNOWN)
                try:
                    stc = int(getattr(sc, 'special_training_count', 1 if getattr(sc, 'can_incr_special_training', False) else 0))
                except Exception:
                    stc = 1 if getattr(sc, 'can_incr_special_training', False) else 0
                if stc > 0:
                    special_counts[idx] += stc
                if bool(getattr(sc, 'spirit_explosion', False)):
                    spirit_counts[idx] += 1
                if ctype == SupportCardType.SUPPORT_CARD_TYPE_NPC:
                    npc += 1
                    npc_scores = getattr(ctx.cultivate_detail, 'npc_score_value', DEFAULT_NPC_SCORE_VALUE)
                    npc_period_idx = get_date_period_index(date)
                    npc_add = 0.0
                    if npc_period_idx < len(npc_scores):
                        npc_arr = npc_scores[npc_period_idx]
                        if favor == SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_1:
                            npc_add = npc_arr[0]
                        elif favor == SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_2:
                            npc_add = npc_arr[1]
                        elif favor in (SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_3, SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_4):
                            npc_add = npc_arr[2]
                    score += npc_add
                    npc_total_contrib += npc_add
                    continue
                if ctype == SupportCardType.SUPPORT_CARD_TYPE_UNKNOWN:
                    continue
                if favor == SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_UNKNOWN:
                    continue

                if ctype == SupportCardType.SUPPORT_CARD_TYPE_FRIEND:
                    pal_count += 1
                    pal_scores = ctx.cultivate_detail.pal_friendship_score
                    if favor == SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_1:
                        score += pal_scores[0]
                    elif favor == SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_2:
                        score += pal_scores[1]
                    elif favor in (SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_3, SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_4):
                        score += pal_scores[2]
                    continue
                if favor in (SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_3, SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_4) and ctype == target_type:
                    continue
                if favor == SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_1:
                    lv1c += 1
                    score += w_lv1
                elif favor == SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_2:
                    lv2c += 1
                    score += w_lv2
            
            stat_results = getattr(til, 'stat_results', {})
            stat_score = 0.0
            stat_parts = []
            for sk_idx, sk in enumerate(stat_keys):
                sv_val = stat_results.get(sk, 0)
                if sv_val > 0:
                    contrib = sv_val * stat_mult[sk_idx]
                    stat_score += contrib
                    stat_contributions[idx][sk_idx] = contrib
                    if pre_highest_stat_idx is not None and sk_idx == pre_highest_stat_idx:
                        stat_parts.append(f"{sk}:{sv_val} (-5% score)")
                    else:
                        stat_parts.append(f"{sk}:{sv_val}")
            
            score += stat_score
            try:
                fr = int(getattr(til, 'failure_rate', -1))
            except Exception:
                fr = -1
            hint_bonus = 0.0
            try:
                hint_bonus = w_hint if bool(getattr(til, 'has_hint', False)) else 0.0
            except Exception:
                hint_bonus = 0.0
            score += hint_bonus
            energy_change_val = getattr(til, 'energy_change', 0.0)
            energy_change_contrib = energy_change_val * w_energy_change
            if base_energy is not None and base_energy >= 80 and energy_change_val < 0:
                energy_change_contrib *= 0.9
            score += energy_change_contrib
            stc_lane = special_counts[idx]
            special_bonus = 0.0
            if stc_lane > 0:
                special_bonus = float(w_special)
                score += special_bonus
            try:
                se_w = float(se_weights[idx]) if isinstance(se_weights, (list, tuple)) and len(se_weights) == 5 else 0.0
            except Exception:
                se_w = 0.0

            if current_energy is not None and se_w != 0.0 and idx != 4:
                if current_energy >= 90:
                    se_w *= 1.1
                elif 40 <= current_energy <= 50:
                    se_w *= 0.9

            se_lane = spirit_counts[idx]
            spirit_bonus = 0.0
            if se_lane > 0 and se_w != 0.0:
                spirit_bonus = se_w
                score += spirit_bonus

            try:
                scenario = ctx.cultivate_detail.scenario
                if scenario is not None:
                    score = scenario.adjust_training_score(ctx, idx, score, spirit_counts, current_energy)
            except Exception:
                pass

            pal_mult = 1.0
            if pal_count > 0:
                clamped_multiplier = max(0.0, min(1.0, ctx.cultivate_detail.pal_card_multiplier))
                pal_mult = 1.0 + clamped_multiplier
                score *= pal_mult
            
            fail_mult = 1.0
            try:
                if getattr(ctx.cultivate_detail, 'compensate_failure', True):
                    fr_val = int(getattr(til, 'failure_rate', -1))
                    if fr_val >= 0:
                        fail_mult = max(0.0, 1.0 - (float(fr_val) / 50.0))
                        score *= fail_mult
            except Exception:
                pass

            energy_mult = 1.0
            if idx == 4 and current_energy is not None:
                if current_energy > 90:
                    if date > 72:
                        energy_mult = 0.35
                    else:
                        energy_mult = 0.75
                elif 85 > current_energy:
                    energy_mult = 1.10
                score *= energy_mult

            target_mult = 1.0
            try:
                expect_attr = ctx.cultivate_detail.expect_attribute
                if isinstance(expect_attr, list) and len(expect_attr) == 5:
                    uma = ctx.cultivate_detail.turn_info.uma_attribute
                    curr_vals = [uma.speed, uma.stamina, uma.power, uma.will, uma.intelligence]
                    cap_val = float(expect_attr[idx])
                    curr_val = float(curr_vals[idx])
                    if cap_val > 0:
                        ratio = curr_val / cap_val
                        if ratio > 0.95:
                            target_mult = 0.0
                        elif ratio >= 0.90:
                            target_mult = 0.7
                        elif ratio >= 0.80:
                            target_mult = 0.8
                        elif ratio >= 0.70:
                            target_mult = 0.9
                        score *= target_mult
            except Exception:
                pass
            
            weight_mult = 1.0
            try:
                ew = extra_weight[idx] if isinstance(extra_weight, (list, tuple)) and len(extra_weight) == 5 else 0.0
            except Exception:
                ew = 0.0
            if ew > -1.0:
                weight_mult = 1.0 + float(ew)
                if weight_mult < 0.0:
                    weight_mult = 0.0
                elif weight_mult > 2.0:
                    weight_mult = 2.0
                score *= weight_mult

            computed_scores[idx] = score
            
            base_val = base_scores[idx] if isinstance(base_scores, (list, tuple)) and len(base_scores) > idx else 0.0
            lv1_contrib = lv1c * w_lv1
            lv2_contrib = lv2c * w_lv2
            
            formula_parts = []
            formula_parts.append(f"base:{base_val:.2f}")
            if stat_score > 0:
                formula_parts.append(f"stats:+{stat_score:.3f}")
            if lv1_contrib > 0:
                formula_parts.append(f"lv1({lv1c}):+{lv1_contrib:.3f}")
            if lv2_contrib > 0:
                formula_parts.append(f"lv2({lv2c}):+{lv2_contrib:.3f}")
            if energy_change_contrib != 0:
                formula_parts.append(f"nrg({energy_change_val:+.1f}):{energy_change_contrib:+.3f}")
            if npc_total_contrib > 0:
                formula_parts.append(f"npc({npc}):+{npc_total_contrib:.3f}")
            if hint_bonus > 0:
                formula_parts.append(f"hint:+{hint_bonus:.3f}")
            if special_bonus > 0:
                formula_parts.append(f"special:+{special_bonus:.3f}")
            if spirit_bonus > 0:
                formula_parts.append(f"spirit:+{spirit_bonus:.3f}")
            
            mult_parts = []
            if pal_mult != 1.0:
                mult_parts.append(f"pal:x{pal_mult:.2f}")
            if fail_mult != 1.0:
                mult_parts.append(f"fail:x{fail_mult:.2f}")
            if energy_mult != 1.0:
                mult_parts.append(f"energy:x{energy_mult:.2f}")
            if target_mult != 1.0:
                mult_parts.append(f"target:x{target_mult:.2f}")
            if weight_mult != 1.0:
                mult_parts.append(f"weight:x{weight_mult:.2f}")
            
            formula_str = " ".join(formula_parts)
            if mult_parts:
                formula_str += " | " + " ".join(mult_parts)
            
            stat_str = " | " + " ".join(stat_parts) if stat_parts else ""
            nrg_change = getattr(til, 'energy_change', 0.0)
            nrg_str = f" | nrg:{nrg_change:+.1f}" if nrg_change != 0 else ""
            log.info(f"{names[idx]}: {score:.3f} = [{formula_str}]{stat_str}{nrg_str}")

        ctx.cultivate_detail.turn_info.parse_train_info_finish = True

        for idx in range(5):
            if extra_weight[idx] == -1:
                computed_scores[idx] = -float('inf')

        try:
            d = int(ctx.cultivate_detail.turn_info.date)
        except Exception:
            d = -1
        highest_stat_idx = None
        if isinstance(d, int) and d > 48 and d <= 72:
            try:
                uma = ctx.cultivate_detail.turn_info.uma_attribute
                stats = [uma.speed, uma.stamina, uma.power, uma.will, uma.intelligence]
                highest_stat_idx = int(np.argmax(stats)) if len(stats) == 5 else None
                if highest_stat_idx is not None:
                    computed_scores[highest_stat_idx] *= 0.95
                    penalty_parts = []
                    for i in range(5):
                        penalty = stat_contributions[i][highest_stat_idx] * 0.05
                        if penalty > 0:
                            computed_scores[i] -= penalty
                            penalty_parts.append(f"{names[i]}:-{penalty:.3f}")
                    try:
                        log.info(f"-5% to {names[highest_stat_idx]} facility (highest stat); -5% {stat_keys[highest_stat_idx]} score across: {', '.join(penalty_parts) if penalty_parts else 'none'}")
                    except Exception:
                        pass
            except Exception:
                pass

        max_score = max(computed_scores) if len(computed_scores) == 5 else 0.0
        eps = 1e-9
        
        blocked_count = sum(blocked_trainings)
        available_trainings = [i for i, blocked in enumerate(blocked_trainings) if not blocked]
        
        if blocked_count == 4 and len(available_trainings) == 1:
            chosen_idx = available_trainings[0]
        else:
        
            if not hasattr(ctx.cultivate_detail.turn_info, 'race_search_attempted') and date <= 72:
                wit_race_threshold = getattr(ctx.cultivate_detail, 'wit_race_search_threshold', 0.15)
                
                from bot.conn.fetch import read_energy
                current_energy = read_energy()
                if current_energy == 0:
                    time.sleep(0.37)
                    current_energy = read_energy()
                
                from module.umamusume.asset.race_data import get_races_for_period
                next_date = ctx.cultivate_detail.turn_info.date + 1
                available_races = get_races_for_period(next_date)
                has_extra_race_next = len([r for r in ctx.cultivate_detail.extra_race_list 
                                           if r in available_races]) > 0
                
                if (max_score < wit_race_threshold and 
                    current_energy > 90 and 
                    not has_extra_race_next):
                    
                    log.info(f"Race search: Max score {max_score:.3f}<{wit_race_threshold}, Energy {current_energy}>90, No races next turn")
                    
                    ctx.cultivate_detail.turn_info.race_search_attempted = True
                    
                    op = TurnOperation()
                    op.turn_operation_type = TurnOperationType.TURN_OPERATION_TYPE_RACE
                    op.race_id = 0
                    ctx.cultivate_detail.turn_info.turn_operation = op
                    
                    ctx.ctrl.click_by_point(RETURN_TO_CULTIVATE_MAIN_MENU)
                    return
            
            if date in (35, 36, 59, 60):
                best_idx_tmp = int(np.argmax(computed_scores))
                best_score_tmp = computed_scores[best_idx_tmp]
                summer_threshold = getattr(ctx.cultivate_detail, 'summer_score_threshold', 0.34)
                if best_score_tmp < summer_threshold:
                    log.info(f"Low training score before summer, conserving energy (score < {summer_threshold:.2f})")
                    chosen_idx = 4
                else:
                    ties = [i for i, v in enumerate(computed_scores) if abs(v - max_score) < eps]
                    chosen_idx = 4 if 4 in ties else (min(ties) if len(ties) > 0 else best_idx_tmp)
            else:
                ties = [i for i, v in enumerate(computed_scores) if abs(v - max_score) < eps]
                chosen_idx = 4 if 4 in ties else (min(ties) if len(ties) > 0 else int(np.argmax(computed_scores)))
        local_training_type = TrainingType(chosen_idx + 1)

    from module.umamusume.script.cultivate_task.ai import get_operation
    op_ai = get_operation(ctx)
    if op_ai is None:
        op = TurnOperation()
        op.turn_operation_type = TurnOperationType.TURN_OPERATION_TYPE_TRAINING
        op.training_type = local_training_type
        ctx.cultivate_detail.turn_info.turn_operation = op
    else:
        if op_ai.turn_operation_type == TurnOperationType.TURN_OPERATION_TYPE_TRAINING and (op_ai.training_type == TrainingType.TRAINING_TYPE_UNKNOWN):
            op_ai.training_type = local_training_type
        ctx.cultivate_detail.turn_info.turn_operation = op_ai

    try:
        best_idx_tmp = int(np.argmax(computed_scores))
        best_score_tmp = computed_scores[best_idx_tmp]
    except Exception:
        best_idx_tmp = None
        best_score_tmp = 0.0
    
    if (ctx.cultivate_detail.prioritize_recreation and 
        ctx.cultivate_detail.pal_event_stage > 0 and
        best_idx_tmp is not None):
        
        op_from_ai = ctx.cultivate_detail.turn_info.turn_operation
        
        is_race_operation = (op_from_ai is not None and 
                            op_from_ai.turn_operation_type == TurnOperationType.TURN_OPERATION_TYPE_RACE)
        
        if is_race_operation:
            log.info("Race goal detected - prioritizing race over pal outing")
        elif op_from_ai is not None and op_from_ai.turn_operation_type == TurnOperationType.TURN_OPERATION_TYPE_TRAINING:
            from bot.conn.fetch import fetch_state
            
            pal_name = ctx.cultivate_detail.pal_name
            pal_thresholds = ctx.cultivate_detail.pal_thresholds
            
            if pal_name and pal_thresholds:
                pal_data = pal_thresholds
                stage = ctx.cultivate_detail.pal_event_stage
                
                if stage <= len(pal_data):
                    thresholds = pal_data[stage - 1]
                    mood_threshold, energy_threshold, score_threshold = thresholds
                    
                    state = fetch_state()
                    current_energy = state.get("energy", 0)
                    current_mood_raw = state.get("mood")
                    current_mood = current_mood_raw if current_mood_raw is not None else 4
                    current_score = best_score_tmp
                    
                    mood_below = current_mood <= mood_threshold
                    energy_below = current_energy <= energy_threshold
                    score_below = current_score <= score_threshold
                    
                    log.info(f"PAL outing - Stage {stage}:")
                    log.info(f"Mood: {current_mood} vs {mood_threshold} - {'<' if mood_below else '>'}")
                    log.info(f"Energy: {current_energy} vs {energy_threshold} - {'<' if energy_below else '>'}")
                    log.info(f"Score: {current_score:.3f} vs {score_threshold} - {'<' if score_below else '>'}")
                    
                    if mood_below and energy_below and score_below:
                        log.info("All 3 conditions < thresholds - overriding to pal outing")
                        op_from_ai.turn_operation_type = TurnOperationType.TURN_OPERATION_TYPE_TRIP
                        ctx.cultivate_detail.turn_info.turn_operation = op_from_ai
                        ctx.ctrl.click_by_point(RETURN_TO_CULTIVATE_MAIN_MENU)
                        return
                    else:
                        log.info("At least one condition failed - continuing with training")
    
    op = ctx.cultivate_detail.turn_info.turn_operation
    if op.turn_operation_type == TurnOperationType.TURN_OPERATION_TYPE_TRAINING:
        if op.training_type == TrainingType.TRAINING_TYPE_UNKNOWN:
            op.training_type = local_training_type
        
        ctx.ctrl.click_by_point(TRAINING_POINT_LIST[op.training_type.value - 1])
        time.sleep(0.35)
        ctx.ctrl.click_by_point(TRAINING_POINT_LIST[op.training_type.value - 1])
        time.sleep(1.5)
        return
    
    ctx.ctrl.click_by_point(RETURN_TO_CULTIVATE_MAIN_MENU)
    return
