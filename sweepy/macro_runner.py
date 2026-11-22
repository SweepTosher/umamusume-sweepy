from __future__ import annotations

import hashlib
import threading
import time
from typing import Any

from sweepy.brain_client import BrainAPIError, BrainClient
from sweepy.race_binary import decode_player_rank
from sweepy.stripper import strip_career_state
from sweepy.umadump_export import (
    build_final_turn_payload,
    export_filename,
    is_final_turn,
)


_COMMAND_LABELS: dict[int, str] = {
    101: "Speed Training",
    102: "Power Training",
    103: "Guts Training",
    105: "Stamina Training",
    106: "Wit Training",
    301: "Outing",
    302: "Outing",
    303: "Outing",
    304: "Summer Rest",
    390: "Pal Outing",
    401: "Rest",
    601: "Summer Speed",
    602: "Summer Stamina",
    603: "Summer Power",
    604: "Summer Guts",
    605: "Summer Wit",
    701: "Summer Rest",
    801: "Infirmary",
}


class _StopCareerLoop(BaseException):
    pass


def _state_recovery_error_cls() -> type[BaseException]:
    try:
        from uma_headless import StateRecoveryError
        return StateRecoveryError
    except ImportError:
        return RuntimeError


def _unwrap_envelope(resp: Any) -> dict[str, Any]:
    if not isinstance(resp, dict):
        raise RuntimeError("UmaClient returned a non-dict envelope")
    inner = resp.get("data")
    if isinstance(inner, dict) and (
        "chara_info" in inner
        or "single_mode_start_common" in inner
        or "single_mode_load_common" in inner
        or "single_mode_factor_select_common" in inner
        or "single_mode_finish_common" in inner
        or "race_start_info" in inner
        or "race_reward_info" in inner
        or "live_data_set" in inner
        or "tp_info" in inner
        or "friend_support_card_data" in inner
        or "summary_user_info_array" in inner
        or "user_info" in inner
    ):
        return dict(inner)
    return dict(resp)


def _normalize_career_state(raw: dict[str, Any]) -> dict[str, Any]:
    state = dict(raw)
    for wrapper_key in ("single_mode_start_common", "single_mode_load_common"):
        common = state.get(wrapper_key)
        if isinstance(common, dict):
            for lift_key in (
                "chara_info",
                "home_info",
                "unchecked_event_array",
                "race_condition_array",
                "race_random_program_array",
                "race_start_info",
                "race_history",
                "single_mode_finish_common",
            ):
                if state.get(lift_key) is None and lift_key in common:
                    state[lift_key] = common[lift_key]
    if state.get("unchecked_event_array") is None:
        state["unchecked_event_array"] = []
    if state.get("race_condition_array") is None:
        state["race_condition_array"] = []
    return state


def _merge_career_state(state: dict[str, Any], update_raw: dict[str, Any], *, clear_race: bool = False) -> None:
    update = _normalize_career_state(update_raw)
    for key in (
        "chara_info",
        "home_info",
        "live_data_set",
        "race_reward_info",
        "command_result",
        "single_mode_finish_common",
    ):
        val = update.get(key)
        if isinstance(val, dict):
            if key == "live_data_set" and isinstance(state.get(key), dict):
                merged = dict(state[key])
                merged.update(val)
                state[key] = merged
            else:
                state[key] = val
    if "unchecked_event_array" in update_raw or "single_mode_start_common" in update_raw:
        evs = update.get("unchecked_event_array")
        if isinstance(evs, list):
            state["unchecked_event_array"] = evs
    if "race_condition_array" in update_raw or "single_mode_start_common" in update_raw:
        rca = update.get("race_condition_array")
        if isinstance(rca, list):
            state["race_condition_array"] = rca
    if "race_history" in update_raw and isinstance(update_raw.get("race_history"), list):
        state["race_history"] = update_raw["race_history"]
    if clear_race:
        state["race_start_info"] = None
        state["race_scenario"] = None
    else:
        if "race_start_info" in update_raw and update_raw.get("race_start_info") is not None:
            state["race_start_info"] = update_raw["race_start_info"]
        if "race_scenario" in update_raw and update_raw.get("race_scenario") is not None:
            state["race_scenario"] = update_raw["race_scenario"]


def _event_choices(event: dict[str, Any]) -> list[Any]:
    contents = event.get("event_contents_info")
    if isinstance(contents, dict):
        choices = contents.get("choice_array")
        if isinstance(choices, list) and choices:
            return choices
    direct = event.get("choice_array")
    if isinstance(direct, list):
        return direct
    return []


def _extract_item_count(data: dict[str, Any], item_id: int) -> int:
    items = data.get("item_list") or data.get("user_item_array") or []
    if not isinstance(items, list):
        return 0
    for row in items:
        if isinstance(row, dict) and int(row.get("item_id") or 0) == item_id:
            return int(row.get("number") or 0)
    return 0


class MacroCareerRunner:
    def __init__(self, *, fast_sleep: bool = False, account_salt: str = "") -> None:
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._fast_sleep = bool(fast_sleep)
        self._account_salt = str(account_salt or "").strip()

        self.client: Any = None
        self.brain: BrainClient | None = None
        self.burn_clocks: bool = False

        self._running: bool = False
        self._finished: bool = False
        self._stopped: bool = False
        self._status: str = "idle"
        self._error: str | None = None
        self._result: dict[str, Any] | None = None
        self._latest_account_data: dict[str, Any] | None = None
        self._latest_account_data_version: int = 0
        self._final_turn_payload: dict[str, Any] | None = None

        self._viewer_id_hash: str = ""
        self._pending_drained_stories: list[int] = []
        self._pending_settled_races: list[dict[str, int]] = []
        self._last_command: dict[str, Any] | None = None
        self._needs_post_square_reload: bool = False
        self._rejected_programs: list[list[int]] = []
        self._rejected_commands: list[list[int]] = []
        self._command_attempts: list[list[int]] = []
        self._prev_endpoint_was_master_square: bool = False

        self._api_calls: int = 0
        self._clocks_used: int = 0
        self._alarm_clock_inventory: int = 0
        self._last_action: str = "IDLE"
        self._history: list[dict[str, Any]] = []
        self._telemetry_turn: int = 0
        self._telemetry_playing_state: int = 0
        self._telemetry_stats: dict[str, int] = {
            "hp": 100,
            "max_hp": 100,
            "mood": 3,
            "speed": 0,
            "stamina": 0,
            "power": 0,
            "guts": 0,
            "wit": 0,
            "sp": 0,
            "fans": 0,
        }
        self._telemetry_tokens: dict[str, int] = {
            "da": 0,
            "pa": 0,
            "vo": 0,
            "vi": 0,
            "me": 0,
        }
        self._telemetry_songs: dict[str, int] = {
            "mastered": 0,
            "staged": 0,
            "concerts_done": 0,
        }

    @property
    def running(self) -> bool:
        with self._lock:
            return self._running

    @property
    def finished(self) -> bool:
        with self._lock:
            return self._finished

    @property
    def latest_account_data(self) -> dict[str, Any] | None:
        with self._lock:
            return dict(self._latest_account_data) if isinstance(self._latest_account_data, dict) else None

    def latest_account_snapshot(self) -> tuple[dict[str, Any] | None, int]:
        with self._lock:
            data = dict(self._latest_account_data) if isinstance(self._latest_account_data, dict) else None
            return data, self._latest_account_data_version

    def set_burn_clocks(self, enabled: bool) -> None:
        with self._lock:
            self.burn_clocks = bool(enabled)

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=5.0)

    def clear_account_data(self) -> None:
        with self._lock:
            self._latest_account_data = None
            self._latest_account_data_version += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": self._running,
                "finished": self._finished,
                "stopped": self._stopped,
                "status": self._status,
                "error": self._error,
                "last_error": self._error,
                "result": dict(self._result) if isinstance(self._result, dict) else None,
                "burn_clocks": self.burn_clocks,
                "turn": self._telemetry_turn,
                "playing_state": self._telemetry_playing_state,
                "stats": dict(self._telemetry_stats),
                "tokens": dict(self._telemetry_tokens),
                "songs": dict(self._telemetry_songs),
                "api_calls": self._api_calls,
                "clocks_used": self._clocks_used,
                "last_action": self._last_action,
                "history": [dict(item) for item in self._history],
                "final_turn_export_ready": self._final_turn_payload is not None,
            }

    def _capture_final_turn_export(self, state: dict[str, Any]) -> None:
        chara = state.get("chara_info") if isinstance(state, dict) else None
        if not is_final_turn(chara):
            return
        payload = build_final_turn_payload(state)
        if payload is None:
            return
        with self._lock:
            self._final_turn_payload = payload

    def final_turn_export(self) -> dict[str, Any] | None:
        with self._lock:
            payload = self._final_turn_payload
        if payload is None:
            return None
        chara = payload.get("chara_info") or {}
        return {
            "json": payload,
            "filename": export_filename(chara),
            "turn": chara.get("turn"),
        }

    def start(
        self,
        client: Any,
        brain: BrainClient,
        *,
        burn_clocks: bool = False,
        initial_state: dict[str, Any] | None = None,
        account_data: dict[str, Any] | None = None,
        max_steps: int = 1200,
    ) -> None:
        if not str(getattr(brain, "api_key", "") or "").strip():
            raise BrainAPIError("Brain API key is required to run a career")
        with self._lock:
            if self._running and self._thread is not None and self._thread.is_alive():
                raise RuntimeError("Runner already running")
            self._reset_run_state(burn_clocks=burn_clocks)
            self._running = True
            self._status = "running"
            self._thread = threading.Thread(
                target=self._worker_entry,
                kwargs={
                    "client": client,
                    "brain": brain,
                    "burn_clocks": burn_clocks,
                    "initial_state": initial_state,
                    "account_data": account_data,
                    "max_steps": max_steps,
                },
                daemon=True,
            )
            self._thread.start()

    def run_sync(
        self,
        client: Any,
        brain: BrainClient,
        *,
        burn_clocks: bool = False,
        initial_state: dict[str, Any] | None = None,
        account_data: dict[str, Any] | None = None,
        max_steps: int = 1200,
    ) -> dict[str, Any]:
        if not str(getattr(brain, "api_key", "") or "").strip():
            raise BrainAPIError("Brain API key is required to run a career")
        with self._lock:
            if self._running:
                raise RuntimeError("Runner already running")
            self._reset_run_state(burn_clocks=burn_clocks)
            self._running = True
            self._status = "running"
        self._worker_entry(
            client=client,
            brain=brain,
            burn_clocks=burn_clocks,
            initial_state=initial_state,
            account_data=account_data,
            max_steps=max_steps,
        )
        return self.snapshot()

    def _reset_run_state(self, *, burn_clocks: bool) -> None:
        self._stop_event.clear()
        self.burn_clocks = bool(burn_clocks)
        self._finished = False
        self._stopped = False
        self._error = None
        self._result = None
        self._latest_account_data = None
        self._final_turn_payload = None
        self._pending_drained_stories = []
        self._pending_settled_races = []
        self._last_command = None
        self._needs_post_square_reload = False
        self._rejected_programs = []
        self._rejected_commands = []
        self._command_attempts = []
        self._prev_endpoint_was_master_square = False
        self._resume_pending = False
        self._api_calls = 0
        self._clocks_used = 0
        self._alarm_clock_inventory = 0
        self._last_action = "STARTING"
        self._history = []
        self._telemetry_turn = 0
        self._telemetry_playing_state = 0
        self._telemetry_stats = {
            "hp": 100,
            "max_hp": 100,
            "mood": 3,
            "speed": 0,
            "stamina": 0,
            "power": 0,
            "guts": 0,
            "wit": 0,
            "sp": 0,
            "fans": 0,
        }
        self._telemetry_tokens = {"da": 0, "pa": 0, "vo": 0, "vi": 0, "me": 0}
        self._telemetry_songs = {"mastered": 0, "staged": 0, "concerts_done": 0}

    def _check_stop(self) -> None:
        if self._stop_event.is_set():
            raise _StopCareerLoop()

    def _sleep_fixed(self, seconds: float) -> None:
        self._check_stop()
        if self._fast_sleep or seconds <= 0:
            return
        timing = getattr(self.client, "timing", None)
        if timing is not None and bool(getattr(timing, "disabled", False)):
            if seconds < 0.15:
                return
        end_ts = time.monotonic() + seconds
        while True:
            self._check_stop()
            rem = end_ts - time.monotonic()
            if rem <= 0:
                break
            time.sleep(min(0.05, rem))

    def _sleep_turn_pacing(self) -> None:
        self._check_stop()
        if self._fast_sleep:
            return
        timing = getattr(self.client, "timing", None)
        if timing is not None and callable(getattr(timing, "sleep_turn", None)):
            timing.sleep_turn()

    def _rpc(self, endpoint: str, payload: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        self._check_stop()
        with self._lock:
            self._api_calls += 1
        return self.client.call(endpoint, payload or {}, **kwargs)

    def _load_career(self, scenario_id: int = 3) -> dict[str, Any]:
        self._check_stop()
        with self._lock:
            self._api_calls += 1
        return self.client.load_career(scenario_id)

    def _record_history(self, turn: int, kind: str, action: str, detail: str = "") -> None:
        with self._lock:
            self._last_action = action
            entry = {
                "turn": int(turn),
                "kind": kind,
                "type": kind,
                "action": action,
                "detail": detail,
                "snapshot": detail,
                "ts": round(time.time(), 3),
            }
            self._history.append(entry)
            if len(self._history) > 80:
                self._history = self._history[-80:]

    def _update_telemetry(self, state: dict[str, Any]) -> None:
        self._capture_final_turn_export(state)
        chara = state.get("chara_info")
        live = state.get("live_data_set")
        with self._lock:
            if isinstance(chara, dict):
                self._telemetry_turn = int(chara.get("turn") or 0)
                self._telemetry_playing_state = int(chara.get("playing_state") or 0)
                self._telemetry_stats = {
                    "hp": int(chara.get("vital") or 0),
                    "max_hp": int(chara.get("max_vital") or 100),
                    "mood": int(chara.get("motivation") or 3),
                    "speed": int(chara.get("speed") or 0),
                    "stamina": int(chara.get("stamina") or 0),
                    "power": int(chara.get("power") or 0),
                    "guts": int(chara.get("guts") or 0),
                    "wit": int(chara.get("wiz") or 0),
                    "sp": int(chara.get("skill_point") or 0),
                    "fans": int(chara.get("fans") or 0),
                }
            if isinstance(live, dict):
                perf = live.get("live_performance_info")
                if isinstance(perf, dict):
                    self._telemetry_tokens = {
                        "da": int(perf.get("dance") or 0),
                        "pa": int(perf.get("passion") or 0),
                        "vo": int(perf.get("vocal") or 0),
                        "vi": int(perf.get("visual") or 0),
                        "me": int(perf.get("mental") or 0),
                    }
                self._telemetry_songs = {
                    "mastered": len(live.get("master_live_id_array") or []),
                    "staged": len(live.get("next_live_id_array") or []),
                    "concerts_done": len(live.get("live_result_array") or []),
                }

    def _bootstrap_or_resume_state(
        self,
        *,
        initial_state: dict[str, Any] | None,
        account_data: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if isinstance(initial_state, dict):
            normalized = _normalize_career_state(_unwrap_envelope(initial_state))
            self._update_telemetry(normalized)
            return normalized

        if isinstance(account_data, dict):
            acct = _unwrap_envelope(account_data)
        else:
            with self._lock:
                self._api_calls += 1
            acct = _unwrap_envelope(self.client.login(read_info=False))

        if isinstance(acct, dict):
            with self._lock:
                self._latest_account_data = acct
                self._latest_account_data_version += 1

        self._alarm_clock_inventory = _extract_item_count(acct, 95)
        active_light = acct.get("single_mode_chara_light") or acct.get("single_mode_chara")
        if isinstance(active_light, dict) and int(active_light.get("single_mode_chara_id") or 0) > 0:
            active_scen = int(active_light.get("scenario_id") or 3)
            if active_scen != 3:
                raise RuntimeError(f"Career scenario {active_scen}, not Grand Live (3)")
            loaded = _normalize_career_state(_unwrap_envelope(self._load_career(3)))
            self._update_telemetry(loaded)
            turn = int((loaded.get("chara_info") or {}).get("turn") or 1)
            self._record_history(turn, "Resume", "Resumed active Grand Live career", f"Turn {turn}")
            return loaded

        raise RuntimeError(
            "no active career (start one in-game)"
        )

    def _drain_single_choice_events(self, state: dict[str, Any]) -> bool:
        for _ in range(64):
            self._check_stop()
            events = state.get("unchecked_event_array") or []
            if not isinstance(events, list) or not events:
                return False
            ev = events[0]
            if not isinstance(ev, dict):
                return False
            choices = _event_choices(ev)
            if len(choices) > 1:
                return True
            turn = int((state.get("chara_info") or {}).get("turn") or 1)
            raw_event_id = ev.get("event_id")
            if isinstance(raw_event_id, int) and not isinstance(raw_event_id, bool) and raw_event_id > 0:
                event_id = raw_event_id
            else:
                raise RuntimeError(f"Queued event has no usable event_id: {raw_event_id!r}")
            raw_chara_id = ev.get("chara_id")
            if isinstance(raw_chara_id, int) and not isinstance(raw_chara_id, bool):
                chara_id = raw_chara_id
            elif isinstance(raw_chara_id, str) and raw_chara_id.strip().isdigit():
                chara_id = int(raw_chara_id.strip())
            else:
                chara_id = 0
            story_id = ev.get("story_id")
            res = self._rpc(
                "single_mode_live/check_event",
                {
                    "event_id": event_id,
                    "chara_id": chara_id,
                    "choice_number": 0,
                    "current_turn": turn,
                },
            )
            _merge_career_state(state, _unwrap_envelope(res))
            if isinstance(story_id, int) and not isinstance(story_id, bool):
                self._pending_drained_stories.append(story_id)
            elif isinstance(story_id, str) and story_id.strip().isdigit():
                self._pending_drained_stories.append(int(story_id.strip()))
            self._update_telemetry(state)
        raise RuntimeError("64 undrained single-choice events in a row")

    def _set_viewer_hash(self, client: Any) -> None:
        raw_vid = str(getattr(client, "viewer_id", "") or "").strip()
        if not raw_vid or raw_vid == "0":
            raise RuntimeError("Client viewer identity is unavailable")
        material = f"{self._account_salt}:{raw_vid}" if self._account_salt else raw_vid
        self._viewer_id_hash = hashlib.sha256(material.encode("utf-8")).hexdigest()

    def _clocks_budget(self, state: dict[str, Any]) -> tuple[int, int]:
        home = state.get("home_info") or {}
        free_clocks = int(home.get("available_free_continue_num") or 0)
        avail_cont = home.get("available_continue_num")
        if isinstance(avail_cont, int) and not isinstance(avail_cont, bool):
            total_avail = max(0, avail_cont)
        else:
            total_avail = max(0, free_clocks + self._alarm_clock_inventory)
        return total_avail, max(0, free_clocks)

    def _execute_race_macro(
        self,
        op: str,
        params: dict[str, Any],
        state: dict[str, Any],
    ) -> None:
        chara = state.get("chara_info") or {}
        turn = int(params.get("current_turn") or chara.get("turn") or 1)
        pid = int(
            params.get("program_id")
            or (state.get("race_start_info") or {}).get("program_id")
            or chara.get("race_program_id")
            or 0
        )
        mandatory = bool(params.get("mandatory", False))
        target_rank = int(params.get("target_rank", 18))
        phase = str(params.get("phase") or "start")
        rec_err_cls = _state_recovery_error_cls()

        if op == "race_macro":
            if pid <= 0:
                raise BrainAPIError("race_macro missing positive program_id")
            if [turn, pid] in self._rejected_programs:
                self._record_history(turn, "Race", f"Program {pid} already raced this turn", "Skipped")
                return
            state.pop("race_reward_info", None)
            live = state.get("race_start_info") or {}
            live_pid = int(live.get("program_id") or 0) if isinstance(live, dict) else 0
            if pid > 0 and live_pid == pid:
                entry_res = None
                self._record_history(turn, "Race", f"Program {pid} already entered", "Starting")
            else:
                try:
                    entry_res = self._rpc(
                        "single_mode_live/race_entry",
                        {"program_id": pid, "current_turn": turn},
                    )
                except rec_err_cls as exc:
                    if getattr(exc, "code", None) not in (102, 205):
                        raise
                    entry_res = None
                    self._record_history(
                        turn, "Race", f"Program {pid} was already entered", "Starting directly"
                    )

            if entry_res is not None:
                _merge_career_state(state, _unwrap_envelope(entry_res))
                self._update_telemetry(state)
                has_multi_choice = self._drain_single_choice_events(state)
                if has_multi_choice:
                    self._record_history(turn, "Race", f"Entered race {pid} (awaiting pre-race choice)", "Multi-choice")
                    return
            phase = "start"

        if op == "race_resume_macro":
            has_multi_choice = self._drain_single_choice_events(state)
            if has_multi_choice:
                return

        rank = 1
        sm_cid = int((state.get("chara_info") or {}).get("single_mode_chara_id") or 0)

        if phase == "start":
            try:
                start_res = self._rpc(
                    "single_mode_live/race_start",
                    {"is_short": 1, "current_turn": turn},
                )
            except rec_err_cls as exc:
                code = getattr(exc, "code", None)
                if code == 102:
                    loaded = _unwrap_envelope(self._load_career(3))
                    state.clear()
                    state.update(_normalize_career_state(loaded))
                    self._needs_post_square_reload = False
                    self._update_telemetry(state)
                    start_res = {"data": loaded}
                elif code != 205:
                    raise
                else:
                    reloaded = _normalize_career_state(_unwrap_envelope(self._load_career(3)))
                    state.clear()
                    state.update(reloaded)
                    self._needs_post_square_reload = False
                    self._update_telemetry(state)
                    cur_turn = int((state.get("chara_info") or {}).get("turn") or turn)
                    pair = [cur_turn, pid]
                    if pair not in self._rejected_programs:
                        self._rejected_programs.append(pair)
                    self._record_history(cur_turn, "Race", f"Program {pid} refused to start (205)", "Reloaded")
                    return
            start_data = _unwrap_envelope(start_res)
            _merge_career_state(state, start_data)
            rsi = start_data.get("race_start_info") or state.get("race_start_info") or {}
            if pid <= 0 and isinstance(rsi, dict) and rsi.get("program_id"):
                pid = int(rsi["program_id"])
            horses = rsi.get("race_horse_data") if isinstance(rsi, dict) else None
            scenario_b64 = start_data.get("race_scenario")
            if isinstance(scenario_b64, str) and isinstance(horses, list) and sm_cid > 0:
                rank = decode_player_rank(scenario_b64, horses, sm_cid)

            if (mandatory or self.burn_clocks) and self._clocks_budget(state)[0] > 0:
                fresh = _normalize_career_state(_unwrap_envelope(self._load_career(3)))
                if isinstance(fresh.get("home_info"), dict):
                    state["home_info"] = fresh["home_info"]
            clocks_available, free_clocks = self._clocks_budget(state)
            clock_limit = 1 if self.burn_clocks else target_rank
            refused_once = False
            while (mandatory or self.burn_clocks) and rank > clock_limit and clocks_available > 0:
                cont_type = 1 if free_clocks > 0 else 2
                try:
                    cont_res = self._rpc(
                        "single_mode_live/continue",
                        {"current_turn": turn, "continue_type": cont_type},
                    )
                except rec_err_cls as exc:
                    if getattr(exc, "code", None) != 205:
                        raise
                    loaded = _normalize_career_state(_unwrap_envelope(self._load_career(3)))
                    state.clear()
                    state.update(loaded)
                    self._needs_post_square_reload = False
                    self._update_telemetry(state)
                    cur_turn = int((state.get("chara_info") or {}).get("turn") or turn)
                    pair = [cur_turn, pid]
                    if pid > 0 and pair not in self._rejected_programs:
                        self._rejected_programs.append(pair)
                    turn = cur_turn
                    if not state.get("race_start_info"):
                        return
                    if refused_once:
                        break
                    refused_once = True
                    clocks_available, free_clocks = self._clocks_budget(state)
                    continue
                with self._lock:
                    self._clocks_used += 1
                if cont_type == 1:
                    free_clocks = max(0, free_clocks - 1)
                else:
                    self._alarm_clock_inventory = max(0, self._alarm_clock_inventory - 1)
                clocks_available -= 1

                cont_data = _unwrap_envelope(cont_res)
                _merge_career_state(state, cont_data)
                if isinstance(cont_data.get("home_info"), dict):
                    clocks_available, free_clocks = self._clocks_budget(state)

                if self._drain_single_choice_events(state):
                    return

                retry_res = self._rpc(
                    "single_mode_live/race_start",
                    {"is_short": 1, "current_turn": turn},
                )
                retry_data = _unwrap_envelope(retry_res)
                _merge_career_state(state, retry_data)
                r_rsi = retry_data.get("race_start_info") or state.get("race_start_info") or {}
                r_horses = r_rsi.get("race_horse_data") if isinstance(r_rsi, dict) else None
                r_scen = retry_data.get("race_scenario")
                if isinstance(r_scen, str) and isinstance(r_horses, list) and sm_cid > 0:
                    rank = decode_player_rank(r_scen, r_horses, sm_cid)
                self._record_history(
                    turn,
                    "Race",
                    f"Clock used · retry {self._clocks_used}",
                    f"Program {pid} · rank {rank}",
                )

            phase = "end"

        result_rank = rank
        if phase == "end":
            self._sleep_fixed(0.16)
            try:
                end_res = self._rpc(
                    "single_mode_live/race_end",
                    {"current_turn": turn},
                )
            except rec_err_cls as exc:
                if getattr(exc, "code", None) != 102:
                    raise
                loaded = _unwrap_envelope(self._load_career(3))
                state.clear()
                state.update(_normalize_career_state(loaded))
                self._needs_post_square_reload = False
                self._update_telemetry(state)
                if not state.get("race_start_info") and not state.get("race_reward_info"):
                    cur_turn = int((state.get("chara_info") or {}).get("turn") or turn)
                    pair = [cur_turn, pid]
                    if pid > 0 and pair not in self._rejected_programs:
                        self._rejected_programs.append(pair)
                    self._record_history(cur_turn, "Race", f"Program {pid} already settled (102)", "Skipped")
                    return
                end_res = {"data": loaded}
            end_data = _unwrap_envelope(end_res)
            _merge_career_state(state, end_data)
            reward_info = end_data.get("race_reward_info") or {}
            if isinstance(reward_info, dict) and reward_info.get("result_rank") is not None:
                result_rank = int(reward_info["result_rank"])
            phase = "out"

        if phase == "out":
            try:
                out_res = self._rpc(
                    "single_mode_live/race_out",
                    {"current_turn": turn},
                )
            except rec_err_cls as exc:
                if getattr(exc, "code", None) not in (102, 205):
                    raise
                loaded = _normalize_career_state(_unwrap_envelope(self._load_career(3)))
                state.clear()
                state.update(loaded)
                state.pop("race_reward_info", None)
                self._update_telemetry(state)
                cur_turn = int((state.get("chara_info") or {}).get("turn") or turn)
                pair = [cur_turn, pid]
                if pid > 0 and pair not in self._rejected_programs:
                    self._rejected_programs.append(pair)
                self._record_history(cur_turn, "Race", f"Program {pid} already out", "Reloaded")
                return
            _merge_career_state(state, _unwrap_envelope(out_res), clear_race=True)
            reward_info = state.get("race_reward_info")
            if isinstance(reward_info, dict) and reward_info.get("result_rank") is not None:
                result_rank = int(reward_info["result_rank"])
            state.pop("race_reward_info", None)
            if int((state.get("chara_info") or {}).get("turn") or 0) <= turn:
                loaded = _normalize_career_state(_unwrap_envelope(self._load_career(3)))
                state.clear()
                state.update(loaded)
                state.pop("race_reward_info", None)
            self._update_telemetry(state)
            if pid > 0 and [turn, pid] not in self._rejected_programs:
                self._rejected_programs.append([turn, pid])
            if pid > 0:
                self._pending_settled_races.append({
                    "turn": turn,
                    "program_id": pid,
                    "result_rank": result_rank,
                })
            self._record_history(
                turn,
                "Race",
                f"Program {pid} finished P{result_rank}",
                f"Rank {result_rank}",
            )
            self._drain_single_choice_events(state)

    def _execute_rpc_step(self, params: dict[str, Any], state: dict[str, Any]) -> None:
        endpoint = str(params.get("endpoint") or "").strip()
        payload = dict(params.get("payload") or {})
        if not endpoint:
            raise BrainAPIError("rpc_step missing endpoint")

        turn = int((state.get("chara_info") or {}).get("turn") or payload.get("current_turn") or 1)

        if endpoint.endswith("/master_square"):
            if self._prev_endpoint_was_master_square:
                self._sleep_fixed(0.08)
            res = self._rpc(endpoint, payload)
            _merge_career_state(state, _unwrap_envelope(res))
            loaded = _normalize_career_state(_unwrap_envelope(self._load_career(3)))
            state.clear()
            state.update(loaded)
            self._needs_post_square_reload = False
            self._prev_endpoint_was_master_square = True
            self._update_telemetry(state)
            sq_id = payload.get("square_id", "")
            self._record_history(turn, "Song", f"Learned song · slot {sq_id}", f"Songs: {self._telemetry_songs['mastered']}")
            return

        if endpoint.endswith("/gain_skills"):
            raw_arr = payload.get("gain_skill_info_array")
            if not isinstance(raw_arr, list):
                raw_arr = payload.get("skill_Select_array") or []
            skill_items = [
                {"skill_id": int(item["skill_id"]), "level": int(item.get("level", item.get("skill_level", 1)))}
                for item in raw_arr
                if isinstance(item, dict) and item.get("skill_id")
            ]
            if not skill_items:
                raise BrainAPIError("gain_skills missing skill items")
            req_turn = int(payload.get("current_turn") or turn)
            res = self.client.gain_skills(skill_items, req_turn)
            _merge_career_state(state, _unwrap_envelope(res))
            loaded = _normalize_career_state(_unwrap_envelope(self._load_career(3)))
            state.clear()
            state.update(loaded)
            self._needs_post_square_reload = False
            self._prev_endpoint_was_master_square = False
            self._update_telemetry(state)
            sid0 = skill_items[0]["skill_id"]
            self._record_history(turn, "Skill", f"Learned skill {sid0}", f"SP left: {(state.get('chara_info') or {}).get('skill_point', 0)}")
            return

        self._prev_endpoint_was_master_square = False

        if endpoint.endswith("/load"):
            loaded = _normalize_career_state(_unwrap_envelope(self._load_career(3)))
            state.clear()
            state.update(loaded)
            self._needs_post_square_reload = False
            self._update_telemetry(state)
            return

        if endpoint.endswith("/exec_command"):
            raw_cmd_id = int(payload.get("command_id") or 0)
            eff_cmd_id = raw_cmd_id if raw_cmd_id != 0 else int(payload.get("command_group_id") or 0)
            partners: list[int] = []
            cmd_array = (
                (state.get("home_info") or {}).get("command_info_array")
                or (state.get("live_data_set") or {}).get("command_info_array")
                or []
            )
            if isinstance(cmd_array, list):
                for row in cmd_array:
                    if isinstance(row, dict) and int(row.get("command_id") or -1) in (raw_cmd_id, eff_cmd_id):
                        partners = [int(p) for p in (row.get("training_partner_array") or [])]
                        break
            self._sleep_turn_pacing()
            try:
                res = self._rpc(endpoint, payload)
            except _state_recovery_error_cls() as exc:
                code = getattr(exc, "code", None)
                if code not in (205, 2501):
                    raise
                same_turn = [pair for pair in self._command_attempts if pair[0] == turn]
                if len(same_turn) >= 3:
                    raise
                self._command_attempts.append([turn, eff_cmd_id])
                del self._command_attempts[:-64]
                loaded = _normalize_career_state(_unwrap_envelope(self._load_career(3)))
                state.clear()
                state.update(loaded)
                self._needs_post_square_reload = False
                self._prev_endpoint_was_master_square = False
                self._update_telemetry(state)
                pair = [turn, eff_cmd_id]
                if pair not in self._rejected_commands:
                    self._rejected_commands.append(pair)
                    del self._rejected_commands[:-32]
                self._record_history(
                    turn, "Recovery", f"Command {eff_cmd_id} refused by the server ({code})", "Reloaded"
                )
                return
            res_data = _unwrap_envelope(res)
            cmd_res = res_data.get("command_result") or {}
            self._last_command = {
                "turn": turn,
                "command_id": int(cmd_res.get("command_id", eff_cmd_id)),
                "result_state": int(cmd_res.get("result_state", 0)),
                "partners": partners,
            }
            _merge_career_state(state, res_data)
            try:
                loaded = _normalize_career_state(_unwrap_envelope(self._load_career(3)))
            except Exception:
                loaded = None
            if loaded is not None:
                state.clear()
                state.update(loaded)
            self._needs_post_square_reload = False
            self._prev_endpoint_was_master_square = False
            self._update_telemetry(state)
            label = _COMMAND_LABELS.get(eff_cmd_id, f"Command {eff_cmd_id}")
            st = self._telemetry_stats
            self._record_history(
                turn,
                "Turn",
                label,
                f"HP {st['hp']}/{st['max_hp']} · SPD {st['speed']} WIT {st['wit']}",
            )
            return

        if endpoint.endswith(("/check_event", "/live_start", "/minigame_end")):
            res = self._rpc(endpoint, payload)
            _merge_career_state(state, _unwrap_envelope(res))
            self._update_telemetry(state)
            if endpoint.endswith("/check_event"):
                choice_num = payload.get("choice_number", 0)
                self._record_history(turn, "Choice", f"Event {payload.get('event_id')} -> choice {choice_num}", "Brain choice")
            elif endpoint.endswith("/live_start"):
                self._record_history(turn, "Concert", "Started Grand Live concert", f"Songs: {self._telemetry_songs['mastered']}")
            else:
                self._record_history(turn, "Minigame", "Completed minigame", f"Turn {turn}")
            return

        if endpoint.endswith("/race_entry"):
            pid = int(payload.get("program_id") or 0)
            if pid <= 0:
                raise BrainAPIError("rpc_step race_entry missing program_id")
            self._execute_race_macro(
                "race_macro",
                {
                    "program_id": pid,
                    "current_turn": turn,
                    "mandatory": bool(payload.get("mandatory", False)),
                    "target_rank": int(payload.get("target_rank", 18) or 18),
                },
                state,
            )
            return

        res = self._rpc(endpoint, payload)
        _merge_career_state(state, _unwrap_envelope(res))
        self._update_telemetry(state)
        self._record_history(turn, "RPC", endpoint, f"Turn {turn}")


    def _decide_recovering(self, brain: BrainClient, state: dict[str, Any]) -> dict[str, Any]:
        turn = self._telemetry_turn
        probe_resets = 0
        stat_resets = 0
        while True:
            stripped = strip_career_state(state)
            delta = {
                "drained_stories": list(self._pending_drained_stories),
                "settled_races": list(self._pending_settled_races),
                "last_command": dict(self._last_command) if isinstance(self._last_command, dict) else None,
                "needs_post_square_reload": bool(self._needs_post_square_reload),
                "rejected_programs": [list(item) for item in self._rejected_programs],
                "rejected_commands": [list(item) for item in self._rejected_commands],
            }
            options = {
                "burn_clocks": bool(self.burn_clocks),
                "resume": self._resume_pending,
            }
            self._resume_pending = False
            try:
                decision = brain.decide(self._viewer_id_hash, stripped, delta, options)
            except BrainAPIError as exc:
                status = getattr(exc, "status_code", None)
                code = getattr(exc, "code", None)
                if status == 422 and code == "stat_regression" and stat_resets < 2:
                    stat_resets += 1
                    note = f"Stats dropped; brain session reset {stat_resets}/2"
                elif status == 429 and code == "probe_cap" and probe_resets < 4:
                    probe_resets += 1
                    note = f"probe cap reached; session reset {probe_resets}/4"
                else:
                    raise
                self._record_history(turn, "Recovery", note, "retry")
                self._close_brain_career(brain)
                self._resume_pending = True
                self._sleep_fixed(1.0)
                loaded = _normalize_career_state(_unwrap_envelope(self._load_career(3)))
                state.clear()
                state.update(loaded)
                self._needs_post_square_reload = False
                self._prev_endpoint_was_master_square = False
                self._update_telemetry(state)
                turn = self._telemetry_turn
                continue
            self._pending_drained_stories.clear()
            self._pending_settled_races.clear()
            self._last_command = None
            return decision

    def _close_brain_career(self, brain: BrainClient) -> None:
        try:
            brain.close_career(self._viewer_id_hash)
        except Exception as exc:
            self._record_history(
                self._telemetry_turn, "Cleanup", f"Brain session close failed: {exc}", "close_failed"
            )


    def _worker_entry(
        self,
        *,
        client: Any,
        brain: BrainClient,
        burn_clocks: bool,
        initial_state: dict[str, Any] | None,
        account_data: dict[str, Any] | None,
        max_steps: int,
    ) -> None:
        self.client = client
        self.brain = brain

        try:
            self._set_viewer_hash(client)
            rec_err_cls = _state_recovery_error_cls()
            state = self._bootstrap_or_resume_state(
                initial_state=initial_state,
                account_data=account_data,
            )
            self._resume_pending = True
            consecutive_recoveries = 0

            for _step in range(max_steps):
                self._check_stop()
                if self._finished:
                    break
                try:
                    self._drain_single_choice_events(state)
                    self._check_stop()

                    decision = self._decide_recovering(brain, state)

                    op = decision["op"]
                    params = decision["params"]

                    if op == "rpc_step":
                        self._execute_rpc_step(params, state)
                    elif op in ("race_macro", "race_resume_macro"):
                        self._prev_endpoint_was_master_square = False
                        self._execute_race_macro(op, params, state)
                    elif op == "terminal_skills":
                        raise BrainAPIError("Skill purchases are disabled")
                    elif op == "terminal_finish":
                        raise BrainAPIError("Career ending is disabled")
                    else:
                        raise BrainAPIError(f"Unsupported brain opcode: {op!r}")

                    consecutive_recoveries = 0
                except _StopCareerLoop:
                    raise
                except BrainAPIError as exc:
                    if getattr(exc, "status_code", None) == 409:
                        self._close_brain_career(brain)
                        if getattr(exc, "code", None) == "career_complete":
                            with self._lock:
                                self._finished = True
                                self._status = "finished"
                                self._error = None
                                self._result = {
                                    "reason": "career_complete",
                                    "turn": self._telemetry_turn,
                                }
                                self._last_action = "FINISHED: career_complete"
                            self._record_history(
                                self._telemetry_turn,
                                "Finish",
                                "career complete",
                                "career_complete",
                            )
                            break
                    raise
                except rec_err_cls as exc:
                    consecutive_recoveries += 1
                    if consecutive_recoveries > 4:
                        raise RuntimeError(f"4 consecutive recovery failures: {exc}") from exc
                    mode = str(getattr(exc, "recovery", "reconcile") or "reconcile")
                    code = getattr(exc, "code", None)
                    if mode in ("rebootstrap_and_reconcile", "replace_identity_and_rebootstrap") or code in (201, 217, 709):
                        with self._lock:
                            self._api_calls += 1
                        self.client.login(read_info=False)
                        self._set_viewer_hash(self.client)
                    reloaded = _normalize_career_state(_unwrap_envelope(self._load_career(3)))
                    state.clear()
                    state.update(reloaded)
                    self._needs_post_square_reload = False
                    self._prev_endpoint_was_master_square = False
                    self._update_telemetry(state)
                    turn = int((state.get("chara_info") or {}).get("turn") or 0)
                    self._record_history(turn, "Recovery", f"State reconciled ({consecutive_recoveries}/4)", mode)
            else:
                if not self._finished:
                    raise RuntimeError(f"Run hit max_steps={max_steps}")
        except _StopCareerLoop:
            with self._lock:
                self._stopped = True
                self._status = "stopped"
                self._last_action = "STOPPED"
        except Exception as exc:
            with self._lock:
                self._error = str(exc)
                self._status = "error"
                self._last_action = f"ERROR: {type(exc).__name__}"
        finally:
            with self._lock:
                self._running = False
                if self._status == "running":
                    self._status = "finished" if self._finished else "idle"
