import time
import cv2

import bot.base.log as logger
from bot.recog.image_matcher import image_match
from module.umamusume.context import UmamusumeContext
from module.umamusume.types import TurnInfo, TurnOperation
from module.umamusume.define import TurnOperationType
from module.umamusume.asset.point import (
    CULTIVATE_TRIP, CULTIVATE_REST, CULTIVATE_SKILL_LEARN,
    TO_TRAINING_SELECT, CULTIVATE_RACE, CULTIVATE_RACE_SUMMER,
    CULTIVATE_MEDIC, CULTIVATE_MEDIC_SUMMER
)
from module.umamusume.constants.game_constants import (
    is_summer_camp_period, is_ura_race, NEW_RUN_DETECTION_DATE,
    URA_QUALIFIER_ID, URA_SEMIFINAL_ID, URA_FINAL_IDS
)
from module.umamusume.constants.timing_constants import (
    MEDIC_CHECK_DELAY, RACE_SEARCH_TIMEOUT
)
from module.umamusume.script.cultivate_task.parse import parse_date, parse_cultivate_main_menu
from module.umamusume.script.cultivate_task.helpers import should_use_pal_outing_simple, detect_pal_stage
from bot.recog.energy_scanner import scan_energy

log = logger.get_logger(__name__)


def script_cultivate_main_menu(ctx: UmamusumeContext):
    img = ctx.current_screen
    current_date = parse_date(img, ctx)
    if current_date == -1:
        log.warning("Failed to parse date")
        return
    
    if ctx.cultivate_detail.turn_info is None or current_date != ctx.cultivate_detail.turn_info.date:
        if ctx.cultivate_detail.turn_info is not None:
            ctx.cultivate_detail.turn_info_history.append(ctx.cultivate_detail.turn_info)
        ctx.cultivate_detail.turn_info = TurnInfo()
        ctx.cultivate_detail.turn_info.date = current_date
        
        if current_date == NEW_RUN_DETECTION_DATE:
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
            log.info("Extra races available for current date - prioritizing races above all else")
            if ctx.cultivate_detail.turn_info.turn_operation is None:
                ctx.cultivate_detail.turn_info.turn_operation = TurnOperation()
            ctx.cultivate_detail.turn_info.turn_operation.turn_operation_type = TurnOperationType.TURN_OPERATION_TYPE_RACE
            matching_races = [race_id for race_id in ctx.cultivate_detail.extra_race_list if race_id in available_races]
            if matching_races:
                target_race_id = matching_races[0]
                ctx.cultivate_detail.turn_info.turn_operation.race_id = target_race_id
                log.info(f"Set specific race ID: {target_race_id} from user's selected races")
            else:
                log.warning("No matching races found in available races for current date")
            ctx.cultivate_detail.turn_info.parse_train_info_finish = True
            ctx.cultivate_detail.turn_info.parse_main_menu_finish = True
            return
        
        if ctx.cultivate_detail.prioritize_recreation:
            img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            from module.umamusume.asset.template import UI_RECREATION_FRIEND_NOTIFICATION
            result = image_match(img_gray, UI_RECREATION_FRIEND_NOTIFICATION)
            log.info(f"Recreation friend notification detection: {result.find_match}")
            
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
                log.info("Opening recreation menu to detect stage")
                ctx.ctrl.click_by_point(CULTIVATE_TRIP)
                time.sleep(0.5)
                img = ctx.ctrl.get_screen()
                
                calculated_stage = detect_pal_stage(ctx, img)
                ctx.cultivate_detail.pal_event_stage = calculated_stage
                ctx.cultivate_detail.pal_last_detection_date = current_date
                
                pal_thresholds = ctx.cultivate_detail.pal_thresholds
                if pal_thresholds and calculated_stage <= len(pal_thresholds):
                    log.info(f"STAGE DETECTED: {calculated_stage}")
                    thresholds = pal_thresholds[calculated_stage - 1]
                    mood, energy, score = thresholds
                    log.info(f"Stage {calculated_stage} thresholds - Mood: {mood}, Energy: {energy}, Score: {score}")

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

    skip_auto_skill_learning = (ctx.task.detail.manual_purchase_at_end and ctx.cultivate_detail.cultivate_finish)
    
    log.debug(f"Skill learning check - Skill points: {ctx.cultivate_detail.turn_info.uma_attribute.skill_point}, Threshold: {ctx.cultivate_detail.learn_skill_threshold}")
    log.debug(f"Manual purchase enabled: {ctx.task.detail.manual_purchase_at_end}, Cultivate finish: {ctx.cultivate_detail.cultivate_finish}")
    log.debug(f"Skip auto skill learning: {skip_auto_skill_learning}")
    
    if (ctx.cultivate_detail.turn_info.uma_attribute.skill_point > ctx.cultivate_detail.learn_skill_threshold
            and not ctx.cultivate_detail.turn_info.turn_learn_skill_done
            and not skip_auto_skill_learning):
        log.info(f"Auto-learning skills - Skill points: {ctx.cultivate_detail.turn_info.uma_attribute.skill_point}")
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
        log.info("Executing trip operation")
        if is_summer_camp_period(ctx.cultivate_detail.turn_info.date):
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
            base_energy, _, _ = scan_energy(ctx.ctrl)
            ctx.cultivate_detail.turn_info.base_energy = base_energy
            ctx.ctrl.click_by_point(TO_TRAINING_SELECT)
            return

    if turn_operation is not None:
        if turn_operation.turn_operation_type == TurnOperationType.TURN_OPERATION_TYPE_TRAINING:
            base_energy, _, _ = scan_energy(ctx.ctrl)
            ctx.cultivate_detail.turn_info.base_energy = base_energy
            ctx.ctrl.click_by_point(TO_TRAINING_SELECT)
        elif turn_operation.turn_operation_type == TurnOperationType.TURN_OPERATION_TYPE_REST:
            if should_use_pal_outing_simple(ctx):
                ctx.ctrl.click_by_point(CULTIVATE_TRIP)
            else:
                ctx.ctrl.click_by_point(CULTIVATE_REST)
        elif turn_operation.turn_operation_type == TurnOperationType.TURN_OPERATION_TYPE_MEDIC:
            if is_summer_camp_period(ctx.cultivate_detail.turn_info.date):
                ctx.ctrl.click_by_point(CULTIVATE_MEDIC_SUMMER)
            else:
                ctx.ctrl.click_by_point(CULTIVATE_MEDIC)
            time.sleep(MEDIC_CHECK_DELAY)
            img = ctx.ctrl.get_screen()
            img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            is_summer = is_summer_camp_period(ctx.cultivate_detail.turn_info.date)
            check_point = img_rgb[1130, 200] if is_summer else img_rgb[1125, 105]
            if not (check_point[0] > 200 and check_point[1] > 200 and check_point[2] > 200):
                log.info("not sick resetting decision")
                ctx.ctrl.trigger_decision_reset = True
        elif turn_operation.turn_operation_type == TurnOperationType.TURN_OPERATION_TYPE_TRIP:
            if is_summer_camp_period(ctx.cultivate_detail.turn_info.date):
                ctx.ctrl.click(68, 991, "Summer Camp")
            else:
                ctx.ctrl.click_by_point(CULTIVATE_TRIP)
        elif turn_operation.turn_operation_type == TurnOperationType.TURN_OPERATION_TYPE_RACE:
            race_id = turn_operation.race_id
            
            if race_id is None and has_extra_race:
                available_races = get_races_for_period(ctx.cultivate_detail.turn_info.date)
                for race_id in ctx.cultivate_detail.extra_race_list:
                    if race_id in available_races:
                        log.info(f"Prioritizing extra race {race_id} over other operations")
                        turn_operation.race_id = race_id
                        break
            
            if is_ura_race(race_id):
                img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                from module.umamusume.asset.template import UI_CULTIVATE_URA_RACE_1, UI_CULTIVATE_URA_RACE_2, UI_CULTIVATE_URA_RACE_3
                
                ura_race_available = False
                ura_phase = ""
                
                if race_id == URA_QUALIFIER_ID:
                    ura_race_available = image_match(img_gray, UI_CULTIVATE_URA_RACE_1).find_match
                    ura_phase = "Qualifier"
                elif race_id == URA_SEMIFINAL_ID:
                    ura_race_available = image_match(img_gray, UI_CULTIVATE_URA_RACE_2).find_match
                    ura_phase = "Semi-final"
                elif race_id in URA_FINAL_IDS:
                    ura_race_available = image_match(img_gray, UI_CULTIVATE_URA_RACE_3).find_match
                    ura_phase = "Final"
                
                if ura_race_available:
                    log.info(f"URA {ura_phase} UI detected - proceeding to race")
                    if is_summer_camp_period(ctx.cultivate_detail.turn_info.date):
                        ctx.ctrl.click_by_point(CULTIVATE_RACE_SUMMER)
                    else:
                        ctx.ctrl.click_by_point(CULTIVATE_RACE)
                else:
                    log.info(f"URA {ura_phase} not yet available - continuing with normal flow")
                    ctx.cultivate_detail.turn_info.turn_operation = None
                    if not ctx.cultivate_detail.turn_info.parse_train_info_finish:
                        ctx.cultivate_detail.turn_info.parse_train_info_finish = True
                        return
                    else:
                        ctx.ctrl.click_by_point(TO_TRAINING_SELECT)
            else:
                log.info(f"Proceeding with race operation (race_id: {race_id})")
                ti = ctx.cultivate_detail.turn_info
                op = ctx.cultivate_detail.turn_info.turn_operation
                if not hasattr(ti, 'race_search_started_at') or getattr(ti, 'race_search_id', None) != race_id:
                    ti.race_search_started_at = time.time()
                    ti.race_search_id = race_id
                elif time.time() - ti.race_search_started_at > RACE_SEARCH_TIMEOUT:
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
                if is_summer_camp_period(ctx.cultivate_detail.turn_info.date):
                    ctx.ctrl.click_by_point(CULTIVATE_RACE_SUMMER)
                else:
                    ctx.ctrl.click_by_point(CULTIVATE_RACE)
