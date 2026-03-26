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
OCR_Y1 = 50
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
    try:
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
        _, thr = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        roi_ocr = cv2.cvtColor(thr, cv2.COLOR_GRAY2BGR)
    except Exception:
        roi_ocr = roi

    raw = ocr(roi_ocr, lang="en")
    if not raw or not raw[0]:
        return 1
    for entry in raw[0]:
        if not entry or len(entry) < 2:
            continue
        text = entry[1][0].strip()
        parsed = parse_held_qty(text)
        if parsed is None:
            continue
        if parsed <= 0:
            continue
        if parsed > 9:
            continue
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
    time.sleep(0.3)

    img = ctx.ctrl.get_screen()
    if img is None:
        return []

    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    thumb = inv_find_thumb(img_rgb)

    if thumb is None:
        results = classify_with_qty(img)
        owned = [(name, qty) for name, score, y, qty in results if 130 < y < 1030]
        owned.sort(key=lambda x: x[0])
        return owned

    thumb_h = thumb[1] - thumb[0]
    start_y = (thumb[0] + thumb[1]) // 2

    scan_x_end = _gauss_scan_x()
    swipe_dur = 12000
    swipe_cmd = f"shell input swipe {SB_X} {start_y} {scan_x_end} {INV_TRACK_BOT} {swipe_dur}"
    proc = ctx.ctrl.execute_adb_shell(swipe_cmd, False)

    item_qtys = {}
    scan_deadline = time.time() + 40

    results = classify_with_qty(img)
    for name, score, y, qty in results:
        if 130 < y < 1030 and (name not in item_qtys or qty > item_qtys[name]):
            item_qtys[name] = qty
    if stop_when_found and any(n == stop_when_found for n, _, _, _ in results):
        try:
            proc.terminate()
        except Exception:
            pass
        owned = [(name, qty) for name, qty in item_qtys.items()]
        owned.sort(key=lambda x: x[0])
        scroll_to_top(ctx)
        return owned

    while ctx.task.running() and time.time() < scan_deadline:
        time.sleep(0.08)
        frame = ctx.ctrl.get_screen()
        if frame is None:
            if proc.poll() is not None:
                break
            continue

        results = classify_with_qty(frame)
        for name, score, y, qty in results:
            if 130 < y < 1030 and (name not in item_qtys or qty > item_qtys[name]):
                item_qtys[name] = qty

        if stop_when_found and any(n == stop_when_found for n, _, _, _ in results):
            break

        if proc.poll() is not None:
            break

    try:
        proc.terminate()
    except Exception:
        pass

    prev_cursor = -1
    stall_count = 0
    for _ in range(20):
        if not ctx.task.running():
            break
        time.sleep(0.18)
        frame = ctx.ctrl.get_screen()
        if frame is None:
            continue

        results = classify_with_qty(frame)
        for name, score, y, qty in results:
            if 130 < y < 1030 and (name not in item_qtys or qty > item_qtys[name]):
                item_qtys[name] = qty

        img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        if inv_at_bottom(img_rgb):
            break

        thumb = inv_find_thumb(img_rgb)
        if thumb is None:
            break

        cursor = (thumb[0] + thumb[1]) // 2
        if prev_cursor >= 0 and abs(cursor - prev_cursor) < 5:
            stall_count += 1
            if stall_count >= 3:
                sb_drag(ctx, cursor, INV_TRACK_BOT)
        else:
            stall_count = 0
        prev_cursor = cursor

        step = max(thumb[1] - thumb[0], 30)
        target = min(INV_TRACK_BOT, cursor + step)
        if target <= cursor + 3:
            break
        sb_drag(ctx, cursor, target)

    owned = [(name, qty) for name, qty in item_qtys.items()]
    owned.sort(key=lambda x: x[0])
    scroll_to_top(ctx)
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
        next_y = min(INV_TRACK_BOT, cursor + max(th, 30))
        if next_y <= cursor + 3:
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


def find_training_items_button(frame):
    if frame is None:
        return None
    from bot.recog.image_matcher import image_match
    from module.umamusume.asset.template import REF_TRAINING_ITEMS_BTN
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    result = image_match(gray, REF_TRAINING_ITEMS_BTN)
    if result.find_match and result.center_point:
        return result.center_point
    return None


def open_items_panel(ctx):
    frame = ctx.ctrl.get_screen()
    btn = find_training_items_button(frame)
    if btn:
        ctx.ctrl.click(int(btn[0]), int(btn[1]), "Training Items button")
    elif is_on_training_screen(frame):
        ctx.ctrl.click(37, 347, "Training Items fallback (training)")
    else:
        ctx.ctrl.click(552, 771, "Training Items fallback (menu)")
    for _ in range(10):
        time.sleep(0.3)
        if is_items_panel_open(ctx.ctrl.get_screen()):
            return True
    return False


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
    'Energy Drink MAX EX',
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


LOW_ENERGY_THRESHOLD = 5
MAX_ENERGY = 100


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


def plan_low_energy_recovery(current_energy, owned_map):
    available = []
    for item_name, raw_energy in sorted(ENERGY_ITEMS.items(), key=lambda x: x[1]):
        qty = owned_map.get(item_name, 0)
        if qty > 0:
            available.append((item_name, raw_energy, qty))

    if not available:
        return []

    plan = []
    energy = current_energy

    for item_name, raw_energy, qty in reversed(available):
        if energy >= MAX_ENERGY:
            break
        while qty > 0 and energy + raw_energy <= MAX_ENERGY:
            plan.append(item_name)
            energy += raw_energy
            qty -= 1

    if not plan:
        smallest = available[0]
        plan.append(smallest[0])

    result = []
    seen = {}
    for name in plan:
        if name not in seen:
            seen[name] = 0
        seen[name] += 1
    for name, count in seen.items():
        result.append((name, count))

    return result


def use_item_and_update_inventory(ctx, item_name):
    ok = use_training_item(ctx, item_name, 1)
    if not ok:
        return False
    close_items_panel(ctx)
    owned = getattr(ctx.cultivate_detail, 'mant_owned_items', [])
    owned_map = {n: q for n, q in owned}
    owned_map[item_name] = max(0, owned_map.get(item_name, 0) - 1)
    updated = [(n, q) for n, q in owned_map.items() if q > 0]
    ctx.cultivate_detail.mant_owned_items = updated
    from module.umamusume.context import log_detected_items
    log_detected_items(updated)
    log.info(f"used {item_name}")
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

    scores = getattr(ctx.cultivate_detail.turn_info, 'cached_original_scores', None)
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


def handle_energy_recovery(ctx):
    current_energy = getattr(ctx.cultivate_detail.turn_info, 'cached_energy', None)
    if current_energy is None:
        return False
    current_energy = int(current_energy)

    limit = getattr(ctx.cultivate_detail, 'rest_threshold',
                    getattr(ctx.cultivate_detail, 'rest_treshold', 48))

    owned = getattr(ctx.cultivate_detail, 'mant_owned_items', [])
    owned_map = {n: q for n, q in owned}

    available = []
    for item_name, raw_energy in sorted(ENERGY_ITEMS.items(), key=lambda x: x[1], reverse=True):
        qty = owned_map.get(item_name, 0)
        if qty > 0:
            available.append((item_name, raw_energy, qty))

    if not available:
        return False

    energy = current_energy
    used_any = False
    for item_name, raw_energy, qty in available:
        while qty > 0 and energy <= limit:
            if energy + raw_energy > MAX_ENERGY:
                break
            ok = use_item_and_update_inventory(ctx, item_name)
            if not ok:
                break
            energy += raw_energy
            qty -= 1
            used_any = True
        if energy > limit:
            break

    if not used_any:
        smallest = available[-1]
        ok = use_item_and_update_inventory(ctx, smallest[0])
        if ok:
            used_any = True

    if used_any:
        ctx.cultivate_detail.turn_info.parse_main_menu_finish = False
    return used_any


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
        if try_click_item_plus_once(ctx, item_name):
            selected.append(item_name)
            time.sleep(0.15)
        else:
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

    log.info(f"used instant items: {selected}")

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

    scores = getattr(ctx.cultivate_detail.turn_info, 'cached_original_scores', None)
    if not scores or len(scores) != 5:
        return False

    best_idx = max(range(5), key=lambda i: scores[i])
    best_score = scores[best_idx]

    prev = score_history[:-1]
    below_count = sum(1 for s in prev if s < best_score)
    percentile = below_count / len(prev) * 100

    charm_threshold = getattr(mant_cfg, 'charm_threshold', 80)

    if percentile <= charm_threshold:
        return False

    til = ctx.cultivate_detail.turn_info.training_info_list[best_idx]
    fr = int(getattr(til, 'failure_rate', 0))
    charm_failure_rate = getattr(mant_cfg, 'charm_failure_rate', 10)
    if fr < charm_failure_rate:
        return False

    return use_item_and_update_inventory(ctx, 'Good-Luck Charm')


def rescan_training(ctx):
    close_items_panel(ctx)
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


def handle_cupcake_use(ctx):
    from bot.conn.fetch import read_mood
    from module.umamusume.scenario.mant.constants import get_incoming_mood

    mood = read_mood(ctx.current_screen)
    if mood is None or mood >= 5:
        return False

    date = getattr(ctx.cultivate_detail.turn_info, 'date', 0)
    incoming = get_incoming_mood(date, 3)
    owned = {n: q for n, q in getattr(ctx.cultivate_detail, 'mant_owned_items', [])}


    for name, boost in [('Berry Sweet Cupcake', 2), ('Plain Cupcake', 1)]:
        if owned.get(name, 0) <= 0:
            continue
        if mood + boost + incoming > 5:
            continue
        if use_item_and_update_inventory(ctx, name):
            ctx.cultivate_detail.turn_info.parse_main_menu_finish = False
            return True
    return False


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


MEGAPHONE_TIERS = {
    'Coaching Megaphone': (1, 4),
    'Motivating Megaphone': (2, 3),
    'Empowering Megaphone': (3, 2),
}

MEGAPHONE_CONFIG_KEYS = {
    1: 'mega_small_threshold',
    2: 'mega_medium_threshold',
    3: 'mega_large_threshold',
}

TRAINING_TYPE_ANKLET = {
    1: 'Speed Ankle Weights',
    2: 'Stamina Ankle Weights',
    3: 'Power Ankle Weights',
    4: 'Guts Ankle Weights',
}


def get_best_percentile(ctx):
    scores = getattr(ctx.cultivate_detail.turn_info, 'cached_original_scores', None)
    if not scores or len(scores) != 5:
        return None
    score_history = getattr(ctx.cultivate_detail, 'score_history', [])
    if len(score_history) < 16:
        return None
    best_score = max(scores)
    prev = score_history[:-1]
    below_count = sum(1 for s in prev if s < best_score)
    return below_count / len(prev) * 100


MEGA_STAT_MULT = {1: 1.20, 2: 1.40, 3: 1.60}


def count_races_in_window(ctx, duration):
    current_date = getattr(ctx.cultivate_detail.turn_info, 'date', 0)
    extra_races = getattr(ctx.cultivate_detail, 'extra_race_list', [])
    if not extra_races:
        return 0
    from module.umamusume.asset.race_data import get_races_for_period
    count = 0
    for offset in range(1, duration):
        future_date = current_date + offset
        available = get_races_for_period(future_date)
        if any(r in available for r in extra_races):
            count += 1
    return count


MANT_CLIMAX_START = 73
MANT_CLIMAX_TRAINING_TURNS = [73, 75, 77]


def remaining_training_turns(date):
    if date >= MANT_CLIMAX_START:
        return sum(1 for t in MANT_CLIMAX_TRAINING_TURNS if t >= date)
    return (MANT_CLIMAX_START - date) + len(MANT_CLIMAX_TRAINING_TURNS)


def total_megaphone_turns(owned_map):
    total = 0
    for name, (tier, duration) in MEGAPHONE_TIERS.items():
        qty = owned_map.get(name, 0)
        total += qty * duration
    return total


def handle_megaphone_endgame(ctx):
    owned = getattr(ctx.cultivate_detail, 'mant_owned_items', [])
    owned_map = {n: q for n, q in owned}
    date = getattr(ctx.cultivate_detail.turn_info, 'date', 0)
    active_tier = getattr(ctx.cultivate_detail, 'mant_megaphone_tier', 0)
    active_turns = getattr(ctx.cultivate_detail, 'mant_megaphone_turns', 0)

    if date >= MANT_CLIMAX_START and date not in MANT_CLIMAX_TRAINING_TURNS:
        return False

    remaining = remaining_training_turns(date)
    mega_turns = total_megaphone_turns(owned_map)
    if mega_turns <= remaining:
        return False

    for name, (tier, duration) in sorted(MEGAPHONE_TIERS.items(), key=lambda x: x[1][0]):
        if owned_map.get(name, 0) <= 0:
            continue
        if active_turns > 0 and active_tier > 0 and tier <= active_tier:
            continue
        ok = use_item_and_update_inventory(ctx, name)
        if ok:
            ctx.cultivate_detail.mant_megaphone_tier = tier
            ctx.cultivate_detail.mant_megaphone_turns = duration
            log.info(f"endgame megaphone dump: tier {tier} for {duration} turns")
        return ok

    return False


def handle_megaphone(ctx):
    mant_cfg = getattr(ctx.task.detail.scenario_config, 'mant_config', None)
    if mant_cfg is None:
        return False

    date = getattr(ctx.cultivate_detail.turn_info, 'date', 0)
    if date >= MANT_CLIMAX_START and date not in MANT_CLIMAX_TRAINING_TURNS:
        return False

    if handle_megaphone_endgame(ctx):
        return True

    percentile = get_best_percentile(ctx)
    if percentile is None:
        return False

    owned = getattr(ctx.cultivate_detail, 'mant_owned_items', [])
    owned_map = {n: q for n, q in owned}

    active_tier = getattr(ctx.cultivate_detail, 'mant_megaphone_tier', 0)
    active_turns = getattr(ctx.cultivate_detail, 'mant_megaphone_turns', 0)

    from module.umamusume.constants.game_constants import is_summer_camp_period
    is_summer = is_summer_camp_period(date)
    summer_bonus = getattr(mant_cfg, 'mega_summer_bonus', 10)
    race_penalty = getattr(mant_cfg, 'mega_race_penalty', 5)

    has_higher = {}
    for name, (tier, _) in MEGAPHONE_TIERS.items():
        for other_name, (other_tier, _) in MEGAPHONE_TIERS.items():
            if other_tier > tier and owned_map.get(other_name, 0) > 0:
                has_higher[tier] = True
                break

    best_mega = None
    best_tier = 0
    for name, (tier, duration) in sorted(MEGAPHONE_TIERS.items(), key=lambda x: -x[1][0]):
        if owned_map.get(name, 0) <= 0:
            continue
        cfg_key = MEGAPHONE_CONFIG_KEYS[tier]
        base_threshold = getattr(mant_cfg, cfg_key, 50)

        threshold = base_threshold

        if active_turns > 0 and active_tier > 0:
            tier_diff = tier - active_tier
            if tier_diff <= 0:
                continue
            upgrade_bonus = 7 if tier_diff == 1 else 15
            threshold += upgrade_bonus

        extra_qty = owned_map.get(name, 0) - 1
        if extra_qty > 0:
            threshold -= extra_qty * 5

        if has_higher.get(tier, False):
            threshold -= 5

        races_in_window = count_races_in_window(ctx, duration)
        threshold += races_in_window * race_penalty

        if is_summer:
            threshold -= summer_bonus

        if percentile >= threshold:
            best_mega = name
            best_tier = tier
            break

    if best_mega is None:
        return False

    _, duration = MEGAPHONE_TIERS[best_mega]
    ok = use_item_and_update_inventory(ctx, best_mega)
    if ok:
        ctx.cultivate_detail.mant_megaphone_tier = best_tier
        ctx.cultivate_detail.mant_megaphone_turns = duration
        log.info(f"megaphone active: tier {best_tier} for {duration} turns")
    return ok


def handle_anklet(ctx):
    mant_cfg = getattr(ctx.task.detail.scenario_config, 'mant_config', None)
    if mant_cfg is None:
        return False

    percentile = get_best_percentile(ctx)
    if percentile is None:
        return False

    threshold = getattr(mant_cfg, 'training_weights_threshold', 60)
    if percentile < threshold:
        return False

    op = getattr(ctx.cultivate_detail.turn_info, 'turn_operation', None)
    if op is None:
        return False
    training_type = getattr(op, 'training_type', None)
    if training_type is None:
        return False
    training_val = training_type.value if hasattr(training_type, 'value') else int(training_type)

    anklet_name = TRAINING_TYPE_ANKLET.get(training_val)
    if anklet_name is None:
        return False

    owned = getattr(ctx.cultivate_detail, 'mant_owned_items', [])
    owned_map = {n: q for n, q in owned}
    if owned_map.get(anklet_name, 0) <= 0:
        return False

    return use_item_and_update_inventory(ctx, anklet_name)


def tick_megaphone(ctx):
    active_turns = getattr(ctx.cultivate_detail, 'mant_megaphone_turns', 0)
    if active_turns > 0:
        active_turns -= 1
        ctx.cultivate_detail.mant_megaphone_turns = active_turns
        if active_turns <= 0:
            ctx.cultivate_detail.mant_megaphone_tier = 0


def item_loop(ctx):
    start_date = getattr(ctx.cultivate_detail.turn_info, 'date', None)

    got_charm = has_charm(ctx)
    got_whistle = has_whistle(ctx)
    got_energy = has_energy_recovery(ctx)

    if got_charm and got_whistle:
        whistle_loop(ctx, start_date)
        handle_charm(ctx)
    elif got_charm:
        handle_charm(ctx)
    elif got_whistle and got_energy:
        whistle_loop(ctx, start_date)

    handle_megaphone(ctx)
    handle_anklet(ctx)
    

def should_skip_fast_path(ctx):
    owned = getattr(ctx.cultivate_detail, 'mant_owned_items', [])
    owned_map = {n: q for n, q in owned}
    has_charm_item = owned_map.get(CHARM_ITEM, 0) > 0
    energy_count = sum(owned_map.get(item, 0) for item in ENERGY_RECOVERY_ITEMS)
    if has_charm_item:
        return True
    if energy_count >= ENERGY_ITEM_SKIP_FAST_PATH_THRESHOLD:
        return True
    return False


def handle_energy_drink_max_before_race(ctx):
    owned = getattr(ctx.cultivate_detail, 'mant_owned_items', [])
    owned_map = {n: q for n, q in owned}
    if owned_map.get('Energy Drink MAX', 0) <= 0:
        return False
    current_energy = getattr(ctx.cultivate_detail.turn_info, 'cached_energy', None)
    if current_energy is None:
        return False
    if int(current_energy) > 1:
        return False
    return use_item_and_update_inventory(ctx, 'Energy Drink MAX')


def handle_glow_sticks_before_race(ctx):
    owned = getattr(ctx.cultivate_detail, 'mant_owned_items', [])
    owned_map = {n: q for n, q in owned}
    if owned_map.get('Glow Sticks', 0) <= 0:
        return False
    return use_item_and_update_inventory(ctx, 'Glow Sticks')


MANT_CLIMAX_RACE_TURNS = [74, 76, 78]


def remaining_climax_races(date):
    return sum(1 for t in MANT_CLIMAX_RACE_TURNS if t >= date)


def handle_cleat_before_race(ctx, race_id, is_climax_override=False):
    from module.umamusume.asset.race_data import is_g1_race
    owned = getattr(ctx.cultivate_detail, 'mant_owned_items', [])
    owned_map = {n: q for n, q in owned}
    date = getattr(ctx.cultivate_detail.turn_info, 'date', 0)

    master_qty = owned_map.get('Master Cleat Hammer', 0)
    artisan_qty = owned_map.get('Artisan Cleat Hammer', 0)
    is_climax_race = is_climax_override or date in MANT_CLIMAX_RACE_TURNS

    if is_climax_race:
        if master_qty > 0:
            return use_item_and_update_inventory(ctx, 'Master Cleat Hammer')
        elif artisan_qty > 0:
            return use_item_and_update_inventory(ctx, 'Artisan Cleat Hammer')
        return False

    races_left = remaining_climax_races(date)
    master_reserve = min(races_left, master_qty)
    artisan_reserve = max(0, races_left - master_reserve)
    master_spare = master_qty - master_reserve
    artisan_spare = artisan_qty - artisan_reserve

    if is_g1_race(race_id):
        if master_spare > 0:
            return use_item_and_update_inventory(ctx, 'Master Cleat Hammer')
        elif artisan_spare > 0:
            return use_item_and_update_inventory(ctx, 'Artisan Cleat Hammer')
        return False
    else:
        if artisan_spare > 0:
            return use_item_and_update_inventory(ctx, 'Artisan Cleat Hammer')
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

    active_tier = getattr(ctx.cultivate_detail, 'mant_megaphone_tier', 0)
    active_turns = getattr(ctx.cultivate_detail, 'mant_megaphone_turns', 0)
    effective_skip_pct = skip_pct
    if active_turns > 0 and active_tier > 0:
        mega_mult = MEGA_STAT_MULT.get(active_tier, 1.0)
        bonus_pct = (mega_mult - 1.0) * 100
        effective_skip_pct = max(0, skip_pct - bonus_pct)

    if last_pct > effective_skip_pct:
        log.info(f"skipping optional race: percentile {last_pct:.0f}% > threshold {effective_skip_pct:.0f}%"
                 + (f" (megaphone t{active_tier} active)" if active_tier > 0 else ""))
        return True
    return False
