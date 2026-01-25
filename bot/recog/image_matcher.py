import os
import cv2
import numpy as np
from collections import OrderedDict

from bot.base.common import ImageMatchMode
from bot.base.resource import Template
import bot.base.log as logger
from bot.recog.timeout_tracker import reset_timeout

log = logger.get_logger(__name__)

class LRUCache:
    def __init__(self, maxsize=8000):
        self.cache = OrderedDict()
        self.maxsize = maxsize
    
    def get(self, key):
        if key not in self.cache:
            return None
        self.cache.move_to_end(key)
        return self.cache[key]
    
    def set(self, key, value):
        if key in self.cache:
            self.cache.move_to_end(key)
        self.cache[key] = value
        if len(self.cache) > self.maxsize:
            self.cache.popitem(last=False)
    
    def clear(self):
        self.cache.clear()
    
    def __contains__(self, key):
        return key in self.cache

_image_match_cache = LRUCache(maxsize=8000)

def _compute_match_cache_key(img, template):
    try:
        img_key = (id(img), img.shape[0] if img is not None else 0, img.shape[1] if img is not None else 0)
        template_key = id(template)
        area = template.image_match_config.match_area
        if area:
            roi_key = (area.x1, area.y1, area.x2, area.y2)
        else:
            roi_key = None
        return (img_key, template_key, roi_key)
    except:
        return None

def clear_image_match_cache():
    global _image_match_cache
    _image_match_cache.clear()


class ImageMatchResult:
    matched_area = None
    center_point = None
    find_match: bool = False
    score: int = 0


def to_gray(img):
    if img is None or getattr(img, 'size', 0) == 0:
        return img
    if len(img.shape) == 2:
        return img
    if len(img.shape) == 3:
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return img


def clip_roi(img, area):
    if img is None or getattr(img, 'size', 0) == 0:
        return img, 0, 0
    if area is None:
        return img, 0, 0
    h, w = img.shape[:2]
    x1 = max(0, min(w, area.x1))
    y1 = max(0, min(h, area.y1))
    x2 = max(x1, min(w, area.x2))
    y2 = max(y1, min(h, area.y2))
    return img[y1:y2, x1:x2], x1, y1


def image_match(target, template: Template) -> ImageMatchResult:
    reset_timeout()
    
    cache_key = _compute_match_cache_key(target, template)
    if cache_key:
        cached = _image_match_cache.get(cache_key)
        if cached is not None:
            return cached
    try:
        if template.image_match_config.match_mode == ImageMatchMode.IMAGE_MATCH_MODE_TEMPLATE_MATCH:
            tgt = to_gray(target)
            area = template.image_match_config.match_area
            if area is not None:
                roi, x1, y1 = clip_roi(tgt, area)
                res = template_match(roi, template, template.image_match_config.match_accuracy)
                if res.find_match:
                    cx, cy = res.center_point
                    res.center_point = (cx + x1, cy + y1)
                    (p1, p2) = res.matched_area
                    res.matched_area = ((p1[0] + x1, p1[1] + y1), (p2[0] + x1, p2[1] + y1))
                if cache_key:
                    _image_match_cache.set(cache_key, res)
                return res
            else:
                result = template_match(tgt, template, template.image_match_config.match_accuracy)
                if cache_key:
                    _image_match_cache.set(cache_key, result)
                return result
        else:
            log.error("unsupported match mode")
    except Exception as e:
        log.error(f"image_match failed: {e}")
        return ImageMatchResult()


def template_match(target, template, accuracy: float = 0.86) -> ImageMatchResult:
    reset_timeout()
    if target is None or target.size == 0:
        return ImageMatchResult()
    try:
        arr = getattr(template, 'template_img', None)
        if arr is None:
            arr = getattr(template, 'template_image', None)
        if arr is not None:
            try:
                th, tw = arr.shape[::]
            except Exception:
                return ImageMatchResult()
            if target.shape[0] < th or target.shape[1] < tw:
                return ImageMatchResult()
            
            result = cv2.matchTemplate(target, arr, cv2.TM_CCOEFF_NORMED)
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
            match_result = ImageMatchResult()
            match_result.score = float(max_val)
            if max_val > accuracy:
                match_result.find_match = True
                match_result.center_point = (int(max_loc[0] + tw / 2), int(max_loc[1] + th / 2))
                match_result.matched_area = ((max_loc[0], max_loc[1]), (max_loc[0] + tw, max_loc[1] + th))
            else:
                match_result.find_match = False
            return match_result
        return ImageMatchResult()
    except Exception:
        return ImageMatchResult()


def compare_color_equal(p: list, target: list, tolerance: int = 10) -> bool:
    tol_sq = tolerance * tolerance
    d0 = target[0] - p[0]
    d1 = target[1] - p[1]
    d2 = target[2] - p[2]
    return (d0*d0 + d1*d1 + d2*d2) < tol_sq


def multi_template_match(templates, threshold=0.82):
    best_score = 0.0
    for template, sub_roi in templates:
        try:
            result = image_match(sub_roi, template)
            best_score = max(best_score, result.score)
        except Exception:
            pass
    return best_score >= threshold, best_score
