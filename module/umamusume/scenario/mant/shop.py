import os
import time
import random
import cv2
import numpy as np
from collections import defaultdict, Counter
from concurrent.futures import ThreadPoolExecutor

import bot.base.log as logger
from bot.recog.ocr import ocr
from rapidfuzz import process, fuzz

log = logger.get_logger(__name__)

SHOP_ROI_Y1 = 440
SHOP_ROI_Y2 = 920
CONTENT_TOP = 440
CONTENT_BOT = 920
CONTENT_X1 = 30
CONTENT_X2 = 640
PURCHASED_CHECK_X1 = 200
PURCHASED_CHECK_X2 = 600
PURCHASED_BRIGHTNESS_THRESHOLD = 180
MANT_SHOP_SCAN_START = 14
MANT_SHOP_SCAN_INTERVAL = 6

SHOP_OPEN_X = 412
SHOP_OPEN_X_SUMMER = 359
SHOP_OPEN_Y = 1125

SB_X = 695
SB_X_MIN = 693
SB_X_MAX = 697
TRACK_TOP = 480
TRACK_BOT = 938
SCREEN_WIDTH = 720

OCR_NAME_X1 = 135
OCR_NAME_X2 = 560
OCR_FUZZY_THRESHOLD = 65

SHOP_ITEM_NAMES = [
    "Speed Notepad", "Stamina Notepad", "Power Notepad", "Guts Notepad", "Wit Notepad",
    "Speed Manual", "Stamina Manual", "Power Manual", "Guts Manual", "Wit Manual",
    "Speed Scroll", "Stamina Scroll", "Power Scroll", "Guts Scroll", "Wit Scroll",
    "Vita 20", "Vita 40", "Vita 65",
    "Royal Kale Juice",
    "Energy Drink MAX", "Energy Drink MAX EX",
    "Plain Cupcake", "Berry Sweet Cupcake",
    "Yummy Cat Food", "Grilled Carrots",
    "Pretty Mirror", "Reporter's Binoculars", "Master Practice Guide", "Scholar's Hat",
    "Fluffy Pillow", "Pocket Planner", "Rich Hand Cream", "Smart Scale",
    "Aroma Diffuser", "Practice Drills DVD", "Miracle Cure",
    "Speed Training Application", "Stamina Training Application",
    "Power Training Application", "Guts Training Application", "Wit Training Application",
    "Reset Whistle",
    "Coaching Megaphone", "Motivating Megaphone", "Empowering Megaphone",
    "Speed Ankle Weights", "Stamina Ankle Weights", "Power Ankle Weights", "Guts Ankle Weights",
    "Good-Luck Charm",
    "Artisan Cleat Hammer", "Master Cleat Hammer",
    "Glow Sticks",
]

def display_to_slug(display_name):
    return display_name.lower().replace("'", '').replace(' ', '_')


EFFECT_PREFIXES = (
    'race ', 'energy +', 'speed +', 'stamina +', 'power +', 'guts +',
    'wisdom +', 'motivation', 'maximum', 'training', 'heal ', 'get ',
    'all ', 'shuffle',
)


def is_shop_scan_turn(date):
    return date >= MANT_SHOP_SCAN_START and (date - MANT_SHOP_SCAN_START) % MANT_SHOP_SCAN_INTERVAL == 0


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


def trigger_scrollbar(ctx):
    y = CONTENT_TOP + random.randint(0, 10)
    ctx.ctrl.execute_adb_shell("shell input swipe 30 " + str(y) + " 30 " + str(y) + " 100", True)
    time.sleep(0.15)


def sb_drag(ctx, from_y, to_y):
    sx = random.randint(SB_X_MIN, SB_X_MAX)
    ex = random.randint(SB_X_MIN, SB_X_MAX)
    dur = random.randint(166, 211)
    ctx.ctrl.execute_adb_shell(
        "shell input swipe " + str(sx) + " " + str(from_y) + " " + str(ex) + " " + str(to_y) + " " + str(dur), True)
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


def _gauss_scan_x():
    mu = SCREEN_WIDTH * 0.667
    sigma = SCREEN_WIDTH * 0.194
    while True:
        v = random.gauss(mu, sigma)
        x = int(round(v))
        if 10 <= x <= SCREEN_WIDTH - 10:
            return x


def is_effect_text(text):
    lower = text.lower()
    return any(lower.startswith(p) for p in EFFECT_PREFIXES)


def classify_items_in_frame(frame):
    name_roi = frame[SHOP_ROI_Y1:SHOP_ROI_Y2, OCR_NAME_X1:OCR_NAME_X2]
    raw = ocr(name_roi, lang="en")

    if not raw or not raw[0]:
        return [], False

    items = []
    seen_y = []

    for entry in raw[0]:
        if not entry or len(entry) < 2:
            continue
        bbox = entry[0]
        text = entry[1][0].strip()
        conf = entry[1][1]
        y_center = (bbox[0][1] + bbox[2][1]) / 2

        if len(text) < 4 or conf < 0.5:
            continue
        lower = text.lower()
        if lower in ('effect', 'cost', 'new', 'turn(s)', '6 turn(s)'):
            continue
        if text.replace('+', '').replace('-', '').replace(' ', '').replace('.', '').isdigit():
            continue
        if text.startswith('+') or text.startswith('-'):
            continue
        if is_effect_text(text):
            continue

        match = process.extractOne(text, SHOP_ITEM_NAMES, scorer=fuzz.ratio, score_cutoff=OCR_FUZZY_THRESHOLD)
        if not match:
            continue

        matched_name, match_score, _ = match
        abs_y = SHOP_ROI_Y1 + y_center

        is_dup = False
        for sy in seen_y:
            if abs(abs_y - sy) < 40:
                is_dup = True
                break
        if is_dup:
            continue

        items.append((matched_name, match_score, abs_y))
        seen_y.append(abs_y)

    items.sort(key=lambda r: r[2])
    return items, False


def dedup_detections(all_detections, captured_frames):
    by_frame = defaultdict(list)
    for key, conf, fi, abs_y in all_detections:
        by_frame[fi].append((key, conf, abs_y))

    sorted_frames = sorted(by_frame.keys())
    if not sorted_frames:
        return []

    cumulative_shift = {sorted_frames[0]: 0}
    for i in range(1, len(sorted_frames)):
        prev_fi = sorted_frames[i - 1]
        curr_fi = sorted_frames[i]

        content_shift = 0
        if prev_fi in captured_frames and curr_fi in captured_frames:
            shift, conf = find_content_shift(captured_frames[prev_fi], captured_frames[curr_fi])
            if conf > 0.85 and shift > 0:
                content_shift = shift

        if content_shift == 0:
            prev_items = [(k, y) for k, c, y in by_frame[prev_fi]]
            curr_items = [(k, y) for k, c, y in by_frame[curr_fi]]
            shifts = []
            used_curr = set()
            for pk, py in prev_items:
                best_shift = None
                best_dist = 9999
                best_ci = -1
                for ci, (ck, cy) in enumerate(curr_items):
                    if ci in used_curr:
                        continue
                    if pk == ck:
                        dist = abs(py - cy)
                        if dist < best_dist:
                            best_dist = dist
                            best_shift = py - cy
                            best_ci = ci
                if best_shift is not None:
                    shifts.append(best_shift)
                    used_curr.add(best_ci)
            if shifts:
                shifts.sort()
                content_shift = shifts[len(shifts) // 2]

        cumulative_shift[curr_fi] = cumulative_shift[prev_fi] + content_shift

    global_detections = []
    for key, conf, fi, abs_y in all_detections:
        global_y = abs_y + cumulative_shift.get(fi, 0)
        global_detections.append((key, conf, fi, global_y))

    global_detections.sort(key=lambda d: d[3])
    position_clusters = []
    for key, conf, fi, gy in global_detections:
        placed = False
        for cluster in position_clusters:
            cluster_gy = sum(d[3] for d in cluster) / len(cluster)
            if abs(gy - cluster_gy) < 80:
                cluster.append((key, conf, fi, gy))
                placed = True
                break
        if not placed:
            position_clusters.append([(key, conf, fi, gy)])

    items_list = []
    for cluster in position_clusters:
        name_counts = Counter()
        name_best_conf = {}
        for k, c, fi, gy in cluster:
            name_counts[k] += 1
            if k not in name_best_conf or c > name_best_conf[k]:
                name_best_conf[k] = c
        winner = max(name_counts.keys(), key=lambda n: (name_counts[n], name_best_conf[n]))
        avg_gy = sum(d[3] for d in cluster) / len(cluster)
        items_list.append((winner, name_best_conf[winner], avg_gy))

    items_list.sort(key=lambda x: x[2])
    return items_list


def scan_mant_shop(ctx):
    from module.umamusume.constants.game_constants import is_summer_camp_period
    current_date = getattr(ctx.cultivate_detail.turn_info, 'date', 0)
    shop_x = SHOP_OPEN_X_SUMMER if is_summer_camp_period(current_date) else SHOP_OPEN_X
    ctx.ctrl.click(shop_x, SHOP_OPEN_Y, "MANT shop open")
    time.sleep(1.5)

    scroll_to_top(ctx)
    trigger_scrollbar(ctx)
    img = ctx.ctrl.get_screen()
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    thumb = find_thumb(img_rgb)

    if thumb is None:
        results, _ = classify_items_in_frame(img)
        items_list = [(key, conf) for key, conf, _ in results]
        log.info("shop items: %s", [n for n, _ in items_list])
        ctx.ctrl.click(95, 1228)
        time.sleep(1)
        return [n for n, _ in items_list]

    thumb_h = thumb[1] - thumb[0]
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
    drag_ratio = 1.1
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

    first_results, _ = classify_items_in_frame(img)
    all_detections = []
    captured_frames = {0: img.copy()}
    for key, conf, abs_y in first_results:
        all_detections.append((key, conf, 0, abs_y))

    scan_x_end = _gauss_scan_x()
    swipe_cmd = "shell input swipe " + str(SB_X) + " " + str(start_y) + " " + str(scan_x_end) + " " + str(TRACK_BOT) + " " + str(swipe_dur)
    proc = ctx.ctrl.execute_adb_shell(swipe_cmd, False)

    time.sleep(0.3)
    prev_frame = img
    scan_deadline = time.time() + 30
    frame_idx = 1

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = []

        while ctx.task.running() and time.time() < scan_deadline:
            time.sleep(0.06)
            curr = ctx.ctrl.get_screen()
            if curr is not None and not content_same(prev_frame, curr):
                captured_frames[frame_idx] = curr.copy()
                f = pool.submit(classify_items_in_frame, curr)
                futures.append((frame_idx, f))
                prev_frame = curr
                frame_idx += 1
            if proc.poll() is not None:
                break

        try:
            proc.terminate()
        except Exception:
            pass

        time.sleep(0.15)
        final = ctx.ctrl.get_screen()
        if final is not None and not content_same(prev_frame, final):
            captured_frames[frame_idx] = final.copy()
            f = pool.submit(classify_items_in_frame, final)
            futures.append((frame_idx, f))

        for fi, f in futures:
            hits, _ = f.result()
            for key, conf, abs_y in hits:
                all_detections.append((key, conf, fi, abs_y))

    items_list = dedup_detections(all_detections, captured_frames)
    log.info("shop items: %s", [(n, round(gy)) for n, _, gy in items_list])

    first_item_gy = items_list[0][2] if items_list else 0

    ctx.ctrl.click(95, 1228)
    time.sleep(1)

    return items_list, ratio, drag_ratio, first_item_gy


CHECKBOX_X = 630
CONFIRM_BTN_X = 360
CONFIRM_BTN_Y = 1050
EXCHANGE_CLOSE_X = 200
EXCHANGE_CLOSE_Y = 1210
BACK_BTN_X = 95
BACK_BTN_Y = 1228


def buy_shop_items(ctx, target_names, items_list, ratio, drag_ratio, first_item_gy):
    from module.umamusume.constants.game_constants import is_summer_camp_period
    current_date = getattr(ctx.cultivate_detail.turn_info, 'date', 0)
    shop_x = SHOP_OPEN_X_SUMMER if is_summer_camp_period(current_date) else SHOP_OPEN_X
    ctx.ctrl.click(shop_x, SHOP_OPEN_Y, "MANT shop open")
    time.sleep(1.5)

    targets = [(name, conf, gy) for name, conf, gy in items_list if name in target_names]
    if not targets:
        log.info("no target items found in shop inventory")
        ctx.ctrl.click(BACK_BTN_X, BACK_BTN_Y)
        time.sleep(1)
        return False

    viewport_center = (CONTENT_TOP + CONTENT_BOT) / 2
    selected = 0

    for name, conf, target_gy in targets:
        scroll_to_top(ctx)
        trigger_scrollbar(ctx)
        img = ctx.ctrl.get_screen()
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        thumb = find_thumb(img_rgb)

        content_offset = (target_gy - first_item_gy) - (viewport_center - CONTENT_TOP - 40)
        if content_offset < 0:
            content_offset = 0
        thumb_target = TRACK_TOP + content_offset / ratio
        thumb_target = int(min(max(thumb_target, TRACK_TOP), TRACK_BOT - 20))

        if thumb:
            current_thumb = (thumb[0] + thumb[1]) // 2
            adjusted_target = int(TRACK_TOP + (thumb_target - TRACK_TOP) * drag_ratio)
            adjusted_target = min(adjusted_target, TRACK_BOT - 10)
            if adjusted_target > current_thumb + 5:
                sb_drag(ctx, current_thumb, adjusted_target)
                trigger_scrollbar(ctx)
                time.sleep(0.3)

        frame = ctx.ctrl.get_screen()
        results, _ = classify_items_in_frame(frame)
        matches = [(k, c, y) for k, c, y in results if k == name]

        if not matches:
            for adj in [20, 40, -20, 60]:
                trigger_scrollbar(ctx)
                img_a = ctx.ctrl.get_screen()
                img_a_rgb = cv2.cvtColor(img_a, cv2.COLOR_BGR2RGB)
                t = find_thumb(img_a_rgb)
                if t:
                    sb_drag(ctx, (t[0] + t[1]) // 2, (t[0] + t[1]) // 2 + adj)
                    trigger_scrollbar(ctx)
                    time.sleep(0.3)
                frame = ctx.ctrl.get_screen()
                results, _ = classify_items_in_frame(frame)
                matches = [(k, c, y) for k, c, y in results if k == name]
                if matches:
                    break

        if not matches:
            log.warning("could not find %s in viewport, aborting buy", name)
            ctx.ctrl.click(BACK_BTN_X, BACK_BTN_Y)
            time.sleep(1)
            return False

        click_y = int(matches[0][2]) + 20
        ctx.ctrl.click(CHECKBOX_X, click_y, "select " + name)
        time.sleep(0.3)
        selected += 1
        log.info("selected %s (%d/%d)", name, selected, len(targets))

    ctx.ctrl.click(CONFIRM_BTN_X, CONFIRM_BTN_Y, "shop confirm")
    time.sleep(2)
    log.info("bought %d items", selected)

    ctx.ctrl.click(BACK_BTN_X, BACK_BTN_Y)
    time.sleep(1)
    return True
