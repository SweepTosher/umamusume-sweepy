import json
import time
import threading

import numpy as np

from bot.base.task import TaskStatus, EndTaskReason
from module.umamusume.asset.point import *
from module.umamusume.define import TrainingType
from module.umamusume.types import TurnInfo, TurnOperationType, TurnOperation
from module.umamusume.script.cultivate_task.const import SKILL_LEARN_PRIORITY_LIST
from module.umamusume.script.cultivate_task.event.manifest import get_event_choice
from module.umamusume.script.cultivate_task.parse import *
from module.umamusume.asset.template import *

log = logger.get_logger(__name__)


def should_use_pal_outing_simple(ctx: UmamusumeContext):
    if not getattr(ctx.cultivate_detail, 'prioritize_recreation', False):
        return False
    if ctx.cultivate_detail.pal_event_stage <= 0:
        return False
    
    img = ctx.current_screen
    if img is None:
        return False
    
    img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    from module.umamusume.asset.template import UI_RECREATION_FRIEND_NOTIFICATION
    result = image_match(img_gray, UI_RECREATION_FRIEND_NOTIFICATION)
    if not result.find_match:
        return False
    
    pal_thresholds = ctx.cultivate_detail.pal_thresholds
    if not pal_thresholds:
        return False
    
    stage = ctx.cultivate_detail.pal_event_stage
    if stage > len(pal_thresholds):
        return False
    
    thresholds = pal_thresholds[stage - 1]
    mood_threshold = thresholds[0]
    energy_threshold = thresholds[1]
    
    from bot.conn.fetch import fetch_state
    state = fetch_state()
    current_energy = state.get("energy", 0)
    current_mood_raw = state.get("mood")
    current_mood = current_mood_raw if current_mood_raw is not None else 4
    
    mood_below = current_mood <= mood_threshold
    energy_below = current_energy <= energy_threshold
    
    log.info(f"PAL outing check - Stage {stage}:")
    log.info(f"Mood: {current_mood} vs {mood_threshold} - {'<=' if mood_below else '>'}")
    log.info(f"Energy: {current_energy} vs {energy_threshold} - {'<=' if energy_below else '>'}")
    
    if mood_below and energy_below:
        log.info("Both conditions met - using pal outing instead of rest")
        return True
    else:
        log.info("Conditions not met - using rest")
        return False


def script_cultivate_main_menu(ctx: UmamusumeContext):
    img = ctx.current_screen
    current_date = parse_date(img, ctx)
    if current_date == -1:
        log.warning("Failed to parse date")
        return
    # If entering a new turn, record old turn info and create new one
    if ctx.cultivate_detail.turn_info is None or current_date != ctx.cultivate_detail.turn_info.date:
        if ctx.cultivate_detail.turn_info is not None:
            ctx.cultivate_detail.turn_info_history.append(ctx.cultivate_detail.turn_info)
        ctx.cultivate_detail.turn_info = TurnInfo()
        ctx.cultivate_detail.turn_info.date = current_date
        
        if current_date == 2:
            log.info("new run detected resetting manual purchase state")
            ctx.cultivate_detail.manual_purchase_completed = False
            if hasattr(ctx.cultivate_detail, 'manual_purchase_initiated'):
                delattr(ctx.cultivate_detail, 'manual_purchase_initiated')

    if not ctx.cultivate_detail.turn_info.parse_main_menu_finish:
        parse_cultivate_main_menu(ctx, img)
        
        from module.umamusume.asset.race_data import get_races_for_period
        available_races = get_races_for_period(ctx.cultivate_detail.turn_info.date)
        has_extra_race = len([race_id for race_id in ctx.cultivate_detail.extra_race_list 
                             if race_id in available_races]) != 0
        
        if has_extra_race:
            log.info("🏆 Extra races available for current date - prioritizing races above all else")
            if ctx.cultivate_detail.turn_info.turn_operation is None:
                ctx.cultivate_detail.turn_info.turn_operation = TurnOperation()
            ctx.cultivate_detail.turn_info.turn_operation.turn_operation_type = TurnOperationType.TURN_OPERATION_TYPE_RACE
            matching_races = [race_id for race_id in ctx.cultivate_detail.extra_race_list if race_id in available_races]
            if matching_races:
                target_race_id = matching_races[0]
                ctx.cultivate_detail.turn_info.turn_operation.race_id = target_race_id
                log.info(f"🎯 Set specific race ID: {target_race_id} from user's selected races")
            else:
                log.warning("⚠️ No matching races found in available races for current date")
            ctx.cultivate_detail.turn_info.parse_train_info_finish = True
            ctx.cultivate_detail.turn_info.parse_main_menu_finish = True
            return
        
        if ctx.cultivate_detail.prioritize_recreation:
            img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            from module.umamusume.asset.template import UI_RECREATION_FRIEND_NOTIFICATION
            result = image_match(img_gray, UI_RECREATION_FRIEND_NOTIFICATION)
            log.info(f"🔍 Recreation friend notification detection: {result.find_match}")
            
            need_detection = False
            if result.find_match:
                last_detection_date = getattr(ctx.cultivate_detail, 'pal_last_detection_date', -1)
                if last_detection_date != current_date:
                    need_detection = True
                    log.info(f"Notification present - need detection (last: {last_detection_date}, now: {current_date})")
                else:
                    log.info(f"Stage {ctx.cultivate_detail.pal_event_stage} already detected for date {current_date}")
            else:
                if ctx.cultivate_detail.pal_event_stage > 0:
                    log.info("Notification absent - resetting stage to 0")
                    ctx.cultivate_detail.pal_event_stage = 0
                    if hasattr(ctx.cultivate_detail, 'pal_last_detection_date'):
                        delattr(ctx.cultivate_detail, 'pal_last_detection_date')
            
            if need_detection:
                log.info("🔍 Opening recreation menu to detect stage")
                ctx.ctrl.click_by_point(CULTIVATE_TRIP)
                time.sleep(0.5)
                img = ctx.ctrl.get_screen()
                
                pal_name = ctx.cultivate_detail.pal_name
                pal_thresholds = ctx.cultivate_detail.pal_thresholds
                
                if pal_name and pal_thresholds:
                    pal_data = pal_thresholds
                    num_stages = len(pal_data)
                    
                    coords_to_check = []
                    if num_stages == 3:
                        coords_to_check = [(554, 474), (605, 474)]
                    elif num_stages == 4:
                        coords_to_check = [(503, 474), (554, 474), (605, 474)]
                    elif num_stages == 5:
                        coords_to_check = [(452, 474), (503, 474), (554, 474), (605, 474)]
                    
                    matching_pixels = 0
                    for x, y in coords_to_check:
                        pixel_color = img[y, x]
                        b, g, r = pixel_color[0], pixel_color[1], pixel_color[2]
                        is_match = abs(b - 223) <= 5 and abs(g - 227) <= 5 and abs(r - 231) <= 5
                        if is_match:
                            matching_pixels += 1
                    
                    calculated_stage = len(coords_to_check) - matching_pixels + 1
                    ctx.cultivate_detail.pal_event_stage = calculated_stage
                    ctx.cultivate_detail.pal_last_detection_date = current_date
                    
                    log.info(f"STAGE DETECTED: {ctx.cultivate_detail.pal_event_stage} ({matching_pixels} filled / {len(coords_to_check)} total)")
                    
                    if ctx.cultivate_detail.pal_event_stage <= len(pal_data):
                        thresholds = pal_data[ctx.cultivate_detail.pal_event_stage - 1]
                        mood, energy, score = thresholds
                        log.info(f"Stage {ctx.cultivate_detail.pal_event_stage} thresholds - Mood: {mood}, Energy: {energy}, Score: {score}")
                else:
                    log.error("boi what the hell")

                ctx.ctrl.click(5, 5)
                time.sleep(0.3)
                ctx.cultivate_detail.turn_info.parse_main_menu_finish = False
                return
                
        ctx.cultivate_detail.turn_info.parse_main_menu_finish = True

    from module.umamusume.asset.race_data import get_races_for_period
    available_races = get_races_for_period(ctx.cultivate_detail.turn_info.date)
    has_extra_race = len([race_id for race_id in ctx.cultivate_detail.extra_race_list 
                         if race_id in available_races]) != 0

    turn_operation = ctx.cultivate_detail.turn_info.turn_operation

    if (not ctx.cultivate_detail.cultivate_finish and
        not ctx.cultivate_detail.turn_info.turn_learn_skill_done and
        ctx.cultivate_detail.learn_skill_done):
        ctx.cultivate_detail.reset_skill_learn()

    # Check if we should skip automatic skill learning
    # Only skip when manual purchase is enabled AND we're at cultivate finish
    skip_auto_skill_learning = (ctx.task.detail.manual_purchase_at_end and ctx.cultivate_detail.cultivate_finish)
    
    # Debug logging
    log.debug(f"🔍 Skill learning check - Skill points: {ctx.cultivate_detail.turn_info.uma_attribute.skill_point}, Threshold: {ctx.cultivate_detail.learn_skill_threshold}")
    log.debug(f"🔍 Manual purchase enabled: {ctx.task.detail.manual_purchase_at_end}, Cultivate finish: {ctx.cultivate_detail.cultivate_finish}")
    log.debug(f"🔍 Skip auto skill learning: {skip_auto_skill_learning}")
    
    if (ctx.cultivate_detail.turn_info.uma_attribute.skill_point > ctx.cultivate_detail.learn_skill_threshold
            and not ctx.cultivate_detail.turn_info.turn_learn_skill_done
            and not skip_auto_skill_learning):
        log.info(f"🎯 Auto-learning skills - Skill points: {ctx.cultivate_detail.turn_info.uma_attribute.skill_point}")
        # Always go to skill menu to scan for available skills - don't exit early
        ctx.ctrl.click_by_point(CULTIVATE_SKILL_LEARN)
        ctx.cultivate_detail.turn_info.parse_main_menu_finish = False
        return
    else:
        if not ctx.cultivate_detail.cultivate_finish:
            ctx.cultivate_detail.reset_skill_learn()


    if turn_operation is not None and turn_operation.turn_operation_type == TurnOperationType.TURN_OPERATION_TYPE_REST:
        if should_use_pal_outing_simple(ctx):
            ctx.ctrl.click_by_point(CULTIVATE_TRIP)
        else:
            ctx.ctrl.click_by_point(CULTIVATE_REST)
        return
    
    if turn_operation is not None and turn_operation.turn_operation_type == TurnOperationType.TURN_OPERATION_TYPE_TRIP:
        # AI has already validated PAL availability, execute directly
        log.info("Executing trip operation")
        if 36 < ctx.cultivate_detail.turn_info.date <= 40 or 60 < ctx.cultivate_detail.turn_info.date <= 64:
            ctx.ctrl.click(68, 991, "Summer Camp")
        else:
            ctx.ctrl.click_by_point(CULTIVATE_TRIP)
        return

    if not ctx.cultivate_detail.turn_info.parse_train_info_finish:
        limit = int(getattr(ctx.cultivate_detail, 'rest_treshold', getattr(ctx.cultivate_detail, 'fast_path_energy_limit', 48)))
        if has_extra_race:
            ctx.cultivate_detail.turn_info.parse_train_info_finish = True
            return
        if limit == 0:
            energy = 100
        else:
            from bot.conn.fetch import read_energy
            energy = read_energy()
            if energy == 0:
                time.sleep(0.37)
                energy = read_energy()
        if energy <= limit:
            if should_use_pal_outing_simple(ctx):
                ctx.ctrl.click_by_point(CULTIVATE_TRIP)
            else:
                ctx.ctrl.click_by_point(CULTIVATE_REST)
            return
        else:
            ctx.ctrl.click_by_point(TO_TRAINING_SELECT)
            return

    # Check other turn operations
    if turn_operation is not None:
        if turn_operation.turn_operation_type == TurnOperationType.TURN_OPERATION_TYPE_TRAINING:
            ctx.ctrl.click_by_point(TO_TRAINING_SELECT)
        elif turn_operation.turn_operation_type == TurnOperationType.TURN_OPERATION_TYPE_REST:
            if should_use_pal_outing_simple(ctx):
                ctx.ctrl.click_by_point(CULTIVATE_TRIP)
            else:
                ctx.ctrl.click_by_point(CULTIVATE_REST)
        elif turn_operation.turn_operation_type == TurnOperationType.TURN_OPERATION_TYPE_MEDIC:
            if 36 < ctx.cultivate_detail.turn_info.date <= 40 or 60 < ctx.cultivate_detail.turn_info.date <= 64:
                ctx.ctrl.click_by_point(CULTIVATE_MEDIC_SUMMER)
            else:
                ctx.ctrl.click_by_point(CULTIVATE_MEDIC)
            time.sleep(0.5)
            img = ctx.ctrl.get_screen()
            img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            is_summer = (36 < ctx.cultivate_detail.turn_info.date <= 40 or 60 < ctx.cultivate_detail.turn_info.date <= 64)
            check_point = img_rgb[1130, 200] if is_summer else img_rgb[1125, 105]
            if not (check_point[0] > 200 and check_point[1] > 200 and check_point[2] > 200):
                log.info("not sick resetting decision")
                ctx.ctrl.trigger_decision_reset = True
        elif turn_operation.turn_operation_type == TurnOperationType.TURN_OPERATION_TYPE_TRIP:
            if 36 < ctx.cultivate_detail.turn_info.date <= 40 or 60 < ctx.cultivate_detail.turn_info.date <= 64:
                ctx.ctrl.click(68, 991, "Summer Camp")
            else:
                ctx.ctrl.click_by_point(CULTIVATE_TRIP)
        elif turn_operation.turn_operation_type == TurnOperationType.TURN_OPERATION_TYPE_RACE:
            # Check if this is a URA race operation
            race_id = turn_operation.race_id
            
            # If no specific race_id is set but we have extra races available, prioritize them
            if race_id is None and has_extra_race:
                # Find the first available extra race for current date
                available_races = get_races_for_period(ctx.cultivate_detail.turn_info.date)
                for race_id in ctx.cultivate_detail.extra_race_list:
                    if race_id in available_races:
                        log.info(f"🏆 Prioritizing extra race {race_id} over other operations")
                        turn_operation.race_id = race_id
                        break
            
            if race_id in [2381, 2382, 2385, 2386, 2387]:
                # For URA races, check if the URA race UI is available first
                img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                from module.umamusume.asset.template import UI_CULTIVATE_URA_RACE_1, UI_CULTIVATE_URA_RACE_2, UI_CULTIVATE_URA_RACE_3
                
                # Determine which URA race template to check based on race ID
                ura_race_available = False
                ura_phase = ""
                
                if race_id == 2381:  # Qualifier
                    ura_race_available = image_match(img_gray, UI_CULTIVATE_URA_RACE_1).find_match
                    ura_phase = "Qualifier"
                elif race_id == 2382:  # Semi-final
                    ura_race_available = image_match(img_gray, UI_CULTIVATE_URA_RACE_2).find_match
                    ura_phase = "Semi-final"
                elif race_id in [2385, 2386, 2387]:  # Final
                    ura_race_available = image_match(img_gray, UI_CULTIVATE_URA_RACE_3).find_match
                    ura_phase = "Final"
                
                if ura_race_available:
                    log.info(f"🏆 URA {ura_phase} UI detected - proceeding to race")
                    if 36 < ctx.cultivate_detail.turn_info.date <= 40 or 60 < ctx.cultivate_detail.turn_info.date <= 64:
                        ctx.ctrl.click_by_point(CULTIVATE_RACE_SUMMER)
                    else:
                        ctx.ctrl.click_by_point(CULTIVATE_RACE)
                else:
                    log.info(f"⏳ URA {ura_phase} not yet available - continuing with normal flow")
                    ctx.cultivate_detail.turn_info.turn_operation = None
                    if not ctx.cultivate_detail.turn_info.parse_train_info_finish:
                        ctx.cultivate_detail.turn_info.parse_train_info_finish = True
                        return
                    else:
                        # Let the AI decide what to do (training, rest, etc.)
                        ctx.ctrl.click_by_point(TO_TRAINING_SELECT)
            else:
                # Regular race (including extra races) - proceed normally
                log.info(f"🏁 Proceeding with race operation (race_id: {race_id})")
                ti = ctx.cultivate_detail.turn_info
                op = ctx.cultivate_detail.turn_info.turn_operation
                if not hasattr(ti, 'race_search_started_at') or getattr(ti, 'race_search_id', None) != race_id:
                    ti.race_search_started_at = time.time()
                    ti.race_search_id = race_id
                elif time.time() - ti.race_search_started_at > 30:
                    try:
                        if getattr(ctx.task.detail, 'extra_race_list', None) is ctx.cultivate_detail.extra_race_list:
                            ctx.cultivate_detail.extra_race_list = list(ctx.cultivate_detail.extra_race_list)
                        if race_id and race_id in ctx.cultivate_detail.extra_race_list:
                            ctx.cultivate_detail.extra_race_list.remove(race_id)
                    except Exception as e:
                        log.debug(f"fail: {e}")
                    ctx.cultivate_detail.turn_info.turn_operation = None
                    if hasattr(ti, 'race_search_started_at'):
                        delattr(ti, 'race_search_started_at')
                    if hasattr(ti, 'race_search_id'):
                        delattr(ti, 'race_search_id')
                    return
                if 36 < ctx.cultivate_detail.turn_info.date <= 40 or 60 < ctx.cultivate_detail.turn_info.date <= 64:
                    ctx.ctrl.click_by_point(CULTIVATE_RACE_SUMMER)
                else:
                    ctx.ctrl.click_by_point(CULTIVATE_RACE)


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
            time.sleep(0.35)
            ctx.ctrl.click_by_point(TRAINING_POINT_LIST[training_type.value - 1])
            time.sleep(1.5)
            return

        else:
            ctx.ctrl.click_by_point(RETURN_TO_CULTIVATE_MAIN_MENU)
            return

    limit = int(getattr(ctx.cultivate_detail, 'rest_treshold', getattr(ctx.cultivate_detail, 'fast_path_energy_limit', 48)))
    if limit == 0:
        energy = 100
    else:
        from bot.conn.fetch import read_energy
        energy = read_energy()
        if energy == 0:
            time.sleep(0.37)
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
        class _TrainingDetectionResult:
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

        def _detect_training_once(ctx, img, train_type):
            result = _TrainingDetectionResult()
            try:
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
                import cv2 as _cv2
                roi = img[181:769, 666:690]
                roi_gray = _cv2.cvtColor(roi, _cv2.COLOR_BGR2GRAY)
                result.has_hint = image_match(roi_gray, REF_TRAINING_HINT).find_match
            except Exception:
                pass
            return result

        def _compare_detection_results(result1, result2):
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

        def _apply_detection_result(ctx, train_type, result):
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
            from module.umamusume.define import SupportCardType
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

        def _parse_training_with_retry(ctx, img, train_type):
            max_attempts = 5
            for attempt in range(max_attempts):
                result1 = _detect_training_once(ctx, img, train_type)
                time.sleep(0.1)
                result2 = _detect_training_once(ctx, img, train_type)
                if _compare_detection_results(result1, result2):
                    _apply_detection_result(ctx, train_type, result1)
                    return
                time.sleep(0.1)
            _apply_detection_result(ctx, train_type, result2)

        def _clear_training(ctx: UmamusumeContext, train_type: 'TrainingType'):
            til = ctx.cultivate_detail.turn_info.training_info_list[train_type.value - 1]
            til.speed_incr = 0
            til.stamina_incr = 0
            til.power_incr = 0
            til.will_incr = 0
            til.intelligence_incr = 0
            til.skill_point_incr = 0
            til.support_card_info_list = []

        threads: list[threading.Thread] = []
        blocked_trainings = [False] * 5

        date = ctx.cultivate_detail.turn_info.date
        if date == 0:
            extra_weight = [0, 0, 0, 0, 0]
        elif date <= 24:
            extra_weight = ctx.cultivate_detail.extra_weight[0]
        elif date <= 48:
            extra_weight = ctx.cultivate_detail.extra_weight[1]
        else:
            extra_weight = ctx.cultivate_detail.extra_weight[2]

        try:
            if (36 < date <= 40 or 60 < date <= 64) and isinstance(ctx.cultivate_detail.extra_weight, (list, tuple)) and len(ctx.cultivate_detail.extra_weight) >= 4:
                extra_weight = ctx.cultivate_detail.extra_weight[3]
        except Exception:
            pass

        img = ctx.current_screen
        train_type = parse_train_type(ctx, img)
        if train_type == TrainingType.TRAINING_TYPE_UNKNOWN:
            return
        viewed = train_type.value

        if extra_weight[viewed - 1] > -1:
            thread = threading.Thread(target=_parse_training_with_retry, args=(ctx, img, train_type))
            threads.append(thread)
            time.sleep(0.1)
            thread.start()
        else:
            _clear_training(ctx, train_type)

        for i in range(5):
            if i != (viewed - 1):
                if extra_weight[i] > -1:
                    retry = 0
                    max_retry = 3
                    ctx.ctrl.click_by_point(TRAINING_POINT_LIST[i])
                    img = ctx.ctrl.get_screen()
                    while parse_train_type(ctx, img) != TrainingType(i + 1) and retry < max_retry:
                        if retry > 2:
                            ctx.ctrl.click_by_point(TRAINING_POINT_LIST[i])
                        time.sleep(0.2)
                        img = ctx.ctrl.get_screen()
                        retry += 1
                    if retry == max_retry:
                        log.info(f"🚫 Training {TrainingType(i + 1).name} is restricted by game - skipping")
                        blocked_trainings[i] = True
                        _clear_training(ctx, TrainingType(i + 1))
                        continue

                    thread = threading.Thread(target=_parse_training_with_retry, args=(ctx, img, TrainingType(i + 1)))
                    threads.append(thread)
                    time.sleep(0.1)
                    thread.start()
                else:
                    _clear_training(ctx, TrainingType(i + 1))

        for thread in threads:
            thread.join()

        
        date = ctx.cultivate_detail.turn_info.date
        sv = getattr(ctx.cultivate_detail, 'score_value', [
            [0.11, 0.10, 0.01, 0.09],
            [0.11, 0.10, 0.09, 0.09],
            [0.11, 0.10, 0.12, 0.09],
            [0.03, 0.05, 0.15, 0.09],
            [0, 0, 0.15, 0, 0]
        ])
        # log.info(f"DEBUG: Loaded score_value configuration: {sv}")
        def resolve_weights(sv_list, idx):
            try:
                arr = sv_list[idx]
            except Exception:
                arr = [0.11, 0.10, 0.01, 0.09]
            if not isinstance(arr, (list, tuple)):
                arr = [0.11, 0.10, 0.01, 0.09]
            base = list(arr[:4])
            if len(base) < 4:
                base += [0.09] * (4 - len(base))
            special_defaults = [0.15, 0.12, 0.09, 0.07, 0]
            try:
                special = arr[4]
            except Exception:
                special = special_defaults[idx if 0 <= idx < len(special_defaults) else 0]
            return base + [special]
        if date <= 24:
            w_lv1, w_lv2, w_rainbow, w_hint, w_special = resolve_weights(sv, 0)
        elif 24 < date <= 48:
            w_lv1, w_lv2, w_rainbow, w_hint, w_special = resolve_weights(sv, 1)
        elif 48 < date <= 60:
            w_lv1, w_lv2, w_rainbow, w_hint, w_special = resolve_weights(sv, 2)
        elif 60 < date <= 72:
            w_lv1, w_lv2, w_rainbow, w_hint, w_special = resolve_weights(sv, 3)
        else:
            w_lv1, w_lv2, w_rainbow, w_hint, w_special = resolve_weights(sv, 4)
        try:
            se_config = getattr(ctx.cultivate_detail, 'spirit_explosion', [0.16, 0.16, 0.16, 0.06, 0.11])
            if isinstance(se_config, list) and len(se_config) > 0 and isinstance(se_config[0], list):
                if date <= 24:
                    se_weights = se_config[0]
                elif 24 < date <= 48:
                    se_weights = se_config[1]
                elif 48 < date <= 60:
                    se_weights = se_config[2]
                elif 60 < date <= 72:
                    se_weights = se_config[3]
                else:
                    se_weights = se_config[4]
            else:
                se_weights = se_config
        except Exception:
            se_weights = [0.16, 0.16, 0.16, 0.06, 0.11]

        from module.umamusume.define import SupportCardType, SupportCardFavorLevel
        from module.umamusume.asset.template import REF_TRAINING_HINT
        type_map = [
            SupportCardType.SUPPORT_CARD_TYPE_SPEED,
            SupportCardType.SUPPORT_CARD_TYPE_STAMINA,
            SupportCardType.SUPPORT_CARD_TYPE_POWER,
            SupportCardType.SUPPORT_CARD_TYPE_WILL,
            SupportCardType.SUPPORT_CARD_TYPE_INTELLIGENCE,
        ]
        names = ["Speed", "Stamina", "Power", "Guts", "Wit"]
        computed_scores = [0.0, 0.0, 0.0, 0.0, 0.0]
        rbc_counts = [0, 0, 0, 0, 0]
        special_counts = [0, 0, 0, 0, 0]
        spirit_counts = [0, 0, 0, 0, 0]

        log.info("Score:")
        log.info(f"lv1: {w_lv1}")
        log.info(f"lv2: {w_lv2}")
        log.info(f"Rainbows: {w_rainbow}")
        log.info(f"Hint: {w_hint}")
        try:
            if ctx.cultivate_detail.scenario.scenario_type() == ScenarioType.SCENARIO_TYPE_AOHARUHAI:
                log.info(f"Special Training score: {w_special}")
                log.info(f"Spirit Explosion scores: {se_weights}")
        except Exception:
            pass

        from bot.conn.fetch import read_energy
        try:
            current_energy = int(read_energy())
            if current_energy == 0:
                time.sleep(0.37)
                current_energy = int(read_energy())
        except Exception:
            current_energy = None
        try:
            rest_threshold = int(getattr(ctx.cultivate_detail, 'rest_treshold', getattr(ctx.cultivate_detail, 'fast_path_energy_limit', 48)))
        except Exception:
            rest_threshold = 48
        
        base_scores = getattr(ctx.cultivate_detail, 'base_score', [0.0, 0.0, 0.0, 0.0, 0.07])

        for idx in range(5):
            til = ctx.cultivate_detail.turn_info.training_info_list[idx]
            target_type = type_map[idx]
            lv1c = 0
            lv2c = 0
            rbc = 0
            npc = 0
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
                    score += 0.05
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
                is_rb = False
                if hasattr(sc, "is_rainbow"):
                    is_rb = bool(getattr(sc, "is_rainbow")) and (ctype == target_type)
                if not is_rb and (favor in (SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_3, SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_4) and ctype == target_type):
                    is_rb = True
                if is_rb:
                    rbc += 1
                    if idx == 4 and current_energy is not None and current_energy > 85:
                        log.info("energy >85, wit rainbow=0")
                    else:
                        score += w_rainbow
                    continue
                if favor == SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_1:
                    lv1c += 1
                    score += w_lv1
                elif favor == SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_2:
                    lv2c += 1
                    score += w_lv2
            
            log.info(f"{names[idx]}:")
            try:
                fr = int(getattr(til, 'failure_rate', -1))
            except Exception:
                fr = -1
            if fr >= 0:
                log.info(f"  failure: {fr}%")
            log.info(f"  lv1: {lv1c}")
            log.info(f"  lv2: {lv2c}")
            log.info(f"  Rainbows: {rbc}")
            
            if rbc >= 2:
                rainbow_multiplier = 1.0 + (rbc - 1) * 0.075
                base_score = score
                score *= rainbow_multiplier
                log.info(f"  Multiple rainbows bonus multiplier: x{rainbow_multiplier:.2f} ({rbc} cards) (Base: {base_score:.3f} -> {score:.3f})")
            
            if npc:
                log.info(f"  NPCs: {npc}")
            if pal_count:
                log.info(f"  Pal cards: {pal_count}")
            try:
                if ctx.cultivate_detail.scenario.scenario_type() == ScenarioType.SCENARIO_TYPE_AOHARUHAI:
                    if special_counts[idx] > 0:
                        log.info(f"  Special training available: {special_counts[idx]} cards")
                    if spirit_counts[idx] > 0:
                        try:
                            d = int(ctx.cultivate_detail.turn_info.date)
                        except Exception:
                            d = -1
                        if isinstance(d, int) and d >= 46:
                            pct = min(30, d - 45)
                            log.info(f"  Spirit explosion available: {spirit_counts[idx]} cards (-{pct}% score: date penalty)")
                        else:
                            log.info(f"  Spirit explosion available: {spirit_counts[idx]} cards")
            except Exception:
                pass
            hint_bonus = 0.0
            try:
                hint_bonus = w_hint if bool(getattr(til, 'has_hint', False)) else 0.0
            except Exception:
                hint_bonus = 0.0
            if hint_bonus > 0:
                log.info(f"  Hint bonus: +{hint_bonus:.3f}")
            score += hint_bonus
            stc_lane = special_counts[idx]
            if stc_lane > 0:
                log.info(f"  Special training bonus: +{w_special:.3f}")
                score += float(w_special)
            try:
                se_w = float(se_weights[idx]) if isinstance(se_weights, (list, tuple)) and len(se_weights) == 5 else 0.0
            except Exception:
                se_w = 0.0

            try:
                is_aoharu = (ctx.cultivate_detail.scenario.scenario_type() == ScenarioType.SCENARIO_TYPE_AOHARUHAI)
            except Exception:
                is_aoharu = False
            if is_aoharu and idx == 4 and se_w != 0.0 and spirit_counts[idx] > 0:
                try:
                    energy = int(read_energy())
                    if energy == 0:
                        time.sleep(0.37)
                        energy = int(read_energy())
                except Exception:
                    energy = None
                if energy is not None:
                    if energy > 80:
                        log.info("Energy near full ignoring wit spirit explosion")
                        se_w = 0.0
                    elif energy < 10:
                        log.info("Energy near 0 ignoring wit spirit explosion")
                        se_w = 0.0
                    else:
                        log.info("Energy not full prioritizing wit spirit explosion")
                        se_w = se_w * 2.0

            se_lane = spirit_counts[idx]
            if se_lane > 0 and se_w != 0.0:
                se_bonus = se_w
                log.info(f"  Spirit explosion bonus: +{se_bonus:.3f}")
                score += se_bonus

            if pal_count > 0:
                base_score = score
                clamped_multiplier = max(0.0, min(1.0, ctx.cultivate_detail.pal_card_multiplier))
                multiplier = 1.0 + clamped_multiplier
                score *= multiplier
                log.info(f"  Pal card multiplier: x{multiplier:.2f} (Base: {base_score:.3f} -> Final: {score:.3f})")
            try:
                if getattr(ctx.cultivate_detail, 'compensate_failure', True):
                    fr_val = int(getattr(til, 'failure_rate', -1))
                    if fr_val >= 0:
                        mult_fr = max(0.0, 1.0 - (float(fr_val) / 50.0))
                        if mult_fr != 1.0:
                            log.info(f"  Failure compensation: x{mult_fr:.2f}")
                        score *= mult_fr
            except Exception:
                pass

            if idx == 4 and current_energy is not None:
                log.info(f"energy={current_energy}, rest_threshold={rest_threshold}")
                if current_energy > 90:
                    if date > 72:
                        score *= 0.35
                        log.info("finale date & energy > 90, -65% to wit score")
                    else:
                        score *= 0.75
                        log.info("energy > 90, -25% to wit score")
                elif 85 > current_energy:
                    if rbc > 0:
                        log.info("85 > energy with rainbows +16% to wit score")
                        score *= 1.16
                    else:
                        log.info("85 > energy, +10% to wit score")
                        score *= 1.10
                elif current_energy > 85:
                    pass

            try:
                expect_attr = ctx.cultivate_detail.expect_attribute
                if isinstance(expect_attr, list) and len(expect_attr) == 5:
                    uma = ctx.cultivate_detail.turn_info.uma_attribute
                    curr_vals = [uma.speed, uma.stamina, uma.power, uma.will, uma.intelligence]
                    cap_val = float(expect_attr[idx])
                    curr_val = float(curr_vals[idx])
                    if cap_val > 0:
                        ratio = curr_val / cap_val
                        label = names[idx]
                        if ratio > 0.95:
                            log.info(f"{label} >95% of target: -100% to score")
                            score *= 0.0
                        elif ratio >= 0.90:
                            log.info(f"{label} >=90% of target: -30% to score")
                            score *= 0.7
                        elif ratio >= 0.80:
                            log.info(f"{label} >=80% of target: -20% to score")
                            score *= 0.8
                        elif ratio >= 0.70:
                            log.info(f"{label} >=70% of target: -10% to score")
                            score *= 0.9
            except Exception:
                pass
            try:
                ew = extra_weight[idx] if isinstance(extra_weight, (list, tuple)) and len(extra_weight) == 5 else 0.0
            except Exception:
                ew = 0.0
            if ew > -1.0:
                mult = 1.0 + float(ew)
                if mult < 0.0:
                    mult = 0.0
                elif mult > 2.0:
                    mult = 2.0
                weight_bonus = (mult - 1.0) * 100.0
                log.info(f"  Weight bonus: {weight_bonus:+.0f}%")
                score *= mult

            log.info(f"  Total score: {score:.3f}")
            computed_scores[idx] = score
            rbc_counts[idx] = rbc

        ctx.cultivate_detail.turn_info.parse_train_info_finish = True

        for idx in range(5):
            if extra_weight[idx] == -1:
                computed_scores[idx] = -float('inf')

        try:
            d = int(ctx.cultivate_detail.turn_info.date)
        except Exception:
            d = -1
        if isinstance(d, int) and d > 48 and d <= 72:
            try:
                uma = ctx.cultivate_detail.turn_info.uma_attribute
                stats = [uma.speed, uma.stamina, uma.power, uma.will, uma.intelligence]
                names = ["Speed", "Stamina", "Power", "Guts", "Wit"]
                max_idx = int(np.argmax(stats)) if len(stats) == 5 else None
                if max_idx is not None:
                    computed_scores[max_idx] *= 0.9
                    try:
                        log.info(f"-10% to {names[max_idx]}, the current highest stat")
                    except Exception:
                        pass
            except Exception:
                pass

        max_score = max(computed_scores) if len(computed_scores) == 5 else 0.0
        eps = 1e-9
        # relevant_counts = [getattr(ctx.cultivate_detail.turn_info.training_info_list[i], 'relevant_count', 0) for i in range(5)]
        
        blocked_count = sum(blocked_trainings)
        available_trainings = [i for i, blocked in enumerate(blocked_trainings) if not blocked]
        
        if blocked_count == 4 and len(available_trainings) == 1:
            chosen_idx = available_trainings[0]
        else:
            if not hasattr(ctx.cultivate_detail.turn_info, 'race_search_attempted'):
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
            
            if date >= 61 and sum(rbc_counts) == 0:
                chosen_idx = 4
            else:
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
            log.info("🏆 Race goal detected - prioritizing race over pal outing")
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


def script_main_menu(ctx: UmamusumeContext):
    if ctx.cultivate_detail.cultivate_finish:
        mode_name = getattr(ctx.task.task_execute_mode, "name", None)
        if mode_name == "TASK_EXECUTE_MODE_FULL_AUTO":
            log.info("career run completed in full auto mode - resetting for next run")
            ctx.cultivate_detail.cultivate_finish = False
            ctx.cultivate_detail.turn_info = None
            ctx.cultivate_detail.turn_info_history = []
            return
        else:
            ctx.task.end_task(TaskStatus.TASK_STATUS_SUCCESS, EndTaskReason.COMPLETE)
            return
    ctx.ctrl.click_by_point(TO_CULTIVATE_SCENARIO_CHOOSE)


def script_scenario_select(ctx: UmamusumeContext):
    target_scenario = ctx.cultivate_detail.scenario.scenario_type()
    time.sleep(2) # If network is very poor, this might not wait enough

    for i in range(1, len(ScenarioType)):
        img = ctx.ctrl.get_screen(to_gray=True)

        if image_match(img, UI_SCENARIO[target_scenario]).find_match:
            log.info(f"Found target cultivation scenario {ctx.cultivate_detail.scenario.scenario_name()}")
            ctx.ctrl.click_by_point(TO_CULTIVATE_PREPARE_NEXT)
            return

        log.debug(f"Scenario does not match, checking next scenario")
        ctx.ctrl.swipe(x1=400, y1=600, x2=500, y2=600, duration=300, name="swipe right")
        time.sleep(1)

    log.error(f"Could not find specified scenario")
    ctx.task.end_task(TaskStatus.TASK_STATUS_FAILED, EndTaskReason.SCENARIO_NOT_FOUND)


def script_umamusume_select(ctx: UmamusumeContext):
    ctx.ctrl.click_by_point(TO_CULTIVATE_PREPARE_NEXT)


def script_extend_umamusume_select(ctx: UmamusumeContext):
    try:
        if getattr(ctx.cultivate_detail, 'use_last_parents', False):
            ctx.ctrl.click_by_point(TO_CULTIVATE_PREPARE_NEXT)
            return
    except Exception:
        pass
    ctx.ctrl.click_by_point(TO_CULTIVATE_PREPARE_AUTO_SELECT)
    time.sleep(1)
    ctx.ctrl.click_by_point(TO_CULTIVATE_PREPARE_INCLUDE_GUEST)
    time.sleep(1)
    ctx.ctrl.click_by_point(TO_CULTIVATE_PREPARE_CONFIRM)
    time.sleep(1)
    ctx.ctrl.click_by_point(TO_CULTIVATE_PREPARE_NEXT)


def script_support_card_select(ctx: UmamusumeContext):
    img = ctx.ctrl.get_screen(to_gray=True)
    if image_match(img, REF_CULTIVATE_SUPPORT_CARD_EMPTY).find_match:
        import bot.conn.u2_ctrl as u2c
        ctx.ctrl.click_by_point(TO_FOLLOW_SUPPORT_CARD_SELECT)
        u2c.INPUT_BLOCKED = True
        time.sleep(1.6)
        u2c.INPUT_BLOCKED = False
        return
    ctx.ctrl.click_by_point(TO_CULTIVATE_PREPARE_NEXT)


def script_follow_support_card_select(ctx: UmamusumeContext):
    cycles = 18
    for _ in range(cycles):
        img = ctx.ctrl.get_screen()
        for __ in range(3):
            if find_support_card(ctx, img):
                return
            try:
                img_gray_chk = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                x1, y1, x2, y2 = 279, 48, 326, 76
                h, w = img_gray_chk.shape[:2]
                x1c = max(0, min(w, x1)); x2c = max(x1c, min(w, x2))
                y1c = max(0, min(h, y1)); y2c = max(y1c, min(h, y2))
                roi = img_gray_chk[y1c:y2c, x1c:x2c]
                if not image_match(roi, REF_BORROW_CARD).find_match:
                    log.info("Incorrect ui stopping card search")
                    return
            except Exception:
                pass
            ctx.ctrl.swipe_and_hold(x1=350, y1=1000, x2=350, y2=400, swipe_duration=211, hold_duration=211, name="scroll down list")
            img = ctx.ctrl.get_screen()
        for __ in range(3):
            if find_support_card(ctx, img):
                return
            try:
                img_gray_chk = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                x1, y1, x2, y2 = 279, 48, 326, 76
                h, w = img_gray_chk.shape[:2]
                x1c = max(0, min(w, x1)); x2c = max(x1c, min(w, x2))
                y1c = max(0, min(h, y1)); y2c = max(y1c, min(h, y2))
                roi = img_gray_chk[y1c:y2c, x1c:x2c]
                if not image_match(roi, REF_BORROW_CARD).find_match:
                    log.info("Incorrect ui stopping card search")
                    return
            except Exception:
                pass
            ctx.ctrl.swipe_and_hold(x1=350, y1=400, x2=350, y2=1000, swipe_duration=211, hold_duration=211, name="scroll up list")
            img = ctx.ctrl.get_screen()
        ctx.ctrl.click_by_point(FOLLOW_SUPPORT_CARD_SELECT_REFRESH)
        time.sleep(1.2)
    ctx.ctrl.click_by_point(FOLLOW_SUPPORT_CARD_SELECT_REFRESH)


def script_cultivate_final_check(ctx: UmamusumeContext):
    ctx.ctrl.click_by_point(CULTIVATE_FINAL_CHECK_START)


def script_cultivate_event(ctx: UmamusumeContext):
    log.info("Event handler called")
    
    img = ctx.ctrl.get_screen()
    if img is None or getattr(img, 'size', 0) == 0:
        for _ in range(3):
            time.sleep(0.2)
            img = ctx.ctrl.get_screen()
            if img is not None and getattr(img, 'size', 0) > 0:
                break
    if img is None or getattr(img, 'size', 0) == 0:
        log.warning("Failed to get screen")
        return
    h, w = img.shape[:2]
    y1, y2, x1, x2 = 237, 283, 111, 480
    y1 = max(0, min(h, y1)); y2 = max(y1, min(h, y2))
    x1 = max(0, min(w, x1)); x2 = max(x1, min(w, x2))
    event_name_img = img[y1:y2, x1:x2]
    
    event_name = ocr_line(event_name_img, lang="en")
    
    if not event_name or not event_name.strip():
        h, w = event_name_img.shape[:2]
        event_name_img_upscaled = cv2.resize(event_name_img, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)
        event_name = ocr_line(event_name_img_upscaled, lang="en")
    try:
        from bot.recog.ocr import find_similar_text
        event_blacklist = [
            "", " ",
            "Team Support",
        ]
        if not isinstance(event_name, str) or not event_name.strip():
            return
        if find_similar_text(event_name, event_blacklist, 0.9):
            log.info(f"{event_name} blacklisted. Skipping")
            return
    except Exception:
        pass
    force_choice_index = None
    try:
        if isinstance(event_name, str) and 'team at last' in event_name.lower():
            from module.umamusume.script.cultivate_task.event.scenario_event import aoharuhai_team_name_event
            res = aoharuhai_team_name_event(ctx)
            if isinstance(res, int) and res > 0:
                force_choice_index = int(res)
            else:
                return
    except Exception:
        pass
    
    try:
        _, selectors = parse_cultivate_event(ctx, img)
    except Exception:
        selectors = []

    if not isinstance(selectors, list):
        selectors = []
    if len(selectors) == 0 or len(selectors) > 5:
        try:
            time.sleep(0.25)
            img_retry = ctx.ctrl.get_screen()
            _, selectors2 = parse_cultivate_event(ctx, img_retry)
            if isinstance(selectors2, list) and len(selectors2) > 0:
                selectors = selectors2
                log.info(len(selectors))
        except Exception:
            pass
    
    try:
        if isinstance(event_name, str) and event_name.strip().lower() == "tutorial":
            if isinstance(selectors, list) and len(selectors) == 5:
                target_pt = selectors[4]
                ctx.ctrl.click(int(target_pt[0]), int(target_pt[1]), "tutorial choice 5 override")
                ctx.cultivate_detail.event_cooldown_until = time.time() + 2.5
                return
    except Exception:
        pass
    
    choice_index = force_choice_index if force_choice_index is not None else get_event_choice(ctx, event_name)
    if not isinstance(choice_index, int) or choice_index <= 0:
        return
    if choice_index > 5:
        choice_index = 2
    if isinstance(selectors, list) and len(selectors) > 0:
        idx = int(choice_index)
        if idx < 1:
            idx = 1
        if idx > len(selectors):
            idx = len(selectors)
        target_pt = selectors[idx - 1]
        try:
            log.info(len(selectors))
        except Exception:
            pass
        ctx.ctrl.click(int(target_pt[0]), int(target_pt[1]), f"Event option-{choice_index}")
        ctx.cultivate_detail.event_cooldown_until = time.time() + 2.5
        return
    try:
        tpl = Template(f"dialogue{choice_index}", UMAMUSUME_REF_TEMPLATE_PATH)
    except:
        tpl = None
    img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    x1, y1, x2, y2 = 24, 316, 696, 936
    h, w = img_gray.shape[:2]
    x1 = max(0, min(w, x1)); x2 = max(x1, min(w, x2)); y1 = max(0, min(h, y1)); y2 = max(y1, min(h, y2))
    roi_gray = img_gray[y1:y2, x1:x2]
    clicked = False
    if tpl is not None:
        try:
            for _ in range(2):
                res = image_match(roi_gray, tpl)
                if res.find_match:
                    ctx.ctrl.click(res.center_point[0] + x1, res.center_point[1] + y1, f"Event option-{choice_index}")
                    clicked = True
                    ctx.cultivate_detail.event_cooldown_until = time.time() + 5
                    return
                time.sleep(0.56)
                img = ctx.ctrl.get_screen()
                img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                h, w = img_gray.shape[:2]
                x1 = max(0, min(w, x1)); x2 = max(x1, min(w, x2)); y1 = max(0, min(h, y1)); y2 = max(y1, min(h, y2))
                roi_gray = img_gray[y1:y2, x1:x2]
        except:
            pass
    if not clicked:
        return

def script_aoharuhai_race(ctx: UmamusumeContext):
    img = ctx.ctrl.get_screen(to_gray=True)
    if image_match(img, UI_AOHARUHAI_RACE_1).find_match:
        race_index = 0
    elif image_match(img, UI_AOHARUHAI_RACE_2).find_match:
        race_index = 1
    elif image_match(img, UI_AOHARUHAI_RACE_3).find_match:
        race_index = 2
    elif image_match(img, UI_AOHARUHAI_RACE_4).find_match:
        race_index = 3
    elif image_match(img, UI_AOHARUHAI_RACE_5).find_match:
        race_index = 4
    else:
        ctx.ctrl.click(360, 1180, "Confirm race result")
        return
    
    ctx.cultivate_detail.turn_info.aoharu_race_index = race_index
    return

def script_aoharuhai_race_final_start(ctx: UmamusumeContext):
    ctx.ctrl.click(360, 980, "Confirm final opponent")

def script_aoharuhai_race_select_oponent(ctx: UmamusumeContext):
    return

def script_aoharuhai_race_confirm(ctx: UmamusumeContext):
    ctx.ctrl.click(520, 920, "Confirm battle")

def script_aoharuhai_race_inrace(ctx: UmamusumeContext):
    ctx.ctrl.click(520, 1180, "View battle result")

def script_aoharuhai_race_end(ctx: UmamusumeContext):
    ctx.ctrl.click(350, 1110, "Confirm race end")

def script_aoharuhai_race_schedule(ctx: UmamusumeContext):
    ctx.ctrl.click(360, 1100, "End Youth Cup race")

def script_cultivate_goal_race(ctx: UmamusumeContext):
    log.info("Entering goal race function")
    img = ctx.current_screen
    current_date = parse_date(img, ctx)
    
    if current_date == -1:
        if not hasattr(ctx.cultivate_detail, 'goal_race_parse_failures'):
            ctx.cultivate_detail.goal_race_parse_failures = 0
        
        ctx.cultivate_detail.goal_race_parse_failures += 1
        log.warning(f"Failed to parse date (attempt {ctx.cultivate_detail.goal_race_parse_failures})")
        
        if ctx.cultivate_detail.goal_race_parse_failures >= 3:
            ctx.ctrl.trigger_decision_reset = True
            ctx.cultivate_detail.goal_race_parse_failures = 0
        return
    
    ctx.cultivate_detail.goal_race_parse_failures = 0
    
    # 如果进入新的一回合，记录旧的回合信息并创建新的
    if ctx.cultivate_detail.turn_info is None or current_date != ctx.cultivate_detail.turn_info.date:
        if ctx.cultivate_detail.turn_info is not None:
            ctx.cultivate_detail.turn_info_history.append(ctx.cultivate_detail.turn_info)
        ctx.cultivate_detail.turn_info = TurnInfo()
        ctx.cultivate_detail.turn_info.date = current_date
    
    # Check if this is actually a URA race (championship)
    if ctx.cultivate_detail.turn_info.turn_operation:
        race_id = ctx.cultivate_detail.turn_info.turn_operation.race_id
        log.info(f"🏁 Current race ID: {race_id}")
        if race_id in [2381, 2382, 2385, 2386, 2387]:
            log.info("🏆 This is a URA championship race - proceeding directly to start")
            ctx.ctrl.click_by_point(CULTIVATE_GOAL_RACE_INTER_2)  # Start the race directly
        else:
            log.info(f"🎯 This is a regular race (ID: {race_id}) - entering detail interface")
            ctx.ctrl.click_by_point(CULTIVATE_GOAL_RACE_INTER_1)  # Enter detail interface first
    else:
        log.warning("No turn operation found - cannot determine race type")
        ctx.ctrl.click_by_point(CULTIVATE_GOAL_RACE_INTER_1)  # Default to detail interface


def script_cultivate_race_list(ctx: UmamusumeContext):
    log.info("➡️ Entered Race List menu (CULTIVATE_RACE_LIST)")
    time.sleep(1.0)
    if ctx.cultivate_detail.turn_info is None:
        log.warning("Turn information not initialized")
        ctx.ctrl.click_by_point(RETURN_TO_CULTIVATE_MAIN_MENU)
        return
    
    turn_op = ctx.cultivate_detail.turn_info.turn_operation
    if turn_op and turn_op.turn_operation_type == TurnOperationType.TURN_OPERATION_TYPE_RACE:
        race_id = turn_op.race_id
        
        if race_id == 0:
            log.info("Suitable race search mode")
            time.sleep(1)
            
            img_gray = ctx.ctrl.get_screen(to_gray=True)
            from module.umamusume.asset.template import REF_SUITABLE_RACE
            
            suitable_match = image_match(img_gray, REF_SUITABLE_RACE)
            
            if suitable_match.find_match:
                log.info("Found suitable race")
                center_x = suitable_match.center_point[0]
                center_y = suitable_match.center_point[1]
                ctx.ctrl.click(center_x, center_y, "Suitable race")
                time.sleep(1)
                ctx.ctrl.click_by_point(CULTIVATE_GOAL_RACE_INTER_1)
                return
            else:
                log.info("No suitable race, continuing with wit training")
                ctx.cultivate_detail.turn_info.race_search_attempted = True
                ctx.cultivate_detail.turn_info.turn_operation = None
                ctx.ctrl.click_by_point(RETURN_TO_CULTIVATE_MAIN_MENU)
                return
    
    img = cv2.cvtColor(ctx.current_screen, cv2.COLOR_BGR2GRAY)
    
    goal_match = image_match(img, REF_RACE_LIST_GOAL_RACE).find_match
    ura_match = image_match(img, REF_RACE_LIST_URA_RACE).find_match
    
    log.info(f"🔍 Template matching - Goal Race: {goal_match}, URA Race: {ura_match}")
    
    if goal_match:
        log.info("🎯 Found Goal Race - clicking to enter detail interface")
        ctx.ctrl.click_by_point(CULTIVATE_GOAL_RACE_INTER_1)
    elif ura_match:
        log.info("🏆 Found URA Race - clicking to enter detail interface")
        ctx.ctrl.click_by_point(CULTIVATE_GOAL_RACE_INTER_1)
    else:
        # Special handling for URA races - if we're in race list after URA race click, just click the race button
        if ctx.cultivate_detail.turn_info.turn_operation is None:
            log.warning("No turn operation - returning to main menu")
            ctx.ctrl.click_by_point(RETURN_TO_CULTIVATE_MAIN_MENU)
            return
        else:
            # Log the turn operation type to debug
            log.info(f"🔍 Turn operation type: {ctx.cultivate_detail.turn_info.turn_operation.turn_operation_type}")
            # For URA races, we might have a turn operation but still need to click the race button
            if ctx.cultivate_detail.turn_info.turn_operation.turn_operation_type == TurnOperationType.TURN_OPERATION_TYPE_RACE:
                race_id = ctx.cultivate_detail.turn_info.turn_operation.race_id
                log.info(f"🔍 Race operation with ID: {race_id}")
                # If it's a URA race ID or 0 (unknown), try clicking the race button
                if race_id in [2381, 2382, 2385, 2386, 2387] or race_id == 0:
                    log.info("🏆 Detected URA race operation - clicking race button directly")
                    ctx.ctrl.click(319, 1082, "URA Race Button")
                    time.sleep(1)
                    return
        if ctx.cultivate_detail.turn_info.turn_operation.turn_operation_type == TurnOperationType.TURN_OPERATION_TYPE_RACE:
            swiped = False
            while True:
                img = cv2.cvtColor(ctx.ctrl.get_screen(), cv2.COLOR_BGR2RGB)
                if not compare_color_equal(img[705, 701], [211, 209, 219]):
                    if swiped is True:
                        time.sleep(1.5)
                    break
                ctx.ctrl.swipe(x1=20, y1=850, x2=20, y2=1000, duration=200, name="")
                swiped = True
            img = ctx.ctrl.get_screen()
            ti = ctx.cultivate_detail.turn_info
            current_race_id = ctx.cultivate_detail.turn_info.turn_operation.race_id
            if not hasattr(ti, 'race_search_started_at') or getattr(ti, 'race_search_id', None) != current_race_id:
                ti.race_search_started_at = time.time()
                ti.race_search_id = current_race_id
            while True:
                if time.time() - ti.race_search_started_at > 30:
                    try:
                        if getattr(ctx.task.detail, 'extra_race_list', None) is ctx.cultivate_detail.extra_race_list:
                            ctx.cultivate_detail.extra_race_list = list(ctx.cultivate_detail.extra_race_list)
                        if current_race_id and current_race_id in ctx.cultivate_detail.extra_race_list:
                            ctx.cultivate_detail.extra_race_list.remove(current_race_id)
                    except Exception as e:
                        log.debug(f"Race removal error: {e}")
                    ctx.cultivate_detail.turn_info.turn_operation = None
                    if hasattr(ti, 'race_search_started_at'):
                        delattr(ti, 'race_search_started_at')
                    if hasattr(ti, 'race_search_id'):
                        delattr(ti, 'race_search_id')
                    ctx.ctrl.click_by_point(RETURN_TO_CULTIVATE_MAIN_MENU)
                    return
                race_id = ctx.cultivate_detail.turn_info.turn_operation.race_id
                log.info(f"🔍 Looking for race ID: {race_id}")
                selected = find_race(ctx, img, race_id)
                if selected:
                    log.info(f"✅ Found race ID: {race_id}")
                    if hasattr(ti, 'race_search_started_at'):
                        delattr(ti, 'race_search_started_at')
                    if hasattr(ti, 'race_search_id'):
                        delattr(ti, 'race_search_id')
                    time.sleep(1)
                    ctx.ctrl.click_by_point(CULTIVATE_GOAL_RACE_INTER_1)
                    time.sleep(1)
                    return
                img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                if not compare_color_equal(img[1006, 701], [211, 209, 219]):
                    try:
                        if getattr(ctx.task.detail, 'extra_race_list', None) is ctx.cultivate_detail.extra_race_list:
                            ctx.cultivate_detail.extra_race_list = list(ctx.cultivate_detail.extra_race_list)
                        if race_id and race_id in ctx.cultivate_detail.extra_race_list:
                            ctx.cultivate_detail.extra_race_list.remove(race_id)
                    except Exception as e:
                        log.debug(f"fail2: {e}")
                    ctx.cultivate_detail.turn_info.turn_operation = None
                    if hasattr(ti, 'race_search_started_at'):
                        delattr(ti, 'race_search_started_at')
                    if hasattr(ti, 'race_search_id'):
                        delattr(ti, 'race_search_id')
                    ctx.ctrl.click_by_point(RETURN_TO_CULTIVATE_MAIN_MENU)
                    return
                ctx.ctrl.swipe(x1=20, y1=1000, x2=20, y2=850, duration=1000, name="")
                time.sleep(1)
                img = ctx.ctrl.get_screen()
        else:
            ctx.ctrl.click_by_point(RETURN_TO_CULTIVATE_MAIN_MENU)


def script_cultivate_before_race(ctx: UmamusumeContext):
    img = cv2.cvtColor(ctx.current_screen, cv2.COLOR_BGR2RGB)
    p_check_skip = img[1175, 330]

    date = ctx.cultivate_detail.turn_info.date
    if date != -1:
        tactic_check_point_list = [img[668, 480], img[668, 542], img[668, 600], img[668, 670]]
        if date <= 72:
            p_check_tactic = tactic_check_point_list[ctx.cultivate_detail.tactic_list[int((date - 1) / 24)] - 1]
        else:
            p_check_tactic = tactic_check_point_list[ctx.cultivate_detail.tactic_list[2] - 1]
        if compare_color_equal(p_check_tactic, [170, 170, 170]):
            ctx.ctrl.click_by_point(BEFORE_RACE_CHANGE_TACTIC)
            return

    if p_check_skip[0] < 200 and p_check_skip[1] < 200 and p_check_skip[2] < 200:
        ctx.ctrl.click_by_point(BEFORE_RACE_START)
    else:
        ctx.ctrl.click_by_point(BEFORE_RACE_SKIP)


def script_cultivate_in_race_uma_list(ctx: UmamusumeContext):
    ctx.ctrl.click_by_point(IN_RACE_UMA_LIST_CONFIRM)


def script_in_race(ctx: UmamusumeContext):
    ctx.ctrl.click_by_point(IN_RACE_SKIP)


def script_cultivate_race_result(ctx: UmamusumeContext):
    ctx.ctrl.click_by_point(RACE_RESULT_CONFIRM)


def script_cultivate_race_reward(ctx: UmamusumeContext):
    ctx.ctrl.click_by_point(RACE_REWARD_CONFIRM)


def script_cultivate_goal_achieved(ctx: UmamusumeContext):
    ctx.ctrl.click_by_point(GOAL_ACHIEVE_CONFIRM)


def script_cultivate_goal_failed(ctx: UmamusumeContext):
    ctx.ctrl.click_by_point(GOAL_FAIL_CONFIRM)


def script_cultivate_next_goal(ctx: UmamusumeContext):
    ctx.ctrl.click_by_point(NEXT_GOAL_CONFIRM)


def script_cultivate_extend(ctx: UmamusumeContext):
    ctx.ctrl.click_by_point(CULTIVATE_EXTEND_CONFIRM)


def script_cultivate_result(ctx: UmamusumeContext):
    log.info("🏆 Cultivation Result detected - clicking confirm button")
    ctx.ctrl.click_by_point(CULTIVATE_RESULT_CONFIRM)

# 限时: 富士奇石的表演秀
# 1.878s 2s 0.649s (the first one is actually correct lol i didnt test the rest)
def script_cultivate_catch_doll(ctx: UmamusumeContext):
    ctx.ctrl.click_by_point(CULTIVATE_CATCH_DOLL_START, hold_duration=1888) 


def script_cultivate_catch_doll_result(ctx: UmamusumeContext):
    ctx.ctrl.click_by_point(CULTIVATE_CATCH_DOLL_RESULT_CONFIRM)


def script_cultivate_finish(ctx: UmamusumeContext):
    if not ctx.task.detail.manual_purchase_at_end:
        if not ctx.cultivate_detail.cultivate_finish:
            ctx.cultivate_detail.cultivate_finish = True
            ctx.cultivate_detail.final_skill_sweep_active = True
            ctx.cultivate_detail.learn_skill_done = False
            ctx.cultivate_detail.learn_skill_selected = False
            ctx.ctrl.click_by_point(CULTIVATE_FINISH_LEARN_SKILL)
            return
        if getattr(ctx.cultivate_detail, "final_skill_sweep_active", False):
            if ctx.cultivate_detail.learn_skill_selected:
                ctx.cultivate_detail.learn_skill_done = False
                ctx.cultivate_detail.learn_skill_selected = False
                ctx.ctrl.click_by_point(CULTIVATE_FINISH_LEARN_SKILL)
                return
            else:
                ctx.cultivate_detail.final_skill_sweep_active = False
                ctx.ctrl.click_by_point(CULTIVATE_FINISH_CONFIRM)
                return
    if not ctx.task.detail.manual_purchase_at_end:
        if not ctx.cultivate_detail.learn_skill_done or not ctx.cultivate_detail.cultivate_finish:
            ctx.cultivate_detail.cultivate_finish = True
            ctx.ctrl.click_by_point(CULTIVATE_FINISH_LEARN_SKILL)
        else:
            ctx.ctrl.click_by_point(CULTIVATE_FINISH_CONFIRM)
    else:
        # Manual purchase mode - show notification and wait for user
        if not ctx.cultivate_detail.manual_purchase_completed:
            # Check if user has clicked "Learn Skills" button (indicating they want to purchase manually)
            if not hasattr(ctx.cultivate_detail, 'manual_purchase_initiated'):
                log.info("🔧 Manual purchase mode enabled - showing web notification to user")
                try:
                    # Send web notification to UAT interface
                    import requests
                    import json
                    
                    # Send notification to web interface
                    notification_data = {
                        "type": "manual_skill_purchase",
                        "message": "Please learn skills manually, then press confirm when done",
                        "timestamp": time.time()
                    }
                    
                    try:
                        # Send to local UAT web server
                        response = requests.post(
                            "http://localhost:8071/api/manual-skill-notification",
                            json=notification_data,
                            timeout=1
                        )
                        log.info("✅ Web notification sent successfully")
                        
                        # Wait for user confirmation via web interface
                        while True:
                            try:
                                status_response = requests.get(
                                    "http://localhost:8071/api/manual-skill-notification-status",
                                    timeout=1
                                )
                                status_data = status_response.json()
                                
                                if status_data.get("confirmed"):
                                    log.info("✅ User confirmed manual skill purchase via web interface")
                                    # Mark manual purchase as completed
                                    ctx.cultivate_detail.manual_purchase_completed = True
                                    # Reset the notification state
                                    requests.post("http://localhost:8071/api/manual-skill-notification-cancel")
                                    break
                                elif status_data.get("cancelled"):
                                    log.info("❌ User cancelled manual skill purchase")
                                    # Reset the notification state
                                    requests.post("http://localhost:8071/api/manual-skill-notification-cancel")
                                    return
                                
                                time.sleep(0.5)  # Check every 500ms
                            except requests.exceptions.RequestException:
                                # If web interface is not available, fall back to console
                                break
                        
                    except requests.exceptions.RequestException as e:
                        log.warning(f"⚠️ Web notification failed: {e}")
                        # Fallback to console notification
                        print("\n" + "🔔" * 50)
                        print("🔔 MANUAL SKILL PURCHASE REQUIRED 🔔")
                        print("🔔" * 50)
                        print("Please learn skills manually, then press confirm when done.")
                        print("Press Enter in the console when you're ready to continue...")
                        print("🔔" * 50)
                        input()  # Wait for user input
                    
                    log.info("✅ User acknowledged manual purchase notification")
                except Exception as e:
                    log.error(f"❌ Failed to show notification: {e}")
                    # Fallback to simple console message
                    print("\n" + "="*50)
                    print("🔧 MANUAL SKILL PURCHASE REQUIRED")
                    print("="*50)
                    print("Please learn skills manually, then press confirm when done.")
                    print("Press Enter in the console when you're ready to continue...")
                    print("="*50)
                    input()  # Wait for user input
                
                ctx.cultivate_detail.manual_purchase_initiated = True
                # Don't click anything - let user handle manually
                return
            else:
                # User has been notified, wait for them to complete manual purchase
                # The completion will be detected in script_cultivate_learn_skill when they return
                return
        else:
            # User has completed manual skill purchase, proceed with confirmation
            log.info("✅ User completed manual skill purchase - proceeding with cultivation finish")
            ctx.cultivate_detail.learn_skill_done = True
            ctx.cultivate_detail.cultivate_finish = True
            ctx.ctrl.click_by_point(CULTIVATE_FINISH_CONFIRM)


def script_cultivate_learn_skill(ctx: UmamusumeContext):
    # Safety mechanism: If manual purchase is enabled AND we're at cultivate finish, 
    # and the user has confirmed manual purchase, immediately return to finish UI
    if (ctx.task.detail.manual_purchase_at_end and 
        ctx.cultivate_detail.cultivate_finish and 
        hasattr(ctx.cultivate_detail, 'manual_purchase_completed') and 
        ctx.cultivate_detail.manual_purchase_completed):
        log.info("🔧 Manual purchase completed - returning to cultivate finish UI")
        ctx.cultivate_detail.learn_skill_done = True
        ctx.ctrl.click_by_point(RETURN_TO_CULTIVATE_FINISH)
        return
        
    # If manual purchase is enabled AND we're at cultivate finish, handle manual purchase completion
    if ctx.task.detail.manual_purchase_at_end and ctx.cultivate_detail.cultivate_finish:
        log.info("🔧 Manual purchase mode enabled - returning to cultivate finish UI")
        # Mark manual purchase as completed since user has returned from skill menu
        ctx.cultivate_detail.manual_purchase_completed = True
        ctx.cultivate_detail.learn_skill_done = True
        ctx.ctrl.click_by_point(RETURN_TO_CULTIVATE_FINISH)
        return
        
    if ctx.cultivate_detail.learn_skill_done:
        # If skills are already learned and confirmed, exit skill learning
        log.info("✅ Skills already learned and confirmed - exiting skill learning")
        log.debug(f"🔍 learn_skill_done flag was set to True - checking where this happened")
        ctx.ctrl.click_by_point(RETURN_TO_CULTIVATE_FINISH)
        return
    learn_skill_list: list[list[str]]
    learn_skill_blacklist: list[str] = ctx.cultivate_detail.learn_skill_blacklist
    if ctx.cultivate_detail.learn_skill_only_user_provided:
        if len(ctx.cultivate_detail.learn_skill_list) == 0:
            ctx.ctrl.click_by_point(RETURN_TO_CULTIVATE_FINISH)
            ctx.cultivate_detail.learn_skill_done = True
            ctx.cultivate_detail.turn_info.turn_learn_skill_done = True
            return
        else:
            learn_skill_list = ctx.cultivate_detail.learn_skill_list
    else:
        if len(ctx.cultivate_detail.learn_skill_list) == 0:
            learn_skill_list = SKILL_LEARN_PRIORITY_LIST
        else:
            learn_skill_list = ctx.cultivate_detail.learn_skill_list

    try:
        log.info("Priority list:")
        if isinstance(learn_skill_list, list):
            for idx, plist in enumerate(learn_skill_list):
                try:
                    log.info(f"  priority {idx}: {', '.join(plist) if plist else ''}")
                except Exception:
                    pass
        bl = ctx.cultivate_detail.learn_skill_blacklist or []
        log.info(f"Blacklist: {', '.join(bl) if bl else ''}")
    except Exception:
        pass

    # Traverse entire page, find all clickable skills
    skill_list = []
    while ctx.task.running():
        # Safety check: If manual purchase was confirmed, immediately return
        if (ctx.task.detail.manual_purchase_at_end and 
            ctx.cultivate_detail.cultivate_finish and 
            hasattr(ctx.cultivate_detail, 'manual_purchase_completed') and 
            ctx.cultivate_detail.manual_purchase_completed):
            log.info("🔧 Manual purchase confirmed during skill scanning - returning to finish UI")
            ctx.cultivate_detail.learn_skill_done = True
            ctx.ctrl.click_by_point(RETURN_TO_CULTIVATE_FINISH)
            return
            
        img = ctx.ctrl.get_screen()
        current_screen_skill_list = get_skill_list(img, learn_skill_list,learn_skill_blacklist)
        for i in current_screen_skill_list:
            if i not in skill_list:
                skill_list.append(i)
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        if not compare_color_equal(img[1006, 701], [211, 209, 219]):
            break
        ctx.ctrl.swipe_and_hold(x1=23, y1=1000, x2=23, y2=563, swipe_duration=211, hold_duration=211, name="")
        
        # Additional safety check after each swipe
        if (ctx.task.detail.manual_purchase_at_end and 
            ctx.cultivate_detail.cultivate_finish and 
            hasattr(ctx.cultivate_detail, 'manual_purchase_completed') and 
            ctx.cultivate_detail.manual_purchase_completed):
            log.info("🔧 Manual purchase confirmed after swipe - returning to finish UI")
            ctx.cultivate_detail.learn_skill_done = True
            ctx.ctrl.click_by_point(RETURN_TO_CULTIVATE_FINISH)
            return

    try:
        purchased = []
        for s in skill_list:
            try:
                if s.get('available') is False:
                    n = s.get('skill_name_raw') or s.get('skill_name') or ''
                    if n:
                        purchased.append(n)
            except Exception:
                continue
        log.info(f"Purchased skills: {', '.join(purchased) if purchased else ''}")
    except Exception:
        pass

    log.debug("Current skill state: " + str(skill_list))

    # Bind gold skills with their subsequent skills
    for i in range(len(skill_list)):
        if i != (len(skill_list) - 1) and skill_list[i]["gold"] is True:
            skill_list[i]["subsequent_skill"] = skill_list[i + 1]["skill_name"]

    # Sort by priority
    skill_list = sorted(skill_list, key=lambda x: x["priority"])
    # TODO: Temporarily no way to handle a skill that can be clicked multiple times
    import re
    digits_pattern = re.compile(r"\D")
    img = ctx.ctrl.get_screen()
    total_skill_point_text = digits_pattern.sub("", ocr_line(img[400: 440, 490: 665]))
    if total_skill_point_text == "":
        total_skill_point = 0
    else:
        total_skill_point = int(total_skill_point_text)
    
    log.debug(f"🔍 Total skill points available: {total_skill_point}")
    log.debug(f"🔍 Skills detected: {len(skill_list)}")
    log.debug(f"🔍 Priority breakdown: {[skill['priority'] for skill in skill_list]}")
    
    target_skill_list = []
    target_skill_list_raw = []
    curr_point = 0
    
    # Fix: Properly iterate through priority levels and add skills
    for priority_level in range(len(learn_skill_list) + 1):
        log.debug(f"🔍 Processing priority level {priority_level}")
        
        # Skip user-provided only check for non-cultivate-finish scenarios
        # But ONLY if there are no skills at this priority level in the user's preset
        if (priority_level > 0 and ctx.cultivate_detail.learn_skill_only_user_provided is True and
                not ctx.cultivate_detail.cultivate_finish):
            # Check if there are any skills at this priority level in the user's preset
            # learn_skill_list is a list of lists where index = priority level
            if priority_level < len(learn_skill_list) and len(learn_skill_list[priority_level]) > 0:
                log.debug(f"🔍 Priority {priority_level} has {len(learn_skill_list[priority_level])} skills in preset - processing")
            else:
                log.debug(f"🔍 Skipping priority {priority_level} - no skills in preset at this priority")
                continue
            
        # Find all skills at this priority level
        priority_skills = sorted(
            [skill for skill in skill_list if skill["priority"] == priority_level and skill["available"] is True],
            key=lambda s: -int(s.get("hint_level", 0))
        )
        log.debug(f"🔍 Found {len(priority_skills)} skills at priority {priority_level}")
        
        for skill in priority_skills:
            skill_cost = skill["skill_cost"]
            skill_name = skill["skill_name"]
            skill_name_raw = skill["skill_name_raw"]
            
            log.debug(f"🔍 Considering skill '{skill_name}' (cost: {skill_cost}, priority: {priority_level})")
            
            # Check if we can afford this skill
            if curr_point + skill_cost <= total_skill_point:
                curr_point += skill_cost
                target_skill_list.append(skill_name)
                target_skill_list_raw.append(skill_name_raw)
                log.info(f"✅ Added skill '{skill_name}' to target list (cost: {skill_cost}, total spent: {curr_point})")
                
                # If clicking a gold skill, set its bound lower skill as unclickable
                if skill["gold"] is True and skill["subsequent_skill"] != '':
                    for k in range(len(skill_list)):
                        if skill_list[k]["skill_name"] == skill["subsequent_skill"]:
                            skill_list[k]["available"] = False
                            log.debug(f"🔒 Disabled subsequent skill '{skill['subsequent_skill']}' due to gold skill")
            else:
                log.debug(f"❌ Cannot afford skill '{skill_name}' (cost: {skill_cost}, available: {total_skill_point - curr_point})")
                # Stop adding skills at this priority level if we can't afford them
                break
        
        # If we couldn't afford any skills at this priority level, stop
        if len([skill for skill in skill_list if skill["priority"] == priority_level and skill["available"] is True]) > 0:
            if not any(skill["skill_name"] in target_skill_list for skill in skill_list if skill["priority"] == priority_level):
                log.debug(f"🔍 Stopping at priority {priority_level} - no affordable skills")
                break
    
    log.info(f"🎯 Final target skill list: {target_skill_list}")
    log.info(f"🎯 Total skills to learn: {len(target_skill_list)}")
    log.info(f"🎯 Total points to spend: {curr_point}")

    # If it's URA, mark learned skills, may be used to reset inspiration event weights
    # Since skill points were calculated above, can ensure all skills in list will be learned
    if ctx.task.detail.scenario == ScenarioType.SCENARIO_TYPE_URA:
        for skill in target_skill_list:
            ctx.task.detail.scenario_config.ura_config.removeSkillFromList(skill)

    # Move up to align
    ctx.ctrl.swipe_and_hold(x1=23, y1=950, x2=23, y2=972, swipe_duration=211, hold_duration=211, name="")

    # Remove already learned skills
    for skill in target_skill_list_raw:
        for prioritylist in ctx.cultivate_detail.learn_skill_list:
            if prioritylist.__contains__(skill):
                prioritylist.remove(skill)
    for skill in skill_list:
        for prioritylist in ctx.cultivate_detail.learn_skill_list:
            if skill['available'] is False and prioritylist.__contains__(skill['skill_name_raw']):
                prioritylist.remove(skill['skill_name_raw'])
    # If a priority is completely empty, delete it directly
    ctx.cultivate_detail.learn_skill_list = [x for x in ctx.cultivate_detail.learn_skill_list if x != []]

    # Safety check before starting skill clicking
    if (ctx.task.detail.manual_purchase_at_end and 
        ctx.cultivate_detail.cultivate_finish and 
        hasattr(ctx.cultivate_detail, 'manual_purchase_completed') and 
        ctx.cultivate_detail.manual_purchase_completed):
        log.info("🔧 Manual purchase confirmed before skill clicking - returning to finish UI")
        ctx.cultivate_detail.learn_skill_done = True
        ctx.ctrl.click_by_point(RETURN_TO_CULTIVATE_FINISH)
        return

    # Click skills
    if len(target_skill_list) == 0:
        ctx.cultivate_detail.learn_skill_done = True
        ctx.cultivate_detail.turn_info.turn_learn_skill_done = True
        ctx.ctrl.click_by_point(RETURN_TO_CULTIVATE_FINISH)
        return
    log.info(f"🎯 Starting skill execution for {len(target_skill_list)} skills: {target_skill_list}")
    
    # Create a copy of the target list to avoid modifying the original
    skills_to_process = target_skill_list.copy()
    
    purchases_made = False
    while True:
        # Safety check: If manual purchase was confirmed, immediately return
        if (ctx.task.detail.manual_purchase_at_end and 
            ctx.cultivate_detail.cultivate_finish and 
            hasattr(ctx.cultivate_detail, 'manual_purchase_completed') and 
            ctx.cultivate_detail.manual_purchase_completed):
            log.info("🔧 Manual purchase confirmed during skill clicking - returning to finish UI")
            ctx.cultivate_detail.learn_skill_done = True
            ctx.ctrl.click_by_point(RETURN_TO_CULTIVATE_FINISH)
            return
            
        img = ctx.ctrl.get_screen()
        log.debug(f"🔍 Attempting to find and click skills. Target list: {skills_to_process}")
        skills_found = find_skill(ctx, img, skills_to_process, learn_any_skill=False)
        log.debug(f"🔍 find_skill result: {skills_found}")
        if skills_found:
            ctx.cultivate_detail.learn_skill_selected = True
            purchases_made = True
        
        if len(skills_to_process) == 0:
            log.info("🎯 All target skills have been processed")
            break
            
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        if not compare_color_equal(img[488, 701], [211, 209, 219]):
            log.debug("🔍 Reached end of skill list page")
            break
        ctx.ctrl.swipe_and_hold(x1=23, y1=563, x2=23, y2=1000, swipe_duration=211, hold_duration=211, name="")

    log.debug("Skills to learn: " + str(ctx.cultivate_detail.learn_skill_list))
    log.debug("Skills learned: " + str([skill['skill_name'] for skill in skill_list if not skill['available']]))

    # Safety check before final confirm button click
    if (ctx.task.detail.manual_purchase_at_end and 
        ctx.cultivate_detail.cultivate_finish and 
        hasattr(ctx.cultivate_detail, 'manual_purchase_completed') and 
        ctx.cultivate_detail.manual_purchase_completed):
        log.info("🔧 Manual purchase confirmed before final confirm - returning to finish UI")
        ctx.cultivate_detail.learn_skill_done = True
        ctx.ctrl.click_by_point(RETURN_TO_CULTIVATE_FINISH)
        return

    # Only mark as done if we actually processed skills or if there were no skills to process
    if len(target_skill_list) > 0 or len(skill_list) == 0:
        log.info(f"✅ Skill learning completed - processed {len(target_skill_list)} skills out of {len(skill_list)} available")
        ctx.cultivate_detail.learn_skill_done = True
        ctx.cultivate_detail.turn_info.turn_learn_skill_done = True
        if len(target_skill_list) > 0:
            ctx.cultivate_detail.learn_skill_selected = True
    else:
        # For user-provided only mode, if no skills were processed, it means all desired skills are already learned
        if ctx.cultivate_detail.learn_skill_only_user_provided:
            log.info(f"✅ User-provided only mode: No skills to learn - all desired skills already learned")
            ctx.cultivate_detail.learn_skill_done = True
            ctx.cultivate_detail.turn_info.turn_learn_skill_done = True
        else:
            # Check if all skills are already learned (priority -1 means already learned)
            all_skills_already_learned = all(skill["priority"] == -1 for skill in skill_list)
            if all_skills_already_learned:
                log.info(f"✅ All desired skills are already learned - marking skill learning as complete")
                ctx.cultivate_detail.learn_skill_done = True
                ctx.cultivate_detail.turn_info.turn_learn_skill_done = True
            else:
                log.warning(f"⚠️ No skills were processed - learn_skill_done flag not set")
    
    # After learning skills, click the confirm button first, then back button
    log.info("✅ Skills learned - clicking confirm button first")
    ctx.ctrl.click_by_point(CULTIVATE_LEARN_SKILL_CONFIRM)


def script_not_found_ui(ctx: UmamusumeContext):
    """Enhanced NOT_FOUND_UI handler with goal screen fallback detection"""
    
    # Debug: Log current screen info
    if ctx.current_screen is not None:
        log.debug(f"🔍 NOT_FOUND_UI - Screen shape: {ctx.current_screen.shape}")
        

        try:
            import cv2
            from bot.recog.image_matcher import image_match
            from module.umamusume.asset.template import UI_CULTIVATE_RACE_LIST_2
            img_gray_full = cv2.cvtColor(ctx.current_screen, cv2.COLOR_BGR2GRAY)
            x1, y1, x2, y2 = 238, 525, 300, 588
            h, w = img_gray_full.shape[:2]
            x1c = max(0, min(w, x1)); x2c = max(0, min(w, x2))
            y1c = max(0, min(h, y1)); y2c = max(0, min(h, y2))
            roi = img_gray_full[y1c:y2c, x1c:x2c]
            res = image_match(roi, UI_CULTIVATE_RACE_LIST_2)
            if res.find_match:
                script_cultivate_race_list(ctx)
                return
        except Exception as e:
            log.debug(f"Race List ROI check failed: {e}")
                
        # Try direct template matching for cultivate_result_1.png first
        try:
            import cv2
            from bot.recog.image_matcher import image_match
            from module.umamusume.asset.template import UI_CULTIVATE_RESULT_1
            
            img = ctx.current_screen
            img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            result = image_match(img_gray, UI_CULTIVATE_RESULT_1)
            
            if result.find_match:
                log.info("🏆 Cultivate Result 1 template matched! Clicking confirm button")
                ctx.ctrl.click_by_point(CULTIVATE_RESULT_CONFIRM)
                return
            else:
                log.debug("🔍 Cultivate Result 1 template not found")
                
        except Exception as e:
            log.debug(f"Template matching failed: {str(e)}")
        
        # Try to detect if this might be a cultivation result screen via OCR
        try:
            from bot.recog.ocr import ocr_line
            
            img = ctx.current_screen
            # Sample areas where cultivation result text might appear
            title_area = img[200:400, 100:620]
            title_text = ocr_line(title_area).lower()
            
            # Debug: Log what text was detected
            log.debug(f"🔍 OCR detected text: '{title_text[:100]}...'")
            
            # Check for cultivation result keywords - specifically "REWARDS" screen
            result_keywords = ['rewards', 'result', 'cultivation', '完成', '结果', '培育', '奖励']
            if any(keyword in title_text for keyword in result_keywords):
                log.info(f"🏆 Potential cultivation result detected: '{title_text[:50]}...'")
                log.info("🏆 Attempting to click cultivation result confirm button")
                ctx.ctrl.click_by_point(CULTIVATE_RESULT_CONFIRM)
                return
                
            # Also check for "Bond Level" and "Total Fans" which are specific to this rewards screen
            bond_area = img[400:600, 100:620]
            bond_text = ocr_line(bond_area).lower()
            log.debug(f"🔍 Bond area OCR: '{bond_text[:100]}...'")
            if 'bond level' in bond_text or 'total fans' in bond_text:
                log.info(f"🏆 Rewards screen detected via bond/fans text: '{bond_text[:50]}...'")
                log.info("🏆 Attempting to click cultivation result confirm button")
                ctx.ctrl.click_by_point(CULTIVATE_RESULT_CONFIRM)
                return
                
        except Exception as e:
            log.debug(f"Cultivation result detection failed: {str(e)}")
    
    # Try to detect goal screens through OCR/text detection as fallback
    try:
        import cv2
        from bot.recog.ocr import ocr_line
        
        img = ctx.current_screen
        if img is not None:
            # Convert to grayscale for OCR
            img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            
            # Sample common areas where goal text might appear
            # Top center area (typical for goal titles)
            title_area = img_gray[200:400, 100:620]  # Adjust based on screen resolution
            title_text = ocr_line(title_area).lower()
            
            # Middle area (for goal descriptions/buttons)
            middle_area = img_gray[800:1000, 200:560]
            middle_text = ocr_line(middle_area).lower()
            
            # Check for goal-related keywords (both English and Chinese)
            goal_keywords = ['goal', 'complete', 'achieved', 'failed', 'next', 'finish', 'target', 
                           'objective', '目标', '达成', '完成', '失败', '下一个']
            
            combined_text = f"{title_text} {middle_text}"
            
            # Detect goal screens
            if any(keyword in combined_text for keyword in goal_keywords):
                log.info(f"🎯 Fallback goal screen detected: '{combined_text[:50]}...'")
                
                # Determine goal type and click appropriate position
                if any(word in combined_text for word in ['complete', 'achieved', '达成', '完成']):
                    log.info(f"✅ Goal Achieved detected - clicking confirmation")
                    ctx.ctrl.click_by_point(GOAL_ACHIEVE_CONFIRM)
                    return
                elif any(word in combined_text for word in ['failed', '失败']):
                    log.info(f"❌ Goal Failed detected - clicking confirmation")
                    ctx.ctrl.click_by_point(GOAL_FAIL_CONFIRM)
                    return
                elif any(word in combined_text for word in ['next', '下一个']):
                    log.info(f"➡️ Next Goal detected - clicking confirmation")
                    ctx.ctrl.click_by_point(NEXT_GOAL_CONFIRM)
                    return
                else:
                    # Generic goal screen - try standard position
                    log.info(f"🎯 Generic goal screen - using standard position")
                    ctx.ctrl.click(370, 1110, "Generic goal confirmation")
                    return
            
    except Exception as e:
        log.debug(f"Goal detection fallback failed: {str(e)}")
    try:
        from module.umamusume.asset.template import REF_NEXT
        img = cv2.cvtColor(ctx.current_screen, cv2.COLOR_BGR2GRAY)
        next_match = image_match(img, REF_NEXT)
        if next_match.find_match:
            center_x = next_match.center_point[0]
            center_y = next_match.center_point[1]
            ctx.ctrl.click(center_x, center_y, "Next button")
            return
    except Exception:
        pass
    log.debug("🔍 No specific UI detected - using default fallback click")
    ctx.ctrl.click(719, 1, "Default fallback click")


def script_receive_cup(ctx: UmamusumeContext):
    ctx.ctrl.click_by_point(CULTIVATE_RECEIVE_CUP_CLOSE)


def script_cultivate_level_result(ctx: UmamusumeContext):
    ctx.ctrl.click_by_point(CULTIVATE_LEVEL_RESULT_CONFIRM)


def script_factor_receive(ctx: UmamusumeContext):
    if ctx.cultivate_detail.parse_factor_done:
        ctx.ctrl.click_by_point(CULTIVATE_FACTOR_RECEIVE_CONFIRM)
    else:
        time.sleep(2)
        parse_factor(ctx)


def script_historical_rating_update(ctx: UmamusumeContext):
    ctx.ctrl.click_by_point(HISTORICAL_RATING_UPDATE_CONFIRM)


def script_scenario_rating_update(ctx: UmamusumeContext):
    ctx.ctrl.click_by_point(SCENARIO_RATING_UPDATE_CONFIRM)
