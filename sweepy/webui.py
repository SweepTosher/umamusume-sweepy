from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import errno
import json
import mimetypes
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from typing import Any
from urllib.parse import parse_qs, urlsplit

import sweepy.config as sweepy_config
from sweepy.brain_client import BrainAPIError, BrainClient
from sweepy.catalog import Catalog
from sweepy.config import RuntimeConfig, apply_turn_delay
from sweepy.macro_runner import MacroCareerRunner
from sweepy.qr_svg import render_qr_svg
from sweepy.stripper import (
    resolve_cm_options_for_account,
    strip_cm_mate,
    trained_chara_index,
    unwrap_data,
)
from sweepy.umadump_export import export_filename
from uma_headless import SteamTicketError
from uma_headless.device import read_device_state


_ALLOWED_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

_HEALTH_TIMEOUT_SECONDS = 3.0


_ALLOWED_FETCH_SITES = frozenset({"same-origin", "none"})

_SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "font-src 'self' https://fonts.gstatic.com; "
        "object-src 'none'; "
        "base-uri 'none'; "
        "form-action 'self'; "
        "frame-ancestors 'none'"
    ),
}

_MIME_OVERRIDES: dict[str, str] = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".ico": "image/png",
}


def _host_without_port(raw_host: str) -> str:
    cleaned = str(raw_host or "").strip()
    if cleaned.startswith("[") and "]" in cleaned:
        return cleaned[1 : cleaned.index("]")].casefold()
    return cleaned.rsplit(":", 1)[0].casefold()


def _origin_is_local(origin: str) -> bool:
    if not origin:
        return True
    parsed = urlsplit(origin)
    hostname = (parsed.hostname or "").casefold()
    return parsed.scheme in ("http", "https") and hostname in _ALLOWED_LOCAL_HOSTS


def _mask_api_key(api_key: str) -> str:
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "•" * len(api_key)
    return f"{api_key[:6]}…{api_key[-4:]}"


def _steam_error_payload(exc: Exception) -> dict[str, Any]:
    retryable = bool(getattr(exc, "transport", False))
    stage = str(getattr(exc, "stage", "") or "")
    if stage.startswith("credential") and not retryable:
        return {
            "ok": False,
            "error": str(exc) or "Steam sign-in failed",
            "state": "steam_auth_failed",
            "result_code": getattr(exc, "result_code", None),
            "retryable": False,
        }
    return {
        "ok": False,
        "error": "steam_unavailable",
        "state": "steam_unavailable",
        "retryable": retryable,
    }


class SweepyAppState:
    def __init__(
        self,
        *,
        config: RuntimeConfig | None = None,
        public_dir: Path | str | None = None,
        provider_factory: Any = None,
        bootstrap_fn: Any = None,
        brain_factory: Any = None,
    ) -> None:
        self.config = config if config is not None else RuntimeConfig()
        resolved_public = (
            Path(public_dir).resolve()
            if public_dir is not None
            else (Path(__file__).resolve().parent.parent / "public").resolve()
        )
        self.public_dir = resolved_public
        self.catalog = Catalog(self.public_dir)
        self.runner = MacroCareerRunner(
            account_salt=self.config.account_salt(),
            runtime_dir=self.config.runtime_dir,
        )
        self.runner.set_burn_clocks(self.config.load_settings()["burn_clocks"])

        self._provider_factory = provider_factory
        self._bootstrap_fn = bootstrap_fn
        self._brain_factory = brain_factory if brain_factory is not None else BrainClient

        self._lock = threading.RLock()
        self._auth_lock = threading.RLock()
        self._provider: Any = None
        self._client: Any = None
        self._raw_account_data: dict[str, Any] | None = None
        self._dashboard: dict[str, Any] | None = None
        self._last_qr_url: str = ""
        self._brain_online: bool = False
        self._brain_health: dict[str, Any] | None = None
        self._brain_probe_at: float = 0.0
        self._synced_finished_data_id: int | None = None
        self._device_state: dict[str, Any] | None = self._take_legacy_device_state()

    def _take_legacy_device_state(self) -> dict[str, Any] | None:
        path = self.config.device_file
        if not path.exists():
            return None
        try:
            state = read_device_state(path)
        except Exception:
            state = None
        try:
            path.unlink()
        except OSError:
            return state
        return state

    def _get_provider(self, token: str | None = None) -> Any:
        with self._lock:
            if token and self._provider is not None:
                self._provider.close()
                self._provider = None
            if self._provider is not None:
                return self._provider
            factory = self._provider_factory
            if factory is None:
                from uma_headless import SteamTicketProvider
                factory = SteamTicketProvider
            try:
                self._provider = factory(self.config.refresh_file, token=token or None)
            except TypeError:
                self._provider = factory(self.config.refresh_file)
            return self._provider

    def _complete_uma_login(self, provider: Any) -> dict[str, Any]:
        with self._auth_lock:
            with self._lock:
                already_logged_in = self._client is not None and self._dashboard is not None
            if already_logged_in:
                out = self.session_payload()
                out["status"] = "approved"
                out["logged_in"] = True
                return out

            bootstrap = self._bootstrap_fn
            if bootstrap is None:
                from uma_headless import bootstrap_headless_auth
                bootstrap = bootstrap_headless_auth

            client, boot_res = bootstrap(
                self.config.runtime_dir,
                provider,
                device_state=self._device_state,
                persist_device=False,
            )
            try:
                settings = self.config.load_settings()
                apply_turn_delay(client, settings["turn_delay"])

                boot_inner = unwrap_data(boot_res)
                if any(k in boot_inner for k in ("user_info", "card_list", "tp_info")):
                    raw_data = boot_inner
                else:
                    raw_data = unwrap_data(client.login(read_info=True))
                if not raw_data:
                    raise RuntimeError("Login returned no account data")

                career_res: dict[str, Any] | None = None
                active_light = raw_data.get("single_mode_chara_light") or raw_data.get("single_mode_chara")
                if isinstance(active_light, dict) and int(active_light.get("scenario_id") or 0) == 3:
                    try:
                        career_res = client.load_career(scenario_id=3)
                    except Exception:
                        career_res = None

                dashboard = self.catalog.format_account_status(raw_data, career_data=career_res)
            except BaseException:
                client.close()
                raise
            device_state = getattr(client, "device_state", None)
            with self._lock:
                old_client = self._client
                self._client = client
                self._raw_account_data = raw_data
                self._dashboard = dashboard
                if isinstance(device_state, dict):
                    self._device_state = device_state
            if old_client is not None and old_client is not client:
                old_client.close()

            out = self.session_payload()
            out["status"] = "approved"
            if isinstance(self._device_state, dict):
                out["device_state"] = dict(self._device_state)
            return out

    def _sync_runner_settlement(self) -> None:
        latest, marker = self.runner.latest_account_snapshot()
        if latest is None:
            return
        with self._lock:
            if self._synced_finished_data_id == marker:
                return
            self._synced_finished_data_id = marker
            if (
                isinstance(self._raw_account_data, dict)
                and self._raw_account_data.get("trained_chara_array")
                and not latest.get("trained_chara_array")
            ):
                merged = dict(latest)
                merged["trained_chara_array"] = self._raw_account_data["trained_chara_array"]
                latest = merged
            self._raw_account_data = latest
            self._dashboard = self.catalog.format_account_status(latest)

    def _account_view(self, runner_snapshot: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            dash = dict(self._dashboard) if isinstance(self._dashboard, dict) else None
            logged_in = self._client is not None and dash is not None
        account = dict(dash) if logged_in and dash else None
        if account is not None:
            career = account.get("career")
            live_turn = int(runner_snapshot.get("turn") or 0)
            if isinstance(career, dict) and live_turn > int(career.get("turn") or 0):
                account["career"] = {**career, "turn": live_turn}
        return account

    def _refresh_brain_status(self, settings: dict[str, Any]) -> None:
        if not settings["api_key"] or not settings["api_url"]:
            with self._lock:
                self._brain_online = False
                self._brain_health = None
            return
        now = time.monotonic()
        with self._lock:
            if now - self._brain_probe_at < 5.0:
                return
            self._brain_probe_at = now
        try:
            brain = self._brain_factory(settings["api_url"], settings["api_key"])
        except Exception:
            with self._lock:
                self._brain_online = False
                self._brain_health = None
            return
        if hasattr(brain, "timeout"):
            brain.timeout = min(float(brain.timeout), _HEALTH_TIMEOUT_SECONDS)
        try:
            health = brain.health()
        except Exception:
            with self._lock:
                self._brain_online = False
                self._brain_health = None
            return
        finally:
            close_fn = getattr(brain, "close", None)
            if callable(close_fn):
                close_fn()
        with self._lock:
            self._brain_online = True
            self._brain_health = health

    def _refresh_account(self, *, force: bool = False) -> None:
        if not force:
            return
        with self._lock:
            if self._client is None or self._dashboard is None or self.runner.running:
                return
        if not self._auth_lock.acquire(blocking=False):
            return
        try:
            with self._lock:
                client = self._client
                if client is None or self.runner.running:
                    return
            try:
                raw = client.login(read_info=True)
            except Exception:
                return
            data = unwrap_data(raw)
            if not data:
                return
            career_res: dict[str, Any] | None = None
            light = data.get("single_mode_chara_light") or data.get("single_mode_chara")
            if isinstance(light, dict) and int(light.get("scenario_id") or 0) == 3:
                try:
                    career_res = client.load_career(scenario_id=3)
                except Exception:
                    career_res = None
            dashboard = self.catalog.format_account_status(data, career_data=career_res)
            with self._lock:
                self._raw_account_data = data
                self._dashboard = dashboard
        finally:
            self._auth_lock.release()

    def session_payload(self, *, refresh: bool = False) -> dict[str, Any]:
        self._sync_runner_settlement()
        self._refresh_account(force=refresh)
        settings = self.config.load_settings()
        self._refresh_brain_status(settings)
        runner_snapshot = self.runner.snapshot()
        with self._lock:
            logged_in = self._client is not None and self._dashboard is not None
            brain_online = self._brain_online
            brain_health = dict(self._brain_health) if isinstance(self._brain_health, dict) else None
            raw_acc = dict(self._raw_account_data) if isinstance(self._raw_account_data, dict) else None

        account = self._account_view(runner_snapshot)

        cm_enabled = bool(sweepy_config.CM_ENABLED)
        cm_cfg = dict(settings["cm_config"])
        if not cm_enabled:
            cm_cfg["cm_mode"] = False
        base: dict[str, Any] = {
            "ok": True,
            "logged_in": logged_in,
            "password_auth": True,
            "brain": {
                "api_url": settings["api_url"],
                "has_api_key": bool(settings["api_key"]),
                "api_key_masked": _mask_api_key(settings["api_key"]),
                "online": brain_online,
                "health": brain_health,
                "api_key_seed": self.config.consume_api_key_seed(),
            },
            "api_url": settings["api_url"],
            "has_api_key": bool(settings["api_key"]),
            "turn_delay": settings["turn_delay"],
            "burn_clocks": settings["burn_clocks"],
            "cm_enabled": cm_enabled,
            "cm_config": cm_cfg,
            "cm_catalog": self.catalog.cm_metadata() if cm_enabled else None,
            "veterans": self.catalog.format_veterans(raw_acc) if cm_enabled and logged_in and raw_acc is not None else [],
            "device_state": dict(self._device_state) if isinstance(self._device_state, dict) else None,
            "runner": runner_snapshot,
            "account": account,
        }
        return base

    def configure_brain(self, body: dict[str, Any]) -> dict[str, Any]:
        api_url = self.config.load_settings()["api_url"]
        api_key = str(body.get("api_key") or "").strip()
        if not api_key:
            raise ValueError("Enter an API key")
        brain = self._brain_factory(api_url, api_key)
        if hasattr(brain, "timeout"):
            brain.timeout = min(float(brain.timeout), _HEALTH_TIMEOUT_SECONDS)
        try:
            health = brain.health()
        except BrainAPIError:
            with self._lock:
                self._brain_online = False
                self._brain_health = None
            raise
        finally:
            close_fn = getattr(brain, "close", None)
            if callable(close_fn):
                close_fn()
        saved = self.config.set_brain_config(api_url, api_key)
        with self._lock:
            self._brain_online = True
            self._brain_health = health
        return {
            "ok": True,
            "online": True,
            "api_url": saved["api_url"],
            "has_api_key": bool(saved["api_key"]),
            "health": health,
        }

    def qr_start(self) -> dict[str, Any]:
        with self._auth_lock:
            if self.runner.running:
                raise RuntimeError("Stop the run before QR login")
            with self._lock:
                if self._client is not None:
                    raise RuntimeError("Log out before scanning a new account")
            provider = self._get_provider()
            try:
                info = provider.start_qr_session()
            except SteamTicketError as exc:
                return _steam_error_payload(exc)
            challenge_url = str(info.get("challenge_url") or "")
            if not challenge_url:
                raise RuntimeError("Steam returned no QR URL")
            svg = render_qr_svg(challenge_url)
            with self._lock:
                self._last_qr_url = challenge_url
            return {
                "ok": True,
                "challenge_url": challenge_url,
                "qr_svg": svg,
                "interval": info.get("interval", 2),
            }

    def _finish_steam_approval(self, provider: Any) -> dict[str, Any]:
        provider.ensure_lease()
        with self._lock:
            already_logged_in = self._client is not None
        if not already_logged_in:
            self._forget_device_state()
        payload = self._complete_uma_login(provider)
        try:
            token = provider.current_token()
        except Exception:
            token = ""
        if token:
            payload["refresh_token"] = token
        payload["status"] = "approved"
        payload["logged_in"] = True
        return payload

    def credentials_start(self, body: dict[str, Any]) -> dict[str, Any]:
        with self._auth_lock:
            if self.runner.running:
                raise RuntimeError("Stop the run before signing in")
            with self._lock:
                if self._client is not None:
                    raise RuntimeError("Log out before signing in with another account")
            username = str(body.get("username") or "")
            password = str(body.get("password") or "")
            provider = self._get_provider()
            try:
                res = provider.start_credentials_session(username, password)
                if str(res.get("status") or "") == "approved":
                    return self._finish_steam_approval(provider)
            except SteamTicketError as exc:
                return _steam_error_payload(exc)
            return {"ok": True, **res}

    def credentials_submit_code(self, body: dict[str, Any]) -> dict[str, Any]:
        with self._auth_lock:
            if self.runner.running:
                raise RuntimeError("Stop the run before verifying Steam Guard")
            with self._lock:
                if self._client is not None:
                    raise RuntimeError("Log out before verifying another account")
            code = str(body.get("code") or "")
            raw_code_type = body.get("code_type")
            code_type = int(raw_code_type) if isinstance(raw_code_type, (int, float)) else None
            provider = self._get_provider()
            try:
                res = provider.submit_steam_guard_code(code, code_type_override=code_type)
                if str(res.get("status") or "") == "approved":
                    return self._finish_steam_approval(provider)
            except SteamTicketError as exc:
                return _steam_error_payload(exc)
            return {"ok": True, **res}

    def qr_poll(self) -> dict[str, Any]:
        with self._auth_lock:
            provider = self._get_provider()
            try:
                res = provider.poll_qr_session()
            except SteamTicketError as exc:
                return _steam_error_payload(exc)
            status = str(res.get("status") or "pending")
            if status == "approved":
                try:
                    return self._finish_steam_approval(provider)
                except SteamTicketError as exc:
                    return _steam_error_payload(exc)
            challenge_url = str(res.get("challenge_url") or "")
            payload: dict[str, Any] = {
                "ok": True,
                "status": status,
                "challenge_url": challenge_url,
                "steam_id": res.get("steam_id"),
                "interval": res.get("interval"),
                "had_remote_interaction": bool(res.get("had_remote_interaction", False)),
            }
            if challenge_url:
                with self._lock:
                    changed = challenge_url != self._last_qr_url
                    if changed:
                        self._last_qr_url = challenge_url
                if changed:
                    payload["qr_svg"] = render_qr_svg(challenge_url)
            return payload

    def restore_session(self, body: dict[str, Any] | None = None) -> dict[str, Any]:
        body = body or {}
        api_key = str(body.get("api_key") or "").strip()
        if api_key:
            self.config.set_api_key(api_key)
        device = body.get("device")
        if isinstance(device, dict):
            self._device_state = device
        token = str(body.get("refresh_token") or "").strip()
        with self._auth_lock:
            with self._lock:
                if self._client is not None and self._dashboard is not None:
                    return self.session_payload()
            if not token:
                return {"ok": True, "restored": False, "reason": "no_saved_token"}
            provider = self._get_provider(token or None)
            try:
                payload = self._complete_uma_login(provider)
            except Exception as exc:
                return {"ok": True, "restored": False, "reason": str(exc)}
            payload["restored"] = True
            return payload

    def _teardown(self, *, forget_credentials: bool) -> None:
        with self._auth_lock:
            self.runner.stop()
            with self._lock:
                client = self._client
                provider = self._provider
                self._client = None
                self._provider = None
                self._raw_account_data = None
                self._dashboard = None
                self._last_qr_url = ""
            if client is not None:
                client.close()
            if provider is not None:
                provider.close()
            if forget_credentials:
                self._forget_saved_token()
            self.runner.clear_account_data()
            self._synced_finished_data_id = None

    def logout(self) -> dict[str, Any]:
        self._teardown(forget_credentials=True)
        return {"ok": True, "logged_in": False}

    def set_turn_delay(self, body: dict[str, Any]) -> dict[str, Any]:
        current = self.config.load_settings()["turn_delay"]
        disabled = bool(body.get("disabled", False))
        min_val = float(body.get("min", current["restore_min"]))
        max_val = float(body.get("max", current["restore_max"]))
        saved_delay = self.config.set_turn_delay(min_val, max_val, disabled=disabled)
        with self._lock:
            if self._client is not None:
                apply_turn_delay(self._client, saved_delay)
        return {
            "ok": True,
            **saved_delay,
            "turn_delay": saved_delay,
        }

    def _build_mate_snapshots(
        self,
        mate_ids: list[int | None],
        mate_roles: list[str],
        existing_snaps: list[dict[str, Any] | None],
        raw_account: dict[str, Any] | None,
    ) -> list[dict[str, Any] | None]:
        by_tid = trained_chara_index(raw_account)
        snaps: list[dict[str, Any] | None] = [None, None]
        for idx in range(2):
            tid = mate_ids[idx] if idx < len(mate_ids) else None
            if tid is None:
                continue
            r_ov = mate_roles[idx] if idx < len(mate_roles) else None
            role_arg = None if r_ov in (None, "", "auto") else str(r_ov)
            if tid in by_tid:
                snap = strip_cm_mate(by_tid[tid], role_override=role_arg)
                snap["_snap_tid"] = int(tid)
                snaps[idx] = snap
            elif idx < len(existing_snaps) and isinstance(existing_snaps[idx], dict):
                old_snap = existing_snaps[idx]
                if int(old_snap.get("_snap_tid") or 0) == int(tid):
                    snap = strip_cm_mate(old_snap, role_override=role_arg)
                    snap["_snap_tid"] = int(tid)
                    snaps[idx] = snap
        return snaps

    def set_cm_config(self, body: dict[str, Any]) -> dict[str, Any]:
        patch = body.get("cm_config") if isinstance(body.get("cm_config"), dict) else body
        if not isinstance(patch, dict):
            raise ValueError("Invalid CM config payload")
        settings = self.config.load_settings()
        if not sweepy_config.CM_ENABLED:
            return {
                "ok": True,
                "cm_enabled": False,
                "cm_config": {**dict(settings.get("cm_config") or {}), "cm_mode": False},
            }
        current = dict(settings.get("cm_config") or {})
        merged = {**current, **patch}
        with self._lock:
            raw_account = dict(self._raw_account_data) if isinstance(self._raw_account_data, dict) else None
        normalized = self.config.set_cm_config(merged)
        snaps = self._build_mate_snapshots(
            normalized["mate_ids"],
            normalized["mate_roles"],
            normalized["mate_snapshots"],
            raw_account,
        )
        if snaps != normalized["mate_snapshots"]:
            normalized["mate_snapshots"] = snaps
            normalized = self.config.set_cm_config(normalized)
        return {
            "ok": True,
            "cm_enabled": True,
            "cm_config": normalized,
        }

    def set_burn_clocks(self, body: dict[str, Any]) -> dict[str, Any]:
        enabled = bool(body.get("burn_clocks", False))
        self.config.set_burn_clocks(enabled)
        self.runner.set_burn_clocks(enabled)
        return {
            "ok": True,
            "burn_clocks": enabled,
            "runner": self.runner.snapshot(),
        }

    def _probe_active_grand_live_career(self, client: Any) -> dict[str, Any]:
        raw = unwrap_data(client.login(read_info=False))
        if not raw:
            raise RuntimeError("Account probe returned no data")
        active_light = raw.get("single_mode_chara_light") or raw.get("single_mode_chara")
        if not (isinstance(active_light, dict) and int(active_light.get("single_mode_chara_id") or 0) > 0):
            raise RuntimeError("no active career (start one in-game)")
        active_scen = int(active_light.get("scenario_id") or 3)
        if active_scen != 3:
            raise RuntimeError(f"Career scenario {active_scen}, not Grand Live (3).")
        return raw

    def start_career_run(self, body: dict[str, Any]) -> dict[str, Any]:
        with self._auth_lock:
            with self._lock:
                client = self._client
                raw_account = dict(self._raw_account_data) if isinstance(self._raw_account_data, dict) else None
            if client is None:
                raise RuntimeError("Not logged in")
            if self.runner.running:
                return {"ok": True, "already_running": True, "runner": self.runner.snapshot()}
            probe_data = self._probe_active_grand_live_career(client)
            if raw_account is not None and raw_account.get("trained_chara_array") and not probe_data.get("trained_chara_array"):
                probe_data = {**probe_data, "trained_chara_array": raw_account["trained_chara_array"]}
            raw_account = probe_data

            settings = self.config.load_settings()
            if not settings["api_key"]:
                raise BrainAPIError("Add an API key first")

            burn_clocks = bool(body.get("burn_clocks", settings["burn_clocks"]))
            cm_keys = (
                "cm_mode",
                "cm_preset",
                "cm_course",
                "track",
                "distance",
                "ground",
                "surface",
                "ground_condition",
                "weather",
                "season",
                "course_id",
                "inout",
                "cm_role",
                "cm_target",
                "cm_style",
                "mate_ids",
                "mate_roles",
                "mate_snapshots",
                "cm_mates",
            )
            cm_options = None
            if sweepy_config.CM_ENABLED:
                raw_cm = body.get("cm_config") if isinstance(body.get("cm_config"), dict) else settings.get("cm_config")
                if isinstance(body, dict) and any(k in body for k in cm_keys):
                    merged_cm = dict(raw_cm or {})
                    for k in cm_keys:
                        if k in body:
                            merged_cm[k] = body[k]
                    raw_cm = merged_cm
                cm_options = resolve_cm_options_for_account(raw_cm, raw_account)
                if cm_options is not None and int(cm_options.get("cm_role", 0)) in (2, 3):
                    if len(cm_options.get("cm_mates") or []) < 2:
                        raise ValueError("Selected CM mode/target requires selecting 2 veteran teammates before starting")
                    if isinstance(raw_cm, dict) and not raw_cm.get("cm_mates"):
                        selected_ids = [int(x) for x in (raw_cm.get("mate_ids") or []) if x is not None and not isinstance(x, bool)]
                        if len(set(selected_ids)) < 2:
                            raise ValueError("Selected CM mode/target requires selecting 2 distinct veteran teammates")

            brain = self._brain_factory(settings["api_url"], settings["api_key"])
            brain.on_key_refresh = self._save_rotated_key
            apply_turn_delay(client, settings["turn_delay"])
            self.runner.start(
                client,
                brain,
                burn_clocks=burn_clocks,
                cm_options=cm_options,
                account_data=raw_account,
            )
            return {
                "ok": True,
                "runner": self.runner.snapshot(),
            }

    def _save_rotated_key(self, api_key: str) -> None:
        try:
            self.config.update_settings(api_key=str(api_key))
        except (OSError, ValueError) as exc:
            print(f"sweepy: brain key not persisted: {exc}", file=sys.stderr)

    def runner_status(self) -> dict[str, Any]:
        self._sync_runner_settlement()
        snapshot = self.runner.snapshot()
        return {
            "ok": True,
            "runner": snapshot,
            "account": self._account_view(snapshot),
        }

    def final_turn_export(self) -> dict[str, Any]:
        export = self.runner.final_turn_export()
        if export is None:
            raise ValueError("No final-turn career state captured yet")
        chara = export["json"]["chara_info"]
        name = self.catalog.chara_name(chara.get("card_id"))
        if name.startswith("Unknown ("):
            name = None
        export["filename"] = export_filename(chara, name)
        return {"ok": True, **export}

    def stop_runner(self) -> dict[str, Any]:
        self.runner.stop()
        return {
            "ok": True,
            "runner": self.runner.snapshot(),
        }


    def _forget_device_state(self) -> None:
        with self._lock:
            self._device_state = None
        self.config.device_file.unlink(missing_ok=True)
        for backup in self.config.runtime_dir.glob("headless_device.json.old-*"):
            backup.unlink(missing_ok=True)

    def _forget_saved_token(self) -> None:
        self.config.refresh_file.unlink(missing_ok=True)
        self._forget_device_state()
        for backup in self.config.runtime_dir.glob("login-backup-*.tar.gz"):
            backup.unlink(missing_ok=True)

    def close(self) -> None:
        self._teardown(forget_credentials=False)


def _make_handler_class(app_state: SweepyAppState) -> type[BaseHTTPRequestHandler]:
    class SweepyRequestHandler(BaseHTTPRequestHandler):
        server_version = "sweepy"
        sys_version = ""

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _reject(self, reason: str) -> bool:
            self._send_json(403, {"ok": False, "error": reason})
            return False

        def _validate_local_request(self, *, is_post: bool = False) -> bool:
            host_hdr = _host_without_port(self.headers.get("Host", ""))
            if not host_hdr or host_hdr not in _ALLOWED_LOCAL_HOSTS:
                return self._reject("Forbidden Host header")
            if is_post:
                origin = self.headers.get("Origin", "")
                if origin and not _origin_is_local(origin):
                    return self._reject("Forbidden Origin header")
                fetch_site = (self.headers.get("Sec-Fetch-Site") or "").strip().casefold()
                if fetch_site and fetch_site not in _ALLOWED_FETCH_SITES:
                    return self._reject("Cross-site request rejected")
            return True

        def _send_bytes(
            self,
            status: int,
            content_type: str,
            data: bytes,
            *,
            cache_control: str = "no-store",
            extra_headers: dict[str, str] | None = None,
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", cache_control)
            for name, value in _SECURITY_HEADERS.items():
                self.send_header(name, value)
            if extra_headers:
                for name, value in extra_headers.items():
                    self.send_header(name, value)
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send_bytes(status, "application/json; charset=utf-8", encoded)

        def _send_file(self, path: Path | None) -> None:
            target = path if (path is not None and path.is_file()) else None
            if target is None:
                self._send_json(404, {"ok": False, "error": "Not found", "detail": "Not found"})
                return
            ext = target.suffix.lower()
            ctype = _MIME_OVERRIDES.get(ext) or mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            data = target.read_bytes()
            cache = "public, max-age=300" if ext in (".png", ".webp") else "no-cache"
            self._send_bytes(200, ctype, data, cache_control=cache)

        def _read_json_body(self) -> dict[str, Any]:
            if self.headers.get("Transfer-Encoding"):
                raise ValueError("chunked bodies unsupported")
            raw_len = self.headers.get("Content-Length", "0")
            if not raw_len.isdigit():
                raise ValueError("bad Content-Length")
            length = int(raw_len)
            if length <= 0:
                return {}
            if length > 2 * 1024 * 1024:
                raise ValueError("Request body exceeds 2 MiB limit")
            media_type = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().casefold()
            if media_type != "application/json":
                raise ValueError("Content-Type is not application/json")
            raw = self.rfile.read(length)
            if not raw:
                return {}
            parsed = json.loads(raw.decode("utf-8"))
            if not isinstance(parsed, dict):
                raise ValueError("body is not an object")
            return parsed

        def do_GET(self) -> None:
            if not self._validate_local_request(is_post=False):
                return
            target = urlsplit(self.path)
            path = target.path

            if path in ("/", "/index.html"):
                self._send_file(app_state.public_dir / "index.html")
                return
            if path == "/styles.css":
                self._send_file(app_state.public_dir / "styles.css")
                return
            if path == "/app.js":
                self._send_file(app_state.public_dir / "app.js")
                return
            if path == "/sweepy3.webp":
                self._send_file(app_state.public_dir / "sweepy3.webp")
                return
            if path in ("/sweepy2.png", "/favicon.ico"):
                self._send_file(app_state.public_dir / "sweepy2.png")
                return
            try:
                if path == "/api/session":
                    fresh = parse_qs(target.query).get("fresh") == ["1"]
                    self._send_json(200, app_state.session_payload(refresh=fresh))
                    return
                if path == "/api/career/runner":
                    self._send_json(200, app_state.runner_status())
                    return
                if path == "/api/career/final-turn-export":
                    export = app_state.final_turn_export()
                    if parse_qs(target.query).get("download") == ["1"]:
                        safe_name = str(export.get("filename") or "umadump.json").replace('"', "").replace(";", "")
                        raw_json = json.dumps(export["json"], indent=2, ensure_ascii=False).encode("utf-8")
                        self._send_bytes(
                            200,
                            "application/json; charset=utf-8",
                            raw_json,
                            extra_headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
                        )
                        return
                    self._send_json(200, export)
                    return
            except BrainAPIError as exc:
                self._send_json(502, {"ok": False, "error": str(exc)})
                return
            except Exception as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})
                return

            self._send_json(404, {"ok": False, "error": f"Unknown route: {path}"})

        def _send_auth_payload(self, payload: dict[str, Any]) -> None:
            if payload.get("error") == "steam_unavailable":
                status = 503
            elif payload.get("ok") is False:
                status = 400
            else:
                status = 200
            self._send_json(status, payload)

        def do_POST(self) -> None:
            if not self._validate_local_request(is_post=True):
                return
            path = urlsplit(self.path).path
            try:
                body = self._read_json_body()
                if path == "/api/config/brain":
                    self._send_json(200, app_state.configure_brain(body))
                    return
                if path == "/api/auth/credentials/start":
                    self._send_auth_payload(app_state.credentials_start(body))
                    return
                if path == "/api/auth/credentials/code":
                    self._send_auth_payload(app_state.credentials_submit_code(body))
                    return
                if path == "/api/auth/credentials/poll":
                    self._send_auth_payload(app_state.qr_poll())
                    return
                if path == "/api/auth/qr/start":
                    self._send_auth_payload(app_state.qr_start())
                    return
                if path == "/api/auth/qr/poll":
                    self._send_auth_payload(app_state.qr_poll())
                    return
                if path == "/api/auth/restore":
                    self._send_auth_payload(app_state.restore_session(body))
                    return
                if path == "/api/logout":
                    self._send_json(200, app_state.logout())
                    return
                if path == "/api/settings/turn-delay":
                    self._send_json(200, app_state.set_turn_delay(body))
                    return
                if path == "/api/settings/cm":
                    self._send_json(200, app_state.set_cm_config(body))
                    return
                if path == "/api/career/runner/burn_clocks":
                    self._send_json(200, app_state.set_burn_clocks(body))
                    return
                if path == "/api/career/run":
                    self._send_json(200, app_state.start_career_run(body))
                    return
                if path == "/api/career/runner/stop":
                    self._send_json(200, app_state.stop_runner())
                    return
            except BrainAPIError as exc:
                self._send_json(502, {"ok": False, "online": False, "error": str(exc)})
                return
            except ValueError as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})
                return
            except Exception as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})
                return

            self._send_json(404, {"ok": False, "error": f"Unknown route: {path}"})

    return SweepyRequestHandler


def _run_quiet(args: list[str]) -> str:
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=5.0)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout or ""


def _proc_table_pids(port: int) -> list[int]:
    inodes: set[str] = set()
    for table in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            rows = Path(table).read_text(encoding="utf-8").splitlines()[1:]
        except OSError:
            continue
        for row in rows:
            fields = row.split()
            if len(fields) < 10 or fields[3] != "0A":
                continue
            try:
                local_port = int(fields[1].rsplit(":", 1)[1], 16)
            except (IndexError, ValueError):
                continue
            if local_port == port:
                inodes.add(fields[9])
    if not inodes:
        return []
    pids: list[int] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            handles = list((entry / "fd").iterdir())
        except OSError:
            continue
        for handle in handles:
            try:
                target = os.readlink(handle)
            except OSError:
                continue
            if target.startswith("socket:[") and target[8:-1] in inodes:
                pids.append(int(entry.name))
                break
    return pids


def _listener_pids(port: int) -> list[int]:
    if os.name == "nt":
        found: set[int] = set()
        for line in _run_quiet(["netstat", "-ano"]).splitlines():
            fields = line.split()
            if len(fields) < 5 or fields[0].upper() != "TCP" or fields[3].upper() != "LISTENING":
                continue
            if fields[1].rsplit(":", 1)[-1] == str(port) and fields[4].isdigit():
                found.add(int(fields[4]))
        return sorted(found)
    if Path("/proc/net/tcp").exists():
        return _proc_table_pids(port)
    listed = _run_quiet(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"])
    return sorted({int(value) for value in listed.split() if value.isdigit()})


def _is_sweepy_process(pid: int) -> bool:
    if os.name == "nt":
        command = _run_quiet([
            "powershell", "-NoProfile", "-Command",
            f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine",
        ])
        return "sweepy" in command.lower()
    cmdline_path = Path(f"/proc/{pid}/cmdline")
    if cmdline_path.exists():
        try:
            cmdline = cmdline_path.read_bytes().replace(b"\x00", b" ").lower()
        except OSError:
            return False
        try:
            cwd = str(Path(f"/proc/{pid}/cwd").resolve()).lower()
        except OSError:
            cwd = ""
        return b"sweepy" in cmdline or (b"main.py" in cmdline and "sweepy" in cwd)
    return "sweepy" in _run_quiet(["ps", "-p", str(pid), "-o", "command="]).lower()


def _terminate(pid: int, *, force: bool) -> None:
    if os.name == "nt":
        args = ["taskkill", "/PID", str(pid)] + (["/F"] if force else [])
        try:
            subprocess.run(args, capture_output=True, timeout=10.0)
        except (OSError, subprocess.SubprocessError):
            return
        return
    try:
        os.kill(pid, signal.SIGKILL if force else signal.SIGTERM)
    except OSError:
        return


def _port_released(port: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _listener_pids(port):
            return True
        time.sleep(0.1)
    return False


def _reclaim_port(port: int) -> bool:
    victims = [
        pid for pid in _listener_pids(port)
        if pid != os.getpid() and _is_sweepy_process(pid)
    ]
    if not victims:
        return False
    for pid in victims:
        _terminate(pid, force=False)
    if not _port_released(port, 3.0):
        for pid in victims:
            _terminate(pid, force=True)
        if not _port_released(port, 2.0):
            return False
    print("Sweepy killed", file=sys.stderr, flush=True)
    return True


def _bind_local(host: str, port: int, handler_cls: type[BaseHTTPRequestHandler]) -> ThreadingHTTPServer:
    try:
        return ThreadingHTTPServer((host, port), handler_cls)
    except OSError as exc:
        if exc.errno != errno.EADDRINUSE:
            raise
        if not _reclaim_port(port):
            holders = ", ".join(str(pid) for pid in _listener_pids(port)) or "unknown"
            raise OSError(errno.EADDRINUSE, f"port {port} is held by another process (pid {holders})") from exc
        return ThreadingHTTPServer((host, port), handler_cls)


class SweepyWebServer:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 1616,
        *,
        app_state: SweepyAppState | None = None,
        config: RuntimeConfig | None = None,
        public_dir: Path | str | None = None,
    ) -> None:
        self.state = app_state if app_state is not None else SweepyAppState(config=config, public_dir=public_dir)
        handler_cls = _make_handler_class(self.state)
        self.httpd = _bind_local(host, int(port), handler_cls)
        self.host = str(self.httpd.server_address[0])
        self.port = int(self.httpd.server_address[1])

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def serve_forever(self) -> None:
        self.httpd.serve_forever()

    def shutdown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.state.close()
