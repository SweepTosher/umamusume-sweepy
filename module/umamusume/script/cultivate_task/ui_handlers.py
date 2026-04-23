import time
import cv2

import bot.base.log as logger
from bot.base.task import TaskStatus, EndTaskReason
from bot.recog.image_matcher import image_match
from module.umamusume.context import UmamusumeContext, clear_detected_skills
from module.umamusume.define import ScenarioType
from module.umamusume.asset.point import (
    TO_CULTIVATE_SCENARIO_CHOOSE, TO_CULTIVATE_PREPARE_NEXT,
    TO_CULTIVATE_PREPARE_AUTO_SELECT, TO_CULTIVATE_PREPARE_INCLUDE_GUEST,
    TO_CULTIVATE_PREPARE_CONFIRM, TO_FOLLOW_SUPPORT_CARD_SELECT,
    CULTIVATE_FINAL_CHECK_START, CULTIVATE_RESULT_CONFIRM,
    CULTIVATE_CATCH_DOLL_START, CULTIVATE_CATCH_DOLL_RESULT_CONFIRM,
    CULTIVATE_RECEIVE_CUP_CLOSE, CULTIVATE_LEVEL_RESULT_CONFIRM,
    CULTIVATE_FACTOR_RECEIVE_CONFIRM, HISTORICAL_RATING_UPDATE_CONFIRM,
    SCENARIO_RATING_UPDATE_CONFIRM, CULTIVATE_EXTEND_CONFIRM,
    GOAL_ACHIEVE_CONFIRM, GOAL_FAIL_CONFIRM, NEXT_GOAL_CONFIRM
)
from module.umamusume.asset.template import (
    UI_SCENARIO, REF_CULTIVATE_SUPPORT_CARD_EMPTY
)
from module.umamusume.script.cultivate_task.parse import parse_factor

log = logger.get_logger(__name__)


def is_home_screen(ctx):
    try:
        img = ctx.current_screen
        if img is None:
            return False
        img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        from module.umamusume.asset.template import REF_HOME_COIN
        return image_match(img_gray, REF_HOME_COIN).find_match
    except Exception:
        return False


def script_main_menu(ctx: UmamusumeContext):
    if ctx.cultivate_detail.cultivate_finish:
        from bot.base.runtime_state import get_state
        get_state()["in_career_run"] = False
        mode_name = getattr(ctx.task.task_execute_mode, "name", None)
        if mode_name == "TASK_EXECUTE_MODE_FULL_AUTO":
            log.info("career run completed in full auto mode - resetting for next run")
            ctx.cultivate_detail.cultivate_finish = False
            ctx.cultivate_detail.turn_info = None
            ctx.cultivate_detail.turn_info_history = []
            clear_detected_skills()
            return
        else:
            ctx.task.end_task(TaskStatus.TASK_STATUS_SUCCESS, EndTaskReason.COMPLETE)
            return

    if is_home_screen(ctx):
        current_date = getattr(ctx.cultivate_detail.turn_info, 'date', 0) if ctx.cultivate_detail.turn_info else 0
        if current_date > 0:
            log.info(f"home screen post career date={current_date}")
            from bot.base.runtime_state import get_state
            get_state()["in_career_run"] = False
            ctx.cultivate_detail.cultivate_finish = True
            mode_name = getattr(ctx.task.task_execute_mode, "name", None)
            if mode_name == "TASK_EXECUTE_MODE_FULL_AUTO":
                log.info("full auto reset")
                ctx.cultivate_detail.cultivate_finish = False
                ctx.cultivate_detail.turn_info = None
                ctx.cultivate_detail.turn_info_history = []
                clear_detected_skills()
                return
            else:
                ctx.task.end_task(TaskStatus.TASK_STATUS_SUCCESS, EndTaskReason.COMPLETE)
                return

    ctx.ctrl.click_by_point(TO_CULTIVATE_SCENARIO_CHOOSE)


def script_scenario_select(ctx: UmamusumeContext):
    target_scenario = ctx.cultivate_detail.scenario.scenario_type()
    time.sleep(2)

    for i in range(1, 15):
        img_gray = ctx.ctrl.get_screen(to_gray=True)

        if image_match(img_gray, UI_SCENARIO[target_scenario]).find_match:
            log.info(f"Found target cultivation scenario {ctx.cultivate_detail.scenario.scenario_name()}")
            ctx.ctrl.click_by_point(TO_CULTIVATE_PREPARE_NEXT)
            return

        log.debug(f"Scenario does not match, checking next scenario")
        ctx.ctrl.swipe(x1=400, y1=600, x2=500, y2=600, duration=300, name="swipe right")
        time.sleep(0.7)

    log.error(f"Could not find specified scenario")
    ctx.task.end_task(TaskStatus.TASK_STATUS_FAILED, EndTaskReason.SCENARIO_NOT_FOUND)


def script_umamusume_select(ctx: UmamusumeContext):
    time.sleep(2)
    img_gray = ctx.ctrl.get_screen(to_gray=True)
    if image_match(img_gray, UI_CULTIVATE_UMAMUSUME_SELECT).find_match:
        ctx.ctrl.click_by_point(TO_CULTIVATE_PREPARE_NEXT)
    else:
        ctx.ctrl.click_by_point(TO_CULTIVATE_PREPARE_NEXT)


def script_extend_umamusume_select(ctx: UmamusumeContext):
    try:
        if getattr(ctx.cultivate_detail, 'use_last_parents', False):
            ctx.ctrl.click_by_point(TO_CULTIVATE_PREPARE_NEXT)
            return
    except Exception:
        pass
    ctx.ctrl.click_by_point(TO_CULTIVATE_PREPARE_AUTO_SELECT)
    time.sleep(0.5)
    ctx.ctrl.click_by_point(TO_CULTIVATE_PREPARE_INCLUDE_GUEST)
    time.sleep(0.5)
    ctx.ctrl.click_by_point(TO_CULTIVATE_PREPARE_CONFIRM)
    time.sleep(0.5)
    ctx.ctrl.click_by_point(TO_CULTIVATE_PREPARE_NEXT)


def script_support_card_select(ctx: UmamusumeContext):
    img = ctx.ctrl.get_screen(to_gray=True)
    if image_match(img, REF_CULTIVATE_SUPPORT_CARD_EMPTY).find_match:
        from bot.base.runtime_state import get_state
        state = get_state()
        ctx.ctrl.click_by_point(TO_FOLLOW_SUPPORT_CARD_SELECT)
        state["input_blocked"] = True
        time.sleep(1.0)
        state["input_blocked"] = False
        return
    ctx.ctrl.click_by_point(TO_CULTIVATE_PREPARE_NEXT)


def script_cultivate_final_check(ctx: UmamusumeContext):
    ctx.ctrl.click_by_point(CULTIVATE_FINAL_CHECK_START)


def script_cultivate_result(ctx: UmamusumeContext):
    log.info("Cultivation Result detected - clicking confirm button")
    ctx.ctrl.click_by_point(CULTIVATE_RESULT_CONFIRM)


def script_cultivate_catch_doll(ctx: UmamusumeContext):
    ctx.ctrl.click_by_point(CULTIVATE_CATCH_DOLL_START, hold_duration=1888)


def script_cultivate_catch_doll_result(ctx: UmamusumeContext):
    ctx.ctrl.click_by_point(CULTIVATE_CATCH_DOLL_RESULT_CONFIRM)


def script_cultivate_goal_achieved(ctx: UmamusumeContext):
    ctx.ctrl.click_by_point(GOAL_ACHIEVE_CONFIRM)


def script_cultivate_goal_failed(ctx: UmamusumeContext):
    ctx.ctrl.click_by_point(GOAL_FAIL_CONFIRM)


def script_cultivate_next_goal(ctx: UmamusumeContext):
    ctx.ctrl.click_by_point(NEXT_GOAL_CONFIRM)


def script_cultivate_extend(ctx: UmamusumeContext):
    ctx.ctrl.click_by_point(CULTIVATE_EXTEND_CONFIRM)


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
