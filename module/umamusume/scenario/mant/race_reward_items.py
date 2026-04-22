import os
import json
import threading

import cv2
import numpy as np

import bot.base.log as logger

log = logger.get_logger(__name__)

ITEM_ROI = (11, 345, 717, 783)

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
ITEM_ASSETS_DIR = os.path.normpath(
    os.path.join(THIS_DIR, '../../../../web/src/assets/img/mant_items')
)
MANIFEST_PATH = os.path.join(ITEM_ASSETS_DIR, 'manifest.json')

TMPL_BASE      = 96
TARGET_SZ      = 160

INNER_FRAC     = 0.20
INIT_THRESH    = 0.75
MAX_PEAKS      = 2

ICON_SZ        = 64
FINAL_NCC_W    = 0.55
FINAL_HIST_W   = 0.45
FINAL_THRESH   = 0.58
MARGIN_THRESH  = 0.03

NMS_IOU_THRESH = 0.25
MAX_ITEMS      = 7

template_cache = None
cache_lock = threading.Lock()


def load_templates():
    global template_cache
    with cache_lock:
        if template_cache is not None:
            return template_cache

        if not os.path.exists(MANIFEST_PATH):
            log.warning("mant_items manifest not found at %s", MANIFEST_PATH)
            template_cache = []
            return template_cache

        with open(MANIFEST_PATH, 'r', encoding='utf-8') as fh:
            manifest = json.load(fh)

        cache = []
        p = int(TARGET_SZ * INNER_FRAC)
        isz = TARGET_SZ - 2 * p
        for entry in manifest:
            fn   = entry.get('filename', '')
            name = entry.get('displayName', fn)
            path = os.path.join(ITEM_ASSETS_DIR, fn)
            if not os.path.exists(path):
                continue
            raw = cv2.imread(path, cv2.IMREAD_UNCHANGED)
            if raw is None:
                continue
            if raw.ndim == 2:
                raw = cv2.cvtColor(raw, cv2.COLOR_GRAY2BGRA)
            elif raw.shape[2] == 3:
                raw = np.dstack([raw, np.full(raw.shape[:2], 255, dtype=np.uint8)])

            base = cv2.resize(raw, (TARGET_SZ, TARGET_SZ), cv2.INTER_AREA)
            bgr  = base[:, :, :3]

            inner_bgr = bgr[p:TARGET_SZ - p, p:TARGET_SZ - p]

            icon = cv2.resize(inner_bgr, (ICON_SZ, ICON_SZ), cv2.INTER_AREA)
            hsv  = cv2.cvtColor(icon, cv2.COLOR_BGR2HSV)
            hist = cv2.calcHist([hsv], [0, 1], None, [24, 8], [0, 180, 0, 256])
            cv2.normalize(hist, hist)

            cache.append({
                'name':      name,
                'tmpl_inner': inner_bgr,
                'icon_f32':  icon.astype(np.float32),
                'hist':      hist.flatten(),
            })

        template_cache = cache
        log.info("Loaded %d item templates", len(cache) if cache else 0)
        return cache


def iou(b1, b2):
    ax2, ay2 = b1[0] + b1[2], b1[1] + b1[3]
    bx2, by2 = b2[0] + b2[2], b2[1] + b2[3]
    ix1, iy1 = max(b1[0], b2[0]), max(b1[1], b2[1])
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    if inter == 0:
        return 0.0
    union = b1[2] * b1[3] + b2[2] * b2[3] - inter
    return inter / union if union > 0 else 0.0


def nms(detections):
    detections = sorted(detections, key=lambda d: -d['score'])
    kept = []
    for det in detections:
        box = (det['x'], det['y'], det['w'], det['h'])
        if not any(iou(box, (k['x'], k['y'], k['w'], k['h'])) > NMS_IOU_THRESH
                   for k in kept):
            kept.append(det)
    return kept


def ncc(a_f32, b_f32):
    I = a_f32.ravel().copy()
    T = b_f32.ravel().copy()
    I -= I.mean()
    T -= T.mean()
    denom = np.sqrt((I * I).sum() * (T * T).sum())
    if denom < 1e-6:
        return 0.0
    return float(np.dot(I, T) / denom)


def hist_sim(icon_bgr_uint8, tmpl_hist):
    hsv  = cv2.cvtColor(icon_bgr_uint8, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [24, 8], [0, 180, 0, 256])
    cv2.normalize(hist, hist)
    return float(np.minimum(hist.flatten(), tmpl_hist).sum())


def detect_race_reward_items(img):
    templates = load_templates()
    if not templates:
        return []

    x1, y1, x2, y2 = ITEM_ROI
    h_img, w_img = img.shape[:2]
    roi = img[max(0, y1):min(h_img, y2), max(0, x1):min(w_img, x2)]
    h_roi, w_roi = roi.shape[:2]

    p   = int(TARGET_SZ * INNER_FRAC)
    isz = TARGET_SZ - 2 * p
    suppress_r = max(TARGET_SZ // 3, 15)

    all_cands = []
    for tmpl in templates:
        tmpl_inner = tmpl['tmpl_inner']
        if isz > h_roi or isz > w_roi:
            continue
            
        res    = cv2.matchTemplate(roi, tmpl_inner, cv2.TM_CCOEFF_NORMED)
        h_r, w_r = res.shape
        res_cp = res.copy()
        
        for _ in range(MAX_PEAKS):
            _, max_val, _, max_loc = cv2.minMaxLoc(res_cp)
            if max_val < INIT_THRESH:
                break
            all_cands.append({
                'name':  tmpl['name'],
                'score': float(max_val),
                'x': max_loc[0] - p,
                'y': max_loc[1] - p,
                'w': TARGET_SZ, 'h': TARGET_SZ,
            })
            y1s = max(0, max_loc[1] - suppress_r)
            y2s = min(h_r, max_loc[1] + suppress_r + 1)
            x1s = max(0, max_loc[0] - suppress_r)
            x2s = min(w_r, max_loc[0] + suppress_r + 1)
            res_cp[y1s:y2s, x1s:x2s] = -1.0

    if not all_cands:
        return []

    kept = nms(all_cands)[:MAX_ITEMS]

    result_names = []
    for cand in kept:
        bx, by, bw, bh = cand['x'], cand['y'], cand['w'], cand['h']
        ry1 = max(0, by);      ry2 = min(h_roi, by + bh)
        rx1 = max(0, bx);      rx2 = min(w_roi, bx + bw)
        cell = roi[ry1:ry2, rx1:rx2]
        if cell.size == 0:
            continue

        h_c, w_c = cell.shape[:2]
        py = max(1, int(h_c * INNER_FRAC))
        px = max(1, int(w_c * INNER_FRAC))
        cell_inner = cell[py:h_c - py, px:w_c - px]
        if cell_inner.size == 0:
            cell_inner = cell

        cell_icon = cv2.resize(cell_inner, (ICON_SZ, ICON_SZ), cv2.INTER_AREA)
        cell_f32  = cell_icon.astype(np.float32)

        scores = []
        for tmpl in templates:
            sncc  = ncc(cell_f32, tmpl['icon_f32'])
            shist = hist_sim(cell_icon, tmpl['hist'])
            combined = FINAL_NCC_W * sncc + FINAL_HIST_W * shist
            scores.append((tmpl['name'], combined))

        scores.sort(key=lambda s: -s[1])
        best_name, best_score = scores[0]
        runner_score = scores[1][1] if len(scores) > 1 else 0.0
        margin = best_score - runner_score

        if best_score >= FINAL_THRESH and margin >= MARGIN_THRESH:
            result_names.append(best_name)

    return result_names


def check_and_detect_race_reward_items(img, img_gray, ctx=None):
    try:
        from bot.recog.image_matcher import image_match
        from module.umamusume.asset.template import REF_MANT_REWARD_ITEMS

        res = image_match(img_gray, REF_MANT_REWARD_ITEMS)
        if not res.find_match:
            return

        items = detect_race_reward_items(img)
        log.info("Race reward new shop items: %s", items)
        if items:
            from module.umamusume.context import add_detected_shop_items
            add_detected_shop_items(items, turns=3)

            if ctx is not None:
                existing_names = {name for name, _, _, _, _ in ctx.cultivate_detail.mant_shop_items}
                for name in items:
                    if name not in existing_names:
                        ctx.cultivate_detail.mant_shop_items.append((name, 0, 0, 3, False))
    except Exception:
        pass
