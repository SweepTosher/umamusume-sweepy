import json
import os
import threading

import bot.base.log as logger

log = logger.get_logger(__name__)

PERSISTENCE_FILE = os.path.join(os.path.dirname(__file__), '..', '..', 'career_data.json')
PERSISTENCE_FILE = os.path.normpath(PERSISTENCE_FILE)

PERSIST_FILE = os.path.join(os.path.dirname(__file__), '..', '..', 'persist.json')
PERSIST_FILE = os.path.normpath(PERSIST_FILE)

MAX_DATAPOINTS = 2000
HISTORY_VERSION_FLAG = "aaa"

career_cleared_flag = False
career_data_lock = threading.Lock()


def rebuild_percentile_history(score_history):
    percentiles = []
    for i in range(1, len(score_history)):
        current = score_history[i]
        prev = score_history[:i]
        below_count = sum(1 for s in prev if s < current)
        percentile = below_count / len(prev) * 100
        percentiles.append(percentile)
    return percentiles


def save_career_data(ctx):
    global career_cleared_flag
    try:
        with career_data_lock:
            if career_cleared_flag:
                career_cleared_flag = False
                ctx.cultivate_detail.score_history = []
                ctx.cultivate_detail.percentile_history = []
                log.info("Career data cleared from memory")
                return
            score_history = getattr(ctx.cultivate_detail, 'score_history', [])
            if not score_history:
                return
            scores = score_history[-MAX_DATAPOINTS:]
            stat_only_history = getattr(ctx.cultivate_detail, 'stat_only_history', [])
            stat_only = stat_only_history[-MAX_DATAPOINTS:]
            energy_history = getattr(ctx.cultivate_detail, 'energy_history', [])
            energy = energy_history[-MAX_DATAPOINTS:]
            action_history = getattr(ctx.cultivate_detail, 'action_history', [])
            actions = action_history[-MAX_DATAPOINTS:]
            raw_stat_history = getattr(ctx.cultivate_detail, 'raw_stat_history', [])
            raw_stats = raw_stat_history[-MAX_DATAPOINTS:]
            date_history = getattr(ctx.cultivate_detail, 'date_history', [])
            dates = date_history[-MAX_DATAPOINTS:]
            data = {
                'version': HISTORY_VERSION_FLAG,
                'score_history': scores,
                'stat_only_history': stat_only,
                'energy_history': energy,
                'action_history': actions,
                'raw_stat_history': raw_stats,
                'date_history': dates,
            }
            with open(PERSISTENCE_FILE, 'w') as f:
                json.dump(data, f)
                f.flush()
                os.fsync(f.fileno())
    except Exception as e:
        log.info(f"Failed to save career data: {e}")


def load_career_data(ctx):
    try:
        if not os.path.exists(PERSISTENCE_FILE):
            return False
        with open(PERSISTENCE_FILE, 'r') as f:
            data = json.load(f)
        stored_version = data.get('version', "")
        if stored_version != HISTORY_VERSION_FLAG:
            clear_career_data()
            return False

        required_keys = {'score_history', 'stat_only_history', 'energy_history', 'action_history', 'raw_stat_history', 'date_history'}
        if not required_keys.issubset(data.keys()):
            log.info("Career data format mismatch - clearing old data")
            clear_career_data()
            return False
        score_history = data.get('score_history', [])
        stat_only_history = data.get('stat_only_history', [])
        energy_history = data.get('energy_history', [])
        action_history = data.get('action_history', [])
        raw_stat_history = data.get('raw_stat_history', [])
        date_history = data.get('date_history', [])
        if not score_history:
            return False
        scores = score_history[-MAX_DATAPOINTS:]
        stat_only = stat_only_history[-MAX_DATAPOINTS:]
        energy = energy_history[-MAX_DATAPOINTS:]
        actions = action_history[-MAX_DATAPOINTS:]
        raw_stats = raw_stat_history[-MAX_DATAPOINTS:]
        dates = date_history[-MAX_DATAPOINTS:]
        ctx.cultivate_detail.score_history = scores
        ctx.cultivate_detail.stat_only_history = stat_only
        ctx.cultivate_detail.energy_history = energy
        ctx.cultivate_detail.action_history = actions
        ctx.cultivate_detail.raw_stat_history = raw_stats
        ctx.cultivate_detail.date_history = dates
        ctx.cultivate_detail.percentile_history = rebuild_percentile_history(scores)
        log.info(f"Restored career data: {len(scores)} datapoints")
        return True
    except Exception as e:
        log.info(f"Failed to load career data: {e}")
        return False


def clear_career_data():
    global career_cleared_flag
    try:
        with career_data_lock:
            with open(PERSISTENCE_FILE, 'w') as f:
                json.dump({
                    'version': HISTORY_VERSION_FLAG,
                    'score_history': [], 
                    'stat_only_history': [], 
                    'energy_history': [], 
                    'action_history': [], 
                    'raw_stat_history': [], 
                    'date_history': []
                }, f)
                f.flush()
                os.fsync(f.fileno())
            career_cleared_flag = True
        log.info("Career data cleared")
        return True
    except Exception as e:
        log.info(f"Failed to clear career data: {e}")
        return False


def load_persist():
    try:
        if not os.path.exists(PERSIST_FILE):
            return {}
        with open(PERSIST_FILE, 'r') as f:
            return json.load(f)
    except Exception:
        return {}


def save_persist(data):
    try:
        with open(PERSIST_FILE, 'w') as f:
            json.dump(data, f)
    except Exception:
        pass


def mark_buff_used(item_name):
    data = load_persist()
    used = set(data.get('used_buffs', []))
    used.add(item_name)
    data['used_buffs'] = list(used)
    save_persist(data)


def is_buff_used(item_name):
    data = load_persist()
    return item_name in data.get('used_buffs', [])


def get_used_buffs():
    data = load_persist()
    return set(data.get('used_buffs', []))


def clear_used_buffs():
    data = load_persist()
    data['used_buffs'] = []
    save_persist(data)


def get_ignore_cat_food():
    data = load_persist()
    return data.get('ignore_cat_food', False)


def set_ignore_cat_food(flag=True):
    data = load_persist()
    data['ignore_cat_food'] = flag
    save_persist(data)


def clear_ignore_cat_food():
    data = load_persist()
    data.pop('ignore_cat_food', None)
    save_persist(data)


def get_ignore_grilled_carrots():
    data = load_persist()
    return data.get('ignore_grilled_carrots', False)


def set_ignore_grilled_carrots(flag=True):
    data = load_persist()
    data['ignore_grilled_carrots'] = flag
    save_persist(data)


def clear_ignore_grilled_carrots():
    data = load_persist()
    data.pop('ignore_grilled_carrots', None)
    save_persist(data)


def save_megaphone_state(tier, turns):
    data = load_persist()
    data['megaphone_tier'] = tier
    data['megaphone_turns'] = turns
    save_persist(data)


def load_megaphone_state():
    data = load_persist()
    tier = data.get('megaphone_tier', 0)
    turns = data.get('megaphone_turns', 0)
    return tier, turns


def clear_megaphone_state():
    data = load_persist()
    data.pop('megaphone_tier', None)
    data.pop('megaphone_turns', None)
    save_persist(data)
