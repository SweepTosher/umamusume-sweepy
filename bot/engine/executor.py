import threading
import time
import traceback
import psutil
import os
import gc

import bot.base.log as logger
import cv2

from bot.base.resource import UI, NOT_FOUND_UI
from bot.base.task import TaskStatus, Task, EndTaskReason
from bot.conn.os import push_system_notification
from bot.conn.u2_ctrl import U2AndroidController
from bot.recog.image_matcher import template_match, image_match
from bot.recog.ocr import reset_ocr
from bot.recog.timeout_tracker import check_and_reset_timeout
from bot.base.purge import save_task_data, save_scheduler_tasks, save_scheduler_state, soft_process_restart
from concurrent.futures import ThreadPoolExecutor, as_completed
from bot.base.manifest import APP_MANIFEST_LIST
from config import CONFIG


log = logger.get_logger(__name__)

debug = True


def get_controller() -> U2AndroidController:
    return U2AndroidController()


class Executor:
    active = True

    app_alive_check_counter = 5
    app_alive_check_interval = 5

    def __init__(self):
        psutil.Process().cpu_affinity(list(range(CONFIG.bot.auto.cpu_alloc)))
        self.detect_ui_results_write_lock = threading.Lock()
        self.detect_ui_results = []
        self.executor = ThreadPoolExecutor(max_workers=CONFIG.bot.auto.cpu_alloc)

    def ensure_pool(self):
        if self.executor is None or getattr(self.executor, "_shutdown", False):
            self.executor = ThreadPoolExecutor(max_workers=CONFIG.bot.auto.cpu_alloc)

    def cancel_futures(self, futures):
        for f in futures:
            if not f.done():
                try:
                    f.cancel()
                except Exception:
                    pass

    def close_pool(self):
        try:
            self.executor.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            try:
                self.executor.shutdown(wait=False)
            except Exception:
                pass
        except Exception:
            pass
        finally:
            self.executor = None

    def start(self, task):
        self.active = True
        self.ensure_pool()
        try:
            self.detect_ui_results.clear()
        except Exception:
            self.detect_ui_results = []
        self.run_work_flow(task)

    def stop(self):
        self.active = False
        self.close_pool()
        try:
            purge_all("executor.stop")
        except Exception:
            pass

    def detect_ui(self, ui_list: list[UI], target) -> UI:
        target = cv2.cvtColor(target, cv2.COLOR_BGR2GRAY)
        if len(ui_list) < 3:
            for ui in ui_list:
                result = self.detect_ui_sub(ui, target)
                if result:
                    return ui
            return NOT_FOUND_UI
        self.ensure_pool()
        if self.executor is None or getattr(self.executor, "_shutdown", False):
            return NOT_FOUND_UI
        try:
            futures = {self.executor.submit(self.detect_ui_sub, ui, target): ui for ui in ui_list}
        except RuntimeError as e:
            if "interpreter shutdown" in str(e).lower():
                return NOT_FOUND_UI
            raise
        found = None
        for _ in as_completed(futures):
            if len(self.detect_ui_results) > 0:
                found = self.detect_ui_results[0]
                break
        if found is not None:
            self.cancel_futures(futures)
            self.detect_ui_results = []
            return found
        for f in futures:
            try:
                f.result()
            except Exception:
                pass
        self.detect_ui_results = []
        return NOT_FOUND_UI

    def detect_ui_sub(self, ui: UI, target) -> None:
        result = True
        for template in ui.check_exist_template_list:
            sub_target = target[
                         template.image_match_config.match_area.y1:template.image_match_config.match_area.y2,
                         template.image_match_config.match_area.x1:template.image_match_config.match_area.x2]
            if not image_match(sub_target, template).find_match:
                result = False
                break
        for template in ui.check_non_exist_template_list:
            sub_target = target[
                         template.image_match_config.match_area.y1:template.image_match_config.match_area.y2,
                         template.image_match_config.match_area.x1:template.image_match_config.match_area.x2]
            if image_match(sub_target, template).find_match:
                result = False
                break
        if result is True:
            self.detect_ui_results_write_lock.acquire()
            self.detect_ui_results.append(ui)
            self.detect_ui_results_write_lock.release()

    def run_work_flow(self, task: Task):
        manifest = APP_MANIFEST_LIST[task.app_name]
        ui_list = manifest.ui_list
        before_hook = manifest.before_hook
        after_hook = manifest.after_hook
        controller = get_controller()
        try:
            # 初始化
            controller.init_env()
            ctx = manifest.build_context(task, controller)
            ctx.ctrl = controller

            task.task_status = TaskStatus.TASK_STATUS_RUNNING
            task.start_task()
            task.task_start_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))

            # Launch application
            log.debug("Starting: "+manifest.app_package_name)
            ctx.ctrl.start_app(manifest.app_package_name, manifest.app_activity_name)
            ctx.ctrl.click(355, 1200, "task start")
            
            
            def screen_watchdog():
                last_img = None
                unchanged = 0
                last_restart_time = 0

                def preprocess(im):
                    try:
                        return cv2.resize(im, (137, 244))
                    except Exception:
                        return im

                while self.active and task.task_status == TaskStatus.TASK_STATUS_RUNNING:
                    time.sleep(30)
                    if last_restart_time > 0 and (time.time() - last_restart_time) < 60:
                        continue
                    try:
                        try:
                            from bot.base.runtime_state import update_watchdog, get_watchdog_threshold
                            watchdog_threshold = int(get_watchdog_threshold())
                        except Exception:
                            watchdog_threshold = 3
                            update_watchdog = None 

                        img = controller.get_screen(to_gray=True)
                        if img is None:
                            unchanged += 1
                            try:
                                if update_watchdog:
                                    update_watchdog(unchanged)
                            except Exception:
                                pass
                            print(f"{unchanged}/{watchdog_threshold}", flush=True)
                            try:
                                log.info(f"watchdog {unchanged}/{watchdog_threshold}")
                            except Exception:
                                pass
                        else:
                            cur = preprocess(img)
                            if last_img is None:
                                last_img = cur
                                unchanged = 0
                                try:
                                    if update_watchdog:
                                        update_watchdog(unchanged)
                                except Exception:
                                    pass
                                print(f"0/{watchdog_threshold}", flush=True)
                                try:
                                    log.info(f"watchdog 0/{watchdog_threshold}")
                                except Exception:
                                    pass
                                continue
                            prev = preprocess(last_img)
                            try:
                                diff = cv2.absdiff(cur, prev)
                                score = float(diff.mean())
                            except Exception:
                                score = 0.0
                            try:
                                brightness = float(cur.mean())
                            except Exception:
                                brightness = 0.0
                            if score < 1.0 or brightness < 8.0:
                                unchanged += 1
                                try:
                                    if update_watchdog:
                                        update_watchdog(unchanged)
                                except Exception:
                                    pass
                                print(f"{unchanged}/{watchdog_threshold}", flush=True)
                                try:
                                    log.info(f"watchdog {unchanged}/{watchdog_threshold}")
                                except Exception:
                                    pass
                            else:
                                unchanged = 0
                                try:
                                    if update_watchdog:
                                        update_watchdog(unchanged)
                                except Exception:
                                    pass
                                print(f"0/{watchdog_threshold}", flush=True)
                                try:
                                    log.info(f"watchdog 0/{watchdog_threshold}")
                                except Exception:
                                    pass
                            last_img = cur

                        if unchanged >= watchdog_threshold:
                            print(f"{watchdog_threshold}/{watchdog_threshold} restarting app", flush=True)
                            try:
                                log.info(f"watchdog {watchdog_threshold}/{watchdog_threshold} restarting app")
                            except Exception:
                                pass
                            try:
                                import bot.conn.u2_ctrl as u2c
                                u2c.INPUT_BLOCKED = True
                                controller.execute_adb_shell("shell am force-stop com.cygames.umamusume", True)
                                time.sleep(1.0)
                                controller.start_app(manifest.app_package_name, manifest.app_activity_name)
                                time.sleep(2.0)
                                try:
                                    controller.trigger_decision_reset = True
                                except Exception:
                                    pass
                            except Exception:
                                pass
                            finally:
                                try:
                                    u2c.INPUT_BLOCKED = False
                                except Exception:
                                    pass
                            unchanged = 0
                            last_img = None
                            last_restart_time = time.time()
                            try:
                                if update_watchdog:
                                    update_watchdog(unchanged)
                            except Exception:
                                pass
                            print(f"0/{watchdog_threshold}", flush=True)
                            try:
                                log.info(f"watchdog 0/{watchdog_threshold}")
                            except Exception:
                                pass
                            continue
                    except Exception:
                        unchanged = 0
                        last_img = None

            watchdog_thread = threading.Thread(target=screen_watchdog, args=(), daemon=True)
            watchdog_thread.start()

            while self.active:
                if task.task_status == TaskStatus.TASK_STATUS_RUNNING:
                    if check_and_reset_timeout():
                        log.warning("Recognition timeout detected - restarting decision making")
                        try:
                            ctx.current_screen = None
                        except Exception:
                            pass
                        time.sleep(0.5)
                        continue
                        
                    ctx.current_screen = ctx.ctrl.get_screen()
                    if ctx.current_screen is None:
                        log.debug("No image detected")
                        time.sleep(1)
                        continue
                    ctx.prev_ui = ctx.current_ui
                    ctx.current_ui = self.detect_ui(ui_list, ctx.current_screen)
                    log.debug("current_ui:" + ctx.current_ui.ui_name)
                    if before_hook is not None:
                        before_hook(ctx)
                    manifest.script(ctx)
                    if after_hook is not None:
                        after_hook(ctx)
                    if ctx.is_task_finish():
                        task.end_task(TaskStatus.TASK_STATUS_SUCCESS, EndTaskReason.COMPLETE)
                    try:
                        ctx.current_screen = None
                    except Exception:
                        pass
                else:
                    break
                try:
                    sleep_ms = int(os.getenv("UAT_EXECUTOR_LOOP_SLEEP_MS", "200"))
                    time.sleep(max(0.0, sleep_ms / 1000.0))
                except Exception:
                    time.sleep(0.38)
        except Exception:
            task.end_task(TaskStatus.TASK_STATUS_FAILED, EndTaskReason.SYSTEM_ERROR)
            traceback.print_exc()

        if task.task_status == TaskStatus.TASK_STATUS_RUNNING:
        if not self.active:
            if task.task_status != TaskStatus.TASK_STATUS_INTERRUPT:
                task.end_task(TaskStatus.TASK_STATUS_INTERRUPT, EndTaskReason.MANUAL_ABORTED)
        elif task.task_status == TaskStatus.TASK_STATUS_INTERRUPT:
            self.active = False
        else:
            self.active = False

        task.end_task_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))
        push_system_notification("任务结束", str(getattr(getattr(task, 'end_task_reason', None), 'value', '')), 10)
        controller.destroy()
        self.close_pool()
        try:
            save_task_data(task)
        except Exception:
            pass
        try:
            save_scheduler_tasks()
        except Exception:
            pass
        try:
            save_scheduler_state()
        except Exception:
            pass

        try:
            if task.end_task_reason not in (EndTaskReason.MANUAL_ABORTED,):
                soft_process_restart()
        except Exception:
            pass
