import os
import time
import random
import cv2
import numpy as np
import torch
import torch.nn as nn
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import bot.base.log as logger

log = logger.get_logger(__name__)

ICON_X1 = 53
ICON_X2 = 133
CROP_H = 54
CROP_W = 80
SHOP_ROI_Y1 = 440
SHOP_ROI_Y2 = 920
EDGE_MARGIN = 57
CONTENT_TOP = 440
CONTENT_BOT = 920
CONTENT_X1 = 30
CONTENT_X2 = 640
BORDER_INSET = 6
INNER_TRAIN_SIZE = 48
CNN_CONFIDENCE_THRESHOLD = 0.5
PURCHASED_CHECK_X1 = 200
PURCHASED_CHECK_X2 = 600
PURCHASED_BRIGHTNESS_THRESHOLD = 180
MANT_SHOP_SCAN_START = 14
MANT_SHOP_SCAN_INTERVAL = 6

SB_X = 695
SB_X_MIN = 693
SB_X_MAX = 697
TRACK_TOP = 480
TRACK_BOT = 938
SCREEN_WIDTH = 720

PRIMARY_MODEL_PATH = os.path.join("resource", "umamusume", "ref", "mantShop", "shop_cnn.pt")
INNER_MODEL_PATH = os.path.join("resource", "umamusume", "ref", "mantShop", "shop_cnn_inner.pt")

CONFUSABLE_GROUPS = [
    {"megasmall", "megamedium", "megalarge"},
    {"speedsmall", "powersmall", "staminasmall", "gutssmall", "witsmall", "maxsmall"},
    {"speedmedium", "powermedium", "staminamedium", "gutsmedium", "witmedium"},
    {"speedlarge", "powerlarge", "staminalarge", "gutslarge", "witlarge", "maxlarge"},
    {"speedweights", "powerweights", "staminaweights", "gutsweights"},
    {"speedpet", "powerpet", "staminapet", "gutspet", "witpet"},
    {"energydrinksmall", "energydrinkmedium", "energydrinklarge"},
    {"moodsmall", "moodlarge"},
    {"rb", "rbex"},
]

confusable_lookup = {}
for g in CONFUSABLE_GROUPS:
    for c in g:
        confusable_lookup[c] = g


class PrimaryCNN(nn.Module):
    def __init__(self, num_classes):
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(3, 32, 3, padding=1), nn.BatchNorm2d(32), nn.ReLU(), nn.MaxPool2d(2),
            nn.Conv2d(32, 64, 3, padding=1), nn.BatchNorm2d(64), nn.ReLU(), nn.MaxPool2d(2),
            nn.Conv2d(64, 128, 3, padding=1), nn.BatchNorm2d(128), nn.ReLU(), nn.MaxPool2d(2),
            nn.Conv2d(128, 128, 3, padding=1), nn.BatchNorm2d(128), nn.ReLU(), nn.AdaptiveAvgPool2d((3, 5)),
        )
        self.classifier = nn.Sequential(
            nn.Dropout(0.3), nn.Linear(128 * 3 * 5, 256), nn.ReLU(),
            nn.Dropout(0.3), nn.Linear(256, num_classes),
        )

    def forward(self, x):
        x = self.features(x)
        x = x.view(x.size(0), -1)
        return self.classifier(x)


class InnerCNN(nn.Module):
    def __init__(self, num_classes):
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(3, 32, 3, padding=1), nn.BatchNorm2d(32), nn.ReLU(), nn.MaxPool2d(2),
            nn.Conv2d(32, 64, 3, padding=1), nn.BatchNorm2d(64), nn.ReLU(), nn.MaxPool2d(2),
            nn.Conv2d(64, 128, 3, padding=1), nn.BatchNorm2d(128), nn.ReLU(), nn.MaxPool2d(2),
            nn.Conv2d(128, 128, 3, padding=1), nn.BatchNorm2d(128), nn.ReLU(), nn.AdaptiveAvgPool2d((3, 3)),
        )
        self.classifier = nn.Sequential(
            nn.Dropout(0.3), nn.Linear(128 * 3 * 3, 256), nn.ReLU(),
            nn.Dropout(0.3), nn.Linear(256, num_classes),
        )

    def forward(self, x):
        x = self.features(x)
        x = x.view(x.size(0), -1)
        return self.classifier(x)


primary_model = None
inner_model = None
p_class_names = None
i_class_names = None
name_to_key = None


def load_models():
    global primary_model, inner_model, p_class_names, i_class_names, name_to_key
    if primary_model is not None:
        return

    from module.umamusume.asset.template import MANT_SHOP_ITEM_NAMES

    pdata = torch.load(PRIMARY_MODEL_PATH, map_location="cpu", weights_only=False)
    p_class_names = pdata["class_names"]
    primary_model = PrimaryCNN(len(p_class_names))
    primary_model.load_state_dict(pdata["model_state"])
    primary_model.eval()

    idata = torch.load(INNER_MODEL_PATH, map_location="cpu", weights_only=False)
    i_class_names = idata["class_names"]
    inner_model = InnerCNN(len(i_class_names))
    inner_model.load_state_dict(idata["model_state"])
    inner_model.eval()

    name_to_key = {}
    for key, cnn_name in MANT_SHOP_ITEM_NAMES.items():
        name_to_key[cnn_name] = key


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


def find_item_icon_positions(frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    icon_col = gray[SHOP_ROI_Y1:SHOP_ROI_Y2, ICON_X1:ICON_X2]
    row_means = icon_col.mean(axis=1)

    in_sep = False
    separators = []
    sep_start = 0
    for y in range(len(row_means)):
        if row_means[y] > 240:
            if not in_sep:
                sep_start = y
                in_sep = True
        else:
            if in_sep:
                if y - sep_start >= 5:
                    separators.append((sep_start, y))
                in_sep = False

    zones = []
    for s, e in separators:
        if zones and s - zones[-1][1] < 10:
            zones[-1] = (zones[-1][0], e)
        else:
            zones.append((s, e))

    icon_positions = []
    prev_end = 0
    for s, e in zones:
        if s - prev_end > 40:
            item_h = s - prev_end
            icon_y = prev_end + int(item_h * 0.15)
            if icon_y >= 0 and icon_y + CROP_H <= len(row_means):
                icon_positions.append(SHOP_ROI_Y1 + icon_y)
        prev_end = e

    if len(row_means) - prev_end > 40:
        item_h = len(row_means) - prev_end
        icon_y = prev_end + int(item_h * 0.15)
        if icon_y >= 0 and icon_y + CROP_H <= len(row_means):
            icon_positions.append(SHOP_ROI_Y1 + icon_y)

    return icon_positions


def classify_icon(icon):
    x = torch.from_numpy(icon.astype(np.float32) / 255.0).permute(2, 0, 1).unsqueeze(0)
    with torch.no_grad():
        probs = torch.softmax(primary_model(x), 1)
        p_conf, p_pred = probs.max(1)
    p_class = p_class_names[p_pred.item()]
    p_conf = p_conf.item()

    if p_class not in confusable_lookup and p_conf > 0.9:
        return p_class, p_conf

    if p_class not in confusable_lookup:
        return None, p_conf

    inner = icon[BORDER_INSET:CROP_H, BORDER_INSET:CROP_W - BORDER_INSET]
    inner_resized = cv2.resize(inner, (INNER_TRAIN_SIZE, INNER_TRAIN_SIZE), interpolation=cv2.INTER_AREA)
    x2 = torch.from_numpy(inner_resized.astype(np.float32) / 255.0).permute(2, 0, 1).unsqueeze(0)
    with torch.no_grad():
        iprobs = torch.softmax(inner_model(x2), 1)

    group = confusable_lookup[p_class]
    group_indices = [i for i, n in enumerate(i_class_names) if n in group]
    group_probs = {i_class_names[i]: iprobs[0, i].item() for i in group_indices}
    best_inner = max(group_probs, key=group_probs.get)
    best_inner_conf = group_probs[best_inner]
    return best_inner, best_inner_conf


def is_purchased(frame, abs_y):
    row = frame[abs_y:abs_y + CROP_H, PURCHASED_CHECK_X1:PURCHASED_CHECK_X2]
    return np.mean(row) < PURCHASED_BRIGHTNESS_THRESHOLD


def classify_icons_in_frame(frame):
    load_models()
    positions = find_item_icon_positions(frame)
    results = []
    hit_purchased = False

    for abs_y in positions:
        if abs_y < SHOP_ROI_Y1 + EDGE_MARGIN or abs_y + CROP_H > SHOP_ROI_Y2 - EDGE_MARGIN:
            continue
        icon = frame[abs_y:abs_y + CROP_H, ICON_X1:ICON_X2]
        if icon.shape != (CROP_H, CROP_W, 3):
            continue
        if np.std(icon) < 15:
            continue

        if is_purchased(frame, abs_y):
            hit_purchased = True
            continue

        pred_class, conf = classify_icon(icon)
        if pred_class is None:
            continue
        key = name_to_key.get(pred_class, pred_class)

        if conf < CNN_CONFIDENCE_THRESHOLD:
            continue

        results.append((key, conf, abs_y))

    return results, hit_purchased


def scan_mant_shop(ctx):
    load_models()

    ctx.ctrl.click(412, 1125, "MANT shop open")
    time.sleep(1.5)

    scroll_to_top(ctx)
    trigger_scrollbar(ctx)
    img = ctx.ctrl.get_screen()
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    thumb = find_thumb(img_rgb)

    if thumb is None:
        results, _ = classify_icons_in_frame(img)
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

    first_results, _ = classify_icons_in_frame(img)
    all_detections = []
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
                f = pool.submit(classify_icons_in_frame, curr)
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
            f = pool.submit(classify_icons_in_frame, final)
            futures.append((frame_idx, f))

        for fi, f in futures:
            hits, hit_purchased = f.result()
            for key, conf, abs_y in hits:
                all_detections.append((key, conf, fi, abs_y))

    by_name = defaultdict(list)
    for key, conf, fi, abs_y in all_detections:
        by_name[key].append((conf, fi, abs_y))

    items_list = []
    for name, dets in by_name.items():
        dets.sort(key=lambda d: d[1])
        groups = []
        for conf, fi, abs_y in dets:
            if groups and fi - groups[-1][-1][1] <= 2:
                groups[-1].append((conf, fi, abs_y))
            else:
                groups.append([(conf, fi, abs_y)])

        for group in groups:
            best_conf = max(d[0] for d in group)
            items_list.append((name, best_conf))

    log.info("shop items: %s", [n for n, _ in items_list])

    ctx.ctrl.click(95, 1228)
    time.sleep(1)

    return [name for name, _ in items_list]
