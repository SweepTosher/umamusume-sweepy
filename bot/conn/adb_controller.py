import time
import random
import struct
import cv2
import numpy as np
import threading
import subprocess
import shlex
from typing import Optional
from bot.conn.adb_client import AdbClient
from bot.conn.ctrl import AndroidController
from bot.base.point import ClickPoint, ClickPointType
from bot.recog.image_matcher import image_match
from config import CONFIG

class AdbController(AndroidController):
    def __init__(self, device_name: str):
        self.client = AdbClient(device_name)
        self.lock = threading.Lock()
        self.last_img = None
        self.last_ts = 0.0
        self.max_age = 0.120
        self.last_click = 0.0
        self.trigger_decision_reset = False

    def init_env(self) -> None:
        try:
            res = self.client.run_cmd(["shell", "echo", "ok"])
            if res.returncode != 0: raise Exception(f"ADB failed: {res.stderr}")
        except Exception: raise

    def get_screen(self, to_gray=False, force=False):
        with self.lock:
            now = time.time()
            if not force and self.last_img is not None and (now - self.last_ts) < self.max_age:
                img = self.last_img
            else:
                img = self.capture()
                if img is not None:
                    self.last_img = img
                    self.last_ts = time.time()
        if img is None: return None
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if to_gray else img

    def capture(self) -> Optional[np.ndarray]:
        for _ in range(3):
            raw = self.client.capture_screen_raw()
            if not raw or len(raw) < 16:
                time.sleep(0.1)
                continue
            try:
                w, h, fmt = struct.unpack('<III', raw[:12])
                pixel_size = w * h * 4
                header_size = 16 if len(raw) >= 16 + pixel_size else 12
                if len(raw) < header_size + pixel_size:
                    time.sleep(0.1)
                    continue
                img = np.frombuffer(raw[header_size:header_size + pixel_size], dtype=np.uint8).reshape((h, w, 4))
                return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR if fmt == 5 else cv2.COLOR_RGBA2BGR)
            except Exception: time.sleep(0.1)
        return None

    def click(self, x, y, name="", random_offset=True, hold_duration=0):
        from bot.base.runtime_state import get_state
        if get_state().get("input_blocked"): return
        if random_offset:
            x += int(max(-8, min(8, random.gauss(0, 3))))
            y += int(max(-8, min(8, random.gauss(0, 3))))
        x, y = max(1, min(719, x)), max(1, min(1279, y))
        elapsed = time.time() - self.last_click
        wait = max(0.0, random.uniform(0.06, 0.09) - elapsed)
        if wait > 0: time.sleep(wait)
        if hold_duration == 0:
            self.execute_adb_shell(f"input tap {x} {y}", True)
        else:
            duration = int(max(50, min(180, random.gauss(90, 30)))) + hold_duration
            dx, dy = x + random.randint(-3, 3), y + random.randint(-3, 3)
            self.execute_adb_shell(f"input swipe {x} {y} {dx} {dy} {duration}", True)
        self.last_click = time.time()
        time.sleep(CONFIG.bot.auto.adb.delay)

    def swipe(self, x1, y1, x2, y2, duration=0.2, name=""):
        from bot.base.runtime_state import get_state
        if get_state().get("input_blocked"): return
        if y1 < 30:
            self.click(x1, y1, name=name, random_offset=True, hold_duration=0)
            return
        x1 += int(max(-10, min(10, random.gauss(0, 4))))
        y1 += int(max(-10, min(10, random.gauss(0, 4))))
        x2 += int(max(-10, min(10, random.gauss(0, 4))))
        y2 += int(max(-10, min(10, random.gauss(0, 4))))
        x1, y1 = max(1, min(719, x1)), max(1, min(1279, y1))
        x2, y2 = max(1, min(719, x2)), max(1, min(1279, y2))
        d = int(duration * 1000 * random.uniform(0.94, 1.06))
        self.execute_adb_shell(f"input swipe {x1} {y1} {x2} {y2} {d}", True)
        time.sleep(CONFIG.bot.auto.adb.delay)

    def start_app(self, package, activity=None):
        cmd = f"am start -n {package}/{activity}" if activity else f"monkey -p {package} -c android.intent.category.LAUNCHER 1"
        self.execute_adb_shell(cmd, True)

    def destroy(self):
        self.last_img = None

    def click_by_point(self, point: ClickPoint, random_offset=True, hold_duration=0):
        if point.target_type == ClickPointType.CLICK_POINT_TYPE_COORDINATE:
            self.click(point.coordinate.x, point.coordinate.y, name=point.desc, random_offset=random_offset, hold_duration=hold_duration)
        elif point.target_type == ClickPointType.CLICK_POINT_TYPE_TEMPLATE:
            gray = self.get_screen(to_gray=True)
            res = image_match(gray, point.template)
            if res.find_match:
                self.click(res.center_point[0], res.center_point[1], name=point.desc, random_offset=random_offset, hold_duration=hold_duration)

    def execute_adb_shell(self, cmd: str, sync: bool = True):
        if cmd.startswith("shell "):
            cmd = cmd[6:]
        if sync:
            return self.client.shell(cmd, sync=True)
        else:
            adb_cmd = [self.client.adb_path, "-s", self.client.device_name, "shell"] + shlex.split(cmd)
            return subprocess.Popen(adb_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def reinit_connection(self):
        with self.client.plock:
            if self.client.psock:
                try: self.client.psock.close()
                except Exception: pass
                self.client.psock = None
        try:
            self.client.kill_server()
            time.sleep(1)
            self.client.start_server()
            time.sleep(2)
            self.client.connect()
            self.init_env()
        except Exception: pass
        self.last_img = None
        self.client.prefill_pool()

    def swipe_and_hold(self, x1, y1, x2, y2, swipe_duration, hold_duration, name=""):
        from bot.base.runtime_state import get_state
        if get_state().get("input_blocked"): return
        if y1 < 30:
            self.click(x1, y1, name=name, random_offset=True, hold_duration=0)
            return
        x1 += int(max(-10, min(10, random.gauss(0, 4))))
        y1 += int(max(-10, min(10, random.gauss(0, 4))))
        x2 += int(max(-10, min(10, random.gauss(0, 4))))
        y2 += int(max(-10, min(10, random.gauss(0, 4))))
        x1, y1 = max(1, min(719, x1)), max(1, min(1279, y1))
        x2, y2 = max(1, min(719, x2)), max(1, min(1279, y2))
        sw_d = int(swipe_duration * random.uniform(0.94, 1.06))
        ho_d = int(hold_duration * random.uniform(0.94, 1.06))
        rev_y = y2 - 28 if y2 > y1 else y2 + 28
        rev_y = max(1, min(1279, rev_y))
        self.execute_adb_shell(f"input swipe {x1} {y1} {x2} {y2} {sw_d}", True)
        time.sleep(0.05)
        self.execute_adb_shell(f"input swipe {x2} {y2} {x2} {rev_y} {ho_d}", True)
        time.sleep(CONFIG.bot.auto.adb.delay)
