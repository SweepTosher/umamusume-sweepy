import numpy as np
import time
from bot.recog.image_matcher import image_match

ENERGY_BAR_Y = 161
ENERGY_BAR_START_X = 227
energy_template = None

def get_energy_template():
    global energy_template
    if energy_template is None:
        from module.umamusume.asset.template import REF_ENERGY
        energy_template = REF_ENERGY
    return energy_template

reference_row = None
reference_bar_length = None
reference_gray_count = None
reference_brightness = None


def find_bar_end(img, y=ENERGY_BAR_Y):
    if isinstance(img, np.ndarray):
        width = img.shape[1]
        row = img[y]
        for x in range(ENERGY_BAR_START_X, width):
            b, g, r = row[x]
            if r == 255 and g == 255 and b == 255:
                return x
        return width
    else:
        width = img.width
        for x in range(ENERGY_BAR_START_X, width):
            r, g, b = img.getpixel((x, y))[:3]
            if r == 255 and g == 255 and b == 255:
                return x
        return width


def find_first_gray(img, bar_start, bar_end, y=ENERGY_BAR_Y):
    if isinstance(img, np.ndarray):
        row = img[y]
        for x in range(bar_start, bar_end):
            b, g, r = row[x]
            if abs(r - 117) <= 1 and abs(g - 117) <= 1 and abs(b - 117) <= 1:
                return x
        return None
    else:
        for x in range(bar_start, bar_end):
            r, g, b = img.getpixel((x, y))[:3]
            if abs(r - 117) <= 1 and abs(g - 117) <= 1 and abs(b - 117) <= 1:
                return x
        return None


def extract_row(img, bar_start, bar_end, y=ENERGY_BAR_Y):
    if isinstance(img, np.ndarray):
        return img[y, bar_start:bar_end].copy()
    else:
        row = []
        for x in range(bar_start, bar_end):
            row.append(img.getpixel((x, y))[:3])
        return np.array(row, dtype=np.uint8)


def compare_rows(base_row, current_row):
    length = min(len(base_row), len(current_row))
    if length == 0:
        return 0
    diff = np.abs(base_row[:length].astype(np.int16) - current_row[:length].astype(np.int16))
    mismatches = np.any(diff > 5, axis=1)
    return int(np.sum(mismatches))


def rows_match_exactly(row1, row2):
    if row1 is None or row2 is None:
        return False
    if len(row1) != len(row2):
        return False
    return np.array_equal(row1, row2)


def scan_energy_single(img, y=ENERGY_BAR_Y):
    bar_end = find_bar_end(img, y)
    bar_length = bar_end - ENERGY_BAR_START_X
    if bar_length <= 0:
        return None, None, 0
    row = extract_row(img, ENERGY_BAR_START_X, bar_end, y)
    first_gray = find_first_gray(img, ENERGY_BAR_START_X, bar_end, y)
    if first_gray is None:
        filled = bar_length - 1
        gray_count = 0
    else:
        filled = first_gray - ENERGY_BAR_START_X - 1
        gray_count = bar_end - first_gray
    base_energy = filled / bar_length * 100
    return row, gray_count, base_energy


def scan_energy(ctrl, y=ENERGY_BAR_Y):
    global reference_row, reference_bar_length, reference_gray_count, reference_brightness
    prev_row = None
    prev_valid = False
    while True:
        img = ctrl.get_screen()
        template = get_energy_template()
        match_result = image_match(img, template)
        if not match_result.find_match:
            prev_row = None
            prev_valid = False
            continue
        current_row, gray_count, base_energy = scan_energy_single(img, y)
        if current_row is not None and prev_valid and rows_match_exactly(prev_row, current_row):
            bar_end = find_bar_end(img, y)
            bar_length = bar_end - ENERGY_BAR_START_X
            reference_row = current_row
            reference_bar_length = bar_length
            reference_gray_count = gray_count
            reference_brightness = float(np.mean(current_row))
            return base_energy, 0, "base_hp"
        prev_row = current_row
        prev_valid = True


def scan_training_energy_change_single(img, y=ENERGY_BAR_Y):
    global reference_row, reference_bar_length, reference_gray_count, reference_brightness
    if reference_row is None:
        return 0.0
    bar_end = find_bar_end(img, y)
    current_row = extract_row(img, ENERGY_BAR_START_X, bar_end, y)
    mismatches = compare_rows(reference_row, current_row)
    if mismatches == 0:
        return 0.0
    energy_change_pct = mismatches / reference_bar_length * 100
    first_gray = find_first_gray(img, ENERGY_BAR_START_X, bar_end, y)
    current_gray_count = (bar_end - first_gray) if first_gray else 0
    if current_gray_count > reference_gray_count:
        return -energy_change_pct
    elif current_gray_count < reference_gray_count:
        return energy_change_pct
    else:
        current_brightness = float(np.mean(current_row))
        if current_brightness < reference_brightness:
            return -energy_change_pct
        else:
            return energy_change_pct if energy_change_pct > 0 else 0.0


def scan_training_energy_change(ctrl, facility_name, y=ENERGY_BAR_Y, initial_img=None):
    prev_value = None
    img = initial_img
    if img is not None:
        prev_value = scan_training_energy_change_single(img, y)
    while True:
        img = ctrl.get_screen()
        current_value = scan_training_energy_change_single(img, y)
        if prev_value is not None and current_value == prev_value:
            return current_value, img
        prev_value = current_value


def scan_base_energy(img, y=ENERGY_BAR_Y):
    bar_end = find_bar_end(img, y)
    bar_length = bar_end - ENERGY_BAR_START_X
    if bar_length <= 0:
        return 0
    first_gray = find_first_gray(img, ENERGY_BAR_START_X, bar_end, y)
    if first_gray is None:
        return 100.0
    filled = first_gray - ENERGY_BAR_START_X - 1
    return filled / bar_length * 100
