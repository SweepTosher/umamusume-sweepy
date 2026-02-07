import os
import time
import json
import re
from typing import Dict, Any
import subprocess

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from bot.base.log import task_log_handler
from bot.engine import ctrl as bot_ctrl
from bot.server.protocol.task import *
from starlette.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional


class SafeJSONResponse(JSONResponse):
    _surrogate_re = re.compile(r"[\ud800-\udfff]")

    @classmethod
    def _sanitize(cls, obj):
        if isinstance(obj, str):
            return cls._surrogate_re.sub("\ufffd", obj)
        if isinstance(obj, list):
            return [cls._sanitize(x) for x in obj]
        if isinstance(obj, dict):
            return {k: cls._sanitize(v) for k, v in obj.items()}
        return obj

    def render(self, content) -> bytes:
        safe_content = self._sanitize(content)
        return json.dumps(
            safe_content,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")


server = FastAPI(default_response_class=SafeJSONResponse)

server.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global state for manual skill notifications
manual_skill_notification_state = {
    "show": False,
    "message": "",
    "timestamp": 0,
    "confirmed": False,
    "cancelled": False
}

@server.post("/api/manual-skill-notification")
def manual_skill_notification(notification_data: Dict[str, Any]):
    """Receive manual skill purchase notification from bot"""
    global manual_skill_notification_state
    manual_skill_notification_state.update({
        "show": True,
        "message": notification_data.get("message", ""),
        "timestamp": notification_data.get("timestamp", time.time()),
        "confirmed": False,
        "cancelled": False
    })
    return {"status": "success"}

@server.get("/api/manual-skill-notification-status")
def get_manual_skill_notification_status():
    """Get current notification status for frontend polling"""
    global manual_skill_notification_state
    return manual_skill_notification_state

@server.post("/api/manual-skill-notification-confirm")
def confirm_manual_skill_notification():
    """Confirm manual skill purchase completion"""
    global manual_skill_notification_state
    manual_skill_notification_state.update({
        "show": False,
        "confirmed": True,
        "cancelled": False
    })
    return {"status": "confirmed"}

@server.post("/api/manual-skill-notification-cancel")
def cancel_manual_skill_notification():
    """Cancel manual skill purchase"""
    global manual_skill_notification_state
    manual_skill_notification_state.update({
        "show": False,
        "confirmed": False,
        "cancelled": True
    })
    return {"status": "cancelled"}


@server.post("/task")
def add_task(req: AddTaskRequest):
    bot_ctrl.add_task(req.app_name, req.task_execute_mode, req.task_type, req.task_desc,
                      req.cron_job_config, req.attachment_data)


@server.delete("/task")
def delete_task(req: DeleteTaskRequest):
    bot_ctrl.delete_task(req.task_id)


@server.get("/task")
def get_task():
    return bot_ctrl.get_task_list()


class RuntimeThresholds(BaseModel):
    repetitive_threshold: Optional[int] = None
    watchdog_threshold: Optional[int] = None


@server.get("/api/runtime-state")
def get_runtime_state():
    try:
        from bot.base.runtime_state import get_state
        return get_state()
    except Exception:
        return {
            "repetitive_count": 0,
            "repetitive_other_clicks": 0,
            "repetitive_threshold": 11,
            "watchdog_unchanged": 0,
            "watchdog_threshold": 3,
        }


@server.post("/api/runtime-thresholds")
def set_runtime_thresholds(req: RuntimeThresholds):
    try:
        from bot.base.runtime_state import set_thresholds, save_persisted
        set_thresholds(req.repetitive_threshold, req.watchdog_threshold)
        save_persisted()
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@server.get("/api/update-status")
def get_update_status():
    try:
        repo_root = None
        base = os.path.abspath(os.path.dirname(__file__))
        for _ in range(8):
            if os.path.isdir(os.path.join(base, '.git')):
                repo_root = base
                break
            parent = os.path.dirname(base)
            if parent == base:
                break
            base = parent
        if repo_root is None:
            tl = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, cwd=os.getcwd(), timeout=5)
            if tl.returncode == 0 and os.path.isdir(tl.stdout.strip()):
                repo_root = tl.stdout.strip()
            else:
                return {"has_update": False, "error": "git repo not found from server path"}
        branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, cwd=repo_root, timeout=5)
        if branch.returncode != 0:
            return {"has_update": False, "error": branch.stderr.strip()}
        branch_name = branch.stdout.strip()
        upstream = subprocess.run(["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], capture_output=True, text=True, cwd=repo_root, timeout=5)
        if upstream.returncode == 0:
            upstream_ref = upstream.stdout.strip()
            remote_name = upstream_ref.split('/')[0]
            subprocess.run(["git", "fetch", "--quiet", remote_name], capture_output=True, text=True, cwd=repo_root, timeout=10)
            revspec = f"HEAD...{upstream_ref}"
        else:
            remote_name = "origin"
            subprocess.run(["git", "fetch", "--quiet", remote_name], capture_output=True, text=True, cwd=repo_root, timeout=10)
            revspec = f"HEAD...{remote_name}/{branch_name}"
        cmp = subprocess.run(["git", "rev-list", "--left-right", "--count", revspec], capture_output=True, text=True, cwd=repo_root, timeout=5)
        if cmp.returncode != 0:
            return {"has_update": False, "error": cmp.stderr.strip(), "branch": branch_name}
        parts = cmp.stdout.strip().split()
        ahead = int(parts[0]) if len(parts) > 0 else 0
        behind = int(parts[1]) if len(parts) > 1 else 0
        head_sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=repo_root, timeout=5)
        remote_sha = subprocess.run(["git", "rev-parse", revspec.split('...')[1]], capture_output=True, text=True, cwd=repo_root, timeout=5)
        preset_redo = False
        if behind > 0:
            log_cmd = subprocess.run(["git", "log", "--oneline", f"HEAD..{revspec.split('...')[1]}"], capture_output=True, text=True, cwd=repo_root, timeout=10)
            if log_cmd.returncode == 0 and "(TR)" in log_cmd.stdout:
                preset_redo = True
        return {
            "has_update": bool(behind > 0),
            "preset_redo": preset_redo,
            "branch": branch_name,
            "upstream": revspec.split('...')[1],
            "ahead": ahead,
            "behind": behind,
            "head": head_sha.stdout.strip() if head_sha.returncode == 0 else "",
            "remote": remote_sha.stdout.strip() if remote_sha.returncode == 0 else ""
        }
    except Exception as e:
        return {"has_update": False, "error": str(e)}

@server.get("/log/{task_id}")
def get_task_log(task_id):
    return task_log_handler.get_task_log(task_id)


@server.post("/action/bot/reset-task")
def reset_task(req: ResetTaskRequest):
    bot_ctrl.reset_task(req.task_id)


@server.post("/action/bot/start")
def start_bot():
    bot_ctrl.start()


@server.post("/action/bot/stop")
def stop_bot():
    bot_ctrl.stop()


@server.get("/action/bot/status")
def get_bot_status():
    from bot.engine.scheduler import scheduler
    if scheduler.active:
        running_tasks = [t for t in scheduler.task_list 
                        if t.task_status.value == 2] 
        if running_tasks:
            return {"status": "running"}
        return {"status": "active"}
    return {"status": "idle"}


@server.get("/api/pal-defaults")
def get_pal_defaults():
    from module.umamusume.user_data import read_pal_defaults
    return read_pal_defaults()



@server.get("/")
async def get_index():
    return FileResponse('public/index.html', headers={
        'Cache-Control': 'no-cache, no-store, must-revalidate',
        'Pragma': 'no-cache',
        'Expires': '0'
    })


@server.get("/{whatever:path}")
async def get_static_files_or_404(whatever):
    # try open file for path
    file_path = os.path.join("public", whatever)
    # 设置防缓存头
    no_cache_headers = {
        'Cache-Control': 'no-cache, no-store, must-revalidate',
        'Pragma': 'no-cache',
        'Expires': '0'
    }
    
    if os.path.isfile(file_path):
        if file_path.endswith((".js", ".mjs")):
            return FileResponse(file_path, media_type="application/javascript", headers=no_cache_headers)
        else:
            return FileResponse(file_path, headers=no_cache_headers)
    return FileResponse('public/index.html', headers=no_cache_headers)
