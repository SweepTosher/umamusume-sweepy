from __future__ import annotations

import json
import math
import os
import random
import secrets
import time
from pathlib import Path

HARD_CALL_FLOOR_SECONDS = 0.14
DISABLED_SCHEDULER_YIELD_SECONDS = 0.001

_BASE_DELAYS: dict[str, tuple[float, float, float]] = {
    "load_index": (1.16, 14.69, 5.26),
    "load_career": (0.62, 7.64, 2.56),
    "pre_single_mode": (1.80, 25.95, 2.03),
    "start_career": (1.58, 6.23, 1.98),
    "start_session": (0.62, 4.55, 1.06),
    "pre_signup": (0.62, 4.55, 1.06),
    "signup": (0.62, 4.55, 1.06),
    "check_event": (1.11, 3.90, 1.88),
    "continue": (0.96, 4.82, 3.05),
    "exec_command": (2.86, 17.68, 4.82),
    "finish_career": (3.05, 15.49, 3.54),
    "gain_skills": (7.02, 99.37, 54.62),
    "read_info": (1.16, 14.69, 5.26),
    "recovery_trainer_point": (0.62, 4.55, 1.06),
    "multi_item_exchange": (4.20, 13.79, 8.29),
    "multi_item_use": (2.99, 9.87, 5.67),
    "minigame_end": (1.11, 3.90, 1.88),
    "race_end": (1.85, 3.90, 2.01),
    "race_entry": (0.73, 4.94, 0.78),
    "change_running_style": (0.73, 4.94, 0.78),
    "reserve_race": (2.78, 9.26, 4.90),
    "race_out": (2.20, 9.91, 3.79),
    "race_start": (1.93, 10.36, 3.46),
}

_PATH_TO_PACING_KEY: dict[str, str] = {
    "load/index": "load_index",
    "read_info/index": "read_info",
    "pre_single_mode/index": "pre_single_mode",
    "tool/start_session": "start_session",
    "tool/pre_signup": "pre_signup",
    "tool/signup": "signup",
    "user/recovery_trainer_point": "recovery_trainer_point",
}

_SCENARIO_ALIASES: dict[str, str] = {
    "start": "start_career",
    "load": "load_career",
    "finish": "finish_career",
    "race_continue": "continue",
}


def _load_or_create_seed(seed_path: Path) -> int:
    resolved = Path(os.path.abspath(os.path.expanduser(os.fspath(seed_path))))
    if not resolved.exists():
        resolved.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        generated = secrets.randbelow(9_000_000) + 1_000_000
        raw = f"{generated}\n".encode("ascii")
        temp = resolved.parent / f".{resolved.name}.{os.getpid()}.{secrets.token_hex(6)}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        fd: int | None = None
        try:
            fd = os.open(temp, flags, 0o600)
            os.write(fd, raw)
            os.fsync(fd)
            os.close(fd)
            fd = None
            os.replace(temp, resolved)
            if os.name == "posix":
                os.chmod(resolved, 0o600)
        except BaseException:
            if fd is not None:
                os.close(fd)
            if temp.exists():
                temp.unlink(missing_ok=True)
            raise

    text = resolved.read_text(encoding="utf-8").strip()
    if not text or not text.isdigit():
        raise ValueError(f"Invalid .timing_dna seed in {resolved}")
    seed = int(text)
    if not (1_000_000 <= seed <= 9_999_999):
        raise ValueError(f"Timing DNA seed {seed} must be a 7-digit integer")
    return seed


class TimingDNA:
    def __init__(
        self,
        seed_path: Path | str,
        *,
        disabled: bool = False,
        turn_min: float = 2.5,
        turn_max: float = 5.0,
    ) -> None:
        self.seed_path = Path(seed_path)
        self.seed = _load_or_create_seed(self.seed_path)
        self._rng = random.Random(self.seed)

        self._USER_SIGMA = self._rng.uniform(0.45, 0.75)
        self._USER_SPEED_SHIFT = self._rng.uniform(0.92, 1.08)
        self._USER_DISTRACTION_CHANCE = self._rng.uniform(0.015, 0.065)
        self._USER_DISTRACTION_MIN = self._rng.uniform(1.5, 3.5)
        self._USER_DISTRACTION_MAX = self._rng.uniform(7.0, 14.0)

        self._ENDPOINT_SHIFTS: dict[str, float] = {}
        for ep in _BASE_DELAYS:
            self._ENDPOINT_SHIFTS[ep] = self._rng.uniform(0.85, 1.15)

        self.disabled = bool(disabled)
        self.turn_min = float(turn_min)
        self.turn_max = float(turn_max)

    @staticmethod
    def pacing_name(endpoint: str) -> str:
        clean = str(endpoint or "").strip().strip("/")
        if clean in _BASE_DELAYS:
            return clean
        if clean in _PATH_TO_PACING_KEY:
            return _PATH_TO_PACING_KEY[clean]
        prefix, sep, op = clean.rpartition("/")
        if sep and prefix in {"single_mode", "single_mode_team", "single_mode_live", "single_mode_free"}:
            if op in _SCENARIO_ALIASES:
                return _SCENARIO_ALIASES[op]
            return op
        return clean.rsplit("/", 1)[-1]

    def sample_endpoint_delay(self, endpoint: str) -> float:
        if self.disabled:
            return 0.0
        key = self.pacing_name(endpoint)
        if key not in _BASE_DELAYS:
            target_delay = 0.3 * self._USER_SPEED_SHIFT
            mu = math.log(target_delay) - (self._USER_SIGMA ** 2) / 2.0
            dt = self._rng.lognormvariate(mu, self._USER_SIGMA)
            dt = max(0.08, min(1.2, dt))
        else:
            real_min, real_max, real_avg = _BASE_DELAYS[key]
            ep_shift = self._ENDPOINT_SHIFTS[key]
            target_delay = real_avg * self._USER_SPEED_SHIFT * ep_shift
            shifted_min = real_min * self._USER_SPEED_SHIFT * ep_shift
            shifted_max = real_max * self._USER_SPEED_SHIFT * ep_shift
            mu = math.log(target_delay) - (self._USER_SIGMA ** 2) / 2.0
            dt = self._rng.lognormvariate(mu, self._USER_SIGMA)
            dt = max(shifted_min, min(shifted_max, dt))

        if self._rng.random() < self._USER_DISTRACTION_CHANCE:
            dt += self._rng.uniform(self._USER_DISTRACTION_MIN, self._USER_DISTRACTION_MAX)
        return dt



    def sample_turn_delay(self) -> float:
        if self.disabled:
            return 0.0
        t_min = min(self.turn_min, self.turn_max)
        t_max = max(self.turn_min, self.turn_max)
        span = t_max - t_min
        target_mean = (((t_min + t_max) / 2.0) + (self._rng.uniform(-0.08, 0.08) * span)) * self._USER_SPEED_SHIFT
        sigma = 0.75 * self._USER_SIGMA
        mu = math.log(max(0.1, target_mean)) - (sigma ** 2) / 2.0
        dt = self._rng.lognormvariate(mu, sigma)
        return min(t_max * 5.0, max(t_min * 0.5, dt))

    def sleep_turn(self) -> float:
        dt = self.sample_turn_delay()
        if dt > 0:
            time.sleep(dt)
        return dt

    def enforce_floor(
        self,
        last_call_ts: float | None,
        *,
        now: float | None = None,
    ) -> float:
        if last_call_ts is None or last_call_ts <= 0:
            return 0.0
        current = time.monotonic() if now is None else float(now)
        elapsed = current - float(last_call_ts)
        remaining = HARD_CALL_FLOOR_SECONDS - elapsed
        if remaining > 0:
            time.sleep(remaining)
            return remaining
        return 0.0

    def sleep_range(
        self,
        min_val: float,
        max_val: float,
        mean: float | None = None,
        stddev: float | None = None,
    ) -> float:
        if self.disabled:
            time.sleep(DISABLED_SCHEDULER_YIELD_SECONDS)
            return 0.0
        if mean is not None and stddev is not None:
            dt = max(min_val, min(max_val, self._rng.gauss(mean, stddev)))
        else:
            dt = self._rng.uniform(min_val, max_val)
        if dt > 0:
            time.sleep(dt)
        return dt

    def uniform(self, min_val: float, max_val: float) -> float:
        return self._rng.uniform(min_val, max_val)

    def gauss(self, mean: float, stddev: float) -> float:
        return self._rng.gauss(mean, stddev)

    def randint(self, min_val: int, max_val: int) -> int:
        return self._rng.randint(min_val, max_val)

    def make_race_out_button_info(
        self,
        viewer_id: int,
        scenario_id: int,
        *,
        screen_h: int = 864,
        server_now: float | None = None,
    ) -> str:
        return make_race_out_button_info(
            viewer_id,
            scenario_id,
            dna=self,
            screen_h=screen_h,
            server_now=server_now,
        )


def make_race_out_button_info(
    viewer_id: int,
    scenario_id: int,
    dna: TimingDNA | None = None,
    *,
    screen_h: int = 864,
    server_now: float | None = None,
) -> str:
    if isinstance(viewer_id, bool) or int(viewer_id) <= 0:
        raise ValueError("viewer_id must be a positive integer")
    if isinstance(scenario_id, bool) or int(scenario_id) <= 0:
        raise ValueError("scenario_id must be a positive integer")

    rng_gauss = dna.gauss if dna is not None else random.gauss
    rng_uniform = dna.uniform if dna is not None else random.uniform

    window_w = max(1, int(int(screen_h) * 9 / 16))
    scale_factor = 1080.0 / float(window_w)

    ref_x = max(844, min(1150, int(rng_gauss(991.0, 62.0))))
    ref_y = max(55, min(255, int(rng_gauss(144.0, 33.0))))

    physical_x = int(ref_x / scale_factor)
    physical_y = int(ref_y / scale_factor)

    click_x = int(physical_x * scale_factor * 10000)
    click_y = int(physical_y * scale_factor * 10000)

    base_now = time.time() if server_now is None else float(server_now)
    click_ts = int(base_now - rng_uniform(3.0, 4.5))

    payload = {
        "ViewerId": int(viewer_id),
        "DeviceId": 4,
        "ScenarioId": int(scenario_id),
        "ClickPosX": click_x,
        "ClickPosY": click_y,
        "ClickServerTime": click_ts,
    }
    return json.dumps(payload, separators=(",", ":"))
