import cv2
import time

from bot.recog.image_matcher import image_match
from module.umamusume.context import UmamusumeContext
from module.umamusume.script.cultivate_task.ai import get_operation
from module.umamusume.asset.point import *
from module.umamusume.asset.template import *
from module.umamusume.asset.template import UI_INFO
from bot.recog.ocr import ocr_line, find_similar_text
from bot.base.task import TaskStatus, EndTaskReason
from bot.base.common import Area, ImageMatchConfig
import bot.base.log as logger

log = logger.get_logger(__name__)

def tt_next_sequence(ctx: UmamusumeContext):
    try:
        img_gray = ctx.ctrl.get_screen(to_gray=True)
        res = image_match(img_gray, REF_NEXT)
        if getattr(res, "find_match", False):
            x1, y1 = res.matched_area[0]
            x2, y2 = res.matched_area[1]
            cx = int((x1 + x2) / 2)
            cy = int((y1 + y2) / 2)
            ctx.ctrl.click(cx, cy, "team trials next 1")
        else:
            ctx.ctrl.click(354, 1077, "team trials next 1")
        time.sleep(0.7)
        ctx.ctrl.click(508, 896, "team trials next 2")
    except Exception:
        pass

def complete_team_trials(ctx: UmamusumeContext):
    mode_name = getattr(ctx.task.task_execute_mode, "name", None)
    ctx.ctrl.click(355, 1200, "tt2")
    time.sleep(1)
    ctx.ctrl.click(355, 1200, "tt1")
    if mode_name == "TASK_EXECUTE_MODE_FULL_AUTO":
        log.info("tt done in full auto - switching to career mode")
        ctx.task.detail.do_tt_next = False
    else:
        log.info("tt done - ending task")
        ctx.task.end_task(TaskStatus.TASK_STATUS_SUCCESS, EndTaskReason.COMPLETE)


REF_CANT_TT_REGION = Template("cant_tt", UMAMUSUME_REF_TEMPLATE_PATH, 
                               ImageMatchConfig(match_area=Area(369, 586, 439, 609)))

REF_CANT_TT2_REGION = Template("cant_tt2", UMAMUSUME_REF_TEMPLATE_PATH, 
                                ImageMatchConfig(match_area=Area(391, 43, 433, 81)))

RULES_BY_MODE = {
    "TASK_EXECUTE_MODE_TEAM_TRIALS": [
        {"type": "image", "ref": REF_CANT_TT_REGION, "action": complete_team_trials},
        {"type": "image", "ref": REF_CANT_TT2_REGION, "action": complete_team_trials},
        {"type": "image", "ref": REF_HOME_GIFT, "action": lambda ctx: ctx.ctrl.click(522, 1228, "team trials resume")},
        {"type": "image", "ref": REF_TEAM_TRIALS, "action": lambda ctx: ctx.ctrl.click(106, 812, "team trials resume2")},
        {"type": "image", "ref": REF_TEAM_RACE, "action": lambda ctx: ctx.ctrl.click(351, 839, "team trials resume3")},
        {"type": "image", "ref": REF_SELECT_OPP, "action": lambda ctx: ctx.ctrl.click(73, 278, "team trials resume4")},
        {"type": "image", "ref": REF_TT_SEE_ALL, "action": lambda ctx: ctx.ctrl.click(359, 1200, "team trials resume5")},
        {"type": "image", "ref": REF_NEXT, "action": tt_next_sequence},
        {"type": "title", "ref": "Items Selected", "action": lambda ctx: ctx.ctrl.click(610, 908, "tt6")},
        {"type": "title", "ref": "Daily Sale", "action": lambda ctx: ctx.ctrl.click(0, 0, "daily sale")},
        {"type": "image", "ref": REF_SEE_RESULTS, "action": lambda ctx: ctx.ctrl.click(514, 1208, "tt7")},
        {"type": "image", "ref": REF_NEXT2, "action": lambda ctx: ctx.ctrl.click(393, 1183, "tt8")},
    ]
}


def apply_rules(ctx: UmamusumeContext, img_gray):
    mode = getattr(ctx.task.task_execute_mode, "name", None)
    if not mode:
        return False
    
    if mode == "TASK_EXECUTE_MODE_FULL_AUTO":
        if getattr(ctx.task.detail, "do_tt_next", False):
            rules = RULES_BY_MODE.get("TASK_EXECUTE_MODE_TEAM_TRIALS", [])
        else:
            return False
    else:
        rules = RULES_BY_MODE.get(mode, [])
    title_raw = None
    need_title = any(r.get("type") == "title" for r in rules)
    if need_title:
        res = image_match(img_gray, UI_INFO)
        if res.find_match:
            pos = res.matched_area
            title_img = img_gray[pos[0][1] - 5:pos[1][1] + 5, pos[0][0] + 150: pos[1][0] + 405]
            title_raw = ocr_line(title_img)
    for r in rules:
        try:
            if r.get("type") == "image":
                if image_match(img_gray, r["ref"]).find_match:
                    r["action"](ctx)
                    return True
            elif r.get("type") == "title" and title_raw:
                matched = find_similar_text(title_raw, [r["ref"]], 0.8)
                if matched == r["ref"]:
                    r["action"](ctx)
                    return True
        except Exception:
            pass
    return False


def before_hook(ctx: UmamusumeContext):
    if ctx.task.task_status != TaskStatus.TASK_STATUS_RUNNING:
        return
    img = cv2.cvtColor(ctx.current_screen, cv2.COLOR_BGR2GRAY)
    if apply_rules(ctx, img):
        return
    
    if image_match(img, REF_HOME_GIFT).find_match:
        mode_name = ctx.task.task_execute_mode.name
        
        if mode_name == "TASK_EXECUTE_MODE_TEAM_TRIALS":
            ctx.ctrl.click(522, 1228, "team trials resume")
            return
        
        elif mode_name == "TASK_EXECUTE_MODE_FULL_AUTO":
            if getattr(ctx.task.detail, "do_tt_next", False):
                ctx.ctrl.click(522, 1228, "team trials resume")
                return
            
            # TT pixel check
            try:
                screen = ctx.current_screen
                if screen is not None:
                    pixel = screen[67, 456]
                    b, g, r = int(pixel[0]), int(pixel[1]), int(pixel[2])
                    target_r, target_g, target_b = 81, 76, 89
                    tolerance = 5
                    pixel_matches = (abs(r - target_r) <= tolerance and 
                                   abs(g - target_g) <= tolerance and 
                                   abs(b - target_b) <= tolerance)
                    
                    if pixel_matches:
                        log.info(f"pixel matches - proceeding with career mode")
                        ctx.ctrl.click(552, 1082, "resume career")
                    else:
                        log.info(f"pixel does not match - starting TT mode")
                        ctx.task.detail.do_tt_next = True
                        ctx.ctrl.click(522, 1228, "start team trials")
                        return
                else:
                    ctx.ctrl.click(552, 1082, "resume career")
            except Exception as e:
                ctx.ctrl.click(552, 1082, "resume career")
        
        else:
            ctx.ctrl.click(552, 1082, "resume career")
        
        time.sleep(1)
        img = cv2.cvtColor(ctx.ctrl.get_screen(), cv2.COLOR_BGR2GRAY)
        if image_match(img, REF_RESUME_CAREER).find_match:
            if mode_name == "TASK_EXECUTE_MODE_TEAM_TRIALS":
                ctx.ctrl.click(710, 10, "skip resume career - TT mode")
            elif mode_name == "TASK_EXECUTE_MODE_FULL_AUTO" and getattr(ctx.task.detail, "do_tt_next", False):
                ctx.ctrl.click(710, 10, "skip resume career - full auto TT")
            else:
                ctx.ctrl.click(505, 908, "continue resume career")
        return
    
    if image_match(img, REF_RESUME_CAREER).find_match:
        mode_name = ctx.task.task_execute_mode.name
        if mode_name == "TASK_EXECUTE_MODE_TEAM_TRIALS":
            ctx.ctrl.click(710, 10, "skip resume career - TT mode")
        elif mode_name == "TASK_EXECUTE_MODE_FULL_AUTO" and getattr(ctx.task.detail, "do_tt_next", False):
            ctx.ctrl.click(710, 10, "skip resume career - full auto TT")
        else:
            ctx.ctrl.click(505, 908, "continue resume career")
        return



def after_hook(ctx: UmamusumeContext):
    if ctx.task.task_status != TaskStatus.TASK_STATUS_RUNNING:
        return
    try:
        if getattr(ctx.ctrl, 'trigger_decision_reset', False):
            ctx.ctrl.trigger_decision_reset = False
            log.info("failsafe triggered. restarting decision making")
            ti = getattr(ctx.cultivate_detail, 'turn_info', None)
            if ti is not None:
                try:
                    ti.parse_main_menu_finish = False
                except Exception:
                    pass
                try:
                    ti.parse_train_info_finish = False
                except Exception:
                    pass
                try:
                    ti.turn_operation = None
                except Exception:
                    pass
                for attr in ("race_search_started_at", "race_search_id"):
                    if hasattr(ti, attr):
                        try:
                            delattr(ti, attr)
                        except Exception:
                            pass
    except Exception:
        pass
    img = cv2.cvtColor(ctx.current_screen, cv2.COLOR_BGR2GRAY)
    try:
        scenario = getattr(getattr(ctx, 'cultivate_detail', None), 'scenario', None)
        if scenario is not None:
            if scenario.after_hook(ctx, img):
                return
    except Exception:
        pass
    if apply_rules(ctx, img):
        return
    if image_match(img, BTN_SKIP).find_match:
        ctx.ctrl.click_by_point(SKIP)
    if image_match(img, BTN_SKIP_OFF).find_match:
        ctx.ctrl.click_by_point(SCENARIO_SKIP_OFF)
    if image_match(img, BTN_SKIP_SPEED_1).find_match:
        ctx.ctrl.click_by_point(SCENARIO_SKIP_SPEED_1)
    if ctx.cultivate_detail and ctx.cultivate_detail.turn_info is not None:
        if ctx.cultivate_detail.turn_info.parse_train_info_finish and ctx.cultivate_detail.turn_info.parse_main_menu_finish:
            if not ctx.cultivate_detail.turn_info.turn_info_logged:
                ctx.cultivate_detail.turn_info.log_turn_info(ctx.task.detail.scenario)
                ctx.cultivate_detail.turn_info.turn_info_logged = True
            if ctx.cultivate_detail.turn_info.turn_operation is None:
                # Only get operation if we haven't already decided on training
                # This prevents AI from overriding training decisions with race decisions
                # Also check if we're in training selection screen - don't override training decisions there
                from module.umamusume.asset.template import UI_CULTIVATE_TRAINING_SELECT
                in_training_select = image_match(img, UI_CULTIVATE_TRAINING_SELECT).find_match
                
                if not in_training_select:
                    log.info(f"🔍 Not in training selection screen - calling AI decision")
                    log.info(f"🔍 Extra race list: {ctx.cultivate_detail.extra_race_list}")
                    log.info(f"🔍 Debut race win status: {ctx.cultivate_detail.debut_race_win}")
                    ctx.cultivate_detail.turn_info.turn_operation = get_operation(ctx)
                    ctx.cultivate_detail.turn_info.turn_operation.log_turn_operation()
                else:
                    log.info("🔍 In training selection screen - skipping AI decision to avoid overriding training")




