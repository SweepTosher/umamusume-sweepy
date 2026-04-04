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
    CULTIVATE_MEDIC, CULTIVATE_MEDIC_SUMMER,
    CULTIVATE_MEDIC_MANT, CULTIVATE_MEDIC_MANT_SUMMER,
    CULTIVATE_TRIP_MANT, CULTIVATE_RACE_MANT, CULTIVATE_RACE_MANT_SUMMER
)
from module.umamusume.define import ScenarioType
from module.umamusume.constants.game_constants import (
    is_summer_camp_period, is_ura_race, NEW_RUN_DETECTION_DATE,
    URA_QUALIFIER_ID, URA_SEMIFINAL_ID, URA_FINAL_IDS, PRE_DEBUT_END
)
from module.umamusume.constants.timing_constants import (
    MEDIC_CHECK_DELAY, RACE_SEARCH_TIMEOUT
)
from module.umamusume.script.cultivate_task.parse import parse_date, parse_cultivate_main_menu
from module.umamusume.script.cultivate_task.helpers import should_use_pal_outing_simple, detect_pal_stage, should_use_team_sirius_recreation, execute_team_sirius_recreation, execute_regular_recreation
from bot.recog.energy_scanner import scan_energy

log = logger.get_logger(__name__)


def is_mant(ctx):
    try:
        return ctx.cultivate_detail.scenario.scenario_type() == ScenarioType.SCENARIO_TYPE_MANT
    except Exception:
        return False


def get_trip(ctx):
    return CULTIVATE_TRIP_MANT if is_mant(ctx) else CULTIVATE_TRIP


def get_race(ctx, summer=False):
    if is_mant(ctx):
        return CULTIVATE_RACE_MANT_SUMMER if summer else CULTIVATE_RACE_MANT
    return CULTIVATE_RACE_SUMMER if summer else CULTIVATE_RACE


def get_medic(ctx, summer=False):
    if is_mant(ctx):
        return CULTIVATE_MEDIC_MANT_SUMMER if summer else CULTIVATE_MEDIC_MANT
    return CULTIVATE_MEDIC_SUMMER if summer else CULTIVATE_MEDIC


def script_cultivate_main_menu(ctx: UmamusumeContext):
    img = ctx.current_screen
    current_date = parse_date(img, ctx)
    import bot.conn.u2_ctrl as u2c
    u2c.IN_CAREER_RUN = True
    if current_date == -1:
        current_date = -(len(ctx.cultivate_detail.turn_info_history) + 1)

    if ctx.cultivate_detail.turn_info is None or current_date != ctx.cultivate_detail.turn_info.date:
        if ctx.cultivate_detail.turn_info is not None:
            ctx.cultivate_detail.turn_info_history.append(ctx.cultivate_detail.turn_info)
            if len(ctx.cultivate_detail.turn_info_history) > 100:
                ctx.cultivate_detail.turn_info_history = ctx.cultivate_detail.turn_info_history[-100:]
        ctx.cultivate_detail.turn_info = TurnInfo()
        ctx.cultivate_detail.turn_info.date = current_date
        ctx.cultivate_detail.mant_shop_scanned_this_turn = False
        if current_date > 0:
            ctx.cultivate_detail.team_sirius_available_dates = []
            ctx.cultivate_detail.pal_event_stage = 0
            if hasattr(ctx.cultivate_detail, 'pal_last_detection_date'):
                delattr(ctx.cultivate_detail, 'pal_last_detection_date')

        if is_mant(ctx):
            from module.umamusume.scenario.mant.main_menu import handle_mant_turn_start
            handle_mant_turn_start(ctx, current_date)

        if current_date == NEW_RUN_DETECTION_DATE:
            log.info("new run detected resetting manual purchase state")
            ctx.cultivate_detail.manual_purchase_completed = False
            if hasattr(ctx.cultivate_detail, 'manual_purchase_initiated'):
                delattr(ctx.cultivate_detail, 'manual_purchase_initiated')

    from bot.conn.fetch import read_mood
    ctx.cultivate_detail.turn_info.cached_mood = read_mood(img)

    if not ctx.cultivate_detail.turn_info.parse_main_menu_finish:
        parse_cultivate_main_menu(ctx, img)
        
        from module.umamusume.asset.race_data import get_races_for_period
        available_races = get_races_for_period(ctx.cultivate_detail.turn_info.date)
        ctx.cultivate_detail.turn_info.cached_available_races = available_races
        ctx.cultivate_detail.turn_info.parse_main_menu_finish = True

    has_extra_race = len([race_id for race_id in ctx.cultivate_detail.extra_race_list 
                         if race_id in ctx.cultivate_detail.turn_info.cached_available_races]) != 0

    if not has_extra_race:
        ts_enabled = getattr(ctx.cultivate_detail, 'team_sirius_enabled', False)
        if ts_enabled:
            if not ctx.cultivate_detail.team_sirius_available_dates:
                img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                from module.umamusume.asset.template import UI_RECREATION_FRIEND_NOTIFICATION
                ts_result = image_match(img_gray, UI_RECREATION_FRIEND_NOTIFICATION)
                if ts_result.find_match:
                    from module.umamusume.script.cultivate_task.helpers import detect_team_sirius_dates
                    dates = detect_team_sirius_dates(ctx)
                    ctx.cultivate_detail.team_sirius_available_dates = dates
                    log.info(f"Team Sirius: Available dates: {dates}")
                time.sleep(0.5)
                img = ctx.ctrl.get_screen()
                ctx.current_screen = img

        if not ts_enabled and ctx.cultivate_detail.prioritize_recreation:
            if ctx.cultivate_detail.pal_event_stage <= 0:
                img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                from module.umamusume.asset.template import UI_RECREATION_FRIEND_NOTIFICATION
                result = image_match(img_gray, UI_RECREATION_FRIEND_NOTIFICATION)
                log.info(f"Recreation notification: {result.find_match}")
                
                if result.find_match:
                    log.info("opening recreation menu to detect stage")
                    ctx.ctrl.click_by_point(get_trip(ctx))
                    time.sleep(0.15)
                    img = ctx.ctrl.get_screen()
                    
                    calculated_stage = detect_pal_stage(ctx, img)
                    ctx.cultivate_detail.pal_event_stage = calculated_stage
                    
                    pal_thresholds = ctx.cultivate_detail.pal_thresholds
                    if pal_thresholds and calculated_stage <= len(pal_thresholds):
                        thresholds = pal_thresholds[calculated_stage - 1]
                        mood, energy, score = thresholds
                        log.info(f"Stage {calculated_stage}: mood={mood} energy={energy} score={score}")

                    ctx.ctrl.click(5, 5)
                    time.sleep(0.15)
                    ctx.cultivate_detail.turn_info.parse_main_menu_finish = False
                    return
                else:
                    if ctx.cultivate_detail.pal_event_stage > 0:
                        log.info("pal notification gone, resetting stage")
                        ctx.cultivate_detail.pal_event_stage = 0

    if has_extra_race and not is_mant(ctx):
        log.info("extra race this turn, prioritizing")
        if ctx.cultivate_detail.turn_info.turn_operation is None:
            ctx.cultivate_detail.turn_info.turn_operation = TurnOperation()
        ctx.cultivate_detail.turn_info.turn_operation.turn_operation_type = TurnOperationType.TURN_OPERATION_TYPE_RACE
        matching_races = [race_id for race_id in ctx.cultivate_detail.extra_race_list if race_id in ctx.cultivate_detail.turn_info.cached_available_races]
        if matching_races:
            target_race_id = matching_races[0]
            ctx.cultivate_detail.turn_info.turn_operation.race_id = target_race_id
            log.info(f"Set race: {target_race_id}")
        else:
            log.info("extra race not in available races")
        ctx.cultivate_detail.turn_info.parse_train_info_finish = True
        return
    if has_extra_race and is_mant(ctx):
        log.info("MANT: extra race available but scanning training first")

    if is_mant(ctx):
        from module.umamusume.scenario.mant.main_menu import handle_mant_main_menu
        if handle_mant_main_menu(ctx, img, current_date):
            return

    available_races = getattr(ctx.cultivate_detail.turn_info, 'cached_available_races', None)
    if available_races is None:
        from module.umamusume.asset.race_data import get_races_for_period
        available_races = get_races_for_period(ctx.cultivate_detail.turn_info.date)
        ctx.cultivate_detail.turn_info.cached_available_races = available_races
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
        if should_use_team_sirius_recreation(ctx):
            execute_team_sirius_recreation(ctx, trip_click_point=get_trip(ctx))
            return
        if getattr(ctx.cultivate_detail, 'team_sirius_enabled', False):
            execute_regular_recreation(ctx, trip_click_point=get_trip(ctx))
            return
        if should_use_pal_outing_simple(ctx):
            ctx.ctrl.click_by_point(get_trip(ctx))
            return
        ctx.cultivate_detail.turn_info.turn_operation = None
        ctx.cultivate_detail.turn_info.parse_main_menu_finish = False
        ctx.cultivate_detail.turn_info.parse_train_info_finish = False
        return
    
    if turn_operation is not None and turn_operation.turn_operation_type == TurnOperationType.TURN_OPERATION_TYPE_TRIP:
        log.info("Executing trip operation")
        if is_summer_camp_period(ctx.cultivate_detail.turn_info.date):
            ctx.ctrl.click(68, 991, "Summer Camp")
        else:
            ctx.ctrl.click_by_point(get_trip(ctx))
        return

    if is_mant(ctx):
        from module.umamusume.scenario.mant.main_menu import handle_mant_rival_race
        handle_mant_rival_race(ctx, img)

    if not ctx.cultivate_detail.turn_info.parse_train_info_finish:
        limit = int(getattr(ctx.cultivate_detail, 'rest_threshold', getattr(ctx.cultivate_detail, 'rest_treshold', getattr(ctx.cultivate_detail, 'fast_path_energy_limit', 48))))
        if has_extra_race and not is_mant(ctx):
            ctx.cultivate_detail.turn_info.parse_train_info_finish = True
            return
        if limit == 0:
            energy = 100
        else:
            from bot.conn.fetch import read_energy
            energy = read_energy()
            if energy == 0:
                time.sleep(0.15)
                energy = read_energy()
        if is_mant(ctx) and energy <= limit:
            ctx.cultivate_detail.turn_info.cached_energy = energy
            if has_extra_race:
                from module.umamusume.scenario.mant.inventory import has_energy_recovery
                if has_energy_recovery(ctx):
                    ctx.cultivate_detail.turn_info.energy_recovery_deferred = True
            else:
                from module.umamusume.scenario.mant.inventory import handle_energy_recovery
                if handle_energy_recovery(ctx):
                    energy = read_energy()
        if energy <= limit:
            if getattr(ctx.cultivate_detail.turn_info, 'energy_recovery_deferred', False):
                base_energy, _, _ = scan_energy(ctx.ctrl)
                ctx.cultivate_detail.turn_info.base_energy = base_energy
                ctx.ctrl.click_by_point(TO_TRAINING_SELECT)
                return
            if should_use_pal_outing_simple(ctx):
                ctx.ctrl.click_by_point(get_trip(ctx))
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
            if getattr(ctx.cultivate_detail.turn_info, 'base_energy', None) is None:
                base_energy, _, _ = scan_energy(ctx.ctrl)
                ctx.cultivate_detail.turn_info.base_energy = base_energy
            ctx.ctrl.click_by_point(TO_TRAINING_SELECT)
        elif turn_operation.turn_operation_type == TurnOperationType.TURN_OPERATION_TYPE_REST:
            if should_use_team_sirius_recreation(ctx):
                execute_team_sirius_recreation(ctx, trip_click_point=get_trip(ctx))
                return
            if getattr(ctx.cultivate_detail, 'team_sirius_enabled', False):
                execute_regular_recreation(ctx, trip_click_point=get_trip(ctx))
                return
            if should_use_pal_outing_simple(ctx):
                ctx.ctrl.click_by_point(get_trip(ctx))
                return
            ctx.cultivate_detail.turn_info.turn_operation = None
            ctx.cultivate_detail.turn_info.parse_main_menu_finish = False
            ctx.cultivate_detail.turn_info.parse_train_info_finish = False
        elif turn_operation.turn_operation_type == TurnOperationType.TURN_OPERATION_TYPE_MEDIC:
            is_summer = is_summer_camp_period(ctx.cultivate_detail.turn_info.date)
            ctx.ctrl.click_by_point(get_medic(ctx, summer=is_summer))
            time.sleep(MEDIC_CHECK_DELAY)
            img = ctx.ctrl.get_screen()
            img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            if is_mant(ctx):
                if is_summer:
                    check_point = img_rgb[1118, 100]
                else:
                    check_point = img_rgb[1125, 40]
            elif is_summer:
                check_point = img_rgb[1130, 200]
            else:
                check_point = img_rgb[1125, 105]
            if not (check_point[0] > 200 and check_point[1] > 200 and check_point[2] > 200):
                log.info("not sick resetting decision")
                ctx.ctrl.trigger_decision_reset = True
        elif turn_operation.turn_operation_type == TurnOperationType.TURN_OPERATION_TYPE_TRIP:
            if is_summer_camp_period(ctx.cultivate_detail.turn_info.date):
                ctx.ctrl.click(68, 991, "Summer Camp")
            else:
                ctx.ctrl.click_by_point(get_trip(ctx))
        elif turn_operation.turn_operation_type == TurnOperationType.TURN_OPERATION_TYPE_RACE:
            race_id = turn_operation.race_id
            
            if race_id == 0 and current_date <= PRE_DEBUT_END:
                log.info("Pre-Debut period with race fallback - redirecting to training instead")
                ctx.cultivate_detail.turn_info.turn_operation = None
                base_energy, _, _ = scan_energy(ctx.ctrl)
                ctx.cultivate_detail.turn_info.base_energy = base_energy
                ctx.ctrl.click_by_point(TO_TRAINING_SELECT)
                return
            
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
                    if is_mant(ctx):
                        from module.umamusume.scenario.mant.inventory import handle_energy_drink_max_before_race, handle_glow_sticks_before_race
                        handle_energy_drink_max_before_race(ctx)
                        handle_glow_sticks_before_race(ctx)
                    is_summer = is_summer_camp_period(ctx.cultivate_detail.turn_info.date)
                    ctx.ctrl.click_by_point(get_race(ctx, summer=is_summer))
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
                if is_mant(ctx):
                    from module.umamusume.scenario.mant.inventory import handle_energy_drink_max_before_race, handle_glow_sticks_before_race
                    handle_energy_drink_max_before_race(ctx)
                    handle_glow_sticks_before_race(ctx)
                is_summer = is_summer_camp_period(ctx.cultivate_detail.turn_info.date)
                ctx.ctrl.click_by_point(get_race(ctx, summer=is_summer))
