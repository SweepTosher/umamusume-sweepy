import sys
import threading
import subprocess
import os
import yaml
import time
import random
import datetime

import torch

import cv2
import bot.base.log as logger
import bot.base.gpu_utils as gpu_utils

try:
    cores = str(os.cpu_count() or 1)
    os.environ.setdefault("MKL_NUM_THREADS", cores)
    os.environ.setdefault("OPENBLAS_NUM_THREADS", cores)
    os.environ.setdefault("VECLIB_MAXIMUM_THREADS", cores)
    cv2.setUseOptimized(True)
    cv2.setNumThreads(int(cores))
    try:
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_SILENT)
    except Exception:
        pass
    try:
        os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
    except Exception:
        pass
except Exception:
    pass

from bot.base.task import TaskStatus
import bot.conn.u2_ctrl as u2_ctrl
from bot.base.manifest import register_app
from bot.engine.scheduler import scheduler
from module.umamusume.manifest import UmamusumeManifest
from uvicorn import run

log = logger.get_logger(__name__)
_gpu_available = gpu_utils.detect_gpu_capabilities()
_opencv_gpu = gpu_utils.configure_opencv_gpu()

start_time = 0
end_time = 24
KEEPALIVE_ACTIVE = True
DAILY_WAIT_OFFSET = random.randint(16, 188)
DAILY_OFFSET_DAY = datetime.date.today()

def _get_adb_path():
    return os.path.join("deps", "adb", "adb.exe")

def _run_adb(args, timeout=15):
    adb_path = _get_adb_path()
    return subprocess.run([adb_path] + args, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)

def restart_adb_server():
    try:
        _run_adb(["kill-server"], timeout=10)
        time.sleep(1)
    except Exception:
        pass
    try:
        result = _run_adb(["start-server"], timeout=15)
        time.sleep(2)
        return result.returncode == 0
    except Exception:
        return False

def check_adb_server_status():
    try:
        result = _run_adb(["version"], timeout=5)
        return result.returncode == 0
    except Exception:
        return False

def get_adb_devices():
    try:
        result = _run_adb(["devices"], timeout=10)
        if result.returncode != 0:
            return []
        devices = []
        lines = result.stdout.strip().split('\n')[1:]
        for line in lines:
            if line.strip() and '\t' in line:
                device_id, status = line.split('\t')
                if status == 'device' or status == 'offline':
                    devices.append(device_id)
        return devices
    except Exception:
        return []

def select_device():
    devices = get_adb_devices()
    if not devices:
        return None
    if len(devices) == 1:
        return devices[0]
    while True:
        try:
            choice = input(f"\nSelect device (1-{len(devices)}): ").strip()
            choice_num = int(choice)
            if 1 <= choice_num <= len(devices):
                return devices[choice_num - 1]
        except (ValueError, KeyboardInterrupt):
            return None

def update_config(device_name):
    try:
        with open("config.yaml", 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        config['bot']['auto']['adb']['device_name'] = device_name
        with open("config.yaml", 'w', encoding='utf-8') as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
        return True
    except Exception:
        return False

def uninstall_uiautomator(device_id):
    packages = [
        "com.github.uiautomator",
        "com.github.uiautomator.test",
        "com.github.uiautomator.agent",
        "com.github.uiautomator.server"
    ]
    for pkg in packages:
        try:
            _run_adb(["-s", device_id, "uninstall", pkg], timeout=10)
        except Exception:
            pass

def connect_to_device(device_id, max_retries=3):
    print(f"Connecting to {device_id}...")
    
    for attempt in range(1, max_retries + 1):
        if not check_adb_server_status() and attempt > 1:
            restart_adb_server()
        
        if ":" in device_id:
            try:
                result = _run_adb(["connect", device_id], timeout=10)
                if "connected" not in result.stdout.lower() and "already connected" not in result.stdout.lower():
                    if attempt < max_retries:
                        restart_adb_server()
                        continue
            except subprocess.TimeoutExpired:
                if attempt < max_retries:
                    restart_adb_server()
                    continue
            except Exception:
                pass
        
        devices = get_adb_devices()
        if device_id not in devices:
            if attempt < max_retries:
                restart_adb_server()
                time.sleep(2)
                continue
            return False
        
        try:
            result = _run_adb(["-s", device_id, "shell", "echo", "test"], timeout=15)
            if result.returncode == 0 and "test" in result.stdout:
                print(f"Connected to {device_id}")
                return True
        except Exception:
            pass
        
        if attempt < max_retries:
            if attempt >= 1:
                restart_adb_server()
            if ":" in device_id and attempt >= 2:
                try:
                    _run_adb(["disconnect", device_id], timeout=5)
                    time.sleep(1)
                except Exception:
                    pass
            time.sleep(attempt * 2)
    
    print(f"Failed to connect to {device_id}")
    return False

def run_health_checks(device_id):
    try:
        _run_adb(["-s", device_id, "exec-out", "screencap", "-p"], timeout=15)
        _run_adb(["-s", device_id, "shell", "input", "keyevent", "0"], timeout=10)
        return True
    except Exception:
        return True

def normalize_start_end():
    global start_time, end_time
    try:
        start_time = max(0.0, min(24.0, float(start_time)))
        end_time = max(0.0, min(24.0, float(end_time)))
    except Exception:
        start_time, end_time = 0.0, 24.0

def is_in_allowed_window(now: datetime.datetime) -> bool:
    s, e = start_time, end_time
    h = now.hour + (now.minute / 60.0) + (now.second / 3600.0)
    if s == e:
        return True
    if s < e:
        return s <= h < e
    else:
        return h >= s or h < e

def next_window_start(now: datetime.datetime) -> datetime.datetime:
    s, e = start_time, end_time
    today = now.date()
    if s == e:
        return now

    sh = int(s)
    sm = int(round((s - sh) * 60))
    if sm == 60:
        sh += 1
        sm = 0
    if sh >= 24:
        sh = 0
        sm = 0

    start_today = datetime.datetime.combine(today, datetime.time(hour=sh, minute=sm))

    if s < e:
        if now < start_today:
            return start_today
        else:
            return start_today + datetime.timedelta(days=1)
    else:
        if now < start_today:
            return start_today
        else:
            return start_today + datetime.timedelta(days=1)

def refresh_daily_offset():
    global DAILY_WAIT_OFFSET, DAILY_OFFSET_DAY
    today = datetime.date.today()
    if today != DAILY_OFFSET_DAY:
        DAILY_WAIT_OFFSET = random.randint(16, 188)
        DAILY_OFFSET_DAY = today

def time_window_enforcer(device_id: str):
    global KEEPALIVE_ACTIVE
    paused = False
    paused_task_ids = set()
    
    while True:
        refresh_daily_offset()
        now = datetime.datetime.now()
        
        if is_in_allowed_window(now):
            if paused:
                time.sleep(random.randint(16, 188))
                u2_ctrl.INPUT_BLOCKED = False
                KEEPALIVE_ACTIVE = True
                for tid in list(paused_task_ids):
                    if not str(tid).startswith("CRONJOB_"):
                        try:
                            scheduler.reset_task(tid)
                        except Exception:
                            pass
                scheduler.start()
                paused = False
                paused_task_ids.clear()
        else:
            if not paused:
                time.sleep(random.randint(16, 188))
                try:
                    running = [t.task_id for t in scheduler.get_task_list() 
                              if t.task_status == TaskStatus.TASK_STATUS_RUNNING]
                except Exception:
                    running = []
                paused_task_ids = set(running)
                scheduler.stop()
                try:
                    from bot.base.purge import save_scheduler_tasks, save_scheduler_state
                    save_scheduler_tasks()
                    save_scheduler_state()
                except Exception:
                    pass
                u2_ctrl.INPUT_BLOCKED = True
                KEEPALIVE_ACTIVE = False
                try:
                    _run_adb(["-s", device_id, "shell", "am", "force-stop", 
                             "com.cygames.umamusume"], timeout=5)
                except Exception:
                    pass
                paused = True
            
            next_start = next_window_start(now)
            total_sec = int((next_start - now).total_seconds()) + int(DAILY_WAIT_OFFSET)
            if total_sec < 0:
                total_sec = 0
            print(f"Time until next run: {total_sec}s")
        
        time.sleep(60)

if __name__ == '__main__':
    try:
        from bot.base.purge import acquire_instance_lock
        acquire_instance_lock()
    except Exception:
        pass

    selected_device = None
    if os.environ.get("UAT_AUTORESTART", "0") == "1":
        try:
            with open("config.yaml", 'r', encoding='utf-8') as f:
                cfg = yaml.safe_load(f)
            selected_device = cfg['bot']['auto']['adb']['device_name']
            if not selected_device:
                selected_device = select_device()
        except Exception:
            selected_device = select_device()
    else:
        selected_device = select_device()
    
    if selected_device is None:
        print("No device selected")
        sys.exit(1)
    
    if not connect_to_device(selected_device, max_retries=3):
        print("Connection failed")
        sys.exit(1)
    
    uninstall_uiautomator(selected_device)
    
    if not run_health_checks(selected_device):
        print("Health checks failed")
        sys.exit(1)
    
    if not update_config(selected_device):
        print("Config update failed")
        sys.exit(1)
    
    normalize_start_end()
    
    enforcer_thread = threading.Thread(target=time_window_enforcer, 
                                       args=(selected_device,), daemon=True)
    enforcer_thread.start()
    
    from bake_templates import bake, BAKED_PATH
    if not BAKED_PATH.exists():
        print("Baking character templates...")
        bake()

    from module.umamusume.script.cultivate_task.event.manifest import warmup_event_index
    warmup_event_index()
    
    from bot.recog.image_matcher import preload_templates, init_executor
    preload_templates('resource')
    init_executor()
    
    register_app(UmamusumeManifest)
    
    restored = False
    was_active = None
    try:
        from bot.base.purge import load_saved_tasks, load_scheduler_state
        restored = load_saved_tasks()
        was_active = load_scheduler_state()
    except Exception:
        pass
    
    scheduler_thread = threading.Thread(target=scheduler.init, args=())
    scheduler_thread.start()
    
    try:
        if was_active is True or (was_active is None and restored):
            scheduler.start()
    except Exception:
        pass
    
    print("UAT running on http://127.0.0.1:8071")
    if os.environ.get("UAT_AUTORESTART", "0") != "1":
        threading.Thread(target=lambda: (time.sleep(1), __import__('webbrowser').open("http://127.0.0.1:8071")), daemon=True).start()
    
    try:
        run("bot.server.handler:server", host="127.0.0.1", port=8071, log_level="error")
    finally:
        if ":" in selected_device:
            try:
                _run_adb(["disconnect", selected_device], timeout=5)
            except Exception:
                pass