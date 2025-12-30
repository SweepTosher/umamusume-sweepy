import time
import random
from typing import Optional

import cv2
import uiautomator2 as u2

import bot.conn.os as os
import bot.base.log as logger
import threading

from bot.base.common import ImageMatchMode
from bot.base.point import ClickPoint, ClickPointType
from bot.conn.ctrl import AndroidController
from bot.recog.image_matcher import template_match, image_match
from config import CONFIG, Config
from dataclasses import dataclass, field
from module.umamusume.asset.template import REF_DONT_CLICK

log = logger.get_logger(__name__)

INPUT_BLOCKED = False


@dataclass
class U2AndroidConfig:
    _device_name: str
    delay: float
    bluestacks_config_path: Optional[str] = None
    bluestacks_config_keyword: Optional[str] = None

    _bluestacks_port: Optional[str] = field(init=False, repr=False, default=None)

    @property
    def device_name(self) -> str:
        bluestacks_port = self.bluestacks_port
        if bluestacks_port is not None:
            return f"127.0.0.1:{bluestacks_port}"
        return self._device_name

    @property
    def bluestacks_port(self) -> Optional[str]:
        if self._bluestacks_port is not None:
            return self._bluestacks_port
        if self.bluestacks_config_path and self.bluestacks_config_keyword:
            with open(self.bluestacks_config_path) as file:
                self._bluestacks_port = next((
                    line.split('=')[1].strip().strip('"')
                    for line in file
                    if self.bluestacks_config_keyword in line
                ), None)
        return self._bluestacks_port

    @staticmethod
    def load(config: Config):
        return U2AndroidConfig(
            _device_name=config.bot.auto.adb.device_name,
            delay=config.bot.auto.adb.delay,
            bluestacks_config_path=config.bot.auto.adb.bluestacks_config_path,
            bluestacks_config_keyword=config.bot.auto.adb.bluestacks_config_keyword,
        )


class U2AndroidController(AndroidController):
    config = U2AndroidConfig.load(CONFIG)

    path = "deps\\adb\\"
    recent_point = None
    recent_operation_time = None
    same_point_operation_interval = 0.27
    u2client = None

    repetitive_click_name = None
    repetitive_click_count = 0
    repetitive_other_clicks = 0
    last_click_time = 0.0
    min_click_interval = 0.3

    def __init__(self):
        self.recent_click_buckets = []
        self.fallback_block_until = 0.0
        self.trigger_decision_reset = False
        try:
            from bot.base.runtime_state import load_persisted
            load_persisted()
        except Exception:
            pass

    def in_fallback_block(self, name):
        if isinstance(name, str) and name == "Default fallback click":
            if time.time() < getattr(self, "fallback_block_until", 0.0):
                return True
        return False

    def update_click_buckets(self, x, y):
        bucket = (int(x/25), int(y/25))
        lst = getattr(self, "recent_click_buckets", None)
        if lst is None:
            self.recent_click_buckets = []
            lst = self.recent_click_buckets
        if bucket not in lst:
            lst.append(bucket)
            if len(lst) > 2:
                lst.pop(0)
            self.fallback_block_until = time.time() + 2.0

    def build_click_key(self, x, y, name):
        if isinstance(name, str) and name.strip() != "":
            return name.strip()
        return f"{int(x/50)}:{int(y/50)}"

    def update_repetitive_click(self, click_key):
        try:
            from bot.base.runtime_state import update_repetitive, get_repetitive_threshold
            repetitive_threshold = int(get_repetitive_threshold())
        except Exception:
            repetitive_threshold = 11
            update_repetitive = None

        if self.repetitive_click_name is None:
            self.repetitive_click_name = click_key
            self.repetitive_click_count = 1
            self.repetitive_other_clicks = 0
            try:
                if update_repetitive:
                    update_repetitive(self.repetitive_click_count, self.repetitive_other_clicks)
            except Exception:
                pass
            return False
        if click_key == self.repetitive_click_name:
            self.repetitive_click_count += 1
        else:
            self.repetitive_other_clicks += 1
            if self.repetitive_other_clicks >= 2:
                self.repetitive_click_name = click_key
                self.repetitive_click_count = 1
                self.repetitive_other_clicks = 0
        try:
            if update_repetitive:
                update_repetitive(self.repetitive_click_count, self.repetitive_other_clicks)
        except Exception:
            pass

        if self.repetitive_click_name == click_key and self.repetitive_click_count >= repetitive_threshold:
            try:
                self.recover_home_and_reopen()
            finally:
                self.repetitive_click_name = None
                self.repetitive_click_count = 0
                self.repetitive_other_clicks = 0
                try:
                    if update_repetitive:
                        update_repetitive(0, 0)
                except Exception:
                    pass
            time.sleep(self.config.delay)
            return True
        return False

    def safety_dont_click(self, x, y):
        if 263 <= x <= 458 and 559 <= y <= 808:
            screen_gray = self.get_screen(to_gray=True)
            match = image_match(screen_gray, REF_DONT_CLICK)
            if getattr(match, "find_match", False):
                log.info("unsafe click blocked")
                return True
        return False

    def randomize_and_clamp(self, x, y, random_offset, max_x, max_y):
        if random_offset:
            x += random.randint(-5, 5)
            y += random.randint(-5, 5)
        if x >= max_x:
            x = max_x-1
        if y >= max_y:
            y = max_y-1
        if x < 0:
            x = 1
        if y <= 0:
            y = 1
        return x, y

    def wait_click_interval(self, name):
        now = time.time()
        elapsed = now - self.last_click_time if hasattr(self, "last_click_time") else now
        min_interval = getattr(self, "min_click_interval", 0.3)
        wait_needed = max(0.0, min_interval - elapsed)
        log.debug(f"click queue: elapsed={elapsed:.3f}s, min_interval={min_interval:.3f}s, wait={wait_needed:.3f}s, name={name}")
        if wait_needed > 0:
            time.sleep(wait_needed)

    def tap(self, x, y, hold_duration):
        duration = random.randint(0, 166) + hold_duration
        _ = self.execute_adb_shell("shell input swipe " + str(x) + " " + str(y) + " " + str(x) + " " + str(y) + " " + str(duration), True)
        self.last_click_time = time.time()
        time.sleep(self.config.delay)

    # init_env 初始化环境
    def init_env(self) -> None:
        try:
            # Short timeout for initial connection attempt
            self.u2client = u2.connect(self.config.device_name)
            # Try a simple RPC to verify connection
            _ = self.u2client.window_size()
        except Exception as e:
            log.warning(f"Initial u2 connection failed: {e}. Retrying with forward cleanup...")
            try:
                # Clean forwards which often cause 7912 port conflicts on Windows
                subprocess.run([self.path + "adb.exe", "-s", self.config.device_name, "forward", "--remove-all"], 
                             capture_output=True, timeout=5)
                time.sleep(0.5)
                self.u2client = u2.connect(self.config.device_name)
            except Exception as e2:
                log.error(f"Failed to connect to device {self.config.device_name}: {e2}")
                raise

    # get_screen 获取图片
    def get_screen(self, to_gray=False):
        try:
            cur_screen = self.u2client.screenshot(format='opencv')
        except Exception:
            time.sleep(0.05)
            try:
                cur_screen = self.u2client.screenshot(format='opencv')
            except Exception:
                return None
        try:
            if cur_screen is None or getattr(cur_screen, 'size', 0) == 0:
                return None
            h, w = cur_screen.shape[:2]
            if h < 100 or w < 100:
                return None
            if to_gray:
                return cv2.cvtColor(cur_screen, cv2.COLOR_BGR2GRAY)
            return cur_screen
        except Exception:
            return None

    # ===== ctrl =====
    def click_by_point(self, point: ClickPoint, random_offset=True, hold_duration=0):
        if INPUT_BLOCKED:
            return
        if self.recent_point is not None:
            if self.recent_point == point and time.time() - self.recent_operation_time < self.same_point_operation_interval:
                log.warning("request for a same point too frequently")
                return
        if point.target_type == ClickPointType.CLICK_POINT_TYPE_COORDINATE:
            self.click(point.coordinate.x, point.coordinate.y, name=point.desc, random_offset=random_offset, hold_duration=hold_duration)
        elif point.target_type == ClickPointType.CLICK_POINT_TYPE_TEMPLATE:
            cur_screen = self.get_screen(to_gray=True)
            if point.template.image_match_config.match_mode == ImageMatchMode.IMAGE_MATCH_MODE_TEMPLATE_MATCH:
                match_result = image_match(cur_screen, point.template)
                if getattr(match_result, "find_match", False):
                    self.click(match_result.center_point[0], match_result.center_point[1], name=point.desc, random_offset=random_offset, hold_duration=hold_duration)
        self.recent_point = point
        self.recent_operation_time = time.time()

    def click(self, x, y, name="", random_offset=True, max_x=720, max_y=1280, hold_duration=0):
        if INPUT_BLOCKED:
            return
        if name != "":
            log.debug("click >> " + name)

        if self.in_fallback_block(name):
            return
        self.update_click_buckets(x, y)

        click_key = self.build_click_key(x, y, name)
        if self.update_repetitive_click(click_key):
            return

        try:
            if self.safety_dont_click(x, y):
                return
        except Exception as e:
            log.info("wtf")

        x, y = self.randomize_and_clamp(x, y, random_offset, max_x, max_y)
        
        self.wait_click_interval(name)
        self.tap(x, y, hold_duration)

    def swipe(self, x1=1025, y1=550, x2=1025, y2=550, duration=0.2, name=""):
        if INPUT_BLOCKED:
            return
        if name != "":
            log.debug("swipe >> " + name)
        
        offset_x1 = random.randint(-5, 5)
        offset_y1 = random.randint(-5, 5)
        offset_x2 = random.randint(-5, 5)
        offset_y2 = random.randint(-5, 5)
        
        x1 += offset_x1
        y1 += offset_y1
        x2 += offset_x2
        y2 += offset_y2
        
        _ = self.execute_adb_shell("shell input swipe " + str(x1) + " " + str(y1) + " " + str(x2) + " " + str(y2) + " " + str(duration), True)
        time.sleep(self.config.delay)

    # ===== common =====

    # execute_adb_shell 执行adb命令
    def execute_adb_shell(self, cmd, sync):
        cmd_str = self.path + "adb -s " + self.config.device_name + " " + cmd
        proc = os.run_cmd(cmd_str)
        if sync:
            try:
                # Add a broad 30s timeout to prevent hanging the main loop
                proc.communicate(timeout=30)
            except subprocess.TimeoutExpired:
                log.error(f"ADB command timed out: {cmd_str}")
                proc.kill()
                proc.communicate()
        else:
            def _wait():
                try:
                    proc.communicate(timeout=60)
                except Exception:
                    proc.kill()
            threading.Thread(target=_wait, daemon=True).start()
        return proc

    def recover_home_and_reopen(self):
        try:
            log.info("rannnnn")
            self.execute_adb_shell("shell input keyevent 3", True)
            time.sleep(0.8)
        except Exception:
            pass
        try:
            self.execute_adb_shell("shell monkey -p com.cygames.umamusume -c android.intent.category.LAUNCHER 1", True)
            time.sleep(1.2)
        except Exception:
            pass
        self.trigger_decision_reset = True

    def start_app(self, package_name, activity_name=None):
        if activity_name:
            # Use direct ADB command to bypass uiautomator2 split APK issues
            component = f"{package_name}/{activity_name}"
            cmd = f"shell am start -n {component}"
            self.execute_adb_shell(cmd, True)
            log.debug("starting app using ADB: " + component)
        else:
            # Fallback to uiautomator2 method (may have split APK issues)
            self.u2client.app_start(package_name)
            log.debug("starting app <" + package_name + ">")

    # get_front_activity 获取前台正在运行的应用
    def get_front_activity(self):

        rsp = self.execute_adb_shell("shell \"dumpsys window windows | grep \"Current\"\"", True).communicate()
        log.debug(str(rsp))
        return str(rsp)

    # get_devices 获取adb连接设备状态
    def get_devices(self):
        p = os.run_cmd(self.path + "adb devices").communicate()
        devices = p[0].decode()
        log.debug(devices)
        return devices

    # connect_to_device 连接至设备
    def connect_to_device(self):
        p = os.run_cmd(self.path + "adb connect " + self.config.device_name).communicate()
        log.debug(p[0].decode())

    # kill_adb_server 停止adb-server
    def kill_adb_server(self):
        p = os.run_cmd(self.path + "adb kill-server").communicate()
        log.debug(p[0].decode())

    # check_file_exist 判断文件是否存在
    def check_file_exist(self, file_path, file_name):
        rsp = self.execute_adb_shell("shell ls " + file_path, True).communicate()
        file_list = rsp[0].decode()
        log.debug(str("ls file result:" + file_list))
        return file_name in file_list

    # push_file 推送文件
    def push_file(self, src, dst):
        self.execute_adb_shell("push " + src + " " + dst, True)

    # get_device_os_info 获取系统信息
    def get_device_os_info(self):
        rsp = self.execute_adb_shell("shell getprop ro.build.version.sdk", True).communicate()
        os_info = rsp[0].decode().replace('\r', '').replace('\n', '')
        log.debug("device os info: " + os_info)
        return os_info

    # get_device_cpu_info 获取cpu信息
    def get_device_cpu_info(self):
        rsp = self.execute_adb_shell("shell getprop ro.product.cpu.abi", True).communicate()
        cpu_info = rsp[0].decode().replace('\r', '').replace('\n', '')
        log.debug("device cpu info: " + cpu_info)
        return cpu_info

    # destroy 销毁
    def destroy(self):
        try:
            self.u2client = None
        except Exception:
            pass
