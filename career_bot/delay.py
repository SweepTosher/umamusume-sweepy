import math
import random
import time
import hashlib
import os
import threading

_BASE_DELAYS = {
    'load_index': (1.16, 14.69, 5.26),
    'load_career': (0.62, 7.64, 2.56),
    'pre_single_mode': (1.61, 11.13, 4.06),
    'start_career': (1.39, 1.78, 1.58),
    'check_event': (0.77, 3.49, 1.86),
    'continue': (0.85, 4.77, 2.74),
    'exec_command': (2.06, 16.56, 4.91),
    'finish_career': (2.73, 15.78, 6.22),
    'gain_skills': (5.81, 91.83, 48.48),
    'multi_item_exchange': (1.67, 12.40, 7.22),
    'multi_item_use': (2.05, 8.89, 5.13),
    'race_end': (1.60, 3.52, 1.94),
    'race_entry': (0.62, 4.55, 1.06),
    'race_out': (1.48, 8.95, 3.63),
    'race_start': (1.51, 9.38, 3.28),
}

_dna_path = os.path.join(os.path.dirname(__file__), '.timing_dna')
if not os.path.exists(_dna_path):
    with open(_dna_path, 'w') as f:
        f.write(str(random.randint(1000000, 9999999)))

with open(_dna_path, 'r') as f:
    _dna_seed = int(f.read().strip())

_dna_rng = random.Random(_dna_seed)
_USER_SIGMA = _dna_rng.uniform(0.45, 0.75)
_USER_SPEED_SHIFT = _dna_rng.uniform(0.92, 1.08)

_USER_DISTRACTION_CHANCE = _dna_rng.uniform(0.015, 0.065)
_USER_DISTRACTION_MIN = _dna_rng.uniform(1.5, 3.5)
_USER_DISTRACTION_MAX = _dna_rng.uniform(7.0, 14.0)

TURN_DELAY_MIN = 2.5
TURN_DELAY_MAX = 5.0
TURN_DELAY_RESTORE_MIN = 2.5
TURN_DELAY_RESTORE_MAX = 5.0
GLOBAL_DELAYS_DISABLED = False

_ENDPOINT_SHIFTS = {}
for ep in _BASE_DELAYS:
    _ENDPOINT_SHIFTS[ep] = _dna_rng.uniform(0.85, 1.15)


def simulate_delay(endpoint, client=None):
    if GLOBAL_DELAYS_DISABLED:
        print(f"Endpoint: {endpoint} | Delay: 0.000s", flush=True)
        return 0.0

    if endpoint not in _BASE_DELAYS:
        target_delay = 0.3 * _USER_SPEED_SHIFT
        mu = math.log(target_delay) - (_USER_SIGMA**2) / 2.0
        dt = random.lognormvariate(mu, _USER_SIGMA)
        dt = max(0.08, min(1.2, dt))
    else:
        real_min, real_max, real_avg = _BASE_DELAYS[endpoint]
        ep_shift = _ENDPOINT_SHIFTS[endpoint]
        target_delay = real_avg * _USER_SPEED_SHIFT * ep_shift
        shifted_min = real_min * _USER_SPEED_SHIFT * ep_shift
        shifted_max = real_max * _USER_SPEED_SHIFT * ep_shift
        mu = math.log(target_delay) - (_USER_SIGMA**2) / 2.0
        dt = random.lognormvariate(mu, _USER_SIGMA)
        dt = max(shifted_min, min(shifted_max, dt))

    if random.random() < _USER_DISTRACTION_CHANCE:
        dt += random.uniform(_USER_DISTRACTION_MIN, _USER_DISTRACTION_MAX)

    print(f"Endpoint: {endpoint} | Delay: {dt:.3f}s", flush=True)

    if client and hasattr(client, '_last_raw_call_ts'):
        elapsed = time.time() - client._last_raw_call_ts
        actual_sleep = dt - elapsed
        if actual_sleep > 0:
            time.sleep(actual_sleep)
    else:
        time.sleep(dt)
    return dt


def simulate_turn_delay():
    if GLOBAL_DELAYS_DISABLED:
        print(f"Endpoint: turn_delay | Delay: 0.000s", flush=True)
        return 0.0
    range_span = TURN_DELAY_MAX - TURN_DELAY_MIN
    target_mean = (((TURN_DELAY_MIN + TURN_DELAY_MAX) / 2.0) + (random.uniform(-0.08, 0.08) * range_span)) * _USER_SPEED_SHIFT
    sigma = 0.75 * _USER_SIGMA
    mu = math.log(max(0.1, target_mean)) - (sigma**2) / 2.0
    dt = random.lognormvariate(mu, sigma)
    dt = min(TURN_DELAY_MAX * 5.0, max(TURN_DELAY_MIN * 0.5, dt))
    
    print(f"Endpoint: turn_delay | Delay: {dt:.3f}s", flush=True)
    time.sleep(dt)
    return dt


class GateKeeper:
    def __init__(self, client):
        self._client = client
        self._active = threading.local()

    def wait_turn_delay(self):
        simulate_turn_delay()

    def wait_complex_delay(self):
        pass

    def __setattr__(self, name, value):
        if name in ('_client', '_active'):
            super().__setattr__(name, value)
        else:
            setattr(self._client, name, value)

    def __getattr__(self, name):
        attr = getattr(self._client, name)
        if callable(attr):
            def pacing_wrapper(*args, **kwargs):
                if getattr(self._active, 'in_pacing', False):
                    return attr(*args, **kwargs)
                
                self._active.in_pacing = True
                try:
                    ep_name = name
                    if name == 'call' and args:
                        ep = args[0]
                        path_map = {
                            'load/index': 'load_index',
                            'single_mode_free/start': 'start_career',
                            'single_mode_free/exec_command': 'exec_command',
                            'single_mode_free/read_info': 'load_index',
                            'single_mode_free/pre': 'pre_single_mode',
                            'single_mode_free/race_continue': 'continue',
                            'single_mode_free/gain_skills': 'gain_skills',
                            'single_mode_free/multi_item_exchange': 'multi_item_exchange',
                            'single_mode_free/multi_item_use': 'multi_item_use',
                            'single_mode_free/race_end': 'race_end',
                            'single_mode_free/race_entry': 'race_entry',
                            'single_mode_free/race_out': 'race_out',
                            'single_mode_free/race_start': 'race_start',
                            'single_mode_free/load': 'load_career',
                            'single_mode_free/finish': 'finish_career'
                        }
                        ep_name = path_map.get(ep, ep.split('/')[-1])
                    
                    method_map = {
                        'exchange_items': 'multi_item_exchange',
                        'use_items': 'multi_item_use',
                        'race_continue': 'continue',
                        'read_info': 'load_index'
                    }
                    pacing_name = method_map.get(ep_name, ep_name)
                    
                    simulate_delay(pacing_name, self._client)
                    return attr(*args, **kwargs)
                finally:
                    self._active.in_pacing = False
            return pacing_wrapper
        return attr
