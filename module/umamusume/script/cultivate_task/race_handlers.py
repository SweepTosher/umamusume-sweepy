import time
import cv2

import bot.base.log as logger
from bot.recog.image_matcher import image_match, compare_color_equal
from module.umamusume.context import UmamusumeContext
from module.umamusume.types import TurnInfo
from module.umamusume.define import TurnOperationType
from module.umamusume.asset.point import (
    CULTIVATE_GOAL_RACE_INTER_1, CULTIVATE_GOAL_RACE_INTER_2,
    RETURN_TO_CULTIVATE_MAIN_MENU, BEFORE_RACE_START, BEFORE_RACE_SKIP,
    BEFORE_RACE_CHANGE_TACTIC, IN_RACE_UMA_LIST_CONFIRM, IN_RACE_SKIP,
    RACE_RESULT_CONFIRM, RACE_REWARD_CONFIRM
)
from module.umamusume.asset.template import (
    REF_RACE_LIST_GOAL_RACE, REF_RACE_LIST_URA_RACE, REF_SUITABLE_RACE
)
from module.umamusume.script.cultivate_task.parse import parse_date, find_race

log = logger.get_logger(__name__)


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
    
    if ctx.cultivate_detail.turn_info is None or current_date != ctx.cultivate_detail.turn_info.date:
        if ctx.cultivate_detail.turn_info is not None:
            ctx.cultivate_detail.turn_info_history.append(ctx.cultivate_detail.turn_info)
        ctx.cultivate_detail.turn_info = TurnInfo()
        ctx.cultivate_detail.turn_info.date = current_date
    
    if ctx.cultivate_detail.turn_info.turn_operation:
        race_id = ctx.cultivate_detail.turn_info.turn_operation.race_id
        log.info(f"Current race ID: {race_id}")
        if race_id in [2381, 2382, 2385, 2386, 2387]:
            log.info("This is a URA championship race - proceeding directly to start")
            ctx.ctrl.click_by_point(CULTIVATE_GOAL_RACE_INTER_2)
        else:
            log.info(f"This is a regular race (ID: {race_id}) - entering detail interface")
            ctx.ctrl.click_by_point(CULTIVATE_GOAL_RACE_INTER_1)
    else:
        log.warning("No turn operation found - cannot determine race type")
        ctx.ctrl.click_by_point(CULTIVATE_GOAL_RACE_INTER_1)


def script_cultivate_race_list(ctx: UmamusumeContext):
    log.info("Entered Race List menu (CULTIVATE_RACE_LIST)")
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
    
    log.info(f"Template matching - Goal Race: {goal_match}, URA Race: {ura_match}")
    
    if goal_match:
        log.info("Found Goal Race - clicking to enter detail interface")
        ctx.ctrl.click_by_point(CULTIVATE_GOAL_RACE_INTER_1)
    elif ura_match:
        log.info("Found URA Race - clicking to enter detail interface")
        ctx.ctrl.click_by_point(CULTIVATE_GOAL_RACE_INTER_1)
    else:
        if ctx.cultivate_detail.turn_info.turn_operation is None:
            log.warning("No turn operation - returning to main menu")
            ctx.ctrl.click_by_point(RETURN_TO_CULTIVATE_MAIN_MENU)
            return
        else:
            log.info(f"Turn operation type: {ctx.cultivate_detail.turn_info.turn_operation.turn_operation_type}")
            if ctx.cultivate_detail.turn_info.turn_operation.turn_operation_type == TurnOperationType.TURN_OPERATION_TYPE_RACE:
                race_id = ctx.cultivate_detail.turn_info.turn_operation.race_id
                log.info(f"Race operation with ID: {race_id}")
                if race_id in [2381, 2382, 2385, 2386, 2387] or race_id == 0:
                    log.info("Detected URA race operation - clicking race button directly")
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
                log.info(f"Looking for race ID: {race_id}")
                selected = find_race(ctx, img, race_id)
                if selected:
                    log.info(f"Found race ID: {race_id}")
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
        target_tactic = None

        if hasattr(ctx.cultivate_detail, 'tactic_actions') and ctx.cultivate_detail.tactic_actions:
            for action in ctx.cultivate_detail.tactic_actions:
                op = action.get('op')
                val = int(action.get('val', 0))
                val2 = int(action.get('val2', 0))
                tactic = int(action.get('tactic', 0))
                
                match = False
                if op == '=':
                    if date == val: match = True
                elif op == '>':
                    if date > val: match = True
                elif op == '<':
                    if date < val: match = True
                elif op == 'range':
                    if val < date < val2: match = True
                
                if match:
                    target_tactic = tactic
                    break

        if target_tactic:
            p_check_tactic = tactic_check_point_list[target_tactic - 1]
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
