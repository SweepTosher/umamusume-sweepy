import os
import cv2
import numpy as np
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

from bot.base.resource import Template
import bot.base.log as logger
from bot.recog.timeout_tracker import reset_timeout

log = logger.get_logger(__name__)

TEMPLATE_IMAGE_CACHE = {}
TEMPLATE_SMALL_CACHE = {}
PARALLEL_WORKERS = 16
COARSE_REJECT_THRESHOLD = 0.52
SMALL_TEMPLATE_MIN_SIZE = 16
EXECUTOR = None

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
        if img.size > 50000:
            img_hash = hash(img[::4, ::4].tobytes())
        else:
            img_hash = hash(img.tobytes())
        template_hash = hash(template.template_img.tobytes()) if hasattr(template, 'template_img') and template.template_img is not None else id(template)
        area = template.image_match_config.match_area
        if area:
            roi_key = f"{area.x1},{area.y1},{area.x2},{area.y2}"
        else:
            roi_key = "full"
        return f"{img_hash}:{template_hash}:{roi_key}"
    except:
        return None

def clear_image_match_cache():
    global _image_match_cache
    _image_match_cache.clear()


def preload_templates(resource_dir):
    count = 0
    for root, dirs, files in os.walk(resource_dir):
        for f in files:
            if f.endswith('.png'):
                path = os.path.join(root, f)
                img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
                if img is not None and img.size > 0:
                    TEMPLATE_IMAGE_CACHE[path] = img
                    if img.shape[0] >= SMALL_TEMPLATE_MIN_SIZE and img.shape[1] >= SMALL_TEMPLATE_MIN_SIZE:
                        small = cv2.resize(img, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
                        if small.shape[0] >= 4 and small.shape[1] >= 4:
                            TEMPLATE_SMALL_CACHE[path] = small
                    count += 1
    return count


def init_executor():
    global EXECUTOR
    if EXECUTOR is None:
        EXECUTOR = ThreadPoolExecutor(max_workers=PARALLEL_WORKERS)


def shutdown_executor():
    global EXECUTOR
    if EXECUTOR:
        EXECUTOR.shutdown(wait=False)
        EXECUTOR = None


class ImageMatchResult:
    matched_area = None
    center_point = None
    find_match: bool = False
    score: int = 0


def to_gray(img):
    if img is None or getattr(img, 'size', 0) == 0:
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
            return res
        else:
            result = template_match(tgt, template, template.image_match_config.match_accuracy)
            if cache_key:
                _image_match_cache.set(cache_key, result)
            return result
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


def match_single_worker_with_coarse(args):
    screen, screen_small, template, threshold = args
    try:
        arr = getattr(template, 'template_img', None)
        if arr is None:
            arr = getattr(template, 'template_image', None)
        if arr is None:
            return (template, ImageMatchResult())
        
        th, tw = arr.shape[:2]
        
        if th >= SMALL_TEMPLATE_MIN_SIZE and tw >= SMALL_TEMPLATE_MIN_SIZE:
            arr_small = cv2.resize(arr, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
            if arr_small.shape[0] >= 4 and arr_small.shape[1] >= 4:
                if screen_small.shape[0] >= arr_small.shape[0] and screen_small.shape[1] >= arr_small.shape[1]:
                    coarse_result = cv2.matchTemplate(screen_small, arr_small, cv2.TM_CCOEFF_NORMED)
                    _, coarse_val, _, _ = cv2.minMaxLoc(coarse_result)
                    if coarse_val < COARSE_REJECT_THRESHOLD:
                        match_result = ImageMatchResult()
                        match_result.score = float(coarse_val)
                        match_result.find_match = False
                        return (template, match_result)
        
        if screen.shape[0] < th or screen.shape[1] < tw:
            return (template, ImageMatchResult())
        
        result = cv2.matchTemplate(screen, arr, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
        
        match_result = ImageMatchResult()
        match_result.score = float(max_val)
        if max_val > threshold:
            match_result.find_match = True
            match_result.center_point = (int(max_loc[0] + tw / 2), int(max_loc[1] + th / 2))
            match_result.matched_area = ((max_loc[0], max_loc[1]), (max_loc[0] + tw, max_loc[1] + th))
        else:
            match_result.find_match = False
        return (template, match_result)
    except Exception:
        return (template, ImageMatchResult())


def batch_match_screen(screen, templates, threshold=0.86):
    reset_timeout()
    screen_gray = to_gray(screen)
    screen_small = cv2.resize(screen_gray, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
    args = [(screen_gray, screen_small, tpl, threshold) for tpl in templates]
    
    if EXECUTOR:
        results = list(EXECUTOR.map(match_single_worker_with_coarse, args))
    else:
        with ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as executor:
            results = list(executor.map(match_single_worker_with_coarse, args))
    return results


def batch_match_with_areas(screen, templates):
    reset_timeout()
    screen_gray = to_gray(screen)
    screen_small = cv2.resize(screen_gray, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
    
    def worker(template):
        try:
            area = template.image_match_config.match_area
            threshold = template.image_match_config.match_accuracy
            
            if area is not None:
                roi, x1, y1 = clip_roi(screen_gray, area)
                roi_small, _, _ = clip_roi(screen_small, 
                    type('Area', (), {'x1': area.x1//2, 'y1': area.y1//2, 
                                      'x2': area.x2//2, 'y2': area.y2//2})())
            else:
                roi, x1, y1 = screen_gray, 0, 0
                roi_small = screen_small
            
            arr = getattr(template, 'template_img', None)
            if arr is None:
                arr = getattr(template, 'template_image', None)
            if arr is None:
                return (template, ImageMatchResult())
            
            th, tw = arr.shape[:2]
            
            if th >= SMALL_TEMPLATE_MIN_SIZE and tw >= SMALL_TEMPLATE_MIN_SIZE:
                arr_small = cv2.resize(arr, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
                if arr_small.shape[0] >= 4 and arr_small.shape[1] >= 4:
                    if roi_small.shape[0] >= arr_small.shape[0] and roi_small.shape[1] >= arr_small.shape[1]:
                        coarse_result = cv2.matchTemplate(roi_small, arr_small, cv2.TM_CCOEFF_NORMED)
                        _, coarse_val, _, _ = cv2.minMaxLoc(coarse_result)
                        if coarse_val < COARSE_REJECT_THRESHOLD:
                            match_result = ImageMatchResult()
                            match_result.score = float(coarse_val)
                            match_result.find_match = False
                            return (template, match_result)
            
            if roi.shape[0] < th or roi.shape[1] < tw:
                return (template, ImageMatchResult())
            
            result = cv2.matchTemplate(roi, arr, cv2.TM_CCOEFF_NORMED)
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
            
            match_result = ImageMatchResult()
            match_result.score = float(max_val)
            if max_val > threshold:
                match_result.find_match = True
                cx = int(max_loc[0] + tw / 2) + x1
                cy = int(max_loc[1] + th / 2) + y1
                match_result.center_point = (cx, cy)
                match_result.matched_area = (
                    (max_loc[0] + x1, max_loc[1] + y1),
                    (max_loc[0] + tw + x1, max_loc[1] + th + y1)
                )
            else:
                match_result.find_match = False
            return (template, match_result)
        except Exception:
            return (template, ImageMatchResult())
    
    if EXECUTOR:
        results = list(EXECUTOR.map(worker, templates))
    else:
        with ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as executor:
            results = list(executor.map(worker, templates))
    return results
