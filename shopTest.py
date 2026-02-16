import os
import cv2
import time
import random
import subprocess
import numpy as np
from module.umamusume.asset.template import MANT_SHOP_TEMPLATES

ADB_DEVICE = "127.0.0.1:5557"

TRACK_TOP = 479
TRACK_BOT = 938
SB_X = 696
SB_X_MIN = 693
SB_X_MAX = 699
SHOP_ROI_X1 = 30
SHOP_ROI_X2 = 140
SHOP_ROI_Y1 = 440
SHOP_ROI_Y2 = 920
SAFE_Y_MIN = 500
SAFE_Y_MAX = 860
MATCH_THRESHOLD = 0.82
POSITION_MERGE_PX = 40
MAX_SCROLL_ATTEMPTS = 20
ADB_DELAY = 0.38
BUY_OFFSET_X = 533

def adb_cmd(args, wait=True):
    cmd = f"adb -s {ADB_DEVICE} {args}"
    if wait:
        return subprocess.run(cmd, shell=True, capture_output=True)
    return subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

def adb_screenshot():
    adb_cmd("shell screencap -p /sdcard/mant_scan.png")
    adb_cmd("pull /sdcard/mant_scan.png mant_scan_tmp.png")
    img = cv2.imread("mant_scan_tmp.png")
    try:
        os.remove("mant_scan_tmp.png")
    except OSError:
        pass
    return img

def tap(x, y):
    x += int(max(-8, min(8, random.gauss(0, 3))))
    y += int(max(-8, min(8, random.gauss(0, 3))))
    x = max(1, min(719, x))
    y = max(1, min(1279, y))
    duration = int(max(50, min(180, random.gauss(90, 30))))
    drift_x = x + random.randint(-3, 3)
    drift_y = y + random.randint(-3, 3)
    adb_cmd(f"shell input swipe {x} {y} {drift_x} {drift_y} {duration}")
    time.sleep(ADB_DELAY)

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
    return cv2.cvtColor(img[SHOP_ROI_Y1:SHOP_ROI_Y2, SHOP_ROI_X1:SHOP_ROI_X2], cv2.COLOR_BGR2GRAY)

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

def sb_drag(from_y, to_y):
    sx = random.randint(SB_X_MIN, SB_X_MAX)
    ex = random.randint(SB_X_MIN, SB_X_MAX)
    dur = random.randint(166, 211)
    adb_cmd(f"shell input swipe {sx} {from_y} {ex} {to_y} {dur}")
    time.sleep(0.15)

def trigger_scrollbar():
    y = 475 + random.randint(0, 10)
    adb_cmd(f"shell input swipe 30 {y} 30 {y} 100")
    time.sleep(0.15)

def scroll_to_top():
    for _ in range(15):
        trigger_scrollbar()
        img = adb_screenshot()
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        if at_top(img_rgb):
            return
        thumb = find_thumb(img_rgb)
        if thumb is None:
            continue
        sb_drag((thumb[0] + thumb[1]) // 2, TRACK_TOP)

def scroll_to_bottom():
    for _ in range(15):
        trigger_scrollbar()
        img = adb_screenshot()
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        if at_bottom(img_rgb):
            return
        thumb = find_thumb(img_rgb)
        if thumb is None:
            continue
        sb_drag((thumb[0] + thumb[1]) // 2, TRACK_BOT)

def scroll_down_step(thumb_h):
    buy_step = max(10, int(thumb_h * 0.7))
    trigger_scrollbar()
    img = adb_screenshot()
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    thumb = find_thumb(img_rgb)
    if thumb:
        cursor = (thumb[0] + thumb[1]) // 2
        target_y = min(TRACK_BOT - thumb_h // 2, cursor + buy_step)
        sb_drag(cursor, target_y)

def calibrate_drag_ratio():
    trigger_scrollbar()
    img = adb_screenshot()
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    thumb = find_thumb(img_rgb)
    if thumb is None:
        return 1.1

    cal_from = (thumb[0] + thumb[1]) // 2
    cal_dist = 30
    sb_drag(cal_from, cal_from + cal_dist)
    trigger_scrollbar()
    img2 = adb_screenshot()
    img2_rgb = cv2.cvtColor(img2, cv2.COLOR_BGR2RGB)
    thumb2 = find_thumb(img2_rgb)
    if thumb2 is None:
        return 1.1

    cal_to = (thumb2[0] + thumb2[1]) // 2
    actual_move = cal_to - cal_from
    if actual_move > 3:
        return cal_dist / actual_move
    return 1.1

templates_cache = {}

def load_templates():
    global templates_cache
    if templates_cache:
        return templates_cache
    for name, template in MANT_SHOP_TEMPLATES.items():
        tpl = template.template_image
        if tpl is not None:
            templates_cache[name.lower()] = tpl
    return templates_cache

def detect_items_in_frame(screen, templates, threshold=MATCH_THRESHOLD):
    gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
    roi = gray[SHOP_ROI_Y1:SHOP_ROI_Y2, SHOP_ROI_X1:SHOP_ROI_X2]
    raw_hits = []
    for name, tpl in templates.items():
        th, tw = tpl.shape[:2]
        if roi.shape[0] < th or roi.shape[1] < tw:
            continue
        result = cv2.matchTemplate(roi, tpl, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if max_val >= threshold:
            icon_center_x = SHOP_ROI_X1 + max_loc[0] + tw // 2
            icon_center_y = SHOP_ROI_Y1 + max_loc[1] + th // 2
            raw_hits.append((name, max_val, icon_center_x, icon_center_y))
    raw_hits.sort(key=lambda h: -h[1])
    used_y = []
    deduped = []
    for name, score, cx, cy in raw_hits:
        taken = any(abs(cy - uy) < POSITION_MERGE_PX for uy in used_y)
        if not taken:
            deduped.append((name, score, cx, cy))
            used_y.append(cy)
    return deduped

def scan_mant_shop():
    templates = load_templates()
    if not templates:
        return {}

    scroll_to_top()
    trigger_scrollbar()
    img = adb_screenshot()
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    thumb = find_thumb(img_rgb)

    if thumb is None:
        return {}

    thumb_h = thumb[1] - thumb[0]
    saved_thumb_h = thumb_h

    all_items = {}
    scan_positions = {}
    prev_frame = None

    for attempt in range(MAX_SCROLL_ATTEMPTS):
        frame = adb_screenshot()
        if frame is None:
            continue

        trigger_scrollbar()
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        thumb_now = find_thumb(frame_rgb)
        sb_y = (thumb_now[0] + thumb_now[1]) // 2 if thumb_now else None

        found = detect_items_in_frame(frame, templates)
        for name, score, cx, cy in found:
            if name not in all_items or score > all_items[name][0]:
                all_items[name] = (score, cx, cy)
                if sb_y is not None:
                    scan_positions[name] = sb_y

        if prev_frame is not None and content_same(prev_frame, frame):
            break

        prev_frame = frame
        scroll_down_step(saved_thumb_h)

    scroll_to_top()
    return all_items, scan_positions, saved_thumb_h

def buy_item(item_name, scan_positions=None, saved_thumb_h=36, drag_ratio=1.1):
    templates = load_templates()
    if item_name not in templates:
        print(f"Unknown item: {item_name}")
        return False

    single = {item_name: templates[item_name]}

    if scan_positions and item_name in scan_positions:
        target_pos = scan_positions[item_name]
        target_y = max(TRACK_TOP + saved_thumb_h // 2, min(TRACK_BOT - saved_thumb_h // 2, int(target_pos)))

        trigger_scrollbar()
        img = adb_screenshot()
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        thumb = find_thumb(img_rgb)
        cursor = (thumb[0] + thumb[1]) // 2 if thumb else TRACK_TOP + saved_thumb_h // 2

        if abs(target_y - cursor) > 3:
            needed = target_y - cursor
            compensated = int(needed * drag_ratio)
            end_y = max(TRACK_TOP, min(TRACK_BOT + 20, cursor + compensated))
            sb_drag(cursor, end_y)

        img = adb_screenshot()
        found = detect_items_in_frame(img, single)
        if found:
            name, score, cx, cy = found[0]
            buy_x = cx + BUY_OFFSET_X
            buy_y = cy
            print(f"Found {name} at ({cx},{cy}) score={score:.3f}, clicking buy at ({buy_x},{buy_y})")
            tap(buy_x, buy_y)
            return True

        buy_step = max(10, int(saved_thumb_h * 0.7))
        for m in range(1, 6):
            for sign in (-1, 1):
                offset = sign * buy_step * m
                adj = max(TRACK_TOP + saved_thumb_h // 2, min(TRACK_BOT - saved_thumb_h // 2, target_y + offset))

                trigger_scrollbar()
                img = adb_screenshot()
                img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                thumb = find_thumb(img_rgb)
                cursor = (thumb[0] + thumb[1]) // 2 if thumb else target_y

                if abs(adj - cursor) > 3:
                    needed = adj - cursor
                    compensated = int(needed * drag_ratio)
                    end_y = max(TRACK_TOP, min(TRACK_BOT + 20, cursor + compensated))
                    sb_drag(cursor, end_y)

                img = adb_screenshot()
                found = detect_items_in_frame(img, single)
                if found:
                    name, score, cx, cy = found[0]
                    buy_x = cx + BUY_OFFSET_X
                    buy_y = cy
                    print(f"Found {name} at ({cx},{cy}) score={score:.3f}, clicking buy at ({buy_x},{buy_y})")
                    tap(buy_x, buy_y)
                    return True

    scroll_to_top()

    trigger_scrollbar()
    img = adb_screenshot()
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    thumb = find_thumb(img_rgb)

    if thumb is None:
        return False

    thumb_h = thumb[1] - thumb[0]
    prev_frame = None

    for attempt in range(MAX_SCROLL_ATTEMPTS):
        frame = adb_screenshot()
        if frame is None:
            continue

        found = detect_items_in_frame(frame, single)
        if found:
            name, score, cx, cy = found[0]
            if cy < SAFE_Y_MIN or cy > SAFE_Y_MAX:
                scroll_down_step(thumb_h)
                time.sleep(0.2)
                frame2 = adb_screenshot()
                if frame2 is not None:
                    found2 = detect_items_in_frame(frame2, single)
                    if found2:
                        name, score, cx, cy = found2[0]

            buy_x = cx + BUY_OFFSET_X
            buy_y = cy
            print(f"Found {name} at ({cx},{cy}) score={score:.3f}, clicking buy at ({buy_x},{buy_y})")
            tap(buy_x, buy_y)
            return True

        if prev_frame is not None and content_same(prev_frame, frame):
            break

        prev_frame = frame
        scroll_down_step(thumb_h)

    print(f"Could not find {item_name}")
    return False

if __name__ == "__main__":
    print("Scanning MANT Shop")
    result = scan_mant_shop()
    if isinstance(result, tuple):
        items, positions, thumb_h = result
    else:
        items, positions, thumb_h = result, {}, 36

    print(f"\nDetected {len(items)} items:")
    for name, (score, cx, cy) in items.items():
        pos_info = f" sb_pos={positions[name]:.0f}" if name in positions else ""
        print(f"  {name}: score={score:.3f} center=({cx},{cy}){pos_info}")
