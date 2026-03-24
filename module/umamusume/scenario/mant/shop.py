import os
import re
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
MANT_SHOP_SCAN_START = 13
MANT_SHOP_SCAN_INTERVAL = 3

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

SHOP_ITEM_COSTS = {
    "Speed Notepad": 10, "Stamina Notepad": 10, "Power Notepad": 10, "Guts Notepad": 10, "Wit Notepad": 10,
    "Speed Manual": 15, "Stamina Manual": 15, "Power Manual": 15, "Guts Manual": 15, "Wit Manual": 15,
    "Speed Scroll": 30, "Stamina Scroll": 30, "Power Scroll": 30, "Guts Scroll": 30, "Wit Scroll": 30,
    "Vita 20": 35, "Vita 40": 55, "Vita 65": 75,
    "Royal Kale Juice": 70,
    "Energy Drink MAX": 30, "Energy Drink MAX EX": 50,
    "Plain Cupcake": 30, "Berry Sweet Cupcake": 55,
    "Yummy Cat Food": 10, "Grilled Carrots": 40,
    "Pretty Mirror": 150, "Reporter's Binoculars": 150, "Master Practice Guide": 150, "Scholar's Hat": 280,
    "Fluffy Pillow": 15, "Pocket Planner": 15, "Rich Hand Cream": 15, "Smart Scale": 15,
    "Aroma Diffuser": 15, "Practice Drills DVD": 15, "Miracle Cure": 40,
    "Speed Training Application": 150, "Stamina Training Application": 150,
    "Power Training Application": 150, "Guts Training Application": 150, "Wit Training Application": 150,
    "Reset Whistle": 20,
    "Coaching Megaphone": 40, "Motivating Megaphone": 55, "Empowering Megaphone": 70,
    "Speed Ankle Weights": 50, "Stamina Ankle Weights": 50, "Power Ankle Weights": 50, "Guts Ankle Weights": 50,
    "Good-Luck Charm": 40,
    "Artisan Cleat Hammer": 25, "Master Cleat Hammer": 40,
    "Glow Sticks": 15,
}

SLUG_TO_DISPLAY = {}
for _n in SHOP_ITEM_NAMES:
    SLUG_TO_DISPLAY[_n.lower().replace("'", '').replace(' ', '_')] = _n


def display_to_slug(display_name):
    return display_name.lower().replace("'", '').replace(' ', '_')


EFFECT_PREFIXES = (
    'race ', 'energy +', 'speed +', 'stamina +', 'power +', 'guts +',
    'wisdom +', 'motivation', 'maximum', 'training', 'heal ', 'get ',
    'all ', 'shuffle',
)


def current_shop_chunk(date):
    if date < MANT_SHOP_SCAN_START:
        return -1
    return (date - MANT_SHOP_SCAN_START) // MANT_SHOP_SCAN_INTERVAL


def is_shop_scan_turn(date):
    return date >= MANT_SHOP_SCAN_START


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


def is_purchased(frame, item_y):
    row_y1 = max(0, int(item_y) - 20)
    row_y2 = min(frame.shape[0], int(item_y) + 60)
    roi = frame[row_y1:row_y2, PURCHASED_CHECK_X1:PURCHASED_CHECK_X2]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    return float(cv2.mean(gray)[0]) < PURCHASED_BRIGHTNESS_THRESHOLD


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

        if is_purchased(frame, abs_y):
            continue

        items.append((matched_name, match_score, abs_y))
        seen_y.append(abs_y)

    items.sort(key=lambda r: r[2])
    return items, False


def name_based_shift(by_frame, prev_fi, curr_fi):
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
        return shifts[len(shifts) // 2]
    return 0


def dedup_detections(all_detections, captured_frames):
    by_frame = defaultdict(list)
    for key, conf, fi, abs_y in all_detections:
        by_frame[fi].append((key, conf, abs_y))

    sorted_frames = sorted(by_frame.keys())
    if not sorted_frames:
        return []

    cumulative_shift = {sorted_frames[0]: 0}
    recent_shifts = []
    for i in range(1, len(sorted_frames)):
        prev_fi = sorted_frames[i - 1]
        curr_fi = sorted_frames[i]

        name_shift = name_based_shift(by_frame, prev_fi, curr_fi)

        tmpl_shift = 0
        if prev_fi in captured_frames and curr_fi in captured_frames:
            shift, conf = find_content_shift(captured_frames[prev_fi], captured_frames[curr_fi])
            if conf > 0.85 and shift > 0:
                tmpl_shift = shift

        median_shift = 0
        if recent_shifts:
            rs = sorted(recent_shifts)
            median_shift = rs[len(rs) // 2]

        content_shift = tmpl_shift
        if name_shift > 0:
            if tmpl_shift > 0 and abs(tmpl_shift - name_shift) > 30:
                content_shift = name_shift
            elif tmpl_shift == 0:
                content_shift = name_shift
        if median_shift > 0 and content_shift > median_shift * 2:
            content_shift = name_shift if name_shift > 0 else median_shift

        if content_shift > 0:
            recent_shifts.append(content_shift)

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
    img = ctx.ctrl.get_screen()
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    thumb = find_thumb(img_rgb)

    if thumb is None:
        results, _ = classify_items_in_frame(img)
        items_list = [(key, conf, abs_y) for key, conf, abs_y in results]
        log.info("shop items: %s", [n for n, _, _ in items_list])
        return items_list, 14.0, 1.1, items_list[0][2] if items_list else 0

    thumb_h = thumb[1] - thumb[0]
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
    drag_ratio = 1.1
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

    first_results, _ = classify_items_in_frame(img)
    all_detections = []
    captured_frames = {0: img.copy()}
    for key, conf, abs_y in first_results:
        all_detections.append((key, conf, 0, abs_y))

    shop_debug_dir = os.path.join("scripts", "shop_debug")
    os.makedirs(shop_debug_dir, exist_ok=True)
    import datetime as dt
    ts = dt.datetime.now().strftime("%H%M%S")
    cv2.imwrite(os.path.join(shop_debug_dir, f"shop_{ts}_f0_top.png"), img)

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

    time.sleep(0.2)
    for extra_pass in range(20):
        extra_img = ctx.ctrl.get_screen()
        if extra_img is None:
            break
        extra_rgb = cv2.cvtColor(extra_img, cv2.COLOR_BGR2RGB)
        if at_bottom(extra_rgb):
            if not content_same(prev_frame, extra_img):
                captured_frames[frame_idx] = extra_img.copy()
                hits, _ = classify_items_in_frame(extra_img)
                for key, conf, abs_y in hits:
                    all_detections.append((key, conf, frame_idx, abs_y))
                frame_idx += 1
            break
        extra_thumb = find_thumb(extra_rgb)
        if extra_thumb is None:
            break
        cursor = (extra_thumb[0] + extra_thumb[1]) // 2
        step = max(extra_thumb[1] - extra_thumb[0], 30)
        next_y = min(TRACK_BOT, cursor + step)
        if next_y <= cursor + 3:
            break
        sb_drag(ctx, cursor, next_y)
        time.sleep(0.15)
        after_extra = ctx.ctrl.get_screen()
        if after_extra is not None and not content_same(prev_frame, after_extra):
            captured_frames[frame_idx] = after_extra.copy()
            hits, _ = classify_items_in_frame(after_extra)
            for key, conf, abs_y in hits:
                all_detections.append((key, conf, frame_idx, abs_y))
            prev_frame = after_extra
            frame_idx += 1

    items_list = dedup_detections(all_detections, captured_frames)
    log.info("shop items %d: %s", len(items_list), [(n, round(gy)) for n, _, gy in items_list])

    try:
        last_frame_idx = max(captured_frames.keys())
        cv2.imwrite(os.path.join(shop_debug_dir, f"shop_{ts}_f{last_frame_idx}_bot.png"), captured_frames[last_frame_idx])
        with open(os.path.join(shop_debug_dir, f"shop_{ts}_items.txt"), "w") as df:
            for n, c, gy in items_list:
                df.write(f"{n} (conf={c:.1f}, gy={gy:.0f})\n")
    except Exception:
        pass

    first_item_gy = items_list[0][2] if items_list else 0

    return items_list, ratio, drag_ratio, first_item_gy


EXCHANGE_OCR_Y1 = 170
EXCHANGE_OCR_Y2 = 1040
EXCHANGE_OCR_X1 = 60
EXCHANGE_OCR_X2 = 560
EXCHANGE_PLUS_X = 648
EXCHANGE_PLUS_OFFSET_Y = 38
EXCHANGE_QTY_X1 = 280
EXCHANGE_QTY_X2 = 420

CHECKBOX_X = 630
CHECKBOX_FILL_X1 = 615
CHECKBOX_FILL_X2 = 655
CHECKBOX_FILL_THRESHOLD = 232
CONFIRM_BTN_X = 360
CONFIRM_BTN_Y = 1050
EXCHANGE_CLOSE_X = 200
EXCHANGE_CLOSE_Y = 1210
BACK_BTN_X = 95
BACK_BTN_Y = 1228


RESET_BTN_X = 615
RESET_BTN_Y = 1050

WEBUI_EXCLUDED_PREFIXES = (
    "Speed Notepad", "Stamina Notepad", "Power Notepad", "Guts Notepad", "Wit Notepad",
    "Speed Manual", "Stamina Manual", "Power Manual", "Guts Manual", "Wit Manual",
    "Speed Scroll", "Stamina Scroll", "Power Scroll", "Guts Scroll", "Wit Scroll",
    "Speed Training Application", "Stamina Training Application",
    "Power Training Application", "Guts Training Application", "Wit Training Application",
)



def is_unbuyable(frame, item_y):
    cb_y = int(item_y) + 10
    roi = frame[max(0, cb_y):min(frame.shape[0], cb_y + 10),
                CHECKBOX_FILL_X1:CHECKBOX_FILL_X2]
    if roi.size == 0:
        return False
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    mean_val = float(cv2.mean(gray)[0])
    return mean_val < CHECKBOX_FILL_THRESHOLD


def estimate_screen_y(target_gy, first_item_gy, thumb_pos, ratio):
    content_at_top = first_item_gy - (CONTENT_TOP + 40)
    thumb_offset = (thumb_pos - TRACK_TOP) * ratio if thumb_pos else 0
    scroll_offset = content_at_top + thumb_offset
    return target_gy - scroll_offset


def pick_best_match(matches, target_gy, first_item_gy, thumb_pos, ratio):
    if len(matches) <= 1:
        return matches[0] if matches else None
    expected_y = estimate_screen_y(target_gy, first_item_gy, thumb_pos, ratio)
    return min(matches, key=lambda m: abs(m[2] - expected_y))


def is_item_held_on_exchange(frame, item_y):
    h, w = frame.shape[:2]
    for offset in range(15, 56, 5):
        check_y = int(item_y + offset)
        if check_y < 4 or check_y >= h - 4:
            continue
        patch = frame[check_y - 4:check_y + 4, EXCHANGE_PLUS_X - 4:EXCHANGE_PLUS_X + 4]
        rgb = cv2.cvtColor(patch, cv2.COLOR_BGR2RGB)
        g = float(np.mean(rgb[:, :, 1]))
        r = float(np.mean(rgb[:, :, 0]))
        b = float(np.mean(rgb[:, :, 2]))
        if g > 150 and g > r + 20 and g > b + 20:
            return True
    return False


def read_exchange_qty(frame, item_y):
    h = frame.shape[0]
    regions = [(EXCHANGE_QTY_X1, EXCHANGE_QTY_X2), (170, 380)]
    for x1, x2 in regions:
        for y_off in [25, 30, 20]:
            qty_y1 = int(item_y + y_off)
            qty_y2 = int(item_y + y_off + 35)
            if qty_y1 < 0 or qty_y2 > h:
                continue
            roi = frame[qty_y1:qty_y2, x1:x2]
            raw = ocr(roi, lang="en")
            if not raw or not raw[0]:
                continue
            all_text = ' '.join(entry[1][0] for entry in raw[0] if entry and len(entry) >= 2)
            digits = re.findall(r'\d+', all_text)
            if digits:
                val = int(digits[-1])
                if val < 10:
                    return val
    return -1


def classify_exchange_items(frame):
    roi = frame[EXCHANGE_OCR_Y1:EXCHANGE_OCR_Y2, EXCHANGE_OCR_X1:EXCHANGE_OCR_X2]
    raw = ocr(roi, lang="en")
    if not raw or not raw[0]:
        return []
    items = []
    seen_y = []
    for entry in raw[0]:
        if not entry or len(entry) < 2:
            continue
        bbox = entry[0]
        text = entry[1][0].strip()
        conf = entry[1][1]
        y_center = (bbox[0][1] + bbox[2][1]) / 2
        abs_y = EXCHANGE_OCR_Y1 + y_center
        if len(text) < 3 or conf < 0.4:
            continue
        lower = text.lower()
        if lower in ('held', 'effect', 'cost', 'new', 'turn(s)', 'choose how many to use.',
                      'close', 'confirm use', 'training items', 'confirm', 'cancel',
                      'exchange complete', 'purchased the selected training items.',
                      'automatically used certain training items.'):
            continue
        if text.replace('+', '').replace('-', '').replace(' ', '').replace('.', '').replace('>', '').isdigit():
            continue
        if text.startswith('+') or text.startswith('-'):
            continue
        if is_effect_text(text):
            continue
        if '>' in text or 'held' in lower:
            continue
        match = process.extractOne(text, SHOP_ITEM_NAMES, scorer=fuzz.ratio, score_cutoff=55)
        if not match:
            continue
        matched_name = match[0]
        is_dup = any(abs(abs_y - sy) < 40 for sy in seen_y)
        if is_dup:
            continue
        qty = read_exchange_qty(frame, abs_y)
        if qty >= 0:
            held = qty > 0
        else:
            held = is_item_held_on_exchange(frame, abs_y)
            qty = 1 if held else 0
        items.append((matched_name, held, qty, abs_y))
        seen_y.append(abs_y)
    items.sort(key=lambda r: r[3])
    return items


def scan_exchange_complete(ctx):
    from module.umamusume.scenario.mant.inventory import (
        inv_find_thumb, inv_at_bottom, sb_drag, INV_TRACK_TOP, INV_TRACK_BOT
    )
    detected_items = {}

    frame = ctx.ctrl.get_screen()
    items = classify_exchange_items(frame)
    for name, held, qty, y in items:
        if name not in detected_items:
            detected_items[name] = max(qty, 1)

    img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    thumb = inv_find_thumb(img_rgb)

    if thumb:
        prev_cursor = -1
        stall_count = 0
        for _ in range(25):
            thumb_h = thumb[1] - thumb[0]
            cursor = (thumb[0] + thumb[1]) // 2
            step = max(thumb_h, 30)
            target = min(INV_TRACK_BOT, cursor + step)
            if target <= cursor + 3:
                break
            if prev_cursor >= 0 and abs(cursor - prev_cursor) < 5:
                stall_count += 1
                if stall_count >= 3:
                    break
                target = INV_TRACK_BOT
            else:
                stall_count = 0
            prev_cursor = cursor

            sb_drag(ctx, cursor, target)
            time.sleep(0.3)

            frame = ctx.ctrl.get_screen()
            items = classify_exchange_items(frame)
            for name, held, qty, y in items:
                if name not in detected_items:
                    detected_items[name] = max(qty, 1)

            img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            if inv_at_bottom(img_rgb):
                break
            thumb = inv_find_thumb(img_rgb)
            if not thumb:
                break

    log.info(f"exchange scan: {detected_items}")
    return detected_items


def buy_shop_items(ctx, target_names, items_list, ratio, drag_ratio, first_item_gy):
    remaining = Counter(target_names)
    if not remaining:
        ctx.ctrl.click(BACK_BTN_X, BACK_BTN_Y)
        time.sleep(1)
        return False

    selected = 0
    clicked_positions = set()

    scroll_to_top(ctx)

    img = ctx.ctrl.get_screen()
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    thumb = find_thumb(img_rgb)

    for _ in range(80):
        if not any(v > 0 for v in remaining.values()):
            break

        frame = ctx.ctrl.get_screen()
        results, _ = classify_items_in_frame(frame)

        for item_name, conf, abs_y in results:
            if remaining.get(item_name, 0) <= 0:
                continue
            pos_key = int(abs_y) // 30
            if pos_key in clicked_positions:
                continue
            if is_unbuyable(frame, abs_y):
                continue

            click_y = int(abs_y) + 20
            ctx.ctrl.click(CHECKBOX_X, click_y)
            time.sleep(0.3)
            selected += 1
            remaining[item_name] -= 1
            clicked_positions.add(pos_key)
            log.debug(f"Checked '{item_name}' at y={abs_y:.0f}, remaining={remaining[item_name]}")

        img = ctx.ctrl.get_screen()
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        if at_bottom(img_rgb):
            if any(v > 0 for v in remaining.values()):
                clicked_positions.clear()
                frame = ctx.ctrl.get_screen()
                results, _ = classify_items_in_frame(frame)
                for item_name, conf, abs_y in results:
                    if remaining.get(item_name, 0) <= 0:
                        continue
                    if is_unbuyable(frame, abs_y):
                        continue
                    click_y = int(abs_y) + 20
                    ctx.ctrl.click(CHECKBOX_X, click_y)
                    time.sleep(0.3)
                    selected += 1
                    remaining[item_name] -= 1
                    log.debug(f"Bottom-edge: checked '{item_name}' at y={abs_y:.0f}")
            break

        thumb = find_thumb(img_rgb)
        if thumb is None:
            break
        cursor = (thumb[0] + thumb[1]) // 2
        th = thumb[1] - thumb[0]
        step = max(th, 30)
        next_y = min(TRACK_BOT, cursor + step)
        if next_y <= cursor + 3:
            break
        sb_drag(ctx, cursor, next_y)
        time.sleep(0.2)
        clicked_positions.clear()

    if selected == 0:
        return False, {}

    ctx.ctrl.click(CONFIRM_BTN_X, CONFIRM_BTN_Y)

    from bot.recog.image_matcher import image_match
    from bot.recog.ocr import ocr_line
    from module.umamusume.asset.template import UI_INFO
    from module.umamusume.script.cultivate_task.info import find_similar_text
    exchange_ready = False
    for _ in range(40):
        time.sleep(0.3)
        screen = ctx.ctrl.get_screen(to_gray=True)
        result = image_match(screen, UI_INFO)
        if result.find_match:
            pos = result.matched_area
            title_img = screen[pos[0][1] - 5:pos[1][1] + 5, pos[0][0] + 150:pos[1][0] + 405]
            title_text = ocr_line(title_img)
            title_text = find_similar_text(title_text, ["Exchange Complete"], 0.7)
            if title_text == "Exchange Complete":
                exchange_ready = True
                break

    held_items = {}
    if exchange_ready:
        held_items = scan_exchange_complete(ctx)

    ctx.ctrl.click(EXCHANGE_CLOSE_X, EXCHANGE_CLOSE_Y)
    time.sleep(0.5)

    ctx.ctrl.click(BACK_BTN_X, BACK_BTN_Y)
    time.sleep(0.5)

    return True, held_items
