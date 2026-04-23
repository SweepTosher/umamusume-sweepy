import time
from bot.conn.adb_controller import AdbController
from bot.recog.image_matcher import image_match
from module.umamusume.asset.template import REF_DONT_CLICK
from bot.base.runtime_state import update_repetitive, get_repetitive_threshold, get_state

class Automator:
    def __init__(self, ctrl: AdbController):
        self.ctrl = ctrl
        self.click_name = None
        self.click_cnt = 0
        self.other_cnt = 0
        self.last_recovery = 0
        self.grace_ts = 0.0

    def check_safety(self, x, y) -> bool:
        if 263 <= x <= 458 and 559 <= y <= 808:
            gray = self.ctrl.get_screen(to_gray=True)
            if image_match(gray, REF_DONT_CLICK).find_match: return True
        return False

    def update_repetitive(self, x, y, name):
        now = time.time()
        if now < self.grace_ts: return False
        click_key = name if name else f"{int(x/50)}:{int(y/50)}"
        threshold = get_repetitive_threshold()
        if self.click_name == click_key:
            self.click_cnt += 1
        else:
            self.other_cnt += 1
            if self.other_cnt >= 2:
                self.click_name = click_key
                self.click_cnt = 1
                self.other_cnt = 0
        update_repetitive(self.click_cnt, self.other_cnt)
        if self.click_cnt >= threshold:
            self.recover()
            return True
        return False

    def recover(self):
        if time.time() - self.last_recovery < 10: return
        self.last_recovery = time.time()
        self.grace_ts = time.time() + 60
        try:
            for _ in range(3):
                self.ctrl.execute_adb_shell("shell input keyevent 4", True)
                time.sleep(0.4)
            self.ctrl.execute_adb_shell("shell input keyevent 3", True)
            time.sleep(0.8)
            self.ctrl.start_app("com.cygames.umamusume")
            time.sleep(2.0)
        except Exception: pass
        self.click_name = None
        self.click_cnt = 0
        self.other_cnt = 0
        update_repetitive(0, 0)
