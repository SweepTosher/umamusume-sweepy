import cv2
import numpy as np
import os
import bot.base.log as logger

log = logger.get_logger(__name__)

MODEL_PATH = "resource/umamusume/digit_model.pth"
_classifier = None

def get_classifier():
    global _classifier
    if _classifier is None:
        from bot.recog.digit_cnn import DigitClassifier
        _classifier = DigitClassifier(MODEL_PATH)
    return _classifier

STAT_AREAS_AOHARUHAI = {
    "speed": (31, 798, 132, 831),
    "stamina": (114, 798, 246, 831),
    "power": (256, 798, 359, 831),
    "guts": (369, 798, 471, 831),
    "wits": (482, 798, 585, 831),
    "sp": (595, 798, 698, 831),
}

STAT_AREAS_URA = {
    "speed": (30, 770, 140, 826),
    "stamina": (140, 770, 250, 826),
    "power": (250, 770, 360, 826),
    "guts": (360, 770, 470, 826),
    "wits": (470, 770, 580, 826),
    "sp": (588, 770, 695, 826),
}

FACILITY_STATS = {
    "speed": ["speed", "power", "sp"],
    "stamina": ["stamina", "guts", "sp"],
    "power": ["power", "stamina", "sp"],
    "guts": ["speed", "guts", "power", "sp"],
    "wits": ["speed", "wits", "sp"],
}

def create_color_mask(roi, sat_thresh=70):
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (0, sat_thresh, 70), (180, 255, 255))
    return mask

def remove_bottom_bar(mask):
    h, w = mask.shape
    for row in range(h - 1, max(h - 8, 0), -1):
        row_sum = np.sum(mask[row, :] > 0)
        if row_sum > w * 0.6:
            mask[row, :] = 0
        else:
            break
    return mask

def find_digit_regions(mask):
    mask = remove_bottom_bar(mask.copy())
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    h_img, w_img = mask.shape
    all_candidates = []
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        area = cv2.contourArea(cnt)
        if area < 100:
            continue
        if w > 28 or w < 10:
            continue
        if h < 18 or h > 32:
            continue
        aspect = w / h
        if aspect > 0.98:
            continue
        if aspect < 0.40:
            continue
        if y > 6 or y == 0:
            continue
        right_edge = x + w
        if right_edge >= w_img and x >= w_img - 20:
            continue
        all_candidates.append((x, y, w, h))
    all_candidates.sort(key=lambda r: r[0])
    if len(all_candidates) >= 3:
        min_x = int(w_img * 0.25)
    else:
        min_x = int(w_img * 0.35)
    regions = []
    for x, y, w, h in all_candidates:
        if x < min_x:
            continue
        regions.append((x, y, w, h))
    return regions

def classify_digit_region(roi, mask, region):
    x, y, w, h = region
    padding = 2
    x1 = max(0, x - padding)
    y1 = max(0, y - padding)
    x2 = min(mask.shape[1], x + w + padding)
    y2 = min(mask.shape[0], y + h + padding)
    digit_mask = mask[y1:y2, x1:x2]
    if digit_mask.size == 0:
        return -1, 0.0
    classifier = get_classifier()
    pred, conf = classifier.predict(digit_mask)
    return pred, conf

def recognize_digits_cnn(roi):
    if roi is None or roi.size == 0:
        return 0
    mask = create_color_mask(roi)
    regions = find_digit_regions(mask)
    if not regions:
        return 0
    digits = []
    for region in regions:
        digit, conf = classify_digit_region(roi, mask, region)
        if digit >= 0 and conf > 0.3:
            digits.append((region[0], digit, conf))
    if not digits:
        return 0
    digits.sort(key=lambda d: d[0])
    result_str = "".join(str(d[1]) for d in digits)
    return int(result_str) if result_str else 0

def scan_stat_gain(img, stat_name, scenario="aoharuhai"):
    if scenario == "ura":
        areas = STAT_AREAS_URA
    else:
        areas = STAT_AREAS_AOHARUHAI
    if stat_name not in areas:
        return 0
    h, w = img.shape[:2]
    x1, y1, x2, y2 = areas[stat_name]
    x1 = max(0, min(x1, w))
    x2 = max(0, min(x2, w))
    y1 = max(0, min(y1, h))
    y2 = max(0, min(y2, h))
    roi = img[y1:y2, x1:x2]
    return recognize_digits_cnn(roi)

def scan_facility_stats(img, facility_type, scenario="aoharuhai"):
    if facility_type not in FACILITY_STATS:
        return {}
    stats_to_scan = FACILITY_STATS[facility_type]
    results = {}
    for stat in stats_to_scan:
        value = scan_stat_gain(img, stat, scenario)
        results[stat] = value
    return results

def log_facility_stats(facility_type, results):
    if not results:
        return
    log.info(f"{facility_type} facility:")
    for stat, value in results.items():
        log.info(f"  {stat}: {value}")

def scan_all_stats(img, scenario="aoharuhai"):
    if scenario == "ura":
        areas = STAT_AREAS_URA
    else:
        areas = STAT_AREAS_AOHARUHAI
    results = {}
    for stat_name in areas.keys():
        value = scan_stat_gain(img, stat_name, scenario)
        results[stat_name] = value
    log.info("All stat gains:")
    for stat, value in results.items():
        log.info(f"  {stat}: {value}")
    return results

def parse_training_result_template(img, scenario="aoharuhai"):
    speed = scan_stat_gain(img, "speed", scenario)
    stamina = scan_stat_gain(img, "stamina", scenario)
    power = scan_stat_gain(img, "power", scenario)
    guts = scan_stat_gain(img, "guts", scenario)
    wits = scan_stat_gain(img, "wits", scenario)
    sp = scan_stat_gain(img, "sp", scenario)
    return [speed, stamina, power, guts, wits, sp]
