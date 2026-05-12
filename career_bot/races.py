import json
from pathlib import Path


class RacePlanner:
    def __init__(self, base_dir):
        self.base_dir = Path(base_dir)
        self.meta = {}
        self.program = {}
        self.instance = {}
        self.rejected = set()
        # (turn, program_id) — заезд уже отыгран и race_out выполнен; не предлагать снова (эпилог 78).
        self._completed_race_on_turn = set()
        self._load()

    def clear_completed_races(self):
        self._completed_race_on_turn.clear()

    def mark_race_completed(self, turn, program_id):
        tid = int(turn or 0)
        pid = int(program_id or 0)
        if tid and pid:
            self._completed_race_on_turn.add((tid, pid))
            # Финальная неделя: один заезд; блокирует повторный forced/choose и «ghost» race_start_info.
            if tid >= 78:
                self._completed_race_on_turn.add((tid, 0))

    def mark_epilogue_week_cleared(self, turn):
        """Если финал недели прошёл только через resume race_out (без _race), всё равно ставим сентинел 78+."""
        t = int(turn or 0)
        if t >= 78:
            self._completed_race_on_turn.add((t, 0))

    def should_skip_stale_race_start(self, turn, program_id):
        t = int(turn or 0)
        pid = int(program_id or 0)
        if not pid:
            return False
        if (t, pid) in self._completed_race_on_turn:
            return True
        if t >= 78 and (t, 0) in self._completed_race_on_turn:
            return True
        return False

    def _load(self):
        path = self.base_dir / "data" / "race_map.json"
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        self.meta = {int(k): v for k, v in (data.get("meta") or {}).items()}
        self.program = {int(k): v for k, v in (data.get("program") or {}).items()}
        self.instance = {int(k): [int(item) for item in v] for k, v in (data.get("instance") or {}).items()}

    def wanted_programs(self, preset, turn=None):
        result = set()
        current_turn = int(turn or 0)
        for value in preset.get("extra_race_list") or []:
            try:
                race_id = int(value)
            except (TypeError, ValueError):
                continue
            if race_id in self.meta:
                info = self.meta[race_id]
                occurrence_turn = int(info.get("turn") or 0)
                if current_turn and occurrence_turn and occurrence_turn != current_turn:
                    continue
                pid = info.get("program_id")
                if pid:
                    result.add(pid)
                continue
            if race_id in self.program:
                result.add(race_id)
                continue
            for program_id in self.instance.get(race_id, []):
                result.add(program_id)
        return result

    def available_programs(self, state):
        data = state.get("data") or {}
        rca = data.get("race_condition_array") or []
        available = set()
        for item in rca:
            pid = int(item.get("program_id") or 0)
            if pid:
                available.add(pid)
        return available

    def forced_program(self, state):
        data = state.get("data") or {}
        turn = int((data.get("chara_info") or {}).get("turn") or 0)
        home = data.get("home_info") or {}
        commands = home.get("command_info_array") or []
        race_enabled = any(cmd.get("command_type") == 4 and cmd.get("command_id") == 401 and cmd.get("is_enable", 0) for cmd in commands)
        other_enabled = any(cmd.get("command_type") != 4 and cmd.get("is_enable", 0) for cmd in commands)
        if not race_enabled or other_enabled:
            return 0
        if turn >= 78 and (turn, 0) in self._completed_race_on_turn:
            return 0
        for item in data.get("race_condition_array") or []:
            pid = int(item.get("program_id") or 0)
            if pid and (turn, pid) not in self._completed_race_on_turn:
                return pid
        race = data.get("race_start_info") or {}
        fb = int(race.get("program_id") or 0)
        if fb and (turn, fb) not in self._completed_race_on_turn:
            return fb
        return 0

    def choose(self, state, preset):
        data = state.get("data") or {}
        turn = int((data.get("chara_info") or {}).get("turn") or 0)
        if turn >= 78 and (turn, 0) in self._completed_race_on_turn:
            return 0

        home = data.get("home_info") or {}
        commands = home.get("command_info_array") or []
        race_enabled = any(cmd.get("command_type") == 4 and cmd.get("command_id") == 401 and cmd.get("is_enable", 0) for cmd in commands)
        if not race_enabled:
            return 0

        available = self.available_programs(state)
        if not available:
            return 0
    
        wanted = self.wanted_programs(preset, turn)
        for program_id in sorted(wanted):
            if (
                program_id in available
                and (turn, program_id) not in self.rejected
                and (turn, program_id) not in self._completed_race_on_turn
            ):
                return program_id
        return 0

    def reject(self, turn, program_id):
        self.rejected.add((int(turn or 0), int(program_id or 0)))

    def label(self, program_id):
        info = self.program.get(int(program_id or 0)) or {}
        name = info.get("name") or ""
        race_instance_id = info.get("race_instance_id") or ""
        return f"{program_id} {race_instance_id} {name}".strip()
