import time
import random
import subprocess
import struct
import socket
from typing import Optional

import cv2
import numpy as np

import bot.conn.os as os
import bot.base.log as logger
import threading

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

    repetitive_click_name = None
    repetitive_click_count = 0
    repetitive_other_clicks = 0
    last_click_time = 0.0
    min_click_interval = 0.15

    screen_width = None
    screen_height = None
    screencap_cmd = None
    screencap_lock = None
    pixel_buffer = None
    last_dims = None

    def __init__(self):
        self.recent_click_buckets = []
        self.fallback_block_until = 0.0
        self.trigger_decision_reset = False
        self.last_recovery_time = 0
        self.screencap_lock = threading.Lock()
        
        self._cached_frame = None
        self._cache_time = 0.0
        self._cache_max_age = 0.050
        
        transport_cmd = f'host:transport:{self.config.device_name}'
        self._transport_bytes = f'{len(transport_cmd):04x}{transport_cmd}'.encode()
        self._exec_bytes = b'000eexec:screencap'
        
        try:
            from bot.base.runtime_state import load_persisted
            load_persisted()
        except Exception:
            pass

    def _capture_via_socket(self):
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5.0)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 2097152)
            sock.connect(('127.0.0.1', 5037))
            sock.sendall(self._transport_bytes)
            resp = sock.recv(4)
            if not resp or b'OKAY' not in resp:
                return None
            sock.sendall(self._exec_bytes)
            resp = sock.recv(4)
            if not resp or b'OKAY' not in resp:
                return None
            chunks = []
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
            return b''.join(chunks) if chunks else None
        except Exception:
            return None
        finally:
            if sock:
                try:
                    sock.close()
                except Exception:
                    pass

    def screencap(self):
        now = time.time()
        if self._cached_frame is not None and (now - self._cache_time) < self._cache_max_age:
            return self._cached_frame
        
        for attempt in range(3):
            raw = self._capture_via_socket()
            
            if raw is None or len(raw) < 16:
                time.sleep(0.1)
                continue
            
            try:
                w, h, fmt = struct.unpack('<III', raw[:12])
                if w <= 0 or h <= 0 or w > 10000 or h > 10000:
                    time.sleep(0.1)
                    continue
                
                pixel_size = w * h * 4
                header_size = 16 if len(raw) >= 16 + pixel_size else 12
                
                if len(raw) < header_size + pixel_size:
                    time.sleep(0.1)
                    continue
                
                img = np.frombuffer(raw[header_size:header_size + pixel_size], dtype=np.uint8).reshape((h, w, 4))
                
                if fmt == 5:
                    img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
                else:
                    img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
                
                self._cached_frame = img
                self._cache_time = time.time()
                
                return img
            except Exception:
                time.sleep(0.1)
                continue
        
        self._cached_frame = None
        return None

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

        if isinstance(click_key, str):
            click_key = click_key.strip()

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

        current_name = self.repetitive_click_name.strip() if isinstance(self.repetitive_click_name, str) else self.repetitive_click_name
        is_same_key = (click_key == current_name) or (
            isinstance(click_key, str) and isinstance(current_name, str) and
            click_key.lower() == current_name.lower()
        )

        if is_same_key:
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
            x += int(max(-8, min(8, random.gauss(0, 3))))
            y += int(max(-8, min(8, random.gauss(0, 3))))
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
        min_interval = random.uniform(0.12, 0.15)
        wait_needed = max(0.0, min_interval - elapsed)
        log.debug(f"click queue: elapsed={elapsed:.3f}s, min_interval={min_interval:.3f}s, wait={wait_needed:.3f}s, name={name}")
        if wait_needed > 0:
            time.sleep(wait_needed)

    def tap(self, x, y, hold_duration):
        duration = int(max(50, min(180, random.gauss(90, 30)))) + hold_duration
        drift_x = x + random.randint(-3, 3)
        drift_y = y + random.randint(-3, 3)
        _ = self.execute_adb_shell("shell input swipe " + str(x) + " " + str(y) + " " + str(drift_x) + " " + str(drift_y) + " " + str(duration), True)
        self.last_click_time = time.time()
        time.sleep(self.config.delay)

    def init_env(self) -> None:
        try:
            result = subprocess.run(
                [self.path + "adb.exe", "-s", self.config.device_name, "shell", "echo", "ok"],
                capture_output=True, timeout=5
            )
            if result.returncode != 0:
                raise Exception(f"ADB connection failed: {result.stderr.decode()}")
            log.debug(f"ADB connection verified for {self.config.device_name}")
        except Exception as e:
            log.error(f"Failed to connect to device {self.config.device_name}: {e}")
            raise

    def reinit_connection(self):
        try:
            subprocess.run([self.path + "adb.exe", "-s", self.config.device_name, "reconnect"], 
                          capture_output=True, timeout=5)
        except Exception:
            pass
        time.sleep(0.2)
        self._screen_width = None
        self._screen_height = None
        self._cached_frame = None
        self._cache_time = 0.0
        self.init_env()

    def _get_screen_dimensions(self):
        if self._screen_width is not None and self._screen_height is not None:
            return self._screen_width, self._screen_height
        try:
            result = subprocess.run(
                [self.path + "adb.exe", "-s", self.config.device_name, "shell", "wm", "size"],
                capture_output=True, timeout=5
            )
            if result.returncode == 0:
                output = result.stdout.decode().strip()
                for line in output.split('\n'):
                    if 'x' in line:
                        parts = line.split(':')[-1].strip().split('x')
                        if len(parts) == 2:
                            self._screen_width = int(parts[0])
                            self._screen_height = int(parts[1])
                            return self._screen_width, self._screen_height
        except Exception:
            pass
        return None, None

    def _get_screen_subprocess(self):
        for attempt in range(2):
            try:
                result = subprocess.run(
                    [self.path + "adb.exe", "-s", self.config.device_name, "exec-out", "screencap"],
                    capture_output=True, timeout=10
                )
                if result.returncode != 0 or not result.stdout:
                    if attempt < 1:
                        continue
                    return None
                raw = result.stdout
                if len(raw) < 16:
                    if attempt < 1:
                        continue
                    return None
                w, h, fmt = struct.unpack('<III', raw[:12])
                if w <= 0 or h <= 0 or w > 10000 or h > 10000:
                    if attempt < 1:
                        continue
                    return None
                pixel_size = w * h * 4
                if len(raw) == 16 + pixel_size:
                    header_size = 16
                elif len(raw) == 12 + pixel_size:
                    header_size = 12
                elif len(raw) > 16 + pixel_size:
                    header_size = 16
                elif len(raw) > 12 + pixel_size:
                    header_size = 12
                else:
                    if attempt < 1:
                        continue
                    return None
                data = np.frombuffer(raw[header_size:header_size + pixel_size], dtype=np.uint8)
                img = data.reshape((h, w, 4))
                if fmt == 5:
                    return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
                else:
                    return cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
            except Exception:
                if attempt < 1:
                    continue
                return None
        return None

    def get_screen(self, to_gray=False):
        with self.screencap_lock:
            img = self.screencap()
        if img is None:
            return None
        if to_gray:
            return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return img

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
        
        x1 += int(max(-10, min(10, random.gauss(0, 4))))
        y1 += int(max(-10, min(10, random.gauss(0, 4))))
        x2 += int(max(-10, min(10, random.gauss(0, 4))))
        y2 += int(max(-10, min(10, random.gauss(0, 4))))
        
        duration = int(duration * random.uniform(0.94, 1.06))
        
        _ = self.execute_adb_shell("shell input swipe " + str(x1) + " " + str(y1) + " " + str(x2) + " " + str(y2) + " " + str(duration), True)
        time.sleep(self.config.delay)

    def swipe_and_hold(self, x1, y1, x2, y2, swipe_duration, hold_duration, name=""):
        if INPUT_BLOCKED:
            return
        
        x1 += int(max(-10, min(10, random.gauss(0, 4))))
        y1 += int(max(-10, min(10, random.gauss(0, 4))))
        x2 += int(max(-10, min(10, random.gauss(0, 4))))
        y2 += int(max(-10, min(10, random.gauss(0, 4))))
        
        swipe_duration = int(swipe_duration * random.uniform(0.94, 1.06))
        hold_duration = int(hold_duration * random.uniform(0.94, 1.06))
        
        reverse_y = y2 - 28 if y2 > y1 else y2 + 28
        
        _ = self.execute_adb_shell("shell input swipe " + str(x1) + " " + str(y1) + " " + str(x2) + " " + str(y2) + " " + str(swipe_duration), True)
        _ = self.execute_adb_shell("shell input swipe " + str(x2) + " " + str(y2) + " " + str(x2) + " " + str(reverse_y) + " " + str(hold_duration), True)
        
        time.sleep(self.config.delay)

    # ===== common =====

    # execute_adb_shell 执行adb命令
    def execute_adb_shell(self, cmd, sync):
        cmd_str = self.path + "adb -s " + self.config.device_name + " " + cmd
        proc = os.run_cmd(cmd_str)
        if sync:
            try:
                proc.communicate(timeout=10)
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
        if time.time() - self.last_recovery_time < 10:
            return
        self.last_recovery_time = time.time()
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
            component = f"{package_name}/{activity_name}"
            cmd = f"shell am start -n {component}"
            self.execute_adb_shell(cmd, True)
            log.debug("starting app using ADB: " + component)
        else:
            cmd = f"shell monkey -p {package_name} -c android.intent.category.LAUNCHER 1"
            self.execute_adb_shell(cmd, True)
            log.debug("starting app using ADB: " + package_name)

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

    def destroy(self):
        self._cached_frame = None
