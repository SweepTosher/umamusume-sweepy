import cv2
import importlib, sys, threading
from functools import lru_cache
from collections import OrderedDict
paddleocr = None
from difflib import SequenceMatcher
import bot.base.log as logger
import os
from config import CONFIG
import bot.base.gpu_utils as gpu_utils
from bot.recog.timeout_tracker import reset_timeout

log = logger.get_logger(__name__)
_paddleocr_import_lock = threading.RLock()
_USE_GPU = False
_GPU_INITIALIZED = False

class LRUCache:
    def __init__(self, maxsize=12000):
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

_ocr_result_cache = LRUCache(maxsize=12000)

def _compute_ocr_cache_key(img, lang):
    try:
        return (lang, id(img), img.shape[0] if img is not None else 0, img.shape[1] if img is not None else 0)
    except:
        return None

def clear_ocr_cache():
    global _ocr_result_cache
    _ocr_result_cache.clear()



def cpu_threads():
    try:
        alloc = getattr(CONFIG.bot.auto, 'cpu_alloc', None)
        return int(alloc) if alloc else os.cpu_count()
    except Exception:
        return os.cpu_count()


OCR_JP = None
OCR_CH = None
OCR_EN = None


def initialize_gpu_mode():
    global _USE_GPU, _GPU_INITIALIZED
    
    if _GPU_INITIALIZED:
        return
    
    _GPU_INITIALIZED = True
    
    try:
        gpu_config = getattr(CONFIG.bot, 'gpu', None)
        if gpu_config is None:
            _USE_GPU = False
            return
        
        gpu_enabled = getattr(gpu_config, 'enabled', 'auto')
        
        if gpu_enabled == 'false' or gpu_enabled is False:
            _USE_GPU = False
            return
        
        if gpu_enabled == 'auto' or gpu_enabled == 'true' or gpu_enabled is True:
            if gpu_utils.is_gpu_available():
                memory_fraction = float(getattr(gpu_config, 'memory_fraction', 0.5))
                device_id = int(getattr(gpu_config, 'device_id', 0))
                
                gpu_utils.set_gpu_config(memory_fraction, device_id)
                gpu_utils.configure_paddle_gpu()
                
                _USE_GPU = True
            else:
                _USE_GPU = False
        else:
            _USE_GPU = False
    
    except Exception as e:
        _USE_GPU = False

def ensure_paddleocr():
    global paddleocr
    try:
        if paddleocr is not None and 'paddleocr' in sys.modules:
            return
        if hasattr(sys, "is_finalizing") and sys.is_finalizing():
            raise RuntimeError("Interpreter finalizing; skip paddleocr import")
        with _paddleocr_import_lock:
            if paddleocr is None or 'paddleocr' not in sys.modules:
                paddleocr = importlib.import_module('paddleocr')
    except Exception as e:
        log.error(f"Failed to import paddleocr: {e}")
        raise

def init_ocr_if_needed():
    initialize_gpu_mode()
    ensure_paddleocr()

def _create_ocr_instance(lang):
    try:
        if _USE_GPU:
            return paddleocr.PaddleOCR(
                lang=lang, 
                show_log=False, 
                use_angle_cls=False, 
                use_gpu=True, 
                gpu_mem=250,
                rec_batch_num=1,
                det_db_box_thresh=0.5,
                use_tensorrt=False,
                enable_mkldnn=False
            )
        else:
            os.environ['FLAGS_allocator_strategy'] = 'naive_best_fit'
            os.environ['FLAGS_fraction_of_cpu_memory_to_use'] = '0.27'
            
            return paddleocr.PaddleOCR(
                lang=lang, 
                show_log=False, 
                use_angle_cls=False, 
                use_gpu=False, 
                enable_mkldnn=True, 
                cpu_threads=cpu_threads()
            )
    except Exception as e:
        log.error(f"Failed to initialize PaddleOCR for {lang}: {e}")
        raise


def get_ocr(lang: str):
    global OCR_EN, OCR_JP, OCR_CH
    
    init_ocr_if_needed()
    
    if lang == "en":
        if OCR_EN is None:
            OCR_EN = _create_ocr_instance("en")
        return OCR_EN
    elif lang == "japan":
        if OCR_JP is None:
            OCR_JP = _create_ocr_instance("japan")
        return OCR_JP
    elif lang == "ch":
        if OCR_CH is None:
            OCR_CH = _create_ocr_instance("ch")
        return OCR_CH
    else:
        if OCR_EN is None:
            OCR_EN = _create_ocr_instance("en")
        return OCR_EN






def reset_ocr():
    global OCR_EN, OCR_JP, OCR_CH, paddleocr
    try:
        for obj in (OCR_EN, OCR_JP, OCR_CH):
            try:
                if obj is None:
                    continue
                for attr in ("text_detector", "text_recognizer", "text_classifier"):
                    if hasattr(obj, attr):
                        try:
                            setattr(obj, attr, None)
                        except Exception:
                            pass
            except Exception:
                pass
    finally:
        OCR_EN = None
        OCR_JP = None
        OCR_CH = None
        try:
            import importlib as _il
            _il.invalidate_caches()
        except Exception:
            pass
        try:
            mods = list(sys.modules.keys())
            for name in mods:
                if name.startswith("paddleocr") or name.startswith("ppocr"):
                    try:
                        del sys.modules[name]
                    except Exception:
                        pass
        except Exception:
            pass
        try:
            _paddle = sys.modules.get("paddle")
            if _paddle is not None:
                try:
                    if hasattr(_paddle, "device") and hasattr(_paddle.device, "cuda") and hasattr(_paddle.device.cuda, "empty_cache"):
                        _paddle.device.cuda.empty_cache()
                except Exception:
                    pass
                try:
                    if hasattr(_paddle, "framework") and hasattr(_paddle.framework, "core"):
                        core = _paddle.framework.core
                        if hasattr(core, 'set_flags'):
                            core.set_flags({})
                except Exception:
                    pass
        except Exception:
            pass
        paddleocr = None



def ocr(img, lang="en"):
    reset_timeout()
    gpu_utils.clear_gpu_cache()
    
    cache_key = _compute_ocr_cache_key(img, lang)
    if cache_key:
        cached = _ocr_result_cache.get(cache_key)
        if cached is not None:
            return cached
    o = get_ocr(lang)
    result = o.ocr(img, cls=False)
    if cache_key:
        _ocr_result_cache.set(cache_key, result)
    if _USE_GPU:
        gpu_utils.clear_gpu_cache()
    return result



def normalize_ocr_result(result):
    if not result:
        return []
    try:
        if isinstance(result, (list, tuple)):
            first = result[0] if len(result) > 0 else []
            if first is None:
                return []
            if isinstance(first, dict):
                return first.get("res") or first.get("data") or []
            if isinstance(first, (list, tuple)):
                return first
            return []
        if isinstance(result, dict):
            return result.get("res") or result.get("data") or []
    except Exception:
        return []
    return []

def parse_text_items(result):
    res = normalize_ocr_result(result)
    items = []
    for info in (res or []):
        try:
            if not info:
                continue
            if isinstance(info, dict):
                txt = info.get("text") or ""
                score = info.get("score") or 0
            else:
                txt = info[1][0] if len(info) > 1 else ""
                if len(info) > 1 and isinstance(info[1], (list, tuple)) and len(info[1]) > 1:
                    score = info[1][1]
                else:
                    score = 0
            if txt:
                items.append((str(txt), score))
        except Exception:
            continue
    return items

# ocr_line 文字识别图片，返回所有出现的文字

def ocr_line(img, lang="en"):
    reset_timeout()
    cache_key = _compute_ocr_cache_key(img, lang)
    if cache_key:
        line_key = f"line:{cache_key}"
        cached = _ocr_result_cache.get(line_key)
        if cached is not None:
            return cached
    raw = ocr(img, lang)
    items = parse_text_items(raw)
    text = ""
    for candidate, _ in (items or []):
        text += candidate
    if cache_key:
        line_key = f"line:{cache_key}"
        _ocr_result_cache.set(line_key, text)
    if _USE_GPU:
        gpu_utils.clear_gpu_cache()
    return text


def ocr_digits(img):
    reset_timeout()
    cache_key = _compute_ocr_cache_key(img, "en")
    if cache_key:
        digit_key = f"digit:{cache_key}"
        cached = _ocr_result_cache.get(digit_key)
        if cached is not None:
            return cached
    raw = get_ocr("en").ocr(img, cls=False)
    items = parse_text_items(raw)
    if _USE_GPU:
        gpu_utils.clear_gpu_cache()
    if not items:
        result = ""
    else:
        best, _ = max(items, key=lambda x: x[1])
        result = best
    if cache_key:
        digit_key = f"digit:{cache_key}"
        _ocr_result_cache.set(digit_key, result)
    return result

# find_text_pos 查找目标文字在图片中的位置
def find_text_pos(ocr_result, target):
    threshold = 0.6
    result = None
    for text_info in ocr_result:
        if len(text_info) > 0:
            s = SequenceMatcher(None, target, text_info[0][1][0])
            if s.ratio() > threshold:
                result = text_info[0]
                threshold = s.ratio()
    return result


def find_similar_text(target_text, ref_text_list, threshold=0):
    result = ""
    for ref_text in ref_text_list:
        s = SequenceMatcher(None, target_text, ref_text)
        if s.ratio() > threshold:
            result = ref_text
            threshold = s.ratio()
    return result
