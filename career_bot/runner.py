import gzip
import base64
import msgpack
import threading
import time
import json
import os
import random
import math
from datetime import datetime
from pathlib import Path

from career_bot.scenarios.mant import MantStrategy
from career_bot.races import RacePlanner
from career_bot.skills import SkillBuyer
from career_bot.items import MantItemManager, ITEM_NAMES, SHOP_ITEM_COSTS, DISPLAY_TO_ID, display_to_slug


from career_bot.report import new_report, add_event, add_api_call, add_decision, finish_report, write_report, set_error


STRATEGIES = {
    4: MantStrategy,
}


def runtime_output_root(base_dir):
    override = os.environ.get("UMA_RUNTIME_DIR")
    if override:
        return Path(override).expanduser().resolve()

    base = Path(base_dir).resolve()
    for candidate in (base, *base.parents):
        if (candidate / ".git").exists():
            return candidate / "uma_runtime"
    return base.parent / "uma_runtime"

TRAINING_LABELS = {
    101: "Speed",
    102: "Power",
    103: "Guts",
    105: "Stamina",
    106: "Wit",
    601: "Speed",
    602: "Stamina",
    603: "Power",
    604: "Guts",
    605: "Wit",
}


class CareerRunner:
    def __init__(self, base_dir):
        self.base_dir = Path(base_dir)
        self.report = None
        self.lock = threading.Lock()
        self.thread = None
        self.stop_requested = False
        self.burn_clocks = False
        self.race_planner = RacePlanner(base_dir)
        self.skill_buyer = SkillBuyer(base_dir)
        self.item_manager = MantItemManager()
        self.status = {
            "running": False,
            "preset": "",
            "scenario_id": 0,
            "turn": 0,
            "steps": 0,
            "last_action": "",
            "last_error": "",
            "finished": False,
            "skills_bought": 0,
            "items_bought": 0,
            "items_used": 0,
            "clocks_used": 0,
            "log": [],
            "action_history": [],
        }

    def _init_debug_log(self, preset=None, scenario_id=4):
        self.report = new_report(preset, scenario_id)

    def _debug(self, event, state=None, data=None):
        row = {
            "event": event,
        }
        if state:
            d = state.get("data") or {}
            chara = d.get("chara_info") or {}
            free = d.get("free_data_set") or {}
            row["turn"] = int(chara.get("turn") or 0)
            row["skill_point"] = int(chara.get("skill_point") or 0)
            row["mant_coin"] = int(free.get("coin_num") if free.get("coin_num") is not None else free.get("gained_coin_num") or 0)
            row["motivation"] = int(chara.get("motivation") or 0)
            row["stats"] = self._turn_stats(chara)
        if data:
            row.update(data)
        if self.report:
            add_event(self.report, row)

    def start(self, client, preset, initial_result, max_steps=2500, burn_clocks=False, dev_mode=False):        
        with self.lock:
            if self.status["running"]:
                raise RuntimeError("Career runner already active")
            scenario_id = int(preset.get("scenario_id") or 4)
            strategy_cls = STRATEGIES.get(scenario_id)
            if not strategy_cls:
                raise RuntimeError(f"No runner for scenario {scenario_id}")
            self.stop_requested = False
            self.burn_clocks = burn_clocks
            self.dev_mode = dev_mode
            self.race_planner = RacePlanner(self.base_dir)
            self.skill_buyer = SkillBuyer(self.base_dir)
            self.item_manager = MantItemManager()
            self.status = {
                "running": True,
                "preset": preset.get("name", ""),
                "scenario_id": scenario_id,
                "turn": 0,
                "steps": 0,
                "last_action": "started",
                "last_error": "",
                "finished": False,
                "skills_bought": 0,
                "items_bought": 0,
                "items_used": 0,
                "clocks_used": 0,
                "log": [],
                "action_history": [],
            }
            self.report = new_report(preset, scenario_id)
            if client:
                client.report = self.report
                def _on_api_log(direction, ep, data, req_id=None):
                    if self.report:
                        import time
                        add_api_call(self.report, {
                            "ts": time.time(),
                            "direction": direction,
                            "endpoint": ep,
                            "data": data,
                            "req_id": req_id,
                            "turn": self.status.get("turn", 0)
                        })
                client.on_api_log = _on_api_log
            self._log_locked("started", 0, f"preset {preset.get('name', '')} (burn_clocks={burn_clocks})")
            self.thread = threading.Thread(target=self._run, args=(client, preset, initial_result, strategy_cls(self.race_planner), max_steps), daemon=True)
            self.thread.start()

    def stop(self):
        with self.lock:
            self.stop_requested = True

    def snapshot(self):
        with self.lock:
            data = dict(self.status)
            data["burn_clocks"] = self.burn_clocks
            return data

    def set_burn_clocks(self, value):
        with self.lock:
            self.burn_clocks = value
            self._log_locked("update_setting", 0, f"burn_clocks set to {value}")

    def _run(self, client, preset, result, strategy, max_steps):

        state = result or {}
        last_turn = -1
        try:
            for i in range(max_steps):
                if self._should_stop():
                    break
                data = state.get("data") or {}
                chara = data.get("chara_info") or {}
                turn = int(chara.get("turn") or 0)

                if turn != last_turn:
                    if hasattr(client, "wait_turn_delay"):
                        client.wait_turn_delay()
                    last_turn = turn
                
                self._mark(turn=turn)
                self._track_turn_scores(state)

                if turn == 77 and not getattr(self, "dev_mode", False):
                    print("Turn 77 reached terminating", flush=True)
                    self.stop()
                    break
                
                self.skill_buyer.last_attempt = []
                self.skill_buyer.last_result = {}
                self.item_manager.last_buy_attempt = []
                self.item_manager.last_buy_result = {}
                self.item_manager.last_use_attempt = []
                self.item_manager.last_use_result = {}
                self.skill_buyer.attempt_events = []
                self.item_manager.buy_attempt_events = []
                self.item_manager.use_attempt_events = []

                if data.get("unchecked_event_array"):

                    state = self._drain_events(client, strategy, state)
                    data = state.get("data") or {}
                    chara = data.get("chara_info") or {}
                    self._track_turn_scores(state)
                
                if self._blocked_playing_state(chara):

                    state = self._recover_blocked_state(client, strategy, state)
                    data = state.get("data") or {}
                    chara = data.get("chara_info") or {}
                    if self._blocked_playing_state(chara):

                        self._mark(last_action=f"blocked state {chara.get('playing_state')}")
                        break
                
                self._debug_turn(state, preset)
                decision = strategy.next_decision(state, preset)

                
                if self.report:
                    add_decision(self.report, state, decision)
                
                if decision.action == "command":

                    state = self._handle_items(client, state, preset, self._command_from_decision(state, decision))
                    data = state.get("data") or {}
                    if data.get("unchecked_event_array"):

                        state = self._drain_events(client, strategy, state)
                    data = state.get("data") or {}
                    chara = data.get("chara_info") or {}
                    self._mark(turn=chara.get("turn", 0))
                    decision = strategy.next_decision(state, preset)

                    if self.report:
                        add_decision(self.report, state, decision)
                
                self._log(decision.action, chara.get("turn", 0), decision.reason)
                if decision.action == "idle":
                    self._mark(last_action=decision.reason)
                    break
                if decision.action == "done":
                    self._mark(last_action=decision.reason, finished=True)
                    break
                
                if decision.action == "event":
                    state = self._event(client, strategy, decision.payload)
                elif decision.action == "command":
                    self._log("command_exec", decision.payload.get("current_turn", 0), f"{decision.payload.get('command_type')}:{decision.payload.get('command_id')}:{decision.payload.get('command_group_id')}")
                    self._record_action(decision, chara)
                    try:
                        state = client.exec_command(**decision.payload)
                    except Exception as exc:
                        print(f"Command Error at turn {chara.get('turn', 0)}: {exc}")
                        if not any(err in str(exc) for err in ("102", "1503")):
                            raise
                        state = self._recover_blocked_state(client, strategy, state)
                        data = state.get("data") or {}
                        chara = data.get("chara_info") or {}
                        if self._blocked_playing_state(chara):
                            self._mark(last_action=f"blocked state {chara.get('playing_state')}")
                            break
                        continue
                    data = state.get("data") or {}
                    if data.get("unchecked_event_array"):
                        state = self._drain_events(client, strategy, state)
                elif decision.action == "race":

                    self._record_action(decision, chara)
                    state = self._race(client, state, preset, decision.payload)
                elif decision.action == "race_progress":

                    self._record_action(decision, chara)
                    state = self._race_progress(client, decision.payload)
                elif decision.action == "finish":

                    self._record_action(decision, chara)

                    state = self._buy_skills(client, state, preset, True)

                    data = state.get("data") or {}
                    if data.get("race_start_info"):
                        self._log("race_out", decision.payload.get("current_turn", 78), "clearing active race")
                        try:
                            state = client.race_out(current_turn=decision.payload.get("current_turn", 78))
                        except Exception as e:
                            if any(err in str(e) for err in ("102", "201", "StateRecoveryError")):
                                self._log("race_out_reconciled", decision.payload.get("current_turn", 78), f"graceful exit: {e}")
                            else:
                                raise
                    state = self._drain_events(client, strategy, state, limit=50)

                    chara = (state.get("data") or {}).get("chara_info") or {}
                    if int(chara.get("skill_point") or 0) > 200:
                        print(f"SP still high ({chara.get('skill_point')}), retrying final purchase...")
                        state = self._buy_skills(client, state, preset, True)

                    try:
                        state = client.finish_career(current_turn=decision.payload.get("current_turn", 78), is_force_delete=False)
                        time.sleep(random.uniform(1.0, 3.0))
                        
                        if random.random() < 0.8:
                            try:
                                client.call("chara/nickname", {"nickname_id": 1, "trained_chara_id": state.get("data", {}).get("trained_chara", [{}])[0].get("trained_chara_id", 0)})
                                time.sleep(random.uniform(0.5, 1.5))
                            except Exception:
                                pass
                                
                        client.call("home/index", {})
                    except Exception as e:
                        if any(err in str(e) for err in ("102", "201", "StateRecoveryError")):
                            self._log("finish_reconciled", decision.payload.get("current_turn", 78), f"graceful exit: {e}")
                        else:
                            raise
                    self._mark(last_action="finish", finished=True)
                    break
                else:

                    self._mark(last_action=decision.action)
                    break
                
                if decision.action not in {"finish"}:
                    state = self._buy_skills(client, state, preset, False)
                
                self._advance(decision.action)
                target_mean = 0.5
                sigma = 0.25
                mu = math.log(target_mean) - (sigma**2) / 2.0
                roll = random.lognormvariate(mu, sigma)
                time.sleep(max(0.1, min(1.5, roll)))
        except Exception as exc:
            import traceback
            trace_str = traceback.format_exc()
            traceback.print_exc()
            print(f"RUNNER CRASH: {exc}")
            
            crash_log_path = runtime_output_root(self.base_dir) / "crash_trace.txt"
            try:
                crash_log_path.parent.mkdir(parents=True, exist_ok=True)
                with open(crash_log_path, "a", encoding="utf-8") as f:
                    f.write(f"--- CRASH AT {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
                    f.write(trace_str)
                    f.write("\n\n")
            except Exception:
                pass

            self._log("error", self.snapshot().get("turn", 0), str(exc))
            self._mark(last_error=str(exc))
            if self.report:
                set_error(self.report, exc)
        finally:
            if self._should_stop():
                self._log("stop", self.snapshot().get("turn", 0), "stop requested")
                if self.report:
                    finish_report(self.report, "stopped")
            else:
                if self.report:
                    finish_report(self.report, "finished" if self.status["finished"] else "error")
            self._mark(running=False)
            if self.report:
                try:
                    root_trace_dir = runtime_output_root(self.base_dir) / "bot_logs"
                    out = write_report(self.report, root_trace_dir)
                    print(f"career report written: {out}", flush=True)
                except Exception as e:
                    print(f"failed to write report: {e}", flush=True)

    def _should_stop(self):
        with self.lock:
            return self.stop_requested

    def _advance(self, action):
        with self.lock:
            self.status["steps"] += 1
            self.status["last_action"] = action

    def _mark(self, **values):
        with self.lock:
            self.status.update(values)

    def _log_locked(self, action, turn, detail):
        items = self.status.setdefault("log", [])
        items.append({
            "id": len(items) + 1,
            "action": action,
            "turn": int(turn or 0),
            "detail": str(detail or ""),
            "time": time.strftime("%H:%M:%S"),
        })
        if len(items) > 120:
            del items[:len(items) - 120]

    def _log(self, action, turn, detail):
        with self.lock:
            self._log_locked(action, turn, detail)

    def _record_action(self, decision, chara=None):
        payload = decision.payload or {}
        action = decision.action
        turn = int(payload.get("current_turn") or 0)
        stats = self._turn_stats(chara or {})
        detail = self._format_turn_stats(stats) or str(decision.reason or "")
        facility = ""
        if action == "command":
            command_type = int(payload.get("command_type") or 0)
            command_id = int(payload.get("command_id") or 0)
            command_group_id = int(payload.get("command_group_id") or 0)
            if command_type == 1:
                action = "train"
                facility = TRAINING_LABELS.get(command_id, str(command_id))
            elif command_type == 8:
                action = "medic"
            elif command_type == 7:
                action = "rest"
                facility = str(command_group_id or command_id)
            elif command_type == 3:
                action = "recreation"
                facility = str(command_group_id or command_id)
            else:
                action = f"command {command_type}"
                facility = str(command_id or command_group_id)
        elif action in {"race", "race_progress"}:
            action = "race"
            program_id = int(payload.get("program_id") or 0)
            if program_id and self.race_planner:
                facility = self.race_planner.label(program_id)
            else:
                facility = str(program_id or "")
        elif action == "finish":
            action = "finish"
        row = {
            "turn": turn,
            "action": action,
            "facility": facility,
            "detail": detail,
            "stats": stats,
            "time": time.strftime("%H:%M:%S"),
        }
        with self.lock:
            history = self.status.setdefault("action_history", [])
            if history and history[-1].get("turn") == row["turn"] and history[-1].get("action") == row["action"] and history[-1].get("facility") == row["facility"]:
                history[-1] = row
            else:
                history.append(row)

    def _turn_stats(self, chara):
        if not chara:
            return {}
        return {
            "hp": int(chara.get("vital") or 0),
            "max_hp": int(chara.get("max_vital") or 100),
            "motivation": int(chara.get("motivation") or 0),
            "speed": int(chara.get("speed") or 0),
            "stamina": int(chara.get("stamina") or 0),
            "power": int(chara.get("power") or 0),
            "guts": int(chara.get("guts") or 0),
            "wit": int(chara.get("wiz") or 0),
            "skill_point": int(chara.get("skill_point") or 0),
        }

    def _format_turn_stats(self, stats):
        if not stats:
            return ""
        return (
            f"HP {stats['hp']}/{stats['max_hp']} | "
            f"MOOD {stats['motivation']} | "
            f"SPD {stats['speed']} STA {stats['stamina']} PWR {stats['power']} "
            f"GUT {stats['guts']} WIT {stats['wit']} SP {stats['skill_point']}"
        )

    def _blocked_playing_state(self, chara):
        playing_state = int((chara or {}).get("playing_state") or 1)
        return playing_state not in {1, 2, 3, 4, 5}

    def _recover_blocked_state(self, client, strategy, state):
        data = state.get("data") or {}
        chara = data.get("chara_info") or {}
        if int(chara.get("playing_state") or 0) == 6:
            turn = chara.get("turn", 1)
            if hasattr(client, "minigame_end"):
                state = client.minigame_end(current_turn=turn)
            else:
                state = client.call("single_mode_free/minigame_end", {
                    "result": {
                        "result_state": 1,
                        "result_value": 0,
                        "result_detail_array": None,
                    },
                    "current_turn": turn,
                })
            data = state.get("data") or {}
            if data.get("unchecked_event_array"):
                state = self._drain_events(client, strategy, state)
            return state
        try:
            if hasattr(client, "hard_reset"):
                state = client.hard_reset()
            else:
                state = self._fresh_career_state(client, strategy)
        except Exception as e:
            print(f"Blocked State Recovery Failure: {e}")
            return state
        return state

    def _debug_turn(self, state, preset):
        data = state.get("data") or {}
        chara = data.get("chara_info") or {}
        free = data.get("free_data_set") or {}
        self.skill_buyer.preview(state, preset)
        self._debug("turn", state, {
            "owned_skills": self._debug_owned_skills(state),
            "inventory": self._debug_inventory(state),
            "server_skill_tips_raw": chara.get("skill_tips_array") or [],
            "server_owned_skill_raw": chara.get("skill_array") or [],
            "skill_rows_enriched": self._debug_skill_options(state, preset),
            "bot_skill_candidates": list(self.skill_buyer.last_candidates),
            "bot_skill_selected": list(self.skill_buyer.last_selected),
            "bot_skill_attempt": list(self.skill_buyer.last_attempt),
            "bot_skill_result": dict(self.skill_buyer.last_result),
            "server_shop_rows_raw": free.get("pick_up_item_info_array") or [],
            "shop_rows_enriched": self._debug_item_buy_options(state, preset),
            "bot_shop_candidates": list(self.item_manager.last_buy_options),
            "bot_shop_selected": list(self.item_manager.last_buy_selected),
            "bot_shop_attempt": list(self.item_manager.last_buy_attempt),
            "bot_shop_result": dict(self.item_manager.last_buy_result),
            "decision_item_use_rows": list(self.item_manager.last_use_options),
            "bot_item_use_selected": list(self.item_manager.last_use_selected),
            "bot_item_use_attempt": list(self.item_manager.last_use_attempt),
            "bot_item_use_result": dict(self.item_manager.last_use_result),
        })

    def _debug_skill_options(self, state, preset):
        data = state.get("data") or {}
        chara = data.get("chara_info") or {}
        points = int(chara.get("skill_point") or 0)
        owned = {int(item.get("skill_id") or 0) for item in chara.get("skill_array") or []}
        owned_groups = {self.skill_buyer.skill_to_group_id.get(skill_id, skill_id // 10) for skill_id in owned}
        priority = self.skill_buyer._priority_context(preset)
        blacklist = self.skill_buyer._blacklist(preset)
        selected = {item["skill_id"]: item for item in self.skill_buyer._candidates(chara, preset)}
        result = []
        for tip in chara.get("skill_tips_array") or []:
            resolved = self.skill_buyer.resolve_skill_tip(tip, owned, owned_groups, priority, blacklist, preset)
            skill_id = int((resolved or {}).get("resolved_skill_id") or 0)
            cost = int((resolved or {}).get("cost") or 0)
            selected_flag = skill_id in selected
            skip_reason = (resolved or {}).get("skip_reason")
            if not skip_reason and cost > points:
                skip_reason = "unaffordable"
            elif not skip_reason and not selected_flag:
                skip_reason = "rule_rejected"
            result.append({
                "skill_id": skill_id,
                "group_id": int((resolved or {}).get("group_id") or tip.get("group_id") or 0),
                "tip_rarity": int((resolved or {}).get("tip_rarity") or tip.get("rarity") or 0),
                "hint_level": int((resolved or {}).get("hint_level") or tip.get("level") or 0),
                "candidate_skill_ids": (resolved or {}).get("candidate_skill_ids") or [],
                "name": (resolved or {}).get("resolved_name") or "",
                "cost": cost,
                "affordable": cost <= points,
                "owned_group": (resolved or {}).get("skip_reason") == "owned_group",
                "known": bool((resolved or {}).get("master_exists")),
                "failed_scope": (resolved or {}).get("failed_scope"),
                "selected": selected_flag,
                "resolution_reason": (resolved or {}).get("resolution_reason") or "",
                "skip_reason": skip_reason,
            })
        return result

    def _debug_owned_skills(self, state):
        chara = (state.get("data") or {}).get("chara_info") or {}
        result = []
        for row in chara.get("skill_array") or []:
            skill_id = int(row.get("skill_id") or 0)
            result.append({
                "skill_id": skill_id,
                "group_id": self.skill_buyer.skill_to_group_id.get(skill_id, skill_id // 10),
                "name": self.skill_buyer.skill_names.get(skill_id, ""),
            })
        return result

    def _debug_inventory(self, state):
        free = (state.get("data") or {}).get("free_data_set") or {}
        result = []
        for name, count in sorted(self.item_manager._owned_map(free).items()):
            item_id = DISPLAY_TO_ID.get(name)
            if not item_id:
                continue
            result.append({
                "name": name,
                "item_id": item_id,
                "current_num": int(count),
                "failed_scope": "this_turn" if item_id in self.item_manager.failed_use_this_turn else None,
            })
        return result

    def _debug_item_buy_options(self, state, preset):
        data = state.get("data") or {}
        free = data.get("free_data_set") or {}
        current_turn = int((data.get("chara_info") or {}).get("turn") or 0)
        coin_val = free.get("coin_num")
        if coin_val is None:
            coin_val = free.get("gained_coin_num")
        budget = int(coin_val or 0)
        owned = self.item_manager._owned_map(free)
        result = []
        for row in free.get("pick_up_item_info_array") or []:
            shop_item_id = int(row.get("shop_item_id") or 0)
            item_id = int(row.get("item_id") or 0)
            name = ITEM_NAMES.get(item_id)
            if not name:
                continue
            limit_turn = int(row.get("limit_turn") or 0)
            cost = int(row.get("coin_num") or 0)
            original_cost = int(row.get("original_coin_num") or cost)
            bought = int(row.get("item_buy_num") or 0)
            limit = int(row.get("limit_buy_count") or 1)
            expired = limit_turn > 0 and current_turn > limit_turn
            rejected = shop_item_id in self.item_manager.failed_exchange_this_snapshot
            skip_buy = self.item_manager._skip_buy(name, owned, preset)
            skip_reason = None
            if expired:
                skip_reason = "expired"
            elif bought >= limit:
                skip_reason = "limit_reached"
            elif rejected:
                skip_reason = "rejected"
            elif skip_buy:
                skip_reason = "skip_buy"
            elif cost > budget:
                skip_reason = "unaffordable"
            result.append({
                "shop_item_id": shop_item_id,
                "item_id": item_id,
                "name": name,
                "cost": cost,
                "original_cost": original_cost,
                "mant_coin": budget,
                "affordable": cost <= budget,
                "current_num": bought,
                "limit": limit,
                "absolute_limit_turn": limit_turn,
                "server_turn_delta": (limit_turn - current_turn) if limit_turn > 0 else None,
                "ui_turns_left": None,
                "limit_reached": bought >= limit,
                "expired": expired,
                "rejected": rejected,
                "skip_buy": skip_buy,
                "selected": False,
                "skip_reason": skip_reason,
            })
        cfg = self.item_manager._mant_cfg(preset)
        tiers = cfg.get("item_tiers") or {}
        tier_count = int(cfg.get("tier_count") or 8)
        remaining_budget = budget
        for tier in range(1, tier_count + 1):
            tier_rows = [
                row for row in result
                if row.get("skip_reason") is None
                and not row.get("selected")
                and int(tiers.get(display_to_slug(row.get("name")), 999)) == tier
            ]
            tier_rows.sort(key=lambda row: (int(row.get("absolute_limit_turn") or 99), int(row.get("cost") or 9999)))
            for row in tier_rows:
                cost = int(row.get("cost") or 0)
                remaining = remaining_budget - cost
                if remaining < 0:
                    row["skip_reason"] = "unaffordable"
                    continue
                threshold = 0
                thresholds = cfg.get("tier_thresholds") or {}
                if tier > 1 and current_turn <= 64:
                    threshold = int(thresholds.get(str(tier), thresholds.get(tier, (tier - 1) * 50)) or 0)
                if threshold > 0 and remaining < threshold:
                    row["skip_reason"] = "rule_rejected"
                    continue
                row["selected"] = True
                remaining_budget = remaining
        return result

    def _api_result(self, result):
        result = dict(result or {})
        error = str(result.get("error") or "")
        code = None
        for token in error.replace(":", " ").replace(",", " ").split():
            if token.isdigit():
                value = int(token)
                if value in {201, 202, 205, 208, 394, 709}:
                    code = value
                    break
        if result.get("result") == "ok":
            code = 1
        return {
            "ok": result.get("result") == "ok",
            "result_code": code,
            "error": error or None,
        }

    def _sum_cost(self, rows):
        return sum(int((row or {}).get("cost") or 0) for row in rows or [])

    def _shop_attempt_cost(self, attempt, selected):
        costs = {int(row.get("shop_item_id") or 0): int(row.get("cost") or 0) for row in selected or []}
        return sum(costs.get(int(row.get("shop_item_id") or 0), 0) for row in attempt or [])

    def _fresh_career_state(self, client, strategy=None):
        errors = []
        for relogin in (False, True):
            try:
                if relogin:
                    if not hasattr(client, "login"):
                        break
                    client.login()
                if hasattr(client, "load_career"):
                    state = client.load_career()
                else:
                    state = client.call("single_mode_free/load", {})
                if strategy and (state.get("data") or {}).get("unchecked_event_array"):
                    state = self._drain_events(client, strategy, state)
                self.skill_buyer.reset_scoped_failures()
                self.item_manager.reset_scoped_failures()
                return state
            except Exception as exc:
                errors.append(str(exc))
        raise RuntimeError("career recovery failed: " + " | ".join(errors))

    def _event(self, client, strategy, payload):
        data = dict(payload)
        event = data.pop("_event", None)
        current_turn = data.pop("_current_turn", 0)
        if event:
            choice = strategy.choose_from_event(event, current_turn)
            self._log("event_choice", current_turn, f"{data.get('event_id')} -> {choice}")
            return client.check_event(
                event_id=data["event_id"],
                chara_id=event.get("chara_id", 0),
                choice_number=choice,
                current_turn=current_turn
            )
        if "event_id" not in data:
            self._log("recover", current_turn, "event requested without event_id, forcing state refresh")
            return self._fresh_career_state(client, strategy)
        return client.check_event(**data)

    def _drain_events(self, client, strategy, state, limit=20):
        current = state
        for _ in range(limit):
            data = current.get("data") or {}
            events = data.get("unchecked_event_array") or []
            if not events:
                return current
            event = events[0] or {}
            choice = strategy._choice(event)
            chara_turn = (data.get("chara_info") or {}).get("turn")
            turn = chara_turn if chara_turn is not None else self.status.get("turn")
            turn = turn if turn is not None else 1
            payload = {"event_id": event.get("event_id"), "chara_id": event.get("chara_id", 0), "choice_number": choice, "current_turn": turn}
            if choice is None:
                payload = {"event_id": event.get("event_id"), "_event": event, "_current_turn": turn}
            current = self._event(client, strategy, payload)
        return current

    def _get_clocks_left(self, root, max_clocks=5):
        data = root.get("data") or {}

        home_info = data.get("home_info")
        if isinstance(home_info, dict) and "available_continue_num" in home_info:
            std = int(home_info.get("available_continue_num", 0))
            free = int(home_info.get("available_free_continue_num", 0))
            continue_type = 1 if free > 0 else 2
            return {
                "source": "data.home_info.available_continue_num",
                "clocks_left": std + free,
                "continue_type": continue_type,
            }

        race_start_info = data.get("race_start_info")
        if isinstance(race_start_info, dict) and "continue_num" in race_start_info:
            used = int(race_start_info["continue_num"])
            return {
                "source": "data.race_start_info.continue_num",
                "clocks_used": used,
                "clocks_left": max_clocks - used,
                "continue_type": 2,
            }

        return {"source": "unknown", "clocks_left": 0, "continue_type": 2}

    def _parse_race_rank(self, res):
        import base64
        import gzip
        import struct

        data = res.get("data", {})
        headers = res.get("data_headers", {})
        viewer_id = int(headers.get("viewer_id") or 0)

        race_start_info = data.get("race_start_info", {})
        horses = race_start_info.get("race_horse_data", [])

        player = next((horse for horse in horses if int(horse.get("viewer_id") or 0) == viewer_id), None)
        if not player:
            return 99

        frame_order = player.get("frame_order")
        if not frame_order:
            return 99

        result_index = frame_order - 1

        scenario_b64 = data.get("race_scenario")
        if not scenario_b64:
            return 99

        try:
            blob = gzip.decompress(base64.b64decode(scenario_b64))
        except Exception:
            return 99

        offset = 0

        if len(blob) < offset + 4: return 99
        header_len = struct.unpack_from("<i", blob, offset)[0]
        offset += 4 + header_len

        if len(blob) < offset + 16: return 99
        distance_diff_max, horse_num, horse_frame_size, horse_result_size = struct.unpack_from("<fiii", blob, offset)
        offset += 16

        if len(blob) < offset + 4: return 99
        pad_len = struct.unpack_from("<i", blob, offset)[0]
        offset += 4 + pad_len

        if len(blob) < offset + 8: return 99
        frame_count, frame_size = struct.unpack_from("<ii", blob, offset)
        offset += 8 + frame_count * frame_size

        if len(blob) < offset + 4: return 99
        pad_len = struct.unpack_from("<i", blob, offset)[0]
        offset += 4 + pad_len

        if not (0 <= result_index < horse_num):
            return 99

        if len(blob) < offset + (result_index + 1) * horse_result_size:
            return 99

        finish_order = struct.unpack_from("<i", blob, offset + result_index * horse_result_size)[0]

        return finish_order + 1

    def _race(self, client, state, preset, payload):
        if int((preset or {}).get("scenario_id") or (preset or {}).get("scenario") or 4) == 4:
            self.item_manager.recover_after_use_error = False
            state, used = self.item_manager.handle_pre_race(client, state, preset, payload, self.status, self.race_planner)
            for event in self.item_manager.use_attempt_events:
                self._debug("items_use_attempt", state, {
                    "selected": event.get("selected") or [],
                    "attempt": event.get("attempt") or [],
                    "payload": event.get("payload") or [],
                    "result": self._api_result(event.get("result") or {}),
                })
            if self.item_manager.recover_after_use_error or self.item_manager.use_attempt_events:
                state = self._fresh_career_state(client, payload.get("_strategy"))
                self._debug_turn(state, preset)
                if self.item_manager.recover_after_use_error:
                    return state
            if used > 0:
                with self.lock:
                    self.status["items_used"] += used
                    self._log_locked("items_use", payload.get("current_turn") or 1, f"pre-race {used}")

        program_id = payload.get("program_id")
        current_turn = payload.get("current_turn") or 1
        strategy = payload.get("_strategy")
        try:
            entry = client.race_entry(program_id=program_id, current_turn=current_turn)
        except Exception as exc:
            print(f"Race Entry Error at turn {current_turn}: {exc}")
            if not any(err in str(exc) for err in ("205", "208")):
                raise
            self.race_planner.reject(current_turn, program_id)
            self._log("race_reject", current_turn, program_id)
            return self._fresh_career_state(client, strategy)
        self._log("race_entry", current_turn, program_id)
        if strategy:
            entry_data = entry.get("data") or {}
            if entry_data.get("unchecked_event_array"):
                entry = self._drain_events(client, strategy, entry)
        race_start_info = (entry.get("data") or {}).get("race_start_info") or {}
        is_short = 1

        res = client.race_start(is_short=is_short, current_turn=current_turn)
        self._log("race_start", current_turn, f"short {is_short}")

        rank = self._parse_race_rank(res)
        self._log("race_rank", current_turn, f"rank {rank}")

        home_info = (state.get("data") or {}).get("home_info") or {}
        std_clocks = int(home_info.get("available_continue_num", 0))
        free_clocks = int(home_info.get("available_free_continue_num", 0))

        while self.burn_clocks and rank > 1 and (std_clocks > 0 or free_clocks > 0):
            clocks_left = std_clocks + free_clocks
            continue_type = 1 if free_clocks > 0 else 2
            
            self._log("race_clock", current_turn, f"rank {rank}, using clock ({clocks_left} left, type {continue_type})...")
            try:
                cont_res = client.race_continue(current_turn=current_turn, continue_type=continue_type)
                
                cont_data = cont_res.get("data") or {}
                new_home_info = cont_data.get("home_info")
                if isinstance(new_home_info, dict):
                    std_clocks = int(new_home_info.get("available_continue_num", 0))
                    free_clocks = int(new_home_info.get("available_free_continue_num", 0))
                else:
                    if free_clocks > 0:
                        free_clocks -= 1
                    else:
                        std_clocks -= 1

                if strategy:
                    if cont_data.get("unchecked_event_array"):
                        self._drain_events(client, strategy, cont_res)
                
                roll = random.gauss(0.166 + client.api_jitter, 0.05)
                time.sleep(max(0.1, min(0.45, roll)))
                res = client.race_start(is_short=is_short, current_turn=current_turn)
                rank = self._parse_race_rank(res)
                self._log("race_rank_retry", current_turn, f"rank {rank} after clock")
                with self.lock:
                    self.status["clocks_used"] = int(self.status.get("clocks_used") or 0) + 1
            except Exception as e:
                self._log("race_clock_failed", current_turn, str(e))
                break

        if strategy:
            res_data = res.get("data") or {}
            if res_data.get("unchecked_event_array"):
                res = self._drain_events(client, strategy, res)

        out = res
        try:
            client.race_end(current_turn=current_turn)
            self._log("race_end", current_turn, "")
        except Exception as e:
            if any(err in str(e) for err in ("102", "1503")):
                self._log("race_end_reconciled", current_turn, "server already done (102)")
            else:
                raise

        try:
            out_res = client.race_out(current_turn=current_turn)
            out = out_res
            if strategy:
                out_data = out.get("data") or {}
                if out_data.get("unchecked_event_array"):
                    out = self._drain_events(client, strategy, out)
        except Exception as e:
            if any(err in str(e) for err in ("102", "1503")):
                self._log("race_out_reconciled", current_turn, "server already done (102)")
            else:
                raise

        return out

    def _race_progress(self, client, payload):
        current_turn = payload.get("current_turn") or 1
        phase = payload.get("phase")
        chara = (payload.get("chara_info") or {})
        playing_state = chara.get("playing_state") or 0
        if playing_state not in {2, 3, 4, 5}:
            self._log("race_skip", current_turn, f"not in race (state={playing_state})")
            return payload
        
        if phase == "end":
            if playing_state in {1}:
                self._log("race_end_skip", current_turn, "resume already home")
            else:
                try:
                    client.race_end(current_turn=current_turn)
                    self._log("race_end", current_turn, "resume")
                except Exception as e:
                    if any(err in str(e) for err in ("102", "1503")):
                        self._log("race_end_reconciled", current_turn, "resume already done (102)")
                    else:
                        raise
            try:
                return client.race_out(current_turn=current_turn)
            except Exception as e:
                if any(err in str(e) for err in ("102", "1503", "201", "StateRecoveryError")):
                    self._log("race_out_reconciled", current_turn, f"graceful exit: {e}")
                    return payload
                raise
        if phase == "out":
            self._log("race_out", current_turn, "resume")
            try:
                return client.race_out(current_turn=current_turn)
            except Exception as e:
                if any(err in str(e) for err in ("102", "1503", "201", "StateRecoveryError")):
                    self._log("race_out_reconciled", current_turn, f"graceful exit: {e}")
                    return payload
                raise
        client.race_start(is_short=1, current_turn=current_turn)
        self._log("race_start", current_turn, "resume")
        if playing_state in {1}:
            self._log("race_end_skip", current_turn, "resume already home")
        else:
            try:
                client.race_end(current_turn=current_turn)
                self._log("race_end", current_turn, "resume")
            except Exception as e:
                if any(err in str(e) for err in ("102", "1503")):
                    self._log("race_end_reconciled", current_turn, "resume already done (102)")
                else:
                    raise
        try:
            return client.race_out(current_turn=current_turn)
        except Exception as e:
            if any(err in str(e) for err in ("102", "1503", "201", "StateRecoveryError")):
                self._log("race_out_reconciled", current_turn, f"graceful exit: {e}")
                return payload
            raise

    def _buy_skills(self, client, state, preset, force):
        state, bought = self.skill_buyer.buy(client, state, preset, force)
        for event in self.skill_buyer.attempt_events:
            self._debug("skills_attempt", state, {
                "selected": event.get("selected") or [],
                "attempt": event.get("attempt") or [],
                "selected_total_cost": self._sum_cost(event.get("selected") or []),
                "attempt_total_cost": self._sum_cost(event.get("attempt") or []),
                "payload": event.get("payload") or [],
                "result": self._api_result(event.get("result") or {}),
            })
        if self.skill_buyer.attempt_events or self.skill_buyer.recover_after_error:
            try:
                state = self._fresh_career_state(client)
                self._debug_turn(state, preset)
            except Exception as e:
                print(f"Skill phase reload failure: {e}")
                pass
        if bought:
            with self.lock:
                self.status["skills_bought"] += bought
                self.status["last_action"] = f"skills {bought}"
                self._log_locked("skills", (state.get("data") or {}).get("chara_info", {}).get("turn", 0), bought)
        return state

    def _handle_items(self, client, state, preset, best_command):
        if int((preset or {}).get("scenario_id") or (preset or {}).get("scenario") or 4) != 4:
            return state
        self.item_manager.recover_after_exchange_error = False
        self.item_manager.recover_after_use_error = False
        state, bought, used = self.item_manager.handle(client, state, preset, best_command, self.status, self.race_planner)
        for event in self.item_manager.buy_attempt_events:
            self._debug("items_buy_attempt", state, {
                "selected": event.get("selected") or [],
                "attempt": event.get("attempt") or [],
                "selected_total_cost": self._sum_cost(event.get("selected") or []),
                "attempt_total_cost": self._shop_attempt_cost(event.get("attempt") or [], event.get("selected") or []),
                "payload": event.get("payload") or [],
                "result": self._api_result(event.get("result") or {}),
            })
        for event in self.item_manager.use_attempt_events:
            self._debug("items_use_attempt", state, {
                "selected": event.get("selected") or [],
                "attempt": event.get("attempt") or [],
                "payload": event.get("payload") or [],
                "result": self._api_result(event.get("result") or {}),
            })
        if self.item_manager.recover_after_exchange_error or self.item_manager.recover_after_use_error or self.item_manager.buy_attempt_events or self.item_manager.use_attempt_events:
            try:
                state = self._fresh_career_state(client)
                self._debug_turn(state, preset)
            except Exception as e:
                print(f"Item phase reload failure: {e}")
                pass
        if bought or used:
            turn = (state.get("data") or {}).get("chara_info", {}).get("turn", 0)
            with self.lock:
                self.status["items_bought"] += bought
                self.status["items_used"] += used
                if bought:
                    self._log_locked("items_buy", turn, bought)
                if used:
                    self._log_locked("items_use", turn, used)
        return state

    def _merge_state(self, old_state, new_state):
        if not old_state:
            return new_state
        merged = dict(old_state)
        merged["data"] = dict(old_state.get("data") or {})
        for k, v in (new_state.get("data") or {}).items():
            if isinstance(v, dict) and k in merged["data"] and isinstance(merged["data"][k], dict):
                merged_sub = dict(merged["data"][k])
                for sub_k, sub_v in v.items():
                    if sub_v is not None:
                        merged_sub[sub_k] = sub_v
                merged["data"][k] = merged_sub
            else:
                merged["data"][k] = v
        return merged

    def _command_from_decision(self, state, decision):
        payload = decision.payload or {}
        command_type = int(payload.get("command_type") or 0)
        command_id = int(payload.get("command_id") or 0)
        command_group_id = int(payload.get("command_group_id") or 0)
        for cmd in ((state.get("data") or {}).get("home_info") or {}).get("command_info_array") or []:
            if int(cmd.get("command_type") or 0) != command_type:
                continue
            if command_type == 3 and int(cmd.get("command_id") or 0) == command_group_id:
                return cmd
            if int(cmd.get("command_id") or 0) == command_id:
                return cmd
        return payload

    def _track_turn_scores(self, state):
        data = state.get("data") or {}
        chara = data.get("chara_info") or {}
        turn = int(chara.get("turn") or 0)
        home = data.get("home_info") or {}
        commands = home.get("command_info_array") or []
        max_score = 0
        has_training = False
        for cmd in commands:
            if int(cmd.get("command_type") or 0) == 1:
                has_training = True
                score = self.item_manager._command_stat_gain(cmd)
                if score > max_score:
                    max_score = score
        if has_training:
            with self.lock:
                dh = self.status.setdefault("date_history", [])
                sh = self.status.setdefault("score_history", [])
                if not dh or dh[-1] != turn:
                    dh.append(turn)
                    sh.append(max_score)
                    if len(dh) > 48:
                        dh.pop(0)
                        sh.pop(0)
