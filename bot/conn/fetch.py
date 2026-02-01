import cv2
import time
from typing import Dict, Any, Optional
from bot.conn.u2_ctrl import U2AndroidController
from bot.recog.image_matcher import image_match, compare_color_equal
from bot.recog.ocr import ocr_line
from bot.recog.energy_scanner import scan_base_energy
from module.umamusume.asset import MOTIVATION_LIST

shared_controller: Optional[U2AndroidController] = None


def get_shared_controller() -> U2AndroidController:
    global shared_controller
    if shared_controller is None:
        shared_controller = U2AndroidController()
        shared_controller.init_env()
    return shared_controller

def ocr_text(gray):
    return ocr_line(gray, lang="en").strip()

def ensure_top_img(img: Optional[any]) -> any:
    if img is None:
        try:
            ctrl = get_shared_controller()
            img = ctrl.get_screen(to_gray=False)
        except Exception:
            img = None
    if img is not None and getattr(img, 'shape', None) is not None and img.shape[0] >= 186:
        return img[:186, :]
    return img

def read_energy(img: Optional[any] = None) -> int:
    if img is None:
        try:
            ctrl = get_shared_controller()
            img = ctrl.get_screen(to_gray=False)
        except Exception:
            return 0
    if img is None or img.size == 0:
        return 0
    return scan_base_energy(img)

def read_year(img: Optional[any] = None) -> str:
    if img is None:
        top = ensure_top_img(None)
    else:
        top = img
    if top is None or top.size == 0:
        return "Unknown"
    rois = [
        (40, 120, 0, 1280),
        (60, 140, 0, 1280),
        (74, 100, 250, 575),
    ]
    for y1, y2, x1, x2 in rois:
        sub = top[y1:y2, x1:x2]
        if sub.size == 0:
            continue
        gray = cv2.cvtColor(sub, cv2.COLOR_BGR2GRAY)
        t = ocr_text(gray).lower()
        if not t:
            continue
        if "junior" in t:
            return "Junior"
        if "classic" in t:
            return "Classic"
        if "senior" in t:
            return "Senior"
        if "finale" in t or "final" in t:
            return "Finals"
    return "Unknown"

def read_mood(img: Optional[any] = None) -> Optional[int]:
    if img is None:
        top = ensure_top_img(None)
    else:
        top = img
    if top is None or top.size == 0:
        return None
    gray = cv2.cvtColor(top, cv2.COLOR_BGR2GRAY)
    for i in range(len(MOTIVATION_LIST)):
        res = image_match(gray, MOTIVATION_LIST[i])
        if res.find_match:
            return i + 1
    return None

def fetch_state(img: Optional[any] = None) -> Dict[str, Any]:
    top = ensure_top_img(img)
    return {"year": read_year(top), "mood": read_mood(top), "energy": read_energy(top)}
