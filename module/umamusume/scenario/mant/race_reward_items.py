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

MATCH_SIZE = 96
MATCH_THRESHOLD = 0.38
MARGIN_TIE_THRESH = 0.02
NCC_ACCEPT_LOW = 0.33
TOP_N = 10
HIST_BINS_H = 24
HIST_BINS_S = 8
HIST_MIN_COMBINED = 0.40
HIST_MIN_MARGIN = 0.01
CELL_PAD = 8
INNER_PAD = 0.12

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
        for entry in manifest:
            filename = entry.get('filename', '')
            display_name = entry.get('displayName', filename)
            path = os.path.join(ITEM_ASSETS_DIR, filename)

            if not os.path.exists(path):
                continue

            raw = cv2.imread(path, cv2.IMREAD_UNCHANGED)
            if raw is None:
                continue

            if raw.ndim == 2:
                raw = cv2.cvtColor(raw, cv2.COLOR_GRAY2BGRA)
            elif raw.shape[2] == 3:
                alpha = np.full(raw.shape[:2], 255, dtype=np.uint8)
                raw = np.dstack([raw, alpha])

            rs = cv2.resize(raw, (MATCH_SIZE, MATCH_SIZE), interpolation=cv2.INTER_AREA)
            bgr = rs[:, :, :3]
            alpha_mask = rs[:, :, 3] > 128

            p = int(MATCH_SIZE * 0.15)
            inner_bgr = bgr[p:MATCH_SIZE - p, p:MATCH_SIZE - p]
            hsv = cv2.cvtColor(inner_bgr, cv2.COLOR_BGR2HSV)
            h_hist = cv2.calcHist([hsv], [0, 1], None, [HIST_BINS_H, HIST_BINS_S], [0, 180, 0, 256])
            cv2.normalize(h_hist, h_hist)

            cache.append((display_name, bgr.astype(np.float32), alpha_mask, h_hist.flatten()))

        template_cache = cache
        log.info("Loaded %d item templates", len(cache))
        return template_cache


def robust_ncc(tile_f32, tmpl_f32, alpha_mask, trim_pct=0.10):
    valid = alpha_mask
    if not np.any(valid):
        return 0.0
    I = tile_f32[valid].ravel()
    T = tmpl_f32[valid].ravel()
    cap = np.percentile(I, (1.0 - trim_pct) * 100.0)
    I = np.clip(I, None, cap)
    I = I - np.median(I)
    T = T - np.median(T)
    denom = np.sqrt(np.dot(I, I) * np.dot(T, T))
    if denom < 1e-6:
        return 0.0
    return float(np.dot(I, T) / denom)


def hist_intersection(tile_bgr, tmpl_hist):
    p = int(tile_bgr.shape[0] * 0.15)
    inner = tile_bgr[p:tile_bgr.shape[0] - p, p:tile_bgr.shape[1] - p]
    if inner.size == 0:
        inner = tile_bgr
    if inner.dtype != np.uint8:
        inner = np.clip(inner, 0, 255).astype(np.uint8)
    hsv = cv2.cvtColor(inner, cv2.COLOR_BGR2HSV)
    h = cv2.calcHist([hsv], [0, 1], None, [HIST_BINS_H, HIST_BINS_S], [0, 180, 0, 256])
    cv2.normalize(h, h)
    return float(np.minimum(h.flatten(), tmpl_hist).sum())


def classify_cell(crop_bgr, templates):
    tile_rs = cv2.resize(crop_bgr, (MATCH_SIZE, MATCH_SIZE), interpolation=cv2.INTER_AREA)
    tile_f = tile_rs.astype(np.float32)

    ncc_scores = []
    for display_name, tmpl_f32, alpha_mask, tmpl_hist in templates:
        score = robust_ncc(tile_f, tmpl_f32, alpha_mask)
        ncc_scores.append((display_name, score, tmpl_hist))
    ncc_scores.sort(key=lambda t: -t[1])

    best_name, best_ncc, _ = ncc_scores[0]
    margin = best_ncc - ncc_scores[1][1]

    if best_ncc >= MATCH_THRESHOLD and margin >= MARGIN_TIE_THRESH:
        return best_name, best_ncc, 'ncc'

    if best_ncc >= NCC_ACCEPT_LOW:
        top_n = ncc_scores[:TOP_N]
        hist_ranked = []
        for name, ncc, tmpl_hist in top_n:
            hs = hist_intersection(tile_rs, tmpl_hist)
            combined = 0.5 * ncc + 0.5 * hs
            hist_ranked.append((name, combined, ncc, hs))
        hist_ranked.sort(key=lambda t: -t[1])
        winner_name, combined, wncc, whs = hist_ranked[0]
        runner_combined = hist_ranked[1][1] if len(hist_ranked) > 1 else 0.0
        if combined >= HIST_MIN_COMBINED and (combined - runner_combined) >= HIST_MIN_MARGIN:
            return winner_name, combined, 'hist_rerank'

    return best_name, best_ncc, 'ncc_raw'


def grid_cells(roi_h, roi_w):
    mid_y = roi_h // 2
    mid_x = roi_w // 2
    p = CELL_PAD
    return [
        ('TL', p, mid_y - p, p, mid_x - p),
        ('TR', p, mid_y - p, mid_x + p, roi_w - p),
        ('BL', mid_y + p, roi_h - p, p, mid_x - p),
        ('BR', mid_y + p, roi_h - p, mid_x + p, roi_w - p),
    ]


def detect_race_reward_items(img):
    templates = load_templates()
    if not templates:
        return []

    x1, y1, x2, y2 = ITEM_ROI
    h_img, w_img = img.shape[:2]
    roi = img[max(0, y1):min(h_img, y2), max(0, x1):min(w_img, x2)]
    roi_h, roi_w = roi.shape[:2]

    results = []
    for label, ys, ye, xs, xe in grid_cells(roi_h, roi_w):
        crop = roi[ys:ye, xs:xe]
        if crop.size == 0:
            continue
        cy = int(crop.shape[0] * INNER_PAD)
        cx = int(crop.shape[1] * INNER_PAD)
        inner = crop[cy:crop.shape[0] - cy, cx:crop.shape[1] - cx]
        if inner.size == 0:
            inner = crop
        name, score, method = classify_cell(inner, templates)
        if method in ('ncc', 'hist_rerank'):
            results.append(name)

    return results


def check_and_detect_race_reward_items(img, img_gray):
    try:
        from bot.recog.image_matcher import image_match
        from module.umamusume.asset.template import REF_MANT_REWARD_ITEMS

        res = image_match(img_gray, REF_MANT_REWARD_ITEMS)
        if not res.find_match:
            return

        items = detect_race_reward_items(img)
        log.info("Race reward new shop items: %s", items)
    except Exception:
        pass
