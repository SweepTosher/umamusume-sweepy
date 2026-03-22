import time
import re
import random
import cv2
import numpy as np
from collections import defaultdict, Counter
from concurrent.futures import ThreadPoolExecutor

from bot.recog.ocr import ocr
from rapidfuzz import process, fuzz
import bot.base.log as logger

from module.umamusume.scenario.mant.shop import (
    SHOP_ITEM_NAMES, EFFECT_PREFIXES,
    SB_X, SB_X_MIN, SB_X_MAX,
    _gauss_scan_x,
)


log = logger.get_logger(__name__)

INV_TRACK_TOP = 120
INV_TRACK_BOT = 1060
INV_CONTENT_TOP = 90
INV_CONTENT_BOT = 1080
INV_CONTENT_X1 = 30
INV_CONTENT_X2 = 640
SCREEN_WIDTH = 720
OCR_X1 = 60
OCR_X2 = 560
OCR_Y1 = 90
OCR_Y2 = 1080


def inv_find_thumb(img_rgb):
    from module.umamusume.scenario.mant.shop import is_thumb
    top = bot = None
    for y in range(INV_TRACK_TOP, INV_TRACK_BOT + 1):
        r, g, b = int(img_rgb[y, SB_X, 0]), int(img_rgb[y, SB_X, 1]), int(img_rgb[y, SB_X, 2])
        if is_thumb(r, g, b):
            if top is None:
                top = y
            bot = y
    return (top, bot) if top is not None else None


def inv_at_top(img_rgb):
    thumb = inv_find_thumb(img_rgb)
    if thumb is None:
        return False
    return thumb[0] <= INV_TRACK_TOP + 10


def inv_at_bottom(img_rgb):
    from module.umamusume.scenario.mant.shop import is_track
    thumb = inv_find_thumb(img_rgb)
    if thumb is None:
        return True
    for y in range(thumb[1] + 1, INV_TRACK_BOT + 1):
        r, g, b = int(img_rgb[y, SB_X, 0]), int(img_rgb[y, SB_X, 1]), int(img_rgb[y, SB_X, 2])
        if is_track(r, g, b):
            return False
    return True


def inv_content_gray(img):
    return cv2.cvtColor(img[INV_CONTENT_TOP:INV_CONTENT_BOT, INV_CONTENT_X1:INV_CONTENT_X2], cv2.COLOR_BGR2GRAY)


def inv_content_same(before, after):
    b = inv_content_gray(before)
    a = inv_content_gray(after)
    diff = cv2.absdiff(b, a)
    return cv2.mean(diff)[0] < 3


def inv_find_content_shift(before, after):
    bg = inv_content_gray(before)
    ag = inv_content_gray(after)
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
        if inv_at_top(img_rgb):
            return
        thumb = inv_find_thumb(img_rgb)
        if thumb is None:
            continue
        sb_drag(ctx, (thumb[0] + thumb[1]) // 2, INV_TRACK_TOP)


def is_effect_text(text):
    lower = text.lower()
    return any(lower.startswith(p) for p in EFFECT_PREFIXES) or any(
        lower.startswith(p) for p in (
            'support', 'cure', 'max energy', 'fan ',
            'failure', 'increase', 'reroll', 'choose',
        )
    )


def parse_held_qty(text):
    digits = re.sub(r'[^0-9]', '', text)
    if not digits:
        return None
    n = len(digits)
    if n % 2 == 0:
        first_half = digits[:n // 2]
        second_half = digits[n // 2:]
        if first_half == second_half:
            return int(first_half)
    return int(digits)


def classify_names_only(frame):
    roi = frame[OCR_Y1:OCR_Y2, OCR_X1:OCR_X2]
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
        abs_y = OCR_Y1 + y_center
        if len(text) < 3 or conf < 0.4:
            continue
        lower = text.lower()
        if lower in ('held', 'effect', 'cost', 'new', 'turn(s)', 'choose how many to use.',
                      'close', 'confirm use', 'training items', 'confirm', 'cancel'):
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
        matched_name, match_score, _ = match
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
    return items


def read_qty_at(frame, item_y):
    qty_y1 = int(item_y + 28)
    qty_y2 = int(item_y + 58)
    qty_x1 = 240
    qty_x2 = 370
    h, w = frame.shape[:2]
    if qty_y1 < 0 or qty_y2 > h or qty_x1 < 0 or qty_x2 > w:
        return 1
    roi = frame[qty_y1:qty_y2, qty_x1:qty_x2]
    raw = ocr(roi, lang="en")
    if not raw or not raw[0]:
        return 1
    for entry in raw[0]:
        if not entry or len(entry) < 2:
            continue
        text = entry[1][0].strip()
        parsed = parse_held_qty(text)
        if parsed is not None and parsed > 0:
            return parsed
    return 1


def classify_with_qty(frame):
    roi = frame[OCR_Y1:OCR_Y2, OCR_X1:OCR_X2]
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
        abs_y = OCR_Y1 + y_center
        if len(text) < 3 or conf < 0.4:
            continue
        lower = text.lower()
        if lower in ('held', 'effect', 'cost', 'new', 'turn(s)', 'choose how many to use.',
                      'close', 'confirm use', 'training items', 'confirm', 'cancel'):
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
        matched_name, match_score, _ = match
        is_dup = False
        for sy in seen_y:
            if abs(abs_y - sy) < 40:
                is_dup = True
                break
        if is_dup:
            continue
        qty = read_qty_at(frame, abs_y)
        items.append((matched_name, match_score, abs_y, qty))
        seen_y.append(abs_y)
    items.sort(key=lambda r: r[2])
    return items


def dedup_names(all_detections, captured_frames):
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
            shift, conf = inv_find_content_shift(captured_frames[prev_fi], captured_frames[curr_fi])
            if conf > 0.85 and shift > 0:
                content_shift = shift
        if content_shift == 0:
            prev_items = [(k, y) for k, c, y in by_frame[prev_fi]]
            curr_items = [(k, y) for k, c, y in by_frame[curr_fi]]
            shifts = []
            used = set()
            for pk, py in prev_items:
                best_s = None
                best_d = 9999
                best_ci = -1
                for ci, (ck, cy) in enumerate(curr_items):
                    if ci in used or pk != ck:
                        continue
                    dist = abs(py - cy)
                    if dist < best_d:
                        best_d = dist
                        best_s = py - cy
                        best_ci = ci
                if best_s is not None:
                    shifts.append(best_s)
                    used.add(best_ci)
            if shifts:
                shifts.sort()
                content_shift = shifts[len(shifts) // 2]
        cumulative_shift[curr_fi] = cumulative_shift[prev_fi] + content_shift
    global_dets = []
    for key, conf, fi, abs_y in all_detections:
        gy = abs_y + cumulative_shift.get(fi, 0)
        global_dets.append((key, conf, fi, gy))
    global_dets.sort(key=lambda d: d[3])
    clusters = []
    for key, conf, fi, gy in global_dets:
        placed = False
        for cluster in clusters:
            cluster_gy = sum(d[3] for d in cluster) / len(cluster)
            if abs(gy - cluster_gy) < 80:
                cluster.append((key, conf, fi, gy))
                placed = True
                break
        if not placed:
            clusters.append([(key, conf, fi, gy)])
    items_list = []
    for cluster in clusters:
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


def scan_inventory(ctx, stop_when_found=None):
    scroll_to_top(ctx)

    img = ctx.ctrl.get_screen()
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    thumb = inv_find_thumb(img_rgb)

    if thumb is None:
        results = classify_with_qty(img)
        owned = [(name, qty) for name, score, y, qty in results]
        return owned

    thumb_h = thumb[1] - thumb[0]
    thumb_center = (thumb[0] + thumb[1]) // 2
    if thumb[0] > INV_TRACK_TOP + 5:
        sb_drag(ctx, thumb_center, INV_TRACK_TOP)
        img = ctx.ctrl.get_screen()
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        thumb = inv_find_thumb(img_rgb)
        thumb_center = (thumb[0] + thumb[1]) // 2 if thumb else INV_TRACK_TOP + thumb_h // 2

    start_y = thumb_center if thumb else INV_TRACK_TOP + thumb_h // 2 + 5

    before_cal = img
    sb_drag(ctx, thumb_center, thumb_center + 5)
    after_cal = ctx.ctrl.get_screen()
    shift_cal, conf_cal = inv_find_content_shift(before_cal, after_cal)
    ratio = shift_cal / 5 if (shift_cal > 0 and conf_cal > 0.85) else 14.0

    scroll_to_top(ctx)
    img = ctx.ctrl.get_screen()
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    thumb = inv_find_thumb(img_rgb)
    start_y = (thumb[0] + thumb[1]) // 2 if thumb else INV_TRACK_TOP + thumb_h // 2 + 5

    content_h = INV_CONTENT_BOT - INV_CONTENT_TOP
    track_len = INV_TRACK_BOT - INV_TRACK_TOP
    total_content = track_len * ratio + content_h
    desired_overlap = 160
    desired_shift = content_h - desired_overlap
    est_frames = total_content / desired_shift
    swipe_dur = max(5000, min(25000, int(est_frames * 600)))

    first_results = classify_names_only(img)
    all_detections = []
    captured_frames = {0: img.copy()}
    for name, conf, abs_y in first_results:
        all_detections.append((name, conf, 0, abs_y))

    if stop_when_found and any(n == stop_when_found for n, _, _ in first_results):
        items_names = [(stop_when_found, 1.0, 0.0)]
        scroll_to_top(ctx)
        time.sleep(0.3)
        item_qtys = {}
        for _ in range(6):
            frame = ctx.ctrl.get_screen()
            if frame is None:
                time.sleep(0.2)
                continue
            results = classify_with_qty(frame)
            for name, score, y, qty in results:
                if name == stop_when_found and 130 < y < 1030:
                    item_qtys[name] = qty
                    break
            if stop_when_found in item_qtys:
                break
            time.sleep(0.2)
        qty = item_qtys.get(stop_when_found, 1)
        return [(stop_when_found, qty)]

    scan_x_end = _gauss_scan_x()
    swipe_cmd = ("shell input swipe " + str(SB_X) + " " + str(start_y) +
                 " " + str(scan_x_end) + " " + str(INV_TRACK_BOT) + " " + str(swipe_dur))
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
            if curr is not None and not inv_content_same(prev_frame, curr):
                captured_frames[frame_idx] = curr.copy()
                f = pool.submit(classify_names_only, curr)
                futures.append((frame_idx, f))
                prev_frame = curr
                frame_idx += 1
            if proc.poll() is not None:
                break

            if stop_when_found:
                try:
                    hits_now = classify_names_only(curr) if curr is not None else []
                    if any(n == stop_when_found for n, _, _ in hits_now):
                        break
                except Exception:
                    pass
        try:
            proc.terminate()
        except Exception:
            pass
        time.sleep(0.15)
        final = ctx.ctrl.get_screen()
        if final is not None and not inv_content_same(prev_frame, final):
            captured_frames[frame_idx] = final.copy()
            f = pool.submit(classify_names_only, final)
            futures.append((frame_idx, f))
        for fi, f in futures:
            hits = f.result()
            for name, conf, abs_y in hits:
                all_detections.append((name, conf, fi, abs_y))

    items_names = dedup_names(all_detections, captured_frames)

    scroll_to_top(ctx)
    time.sleep(0.3)

    item_qtys = {}
    for step in range(30):
        time.sleep(0.2)
        frame = ctx.ctrl.get_screen()
        img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        results = classify_with_qty(frame)
        for name, score, y, qty in results:
            if name not in item_qtys and 130 < y < 1030:
                item_qtys[name] = qty

        if all(name in item_qtys for name, _, _ in items_names):
            break

        if inv_at_bottom(img_rgb):
            break

        thumb = inv_find_thumb(img_rgb)
        if thumb:
            tc = (thumb[0] + thumb[1]) // 2
            target = min(tc + 60, INV_TRACK_BOT - 10)
            sb_drag(ctx, tc, target)
            time.sleep(0.3)
        else:
            break

    owned = []
    for name, conf, gy in items_names:
        qty = item_qtys.get(name, 1)
        owned.append((name, qty))

    return owned



def is_plus_disabled(frame, plus_x, plus_y):
    h, w = frame.shape[:2]
    x1 = max(0, min(w - 1, plus_x - 14))
    x2 = max(0, min(w, plus_x + 14))
    y1 = max(0, min(h - 1, plus_y - 14))
    y2 = max(0, min(h, plus_y + 14))
    if x2 <= x1 + 2 or y2 <= y1 + 2:
        return False

    patch = frame[y1:y2, x1:x2]
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    s_mean = float(np.mean(hsv[:, :, 1]))
    v_std = float(np.std(hsv[:, :, 2]))

    return s_mean < 35 and v_std < 35


def try_click_item_plus_once(ctx, item_name: str) -> bool:
    def find_item_y_on_current_screen(frame, target_name: str):
        results = classify_names_only(frame)
        for name, score, abs_y in results:
            if name == target_name:
                return abs_y
        return None

    while True:
        frame = ctx.ctrl.get_screen()
        if frame is None:
            time.sleep(0.2)
            continue

        y = find_item_y_on_current_screen(frame, item_name)
        if y is not None and 130 < y < 1030:
            plus_x = 648
            plus_y = int(round(y + 48))

            if is_plus_disabled(frame, plus_x, plus_y):
                return False

            ctx.ctrl.execute_adb_shell(f"shell input tap {plus_x} {plus_y}", True)
            time.sleep(0.25)
            return True

        img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        if inv_at_bottom(img_rgb):
            return False

        thumb = inv_find_thumb(img_rgb)
        if thumb is None:
            return False

        cursor = (thumb[0] + thumb[1]) // 2
        th = thumb[1] - thumb[0]
        next_y = min(INV_TRACK_BOT, cursor + max(th // 2, 10))
        if next_y <= cursor:
            return False
        sb_drag(ctx, cursor, next_y)
        time.sleep(0.25)


def is_on_training_screen(frame):
    if frame is None:
        return False
    from bot.recog.image_matcher import image_match
    from module.umamusume.asset.template import UI_CULTIVATE_TRAINING_SELECT
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return image_match(gray, UI_CULTIVATE_TRAINING_SELECT).find_match


def is_on_main_menu(frame):
    if frame is None:
        return False
    from bot.recog.image_matcher import image_match
    from module.umamusume.asset.template import UI_CULTIVATE_MAIN_MENU
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return image_match(gray, UI_CULTIVATE_MAIN_MENU).find_match


def is_items_panel_open(frame):
    if frame is None:
        return False
    from bot.recog.image_matcher import image_match
    from module.umamusume.asset.template import UI_CULTIVATE_TRAINING_ITEMS
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return image_match(gray, UI_CULTIVATE_TRAINING_ITEMS).find_match


def has_use_training_items_button(frame):
    if frame is None:
        return False
    from bot.recog.image_matcher import image_match
    from module.umamusume.asset.template import UI_CULTIVATE_USE_TRAINING_ITEMS
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return image_match(gray, UI_CULTIVATE_USE_TRAINING_ITEMS).find_match


def open_items_panel(ctx):
    frame = ctx.ctrl.get_screen()
    if is_on_training_screen(frame):
        ctx.ctrl.execute_adb_shell("shell input tap 37 347", True)
    else:
        ctx.ctrl.execute_adb_shell("shell input tap 552 771", True)
    for _ in range(10):
        time.sleep(0.3)
        if is_items_panel_open(ctx.ctrl.get_screen()):
            return


def close_items_panel(ctx):
    for _ in range(10):
        frame = ctx.ctrl.get_screen()
        if not is_items_panel_open(frame) and not has_use_training_items_button(frame):
            return
        ctx.ctrl.execute_adb_shell("shell input tap 200 1205", True)
        time.sleep(0.3)


def use_training_item(ctx, item_name, quantity=1):
    open_items_panel(ctx)

    for _ in range(quantity):
        if not try_click_item_plus_once(ctx, item_name):
            close_items_panel(ctx)
            owned = getattr(ctx.cultivate_detail, 'mant_owned_items', [])
            owned_map = {n: q for n, q in owned}
            if owned_map.get(item_name, 0) > 0:
                owned_map.pop(item_name, None)
                ctx.cultivate_detail.mant_owned_items = [(n, q) for n, q in owned_map.items() if q > 0]
            return False
        time.sleep(0.15)

    ctx.ctrl.execute_adb_shell("shell input tap 530 1205", True)

    clicked_use = False
    for _ in range(20):
        time.sleep(0.17)
        frame = ctx.ctrl.get_screen()
        if has_use_training_items_button(frame):
            ctx.ctrl.execute_adb_shell("shell input tap 530 1205", True)
            clicked_use = True
            time.sleep(0.5)
            continue
        if clicked_use:
            if is_items_panel_open(frame) or not has_use_training_items_button(frame):
                return True
        if not clicked_use and is_items_panel_open(frame):
            ctx.ctrl.execute_adb_shell("shell input tap 530 1205", True)

    return True


INSTANT_USE_ITEMS = [
    'Grilled Carrots',
    'Yummy Cat Food',
    'Pretty Mirror',
    "Scholar's Hat",
    "Reporter's Binoculars",
    'Master Practice Guide',
]

ONE_TIME_BUFF_ITEMS = {
    'Pretty Mirror',
    "Scholar's Hat",
    "Reporter's Binoculars",
    'Master Practice Guide',
}

ENERGY_RECOVERY_ITEMS = {
    'Vita 20', 'Vita 40', 'Vita 65', 'Royal Kale Juice',
    'Energy Drink MAX', 'Energy Drink MAX EX',
}
CHARM_ITEM = 'Good-Luck Charm'
ENERGY_ITEM_SKIP_FAST_PATH_THRESHOLD = 1

ENERGY_ITEMS = {
    'Vita 20': 20,
    'Vita 40': 40,
    'Vita 65': 65,
    'Royal Kale Juice': 100,
}

KALE_MOOD_PENALTY = 20
ENERGY_USE_MAX = 50
ENERGY_RESULT_MIN = 40
ENERGY_SCORE_THRESHOLD = 20

OVERFLOW_PENALTY = {0: 1.0, 1: 0.9, 2: 0.8, 3: 0.8, 4: 0.8}


def calc_effective_energy(item_name, raw_energy, current_energy, period_idx):
    max_energy = 100
    effective = raw_energy
    overflow = max(0, current_energy + raw_energy - max_energy)
    penalty_rate = OVERFLOW_PENALTY.get(period_idx, 0.8)
    effective -= overflow * penalty_rate
    if item_name == 'Royal Kale Juice':
        effective -= KALE_MOOD_PENALTY
    return effective


def pick_best_energy_item(ctx):
    owned = getattr(ctx.cultivate_detail, 'mant_owned_items', [])
    owned_map = {n: q for n, q in owned}
    current_energy = getattr(ctx.cultivate_detail.turn_info, 'cached_energy', 0)
    if current_energy is None:
        return None
    current_energy = int(current_energy)
    if current_energy >= ENERGY_USE_MAX:
        return None

    date = getattr(ctx.cultivate_detail.turn_info, 'date', 0)
    from module.umamusume.constants.game_constants import get_date_period_index
    period_idx = get_date_period_index(date)

    best_item = None
    best_effective = 0
    for item_name, raw_energy in ENERGY_ITEMS.items():
        if owned_map.get(item_name, 0) <= 0:
            continue
        result_energy = current_energy + raw_energy
        if result_energy < ENERGY_RESULT_MIN:
            continue
        effective = calc_effective_energy(item_name, raw_energy, current_energy, period_idx)
        if effective > best_effective:
            best_effective = effective
            best_item = item_name
    if best_effective < ENERGY_SCORE_THRESHOLD:
        return None
    return best_item


def use_item_and_update_inventory(ctx, item_name):
    log.info(f'[ITEM USE ATTEMPT] {item_name}')
    ok = use_training_item(ctx, item_name, 1)
    if not ok:
        log.info(f'[ITEM USE ATTEMPT FAILED] {item_name} not found in inventory')
        return False
    close_items_panel(ctx)
    owned = getattr(ctx.cultivate_detail, 'mant_owned_items', [])
    owned_map = {n: q for n, q in owned}
    owned_map[item_name] = max(0, owned_map.get(item_name, 0) - 1)
    updated = [(n, q) for n, q in owned_map.items() if q > 0]
    ctx.cultivate_detail.mant_owned_items = updated
    from module.umamusume.context import log_detected_items
    log_detected_items(updated)
    log.info(f'[ITEM USED] {item_name}')
    log.info(f'[INVENTORY] after use: {[(n, q) for n, q in updated]}')
    return True


def handle_training_whistle(ctx):
    mant_cfg = getattr(ctx.task.detail.scenario_config, 'mant_config', None)
    if mant_cfg is None:
        return False

    threshold = getattr(mant_cfg, 'whistle_threshold', None)
    if threshold is None:
        return False

    score_history = getattr(ctx.cultivate_detail, 'score_history', [])
    if len(score_history) < 16:
        return False

    scores = getattr(ctx.cultivate_detail.turn_info, 'cached_computed_scores', None)
    if not scores or len(scores) != 5:
        return False

    best_score = max(scores)
    prev = score_history[:-1]
    below_count = sum(1 for s in prev if s < best_score)
    percentile = below_count / len(prev) * 100

    effective_threshold = float(threshold)
    if mant_cfg.whistle_focus_summer:
        date = getattr(ctx.cultivate_detail.turn_info, 'date', 0)
        from module.umamusume.constants.game_constants import is_summer_camp_period
        if is_summer_camp_period(date):
            from module.umamusume.constants.game_constants import CLASSIC_YEAR_END
            if date <= CLASSIC_YEAR_END:
                effective_threshold += mant_cfg.focus_summer_classic
            else:
                effective_threshold += mant_cfg.focus_summer_senior

    if percentile >= effective_threshold:
        return False

    owned = getattr(ctx.cultivate_detail, 'mant_owned_items', [])
    owned_map = {n: q for n, q in owned}
    if owned_map.get('Reset Whistle', 0) <= 0:
        return False

    return use_item_and_update_inventory(ctx, 'Reset Whistle')


def handle_energy_item(ctx):
    item_name = pick_best_energy_item(ctx)
    if item_name is None:
        return False
    ctx.cultivate_detail.turn_info.energy_item_used = True
    return use_item_and_update_inventory(ctx, item_name)


def handle_instant_use_items(ctx):
    from module.umamusume.persistence import mark_buff_used, is_buff_used
    owned = getattr(ctx.cultivate_detail, 'mant_owned_items', [])
    owned_map = {n: q for n, q in owned}

    items_to_use = []
    for item_name in INSTANT_USE_ITEMS:
        qty = owned_map.get(item_name, 0)
        if qty <= 0:
            continue
        if item_name in ONE_TIME_BUFF_ITEMS and is_buff_used(item_name):
            continue
        items_to_use.append(item_name)

    if not items_to_use:
        return False

    open_items_panel(ctx)

    selected = []
    not_found = []
    for item_name in items_to_use:
        log.info(f'[INSTANT ITEM USE ATTEMPT] {item_name}')
        if try_click_item_plus_once(ctx, item_name):
            selected.append(item_name)
            time.sleep(0.15)
        else:
            log.info(f'[INSTANT ITEM USE ATTEMPT FAILED] {item_name} not found in inventory')
            not_found.append(item_name)

    if not_found:
        owned = getattr(ctx.cultivate_detail, 'mant_owned_items', [])
        owned_map = {n: q for n, q in owned}
        for missing in not_found:
            if owned_map.get(missing, 0) > 0:
                owned_map.pop(missing, None)
        ctx.cultivate_detail.mant_owned_items = [(n, q) for n, q in owned_map.items() if q > 0]

    if not selected:
        close_items_panel(ctx)
        return False

    ctx.ctrl.execute_adb_shell("shell input tap 530 1205", True)

    for _ in range(20):
        time.sleep(0.17)
        frame = ctx.ctrl.get_screen()
        if has_use_training_items_button(frame):
            ctx.ctrl.execute_adb_shell("shell input tap 530 1205", True)
            time.sleep(0.5)
            break
        if is_items_panel_open(frame):
            ctx.ctrl.execute_adb_shell("shell input tap 530 1205", True)

    for _ in range(15):
        time.sleep(0.17)
        frame = ctx.ctrl.get_screen()
        if is_items_panel_open(frame):
            break

    close_items_panel(ctx)

    for item_name in selected:
        owned_map[item_name] = max(0, owned_map.get(item_name, 0) - 1)
        if item_name in ONE_TIME_BUFF_ITEMS:
            mark_buff_used(item_name)

    updated = [(n, q) for n, q in owned_map.items() if q > 0]
    ctx.cultivate_detail.mant_owned_items = updated
    from module.umamusume.context import log_detected_items
    log_detected_items(updated)

    for item_name in selected:
        log.info(f'[ITEM USED] {item_name}')
    log.info(f'[INVENTORY] after instant use: {[(n, q) for n, q in updated]}')

    return True


def handle_charm(ctx):
    mant_cfg = getattr(ctx.task.detail.scenario_config, 'mant_config', None)
    if mant_cfg is None:
        return False

    owned = getattr(ctx.cultivate_detail, 'mant_owned_items', [])
    owned_map = {n: q for n, q in owned}
    if owned_map.get('Good-Luck Charm', 0) <= 0:
        return False

    score_history = getattr(ctx.cultivate_detail, 'score_history', [])
    if len(score_history) < 16:
        return False

    scores = getattr(ctx.cultivate_detail.turn_info, 'cached_computed_scores', None)
    if not scores or len(scores) != 5:
        return False

    best_idx = max(range(5), key=lambda i: scores[i])
    best_score = scores[best_idx]

    prev = score_history[:-1]
    below_count = sum(1 for s in prev if s < best_score)
    percentile = below_count / len(prev) * 100

    if percentile <= mant_cfg.charm_threshold:
        return False

    til = ctx.cultivate_detail.turn_info.training_info_list[best_idx]
    fr = int(getattr(til, 'failure_rate', 0))
    if fr < mant_cfg.charm_failure_rate:
        return False

    return use_item_and_update_inventory(ctx, 'Good-Luck Charm')


def rescan_training(ctx):
    ctx.cultivate_detail.turn_info.parse_train_info_finish = False
    ctx.cultivate_detail.turn_info.turn_operation = None
    ctx.cultivate_detail.last_decision_stats = None
    from module.umamusume.asset.point import RETURN_TO_CULTIVATE_MAIN_MENU
    ctx.ctrl.click_by_point(RETURN_TO_CULTIVATE_MAIN_MENU)
    time.sleep(0.5)
    from module.umamusume.asset.point import TO_TRAINING_SELECT
    ctx.ctrl.click_by_point(TO_TRAINING_SELECT)
    time.sleep(0.5)


def has_energy_recovery(ctx):
    owned = getattr(ctx.cultivate_detail, 'mant_owned_items', [])
    owned_map = {n: q for n, q in owned}
    for item_name in ENERGY_ITEMS:
        if owned_map.get(item_name, 0) > 0:
            return True
    return False


def has_charm(ctx):
    owned = getattr(ctx.cultivate_detail, 'mant_owned_items', [])
    owned_map = {n: q for n, q in owned}
    return owned_map.get('Good-Luck Charm', 0) > 0


def has_whistle(ctx):
    owned = getattr(ctx.cultivate_detail, 'mant_owned_items', [])
    owned_map = {n: q for n, q in owned}
    return owned_map.get('Reset Whistle', 0) > 0


def whistle_loop(ctx, start_date):
    while True:
        if not ctx.task.running():
            return
        if getattr(ctx.cultivate_detail.turn_info, 'date', None) != start_date:
            return
        used = handle_training_whistle(ctx)
        if not used:
            return
        time.sleep(0.5)
        rescan_training(ctx)


def has_instant_use_items(ctx):
    from module.umamusume.persistence import is_buff_used
    owned = getattr(ctx.cultivate_detail, 'mant_owned_items', [])
    owned_map = {n: q for n, q in owned}
    for item in INSTANT_USE_ITEMS:
        if owned_map.get(item, 0) <= 0:
            continue
        if item in ONE_TIME_BUFF_ITEMS and is_buff_used(item):
            continue
        return True
    return False


def item_loop(ctx):
    start_date = getattr(ctx.cultivate_detail.turn_info, 'date', None)
    current_energy = getattr(ctx.cultivate_detail.turn_info, 'cached_energy', 0)
    if current_energy is None:
        current_energy = 0
    current_energy = int(current_energy)

    got_recovery = has_energy_recovery(ctx)
    got_charm = has_charm(ctx)
    got_whistle = has_whistle(ctx)

    limit = getattr(ctx.cultivate_detail, 'rest_threshold',
                    getattr(ctx.cultivate_detail, 'rest_treshold', 48))
    energy_low = current_energy <= limit

    if not got_recovery and not got_charm and energy_low:
        log.info(f"Skipping items: low energy ({current_energy}), no recovery, no charm")
        return

    if got_recovery and got_charm:
        charm_used = handle_charm(ctx)
        if charm_used:
            handle_energy_item(ctx)
            return
        handle_energy_item(ctx)
        whistle_loop(ctx, start_date)
        handle_charm(ctx)
        return

    if got_recovery:
        handle_energy_item(ctx)
        whistle_loop(ctx, start_date)
        return

    if got_charm and got_whistle:
        whistle_loop(ctx, start_date)
        handle_charm(ctx)
        return

    if got_charm:
        handle_charm(ctx)
        return

    whistle_loop(ctx, start_date)


def should_skip_fast_path(ctx):
    owned = getattr(ctx.cultivate_detail, 'mant_owned_items', [])
    owned_map = {n: q for n, q in owned}
    if owned_map.get(CHARM_ITEM, 0) > 0:
        return True
    energy_count = sum(owned_map.get(item, 0) for item in ENERGY_RECOVERY_ITEMS)
    if energy_count >= ENERGY_ITEM_SKIP_FAST_PATH_THRESHOLD:
        return True
    return False


def should_skip_race(ctx):
    mant_cfg = getattr(ctx.task.detail.scenario_config, 'mant_config', None)
    if mant_cfg is None:
        return False
    skip_pct = getattr(mant_cfg, 'skip_race_percentile', 0)
    if skip_pct <= 0:
        return False
    pct_hist = getattr(ctx.cultivate_detail, 'percentile_history', [])
    if len(pct_hist) < 16 or not pct_hist:
        return False
    last_pct = pct_hist[-1]
    if last_pct > skip_pct:
        log.info(f"Skipping optional race: percentile {last_pct:.0f}% > threshold {skip_pct}%")
        return True
    return False
