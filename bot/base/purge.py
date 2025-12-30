import gc
import os
import sys
import time

import bot.base.log as logger

log = logger.get_logger(__name__)
RESTARTING = False


def write_json(path, data):
    try:
        import json
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        return True
    except Exception:
        return False


def read_json(path):
    try:
        import json
        if not os.path.exists(path):
            return None
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def save_task_data(task):
    try:
        d = {
            "task_id": getattr(task, "task_id", None),
            "status": getattr(getattr(task, "task_status", None), "name", None),
            "reason": getattr(getattr(task, "end_task_reason", None), "value", None),
            "start": getattr(task, "task_start_time", None),
            "end": getattr(task, "end_task_time", None),
            "app": getattr(task, "app_name", None),
            "type": getattr(getattr(task, "task_type", None), "name", None),
        }
        write_json("userdata/last_task.json", d)
    except Exception:
        pass


def soft_process_restart():
    try:
        global RESTARTING
        if RESTARTING:
            return
        RESTARTING = True
        os.makedirs('userdata', exist_ok=True)
        try:
            with open('userdata/restart.lock', 'w') as f:
                f.write(str(os.getpid()))
        except Exception:
            pass
        import subprocess, sys as _sys
        env = os.environ.copy()
        env['UAT_AUTORESTART'] = '1'
        subprocess.Popen([_sys.executable, "main.py"], env=env)
        os._exit(0)
    except Exception:
        try:
            os._exit(0)
        except Exception:
            pass


def acquire_instance_lock():
    try:
        os.makedirs('userdata', exist_ok=True)
        try:
            os.remove('userdata/restart.lock')
        except Exception:
            pass
        p = 'userdata/instance.lock'
        old = None
        if os.path.exists(p):
            try:
                with open(p, 'r') as f:
                    old = int((f.read() or '0').strip() or '0')
            except Exception:
                old = None
        if old:
            try:
                import psutil
                if psutil.pid_exists(old):
                    if os.environ.get('UAT_AUTORESTART','0') == '1':
                        limit = time.time() + 20
                        while time.time() < limit and psutil.pid_exists(old):
                            time.sleep(0.5)
            except Exception:
                pass
        if os.path.exists(p):
            try:
                cur = None
                with open(p, 'r') as f:
                    cur = int((f.read() or '0').strip() or '0')
            except Exception:
                cur = None
            try:
                import psutil
                if not cur or not psutil.pid_exists(cur):
                    os.remove(p)
            except Exception:
                try:
                    os.remove(p)
                except Exception:
                    pass
        with open(p, 'x') as f:
            f.write(str(os.getpid()))
        return True
    except FileExistsError:
        return True
    except Exception:
        return True


def serialize_umamusume_task(t):
    try:
        d = t.detail

        def to_jsonable(x):
            import enum
            if x is None:
                return None
            if isinstance(x, (str, int, float, bool)):
                return x
            if isinstance(x, enum.Enum):
                try:
                    return x.value
                except Exception:
                    try:
                        return x.name
                    except Exception:
                        return str(x)
            if isinstance(x, (list, tuple, set)):
                return [to_jsonable(i) for i in x]
            if isinstance(x, dict):
                return {k: to_jsonable(v) for k, v in x.items()}
            try:
                dct = getattr(x, '__dict__', None)
                if isinstance(dct, dict):
                    return {k: to_jsonable(v) for k, v in dct.items() if not k.startswith('_')}
            except Exception:
                pass
            return str(x)

        attachment = {}
        for k, v in getattr(d, '__dict__', {}).items():
            if k in ('scenario_config',):
                continue
            if k == 'scenario':
                try:
                    val = getattr(v, 'value', v)
                    attachment['scenario'] = int(val)
                except Exception:
                    try:
                        attachment['scenario'] = int(v)
                    except Exception:
                        attachment['scenario'] = to_jsonable(v)
                continue
            attachment[k] = to_jsonable(v)

        sc = getattr(d, 'scenario_config', None)
        try:
            ura = getattr(sc, 'ura_config', None) if sc else None
            attachment['ura_config'] = to_jsonable(ura) if ura is not None else None
        except Exception:
            attachment['ura_config'] = None

        try:
            aoharu = getattr(sc, 'aoharu_config', None) if sc else None
            attachment['aoharu_config'] = to_jsonable(aoharu) if aoharu is not None else None
        except Exception:
            attachment['aoharu_config'] = None

        return attachment
    except Exception:
        return None
            

def save_scheduler_state():
    try:
        from bot.engine.scheduler import scheduler
        return bool(write_json('userdata/scheduler_state.json', {'active': bool(getattr(scheduler, 'active', False))}))
    except Exception:
        return False


def load_scheduler_state():
    try:
        path = 'userdata/scheduler_state.json'
        d = read_json(path)
        if d is None:
            return None
        try:
            os.remove(path)
        except Exception:
            pass
        return bool(d.get('active'))
    except Exception:
        return None


def save_scheduler_tasks():
    try:
        from bot.engine.scheduler import scheduler
        from bot.base.task import TaskExecuteMode as TEM, TaskStatus as TS
        tasks = []
        for t in scheduler.get_task_list() or []:
            try:
                app = getattr(t, 'app_name', None)
                mode_enum = getattr(t, 'task_execute_mode', None)
                mode = getattr(mode_enum, 'value', None)
                status = getattr(t, 'task_status', None)
                
                if mode_enum in (TEM.TASK_EXECUTE_MODE_ONE_TIME, TEM.TASK_EXECUTE_MODE_TEAM_TRIALS):
                    if status in (TS.TASK_STATUS_SUCCESS, TS.TASK_STATUS_FAILED):
                        continue
                
                if mode_enum == TEM.TASK_EXECUTE_MODE_FULL_AUTO:
                    if status in (TS.TASK_STATUS_SUCCESS, TS.TASK_STATUS_FAILED):
                        continue
                
                ttype = getattr(getattr(t, 'task_type', None), 'value', None)
                desc = getattr(t, 'task_desc', '')
                cron = getattr(t, 'cron_job_config', None)
                cron_dump = None
                if cron is not None:
                    cron_dump = getattr(cron, 'cron', None)
                attachment = None
                if app == 'umamusume':
                    attachment = serialize_umamusume_task(t)
                entry = {
                    'task_id': getattr(t, 'task_id', None),
                    'app_name': app,
                    'task_execute_mode': mode,
                    'task_type': ttype,
                    'task_desc': desc,
                    'attachment_data': attachment,
                    'cron_job_config': {'cron': cron_dump} if cron_dump else None
                }
                tasks.append(entry)
            except Exception:
                continue
        return bool(write_json('userdata/saved_tasks.json', tasks))
    except Exception:
        return False


def load_saved_tasks():
    try:
        import bot.engine.ctrl as ctrl
        from bot.base.task import TaskExecuteMode as TEM
        from bot.base.common import CronJobConfig
        path = 'userdata/saved_tasks.json'
        data = read_json(path)
        if data is None:
            return False
        for it in data or []:
            try:
                mode_raw = it.get('task_execute_mode')
                try:
                    if isinstance(mode_raw, int):
                        mode = TEM(mode_raw)
                    elif isinstance(mode_raw, str):
                        mode = TEM[mode_raw]
                    else:
                        mode = TEM.TASK_EXECUTE_MODE_ONE_TIME
                except Exception:
                    mode = TEM.TASK_EXECUTE_MODE_ONE_TIME
                cron_src = it.get('cron_job_config')
                cron_obj = None
                if cron_src and isinstance(cron_src, dict) and cron_src.get('cron'):
                    cron_obj = CronJobConfig()
                    cron_obj.cron = cron_src.get('cron')
                    cron_obj.next_time = None
                    cron_obj.last_time = None
                ctrl.add_task(
                    it.get('app_name'),
                    mode,
                    it.get('task_type'),
                    it.get('task_desc'),
                    cron_obj,
                    it.get('attachment_data')
                )
                try:
                    from bot.engine.scheduler import scheduler
                    t = scheduler.get_task_list()[-1]
                    tid = it.get('task_id')
                    if tid:
                        t.task_id = tid
                    if mode in (TEM.TASK_EXECUTE_MODE_ONE_TIME, TEM.TASK_EXECUTE_MODE_LOOP):
                        from bot.base.task import TaskStatus as TS
                        t.task_status = TS.TASK_STATUS_PENDING
                except Exception:
                    pass
            except Exception:
                continue
        try:
            os.remove(path)
        except Exception:
            pass
        return True
    except Exception:
        return False


def purge_all(reason: str = ""):
    try:
        if os.environ.get('UAT_DISABLE_MKLDNN', None) is None:
            os.environ['UAT_DISABLE_MKLDNN'] = '1'
    except Exception:
        pass

    try:
        from bot.recog.ocr import reset_ocr, clear_ocr_cache
        clear_ocr_cache()
        reset_ocr()
        log.info("purge: OCR reset")
    except Exception:
        pass

    try:
        from bot.recog.image_matcher import clear_image_match_cache
        clear_image_match_cache()
        log.info("purge: image match cache cleared")
    except Exception:
        pass

    try:
        from module.umamusume.script.cultivate_task.parse import clear_parse_caches
        clear_parse_caches()
        log.info("purge: parse caches cleared")
    except Exception:
        pass

    try:
        import bot.conn.fetch as fetch
        sc = getattr(fetch, 'shared_controller', None)
        if sc is not None:
            try:
                sc.destroy()
            except Exception:
                pass
            try:
                fetch.shared_controller = None
            except Exception:
                pass
            log.info("purge: shared controller released")
    except Exception:
        pass

    try:
        pass
    except Exception:
        pass

    try:
        pass
    except Exception:
        pass

    try:
        import cv2
        try:
            cv2.destroyAllWindows()
        except Exception:
            pass
    except Exception:
        pass

    try:
        gc.collect()
        gc.collect()
    except Exception:
        pass

    try:
        if os.name == 'nt':
            import ctypes
            h = ctypes.windll.kernel32.GetCurrentProcess()
            try:
                ctypes.windll.kernel32.SetProcessWorkingSetSize(h, -1, -1)
            except Exception:
                pass
            try:
                ctypes.windll.psapi.EmptyWorkingSet(h)
            except Exception:
                pass
    except Exception:
        pass

    try:
        import importlib
        importlib.invalidate_caches()
    except Exception:
        pass

    try:
        import time
        time.sleep(float(os.getenv("UAT_PURGE_PAUSE_SEC", "0.15")))
    except Exception:
        pass
