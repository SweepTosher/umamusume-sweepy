import time
import re
import random
import math
import cv2
from concurrent.futures import ThreadPoolExecutor

import bot.base.log as logger
from bot.recog.ocr import ocr_line
from bot.recog.image_matcher import image_match
from module.umamusume.context import UmamusumeContext

from module.umamusume.asset.point import (
    RETURN_TO_CULTIVATE_FINISH, CULTIVATE_FINISH_LEARN_SKILL,
    CULTIVATE_FINISH_CONFIRM, CULTIVATE_LEARN_SKILL_CONFIRM,
    FOLLOW_SUPPORT_CARD_SELECT_REFRESH
)
from module.umamusume.asset.template import REF_BORROW_CARD
from module.umamusume.script.cultivate_task.const import SKILL_LEARN_PRIORITY_LIST
from module.umamusume.context import log_detected_skill
from module.umamusume.script.cultivate_task.parse import get_skill_list, find_skill, find_support_card

log = logger.get_logger(__name__)

TRACK_TOP = 480
TRACK_BOT = 1010
SB_X = 701
SB_X_MIN = 697
SB_X_MAX = 703
CONTENT_TOP = 475
CONTENT_BOT = 950
CONTENT_X1 = 40
CONTENT_X2 = 670
SCREEN_WIDTH = 720


def _gauss_scan_x():
    mu = SCREEN_WIDTH * 0.667
    sigma = SCREEN_WIDTH * 0.194
    while True:
        v = random.gauss(mu, sigma)
        x = int(round(v))
        if 10 <= x <= SCREEN_WIDTH - 10:
            return x


def is_thumb(r, g, b):
    return abs(r - 122) <= 11 and abs(g - 117) <= 11 and abs(b - 139) <= 11


def is_track(r, g, b):
    return abs(r - 211) <= 5 and abs(g - 209) <= 5 and abs(b - 219) <= 5


def find_thumb(img_rgb):
    top = bot = None
    for y in range(TRACK_TOP, TRACK_BOT + 1):
        r, g, b = int(img_rgb[y, SB_X, 0]), int(img_rgb[y, SB_X, 1]), int(img_rgb[y, SB_X, 2])
        if is_thumb(r, g, b):
            if top is None:
                top = y
            bot = y
    return (top, bot) if top is not None else None


def at_bottom(img_rgb):
    thumb = find_thumb(img_rgb)
    if thumb is None:
        return True
    for y in range(thumb[1] + 1, TRACK_BOT + 1):
        r, g, b = int(img_rgb[y, SB_X, 0]), int(img_rgb[y, SB_X, 1]), int(img_rgb[y, SB_X, 2])
        if is_track(r, g, b):
            return False
    return True


def at_top(img_rgb):
    thumb = find_thumb(img_rgb)
    if thumb is None:
        return False
    return thumb[0] <= TRACK_TOP + 10


def content_gray(img):
    return cv2.cvtColor(img[CONTENT_TOP:CONTENT_BOT, CONTENT_X1:CONTENT_X2], cv2.COLOR_BGR2GRAY)


def find_content_shift(before, after):
    bg = content_gray(before)
    ag = content_gray(after)
    ch = bg.shape[0]
    strip_h = 80
    best_shift = 0
    best_conf = 0
    for strip_y in [ch - strip_h - 10, ch - strip_h - 80, ch // 2]:
        if strip_y < 0 or strip_y + strip_h > ch:
            continue
        strip = bg[strip_y:strip_y + strip_h]
        result = cv2.matchTemplate(ag, strip, cv2.TM_CCOEFF_NORMED)
        _, mv, _, ml = cv2.minMaxLoc(result)
        if mv > best_conf:
            best_conf = mv
            if mv > 0.85:
                best_shift = strip_y - ml[1]
    return best_shift, best_conf


def content_same(before, after):
    b = content_gray(before)
    a = content_gray(after)
    diff = cv2.absdiff(b, a)
    return cv2.mean(diff)[0] < 3


def sb_drag(ctx, from_y, to_y):
    sx = random.randint(SB_X_MIN, SB_X_MAX)
    ex = random.randint(SB_X_MIN, SB_X_MAX)
    dur = random.randint(166, 211)
    ctx.ctrl.execute_adb_shell(
        "shell input swipe " + str(sx) + " " + str(from_y) + " " + str(ex) + " " + str(to_y) + " " + str(dur), True)
    time.sleep(0.15)


def scroll_to_top(ctx):
    for _ in range(15):
        img = ctx.ctrl.get_screen()
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        if at_top(img_rgb):
            return
        thumb = find_thumb(img_rgb)
        if thumb is None:
            continue
        sb_drag(ctx, (thumb[0] + thumb[1]) // 2, TRACK_TOP)


def scroll_to_bottom(ctx):
    for _ in range(15):
        img = ctx.ctrl.get_screen()
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        if at_bottom(img_rgb):
            return
        thumb = find_thumb(img_rgb)
        if thumb is None:
            continue
        sb_drag(ctx, (thumb[0] + thumb[1]) // 2, TRACK_BOT)


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
        time.sleep(0.5)
    ctx.ctrl.click_by_point(FOLLOW_SUPPORT_CARD_SELECT_REFRESH)


def script_cultivate_finish(ctx: UmamusumeContext):
    from bot.base.runtime_state import get_state
    get_state()["in_career_run"] = False
    try:
        from module.umamusume.persistence import clear_used_buffs, clear_megaphone_state
        clear_used_buffs()
        clear_megaphone_state()
    except Exception:
        pass
    if not ctx.task.detail.manual_purchase_at_end:
        if not ctx.cultivate_detail.cultivate_finish:
            ctx.cultivate_detail.cultivate_finish = True
            ctx.cultivate_detail.final_skill_sweep_active = True
            ctx.cultivate_detail.learn_skill_done = False
            ctx.cultivate_detail.learn_skill_selected = False
            ctx.ctrl.click_by_point(CULTIVATE_FINISH_LEARN_SKILL)
            return
        if getattr(ctx.cultivate_detail, "final_skill_sweep_active", False):
            sweep_count = getattr(ctx.cultivate_detail, "final_skill_sweep_count", 0)
            if ctx.cultivate_detail.learn_skill_selected and sweep_count < 2:
                ctx.cultivate_detail.final_skill_sweep_count = sweep_count + 1
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
        if not ctx.cultivate_detail.manual_purchase_completed:
            if not hasattr(ctx.cultivate_detail, 'manual_purchase_initiated'):
                log.info("Manual purchase mode enabled - showing web notification to user")
                try:
                    import requests
                    import json
                    
                    notification_data = {
                        "type": "manual_skill_purchase",
                        "message": "Please learn skills manually, then press confirm when done",
                        "timestamp": time.time()
                    }
                    
                    try:
                        response = requests.post(
                            "http://localhost:8071/api/manual-skill-notification",
                            json=notification_data,
                            timeout=1
                        )
                        log.info("Web notification sent successfully")
                        
                        while True:
                            try:
                                status_response = requests.get(
                                    "http://localhost:8071/api/manual-skill-notification-status",
                                    timeout=1
                                )
                                status_data = status_response.json()
                                
                                if status_data.get("confirmed"):
                                    log.info("User confirmed manual skill purchase via web interface")
                                    ctx.cultivate_detail.manual_purchase_completed = True
                                    requests.post("http://localhost:8071/api/manual-skill-notification-cancel")
                                    break
                                elif status_data.get("cancelled"):
                                    log.info("User cancelled manual skill purchase")
                                    requests.post("http://localhost:8071/api/manual-skill-notification-cancel")
                                    return
                                
                                time.sleep(0.5)
                            except requests.exceptions.RequestException:
                                break
                        
                    except requests.exceptions.RequestException as e:
                        log.warning(f"Web notification failed: {e}")
                        print("\n" + "=" * 50)
                        print("MANUAL SKILL PURCHASE REQUIRED")
                        print("=" * 50)
                        print("Please learn skills manually, then press confirm when done.")
                        print("Press Enter in the console when you're ready to continue...")
                        print("=" * 50)
                        input()
                    
                    log.info("User acknowledged manual purchase notification")
                except Exception as e:
                    log.error(f"Failed to show notification: {e}")
                    print("\n" + "="*50)
                    print("MANUAL SKILL PURCHASE REQUIRED")
                    print("="*50)
                    print("Please learn skills manually, then press confirm when done.")
                    print("Press Enter in the console when you're ready to continue...")
                    print("="*50)
                    input()
                
                ctx.cultivate_detail.manual_purchase_initiated = True
                return
            else:
                return
        else:
            log.info("User completed manual skill purchase - proceeding with cultivation finish")
            ctx.cultivate_detail.learn_skill_done = True
            ctx.cultivate_detail.cultivate_finish = True
            ctx.ctrl.click_by_point(CULTIVATE_FINISH_CONFIRM)


def script_cultivate_learn_skill(ctx: UmamusumeContext):
    if (ctx.task.detail.manual_purchase_at_end and
        ctx.cultivate_detail.cultivate_finish and 
        hasattr(ctx.cultivate_detail, 'manual_purchase_completed') and 
        ctx.cultivate_detail.manual_purchase_completed):
        log.info("Manual purchase completed - returning to cultivate finish UI")
        ctx.cultivate_detail.learn_skill_done = True
        ctx.cultivate_detail.turn_info.turn_learn_skill_done = True
        ctx.ctrl.click_by_point(RETURN_TO_CULTIVATE_FINISH)
        return
        
    if ctx.task.detail.manual_purchase_at_end and ctx.cultivate_detail.cultivate_finish:
        log.info("Manual purchase mode enabled - returning to cultivate finish UI")
        ctx.cultivate_detail.manual_purchase_completed = True
        ctx.cultivate_detail.learn_skill_done = True
        ctx.cultivate_detail.turn_info.turn_learn_skill_done = True
        ctx.ctrl.click_by_point(RETURN_TO_CULTIVATE_FINISH)
        return
        
    if ctx.cultivate_detail.learn_skill_done:
        log.info("Skills already learned and confirmed - exiting skill learning")
        ctx.cultivate_detail.turn_info.turn_learn_skill_done = True
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
            for idx, p_list in enumerate(learn_skill_list):
                try:
                    log.info(f"  priority {idx}: {', '.join(p_list) if p_list else ''}")
                except Exception:
                    pass
        bl = ctx.cultivate_detail.learn_skill_blacklist or []
        log.info(f"Blacklist: {', '.join(bl) if bl else ''}")
    except Exception:
        pass

    skill_list = []
    scan_skill_positions = {}
    saved_thumb_h = 36
    drag_ratio = 1.1

    scroll_to_top(ctx)
    img = ctx.ctrl.get_screen()
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    thumb = find_thumb(img_rgb)

    if thumb is not None:
        thumb_h = thumb[1] - thumb[0]
        saved_thumb_h = thumb_h
        thumb_center = (thumb[0] + thumb[1]) // 2
        if thumb[0] > TRACK_TOP:
            sb_drag(ctx, thumb_center, TRACK_TOP)
            img = ctx.ctrl.get_screen()
            img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            thumb = find_thumb(img_rgb)
            thumb_center = (thumb[0] + thumb[1]) // 2 if thumb else TRACK_TOP + thumb_h // 2

        before_cal = img
        cal_px = 30
        sb_drag(ctx, thumb_center, thumb_center + cal_px)
        after_cal = ctx.ctrl.get_screen()
        shift_cal, conf_cal = find_content_shift(before_cal, after_cal)
        ratio = shift_cal / cal_px if (shift_cal > 0 and conf_cal > 0.85) else 14.0

        img_dr = ctx.ctrl.get_screen()
        img_dr_rgb = cv2.cvtColor(img_dr, cv2.COLOR_BGR2RGB)
        thumb_cal = find_thumb(img_dr_rgb)
        if thumb_cal:
            cal_from = (thumb_cal[0] + thumb_cal[1]) // 2
            cal_dist = 30
            sb_drag(ctx, cal_from, cal_from + cal_dist)
            img_dr2 = ctx.ctrl.get_screen()
            img_dr2_rgb = cv2.cvtColor(img_dr2, cv2.COLOR_BGR2RGB)
            thumb_cal2 = find_thumb(img_dr2_rgb)
            if thumb_cal2:
                cal_to = (thumb_cal2[0] + thumb_cal2[1]) // 2
                actual_move = cal_to - cal_from
                if actual_move > 3:
                    drag_ratio = cal_dist / actual_move

        scroll_to_top(ctx)
        img = ctx.ctrl.get_screen()
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        thumb = find_thumb(img_rgb)
        start_y = (thumb[0] + thumb[1]) // 2 if thumb else TRACK_TOP + thumb_h // 2 + 5

        content_h = CONTENT_BOT - CONTENT_TOP
        track_len = TRACK_BOT - TRACK_TOP
        total_content = track_len * ratio + content_h
        desired_overlap = 160
        desired_shift = content_h - desired_overlap
        est_frames = total_content / desired_shift
        swipe_dur = max(5000, min(25000, int(est_frames * 600)))

        scan_x_end = _gauss_scan_x()
        swipe_cmd = "shell input swipe " + str(SB_X) + " " + str(start_y) + " " + str(scan_x_end) + " " + str(TRACK_BOT) + " " + str(swipe_dur)
        proc = ctx.ctrl.execute_adb_shell(swipe_cmd, sync=False)

        time.sleep(0.3)
        prev_frame = img
        scan_deadline = time.time() + 30
        frame_sb_positions = []
        early_exit = False

        with ThreadPoolExecutor(max_workers=1) as executor:
            futures = []

            while ctx.task.running() and time.time() < scan_deadline:
                if (ctx.task.detail.manual_purchase_at_end and
                    ctx.cultivate_detail.cultivate_finish and
                    hasattr(ctx.cultivate_detail, 'manual_purchase_completed') and
                    ctx.cultivate_detail.manual_purchase_completed):
                    try:
                        proc.terminate()
                    except Exception:
                        pass
                    early_exit = True
                    break

                time.sleep(0.068)
                curr = ctx.ctrl.get_screen()
                if curr is not None and not content_same(prev_frame, curr):
                    curr_rgb = cv2.cvtColor(curr, cv2.COLOR_BGR2RGB)
                    thumb_now = find_thumb(curr_rgb)
                    sb_y = (thumb_now[0] + thumb_now[1]) // 2 if thumb_now else None
                    frame_sb_positions.append(sb_y)
                    futures.append(executor.submit(get_skill_list, curr, learn_skill_list, learn_skill_blacklist))
                    prev_frame = curr
                if proc.poll() is not None:
                    break

            try:
                proc.terminate()
            except Exception:
                pass

            if not early_exit:
                time.sleep(0.15)
                final = ctx.ctrl.get_screen()
                if final is not None and not content_same(prev_frame, final):
                    final_rgb = cv2.cvtColor(final, cv2.COLOR_BGR2RGB)
                    thumb_now = find_thumb(final_rgb)
                    sb_y = (thumb_now[0] + thumb_now[1]) // 2 if thumb_now else None
                    frame_sb_positions.append(sb_y)
                    futures.append(executor.submit(get_skill_list, final, learn_skill_list, learn_skill_blacklist))

            last_known_sb = start_y
            for i, f in enumerate(futures):
                frame_skills = f.result()
                sb_y = frame_sb_positions[i] if i < len(frame_sb_positions) and frame_sb_positions[i] is not None else last_known_sb
                if frame_sb_positions[i] is not None:
                    last_known_sb = frame_sb_positions[i]
                for s in frame_skills:
                    if s not in skill_list:
                        skill_list.append(s)
                    for key in [s.get('skill_name', ''), s.get('skill_name_raw', '')]:
                        if key and key not in scan_skill_positions:
                            scan_skill_positions[key] = sb_y

        if early_exit:
            ctx.cultivate_detail.learn_skill_done = True
            ctx.cultivate_detail.turn_info.turn_learn_skill_done = True
            ctx.ctrl.click_by_point(RETURN_TO_CULTIVATE_FINISH)
            return
    else:
        current_screen_skill_list = get_skill_list(img, learn_skill_list, learn_skill_blacklist)
        for i in current_screen_skill_list:
            if i not in skill_list:
                skill_list.append(i)

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

    for s in skill_list:
        skill_name = s.get("skill_name_raw") or s.get("skill_name", "")
        if skill_name:
            log_detected_skill(
                skill_name, "menu",
                hint_level=int(s.get("hint_level", 0)),
                cost=int(s.get("skill_cost", 0)),
                gold=bool(s.get("gold", False))
            )

    for i in range(len(skill_list)):
        if i != (len(skill_list) - 1) and skill_list[i]["gold"] is True:
            skill_list[i]["subsequent_skill"] = skill_list[i + 1]["skill_name"]

    skill_list = sorted(skill_list, key=lambda x: x["priority"])
    digits_pattern = re.compile(r"\D")
    img = ctx.ctrl.get_screen()
    total_skill_point_text = digits_pattern.sub("", ocr_line(img[400: 440, 490: 665]))
    total_skill_point = int(total_skill_point_text) if total_skill_point_text else 0
    log.info(f"Skill points available: {total_skill_point}")

    target_skill_list = []
    target_skill_list_raw = []
    curr_point = 0
    skip_dc = getattr(ctx.cultivate_detail, 'skip_double_circle_unless_high_hint', False)
    only_user = ctx.cultivate_detail.learn_skill_only_user_provided is True
    at_finish = ctx.cultivate_detail.cultivate_finish

    for priority_level in range(len(learn_skill_list) + 1):
        if only_user and not at_finish and priority_level > 0:
            if priority_level >= len(learn_skill_list) or not learn_skill_list[priority_level]:
                continue

        candidates = sorted(
            [s for s in skill_list if s["priority"] == priority_level and s["available"]],
            key=lambda s: -int(s.get("hint_level", 0))
        )

        for skill in candidates:
            if skip_dc and skill.get("is_double_circle", False) and int(skill.get("hint_level", 0)) < 4:
                continue
            if curr_point + skill["skill_cost"] > total_skill_point:
                continue
            curr_point += skill["skill_cost"]
            target_skill_list.append(skill["skill_name"])
            target_skill_list_raw.append(skill["skill_name_raw"])
            log.info(f"Target: '{skill['skill_name']}' cost={skill['skill_cost']} spent={curr_point}")
            if skill["gold"] and skill["subsequent_skill"]:
                for k in range(len(skill_list)):
                    if skill_list[k]["skill_name"] == skill["subsequent_skill"]:
                        skill_list[k]["available"] = False

    log.info(f"Final target skill list: {target_skill_list}")
    log.info(f"Total skills to learn: {len(target_skill_list)}, points to spend: {curr_point}")

    for skill in target_skill_list:
        ctx.task.detail.scenario_config.remove_skill_from_reset_list(skill)

    for skill in target_skill_list_raw:
        for priority_list in ctx.cultivate_detail.learn_skill_list:
            if skill in priority_list:
                priority_list.remove(skill)
    for skill in skill_list:
        for priority_list in ctx.cultivate_detail.learn_skill_list:
            if not skill['available'] and skill['skill_name_raw'] in priority_list:
                priority_list.remove(skill['skill_name_raw'])
    ctx.cultivate_detail.learn_skill_list = [x for x in ctx.cultivate_detail.learn_skill_list if x]

    def _manual_purchase_confirmed():
        return (ctx.task.detail.manual_purchase_at_end and
                at_finish and
                getattr(ctx.cultivate_detail, 'manual_purchase_completed', False))

    if _manual_purchase_confirmed():
        ctx.cultivate_detail.learn_skill_done = True
        ctx.cultivate_detail.turn_info.turn_learn_skill_done = True
        ctx.ctrl.click_by_point(RETURN_TO_CULTIVATE_FINISH)
        return

    if not target_skill_list:
        ctx.cultivate_detail.learn_skill_done = True
        ctx.cultivate_detail.turn_info.turn_learn_skill_done = True
        ctx.ctrl.click_by_point(RETURN_TO_CULTIVATE_FINISH)
        return

    remaining = target_skill_list.copy()

    for scroll_pass in range(3):
        if not remaining or _manual_purchase_confirmed():
            break

        scroll_to_top(ctx)
        pass_bought = 0

        for _ in range(60):
            if not remaining:
                break

            img = ctx.ctrl.get_screen()
            if img is None:
                time.sleep(0.2)
                continue

            prev_count = len(remaining)
            if find_skill(ctx, img, remaining, learn_any_skill=False):
                ctx.cultivate_detail.learn_skill_selected = True
                pass_bought += prev_count - len(remaining)
                continue

            img = ctx.ctrl.get_screen()
            img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            thumb = find_thumb(img_rgb)
            if thumb is None:
                time.sleep(0.15)
                img = ctx.ctrl.get_screen()
                img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                thumb = find_thumb(img_rgb)
                if thumb is None:
                    continue
            if at_bottom(img_rgb):
                break
            cursor = (thumb[0] + thumb[1]) // 2
            th = thumb[1] - thumb[0]
            next_y = min(TRACK_BOT, cursor + max(th // 2, 10))
            if next_y <= cursor:
                break
            sb_drag(ctx, cursor, next_y)

        if pass_bought == 0:
            break

    if _manual_purchase_confirmed():
        ctx.cultivate_detail.learn_skill_done = True
        ctx.cultivate_detail.turn_info.turn_learn_skill_done = True
        ctx.ctrl.click_by_point(RETURN_TO_CULTIVATE_FINISH)
        return

    ctx.cultivate_detail.learn_skill_done = True
    ctx.cultivate_detail.turn_info.turn_learn_skill_done = True
    ctx.ctrl.click_by_point(CULTIVATE_LEARN_SKILL_CONFIRM)