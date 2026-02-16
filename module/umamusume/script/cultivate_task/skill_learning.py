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
from module.umamusume.define import ScenarioType
from module.umamusume.asset.point import (
    RETURN_TO_CULTIVATE_FINISH, CULTIVATE_FINISH_LEARN_SKILL,
    CULTIVATE_FINISH_CONFIRM, CULTIVATE_LEARN_SKILL_CONFIRM,
    FOLLOW_SUPPORT_CARD_SELECT_REFRESH
)
from module.umamusume.asset.template import REF_BORROW_CARD
from module.umamusume.script.cultivate_task.const import SKILL_LEARN_PRIORITY_LIST
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
    return abs(r - 125) <= 5 and abs(g - 120) <= 5 and abs(b - 142) <= 5


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


def trigger_scrollbar(ctx):
    y = 475 + random.randint(0, 10)
    ctx.ctrl.execute_adb_shell("shell input swipe 30 " + str(y) + " 30 " + str(y) + " 100", True)
    time.sleep(0.15)


def scroll_to_top(ctx):
    for _ in range(15):
        trigger_scrollbar(ctx)
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
        trigger_scrollbar(ctx)
        img = ctx.ctrl.get_screen()
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        if at_bottom(img_rgb):
            return
        thumb = find_thumb(img_rgb)
        if thumb is None:
            continue
        sb_drag(ctx, (thumb[0] + thumb[1]) // 2, TRACK_BOT)


def scroll_down_step(ctx):
    sx = 360 + random.randint(-8, 8)
    ctx.ctrl.execute_adb_shell(
        "shell input swipe " + str(sx) + " 850 " + str(sx) + " 500 200", True)
    time.sleep(0.25)


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
        ctx.ctrl.click_by_point(RETURN_TO_CULTIVATE_FINISH)
        return
        
    if ctx.task.detail.manual_purchase_at_end and ctx.cultivate_detail.cultivate_finish:
        log.info("Manual purchase mode enabled - returning to cultivate finish UI")
        ctx.cultivate_detail.manual_purchase_completed = True
        ctx.cultivate_detail.learn_skill_done = True
        ctx.ctrl.click_by_point(RETURN_TO_CULTIVATE_FINISH)
        return
        
    if ctx.cultivate_detail.learn_skill_done:
        log.info("Skills already learned and confirmed - exiting skill learning")
        log.debug(f"learn_skill_done flag was set to True - checking where this happened")
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

    skill_list = []
    scan_skill_positions = {}
    saved_thumb_h = 36
    drag_ratio = 1.1

    scroll_to_top(ctx)
    trigger_scrollbar(ctx)
    img = ctx.ctrl.get_screen()
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    thumb = find_thumb(img_rgb)

    if thumb is not None:
        thumb_h = thumb[1] - thumb[0]
        saved_thumb_h = thumb_h
        thumb_center = (thumb[0] + thumb[1]) // 2
        if thumb[0] > TRACK_TOP:
            sb_drag(ctx, thumb_center, TRACK_TOP)
            trigger_scrollbar(ctx)
            img = ctx.ctrl.get_screen()
            img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            thumb = find_thumb(img_rgb)
            thumb_center = (thumb[0] + thumb[1]) // 2 if thumb else TRACK_TOP + thumb_h // 2

        before_cal = img
        sb_drag(ctx, thumb_center, thumb_center + 5)
        after_cal = ctx.ctrl.get_screen()
        shift_cal, conf_cal = find_content_shift(before_cal, after_cal)
        ratio = shift_cal / 5 if (shift_cal > 0 and conf_cal > 0.85) else 14.0

        trigger_scrollbar(ctx)
        img_dr = ctx.ctrl.get_screen()
        img_dr_rgb = cv2.cvtColor(img_dr, cv2.COLOR_BGR2RGB)
        thumb_cal = find_thumb(img_dr_rgb)
        if thumb_cal:
            cal_from = (thumb_cal[0] + thumb_cal[1]) // 2
            cal_dist = 30
            sb_drag(ctx, cal_from, cal_from + cal_dist)
            trigger_scrollbar(ctx)
            img_dr2 = ctx.ctrl.get_screen()
            img_dr2_rgb = cv2.cvtColor(img_dr2, cv2.COLOR_BGR2RGB)
            thumb_cal2 = find_thumb(img_dr2_rgb)
            if thumb_cal2:
                cal_to = (thumb_cal2[0] + thumb_cal2[1]) // 2
                actual_move = cal_to - cal_from
                if actual_move > 3:
                    drag_ratio = cal_dist / actual_move

        scroll_to_top(ctx)
        trigger_scrollbar(ctx)
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
        proc = ctx.ctrl.execute_adb_shell(swipe_cmd, False)

        t_swipe_start = time.time()
        time.sleep(0.3)
        prev_frame = img
        scan_deadline = time.time() + 30
        frame_times = []
        swipe_dur_s = swipe_dur / 1000.0
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

                time.sleep(0.06)
                curr = ctx.ctrl.get_screen()
                if curr is not None and not content_same(prev_frame, curr):
                    frame_times.append(time.time() - t_swipe_start)
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
                    frame_times.append(time.time() - t_swipe_start)
                    futures.append(executor.submit(get_skill_list, final, learn_skill_list, learn_skill_blacklist))

            for i, f in enumerate(futures):
                frame_skills = f.result()
                progress = min(1.0, frame_times[i] / swipe_dur_s) if i < len(frame_times) else 1.0
                sb_y = start_y + (TRACK_BOT - start_y) * progress
                for s in frame_skills:
                    if s not in skill_list:
                        skill_list.append(s)
                    for key in [s.get('skill_name', ''), s.get('skill_name_raw', '')]:
                        if key and key not in scan_skill_positions:
                            scan_skill_positions[key] = sb_y

        if early_exit:
            ctx.cultivate_detail.learn_skill_done = True
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

    for i in range(len(skill_list)):
        if i != (len(skill_list) - 1) and skill_list[i]["gold"] is True:
            skill_list[i]["subsequent_skill"] = skill_list[i + 1]["skill_name"]

    skill_list = sorted(skill_list, key=lambda x: x["priority"])
    digits_pattern = re.compile(r"\D")
    img = ctx.ctrl.get_screen()
    total_skill_point_text = digits_pattern.sub("", ocr_line(img[400: 440, 490: 665]))
    if total_skill_point_text == "":
        total_skill_point = 0
    else:
        total_skill_point = int(total_skill_point_text)
    
    log.debug(f"Total skill points available: {total_skill_point}")
    log.debug(f"Skills detected: {len(skill_list)}")
    log.debug(f"Priority breakdown: {[skill['priority'] for skill in skill_list]}")
    
    target_skill_list = []
    target_skill_list_raw = []
    curr_point = 0
    
    for priority_level in range(len(learn_skill_list) + 1):
        log.debug(f"Processing priority level {priority_level}")
        
        if (priority_level > 0 and ctx.cultivate_detail.learn_skill_only_user_provided is True and
                not ctx.cultivate_detail.cultivate_finish):
            if priority_level < len(learn_skill_list) and len(learn_skill_list[priority_level]) > 0:
                log.debug(f"Priority {priority_level} has {len(learn_skill_list[priority_level])} skills in preset - processing")
            else:
                log.debug(f"Skipping priority {priority_level} - no skills in preset at this priority")
                continue
            
        priority_skills = sorted(
            [skill for skill in skill_list if skill["priority"] == priority_level and skill["available"] is True],
            key=lambda s: -int(s.get("hint_level", 0))
        )
        log.debug(f"Found {len(priority_skills)} skills at priority {priority_level}")
        
        for skill in priority_skills:
            skill_cost = skill["skill_cost"]
            skill_name = skill["skill_name"]
            skill_name_raw = skill["skill_name_raw"]
            
            if getattr(ctx.cultivate_detail, 'skip_double_circle_unless_high_hint', False):
                if skill.get("is_double_circle", False) and int(skill.get("hint_level", 0)) < 4:
                    continue
            
            log.debug(f"Considering skill '{skill_name}' (cost: {skill_cost}, priority: {priority_level})")
            
            if curr_point + skill_cost <= total_skill_point:
                curr_point += skill_cost
                target_skill_list.append(skill_name)
                target_skill_list_raw.append(skill_name_raw)
                log.info(f"Added skill '{skill_name}' to target list (cost: {skill_cost}, total spent: {curr_point})")
                
                if skill["gold"] is True and skill["subsequent_skill"] != '':
                    for k in range(len(skill_list)):
                        if skill_list[k]["skill_name"] == skill["subsequent_skill"]:
                            skill_list[k]["available"] = False
                            log.debug(f"Disabled subsequent skill '{skill['subsequent_skill']}' due to gold skill")
            else:
                log.debug(f"Cannot afford skill '{skill_name}' (cost: {skill_cost}, available: {total_skill_point - curr_point})")
                break
        
        if len([skill for skill in skill_list if skill["priority"] == priority_level and skill["available"] is True]) > 0:
            if not any(skill["skill_name"] in target_skill_list for skill in skill_list if skill["priority"] == priority_level):
                log.debug(f"Stopping at priority {priority_level} - no affordable skills")
                break
    
    log.info(f"Final target skill list: {target_skill_list}")
    log.info(f"Total skills to learn: {len(target_skill_list)}")
    log.info(f"Total points to spend: {curr_point}")

    if ctx.task.detail.scenario == ScenarioType.SCENARIO_TYPE_URA:
        for skill in target_skill_list:
            ctx.task.detail.scenario_config.ura_config.removeSkillFromList(skill)

    scroll_to_top(ctx)

    for skill in target_skill_list_raw:
        for prioritylist in ctx.cultivate_detail.learn_skill_list:
            if prioritylist.__contains__(skill):
                prioritylist.remove(skill)
    for skill in skill_list:
        for prioritylist in ctx.cultivate_detail.learn_skill_list:
            if skill['available'] is False and prioritylist.__contains__(skill['skill_name_raw']):
                prioritylist.remove(skill['skill_name_raw'])
    ctx.cultivate_detail.learn_skill_list = [x for x in ctx.cultivate_detail.learn_skill_list if x != []]

    if (ctx.task.detail.manual_purchase_at_end and 
        ctx.cultivate_detail.cultivate_finish and 
        hasattr(ctx.cultivate_detail, 'manual_purchase_completed') and 
        ctx.cultivate_detail.manual_purchase_completed):
        log.info("Manual purchase confirmed before skill clicking - returning to finish UI")
        ctx.cultivate_detail.learn_skill_done = True
        ctx.ctrl.click_by_point(RETURN_TO_CULTIVATE_FINISH)
        return

    if len(target_skill_list) == 0:
        ctx.cultivate_detail.learn_skill_done = True
        ctx.cultivate_detail.turn_info.turn_learn_skill_done = True
        ctx.ctrl.click_by_point(RETURN_TO_CULTIVATE_FINISH)
        return
    log.info(f"Starting skill execution for {len(target_skill_list)} skills: {target_skill_list}")
    
    skills_to_process = target_skill_list.copy()

    purchases_made = False

    if len(skills_to_process) > 0 and len(scan_skill_positions) > 0:
        targets_with_pos = []
        for name in skills_to_process[:]:
            pos = scan_skill_positions.get(name)
            if pos is not None:
                targets_with_pos.append((name, pos))
        targets_with_pos.sort(key=lambda x: x[1])

        if targets_with_pos:
            buy_step = max(10, int(saved_thumb_h * 0.7))

            for target_name, target_pos in targets_with_pos:
                if (ctx.task.detail.manual_purchase_at_end and
                    ctx.cultivate_detail.cultivate_finish and
                    hasattr(ctx.cultivate_detail, 'manual_purchase_completed') and
                    ctx.cultivate_detail.manual_purchase_completed):
                    ctx.cultivate_detail.learn_skill_done = True
                    ctx.ctrl.click_by_point(RETURN_TO_CULTIVATE_FINISH)
                    return

                if target_name not in skills_to_process:
                    continue

                target_y = max(TRACK_TOP + saved_thumb_h // 2, min(TRACK_BOT - saved_thumb_h // 2, int(target_pos)))

                trigger_scrollbar(ctx)
                img = ctx.ctrl.get_screen()
                img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                thumb = find_thumb(img_rgb)
                cursor = (thumb[0] + thumb[1]) // 2 if thumb else TRACK_TOP + saved_thumb_h // 2

                if abs(target_y - cursor) > 3:
                    needed = target_y - cursor
                    compensated = int(needed * drag_ratio)
                    end_y = max(TRACK_TOP, min(TRACK_BOT + 20, cursor + compensated))
                    sb_drag(ctx, cursor, end_y)

                img = ctx.ctrl.get_screen()
                if find_skill(ctx, img, skills_to_process, learn_any_skill=False):
                    ctx.cultivate_detail.learn_skill_selected = True
                    purchases_made = True

                if target_name in skills_to_process:
                    for m in range(1, 6):
                        if target_name not in skills_to_process:
                            break
                        for sign in (-1, 1):
                            if target_name not in skills_to_process:
                                break
                            offset = sign * buy_step * m
                            adj = max(TRACK_TOP + saved_thumb_h // 2, min(TRACK_BOT - saved_thumb_h // 2, target_y + offset))

                            trigger_scrollbar(ctx)
                            img = ctx.ctrl.get_screen()
                            img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                            thumb = find_thumb(img_rgb)
                            cursor = (thumb[0] + thumb[1]) // 2 if thumb else target_y

                            if abs(adj - cursor) > 3:
                                needed = adj - cursor
                                compensated = int(needed * drag_ratio)
                                end_y = max(TRACK_TOP, min(TRACK_BOT + 20, cursor + compensated))
                                sb_drag(ctx, cursor, end_y)

                            img = ctx.ctrl.get_screen()
                            if find_skill(ctx, img, skills_to_process, learn_any_skill=False):
                                ctx.cultivate_detail.learn_skill_selected = True
                                purchases_made = True

                if len(skills_to_process) == 0:
                    break

    log.debug("Skills to learn: " + str(ctx.cultivate_detail.learn_skill_list))
    log.debug("Skills learned: " + str([skill['skill_name'] for skill in skill_list if not skill['available']]))

    if (ctx.task.detail.manual_purchase_at_end and 
        ctx.cultivate_detail.cultivate_finish and 
        hasattr(ctx.cultivate_detail, 'manual_purchase_completed') and 
        ctx.cultivate_detail.manual_purchase_completed):
        log.info("Manual purchase confirmed before final confirm - returning to finish UI")
        ctx.cultivate_detail.learn_skill_done = True
        ctx.ctrl.click_by_point(RETURN_TO_CULTIVATE_FINISH)
        return

    if len(target_skill_list) > 0 or len(skill_list) == 0:
        log.info(f"Skill learning completed - processed {len(target_skill_list)} skills out of {len(skill_list)} available")
        ctx.cultivate_detail.learn_skill_done = True
        ctx.cultivate_detail.turn_info.turn_learn_skill_done = True
        if len(target_skill_list) > 0:
            ctx.cultivate_detail.learn_skill_selected = True
    else:
        if ctx.cultivate_detail.learn_skill_only_user_provided:
            log.info(f"User-provided only mode: No skills to learn - all desired skills already learned")
            ctx.cultivate_detail.learn_skill_done = True
            ctx.cultivate_detail.turn_info.turn_learn_skill_done = True
        else:
            all_skills_already_learned = all(skill["priority"] == -1 for skill in skill_list)
            if all_skills_already_learned:
                log.info(f"All desired skills are already learned - marking skill learning as complete")
                ctx.cultivate_detail.learn_skill_done = True
                ctx.cultivate_detail.turn_info.turn_learn_skill_done = True
            else:
                log.warning(f"No skills were processed - learn_skill_done flag not set")
    
    log.info("Skills learned - clicking confirm button first")
    ctx.ctrl.click_by_point(CULTIVATE_LEARN_SKILL_CONFIRM)