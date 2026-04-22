from typing import Union
import requests
import re
import time
import json
import os
import unicodedata

from bot.conn.fetch import *

from bot.recog.ocr import find_similar_text
from module.umamusume.context import UmamusumeContext
from module.umamusume.script.cultivate_task.event.scenario_event import *
import bot.base.log as logger
from bot.server.events_state import update_events_load_info

from rapidfuzz import process, fuzz

log = logger.get_logger(__name__)

event_map: dict[str, Union[callable, int]] = {
    "": 5,
    "": scenario_event_1,
    "": scenario_event_2,
    "": scenario_event_2,

    # Youth Cup events
    "": 2,
    "!": aoharuhai_team_name_event,
    "A Team at Last": aoharuhai_team_name_event,
}

event_name_list: list[str] = [*event_map]

# Global variable to store the events database
_events_database = None

def load_events_database():
    """Load the events database from the JSON file"""
    global _events_database
    
    if _events_database is not None:
        return _events_database
    
    try:
        # Try to load from the JSON file in resource/umamusume/data folder, robustly
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', '..'))
        candidates = [
            os.path.join(base_dir, 'resource', 'umamusume', 'data', 'event_data.json'),
            os.path.join(os.getcwd(), 'resource', 'umamusume', 'data', 'event_data.json'),
        ]
        events_dict = None
        for json_path in candidates:
            if os.path.exists(json_path):
                log.info("Loading events database from event_data.json...")
                with open(json_path, 'r', encoding='utf-8') as f:
                    events_dict = json.load(f)
                break
        if events_dict is not None:
            _events_database = events_dict
            count = len(events_dict)
            log.info(f"Loaded {count} events from local database")
            try:
                update_events_load_info(count)
            except Exception:
                pass
            return events_dict
        else:
            log.warning("Events JSON file not found, will use web scraping fallback")
            return {}
            
    except Exception as e:
        log.error(f"Error loading events database: {e}")
        return {}

def get_local_event_choice(ctx: UmamusumeContext, event_name: str) -> Union[int, None]:
    if not event_name or not event_name.strip():
        return None

    events_db = load_events_database()
    if not events_db:
        return None

    if event_name in events_db:
        return calculate_optimal_choice_from_db(ctx, events_db[event_name])

    def normalize_string(text: str) -> str:
        if not text:
            return ""
        t = unicodedata.normalize('NFKD', str(text))
        t = t.lower().strip()
        t = re.sub(r"[^a-z0-9]+", " ", t)
        t = " ".join(t.split())
        return t

    query = normalize_string(event_name)

    norm_map = getattr(get_local_event_choice, "cache_normalized_key_map", None)
    if norm_map and query in norm_map:
        key = norm_map[query]
        return calculate_optimal_choice_from_db(ctx, events_db[key])

    choices = getattr(get_local_event_choice, "cache_choices", None)
    source_cache = getattr(get_local_event_choice, "cache_source", None)
    norm_map = getattr(get_local_event_choice, "cache_normalized_key_map", None)

    if choices is None or source_cache is not events_db or norm_map is None:
        norm_map = {}
        normalized_choices = []
        for original_key in events_db.keys():
            normalized_key = normalize_string(original_key)
            if normalized_key:
                norm_map[normalized_key] = original_key
                normalized_choices.append(normalized_key)
        setattr(get_local_event_choice, "cache_choices", normalized_choices)
        setattr(get_local_event_choice, "cache_source", events_db)
        setattr(get_local_event_choice, "cache_normalized_key_map", norm_map)
        choices = normalized_choices

    if not query or not choices:
        return None

    match = process.extractOne(query, choices, scorer=fuzz.WRatio, score_cutoff=85, processor=None)
    if not match:
        return None

    matched_normalized = match[0]
    score = match[1]
    if score < 95:
        a_len = len(query)
        b_len = len(matched_normalized) if matched_normalized else 0
        if a_len == 0 or b_len == 0:
            return None
        len_ratio = min(a_len, b_len) / max(a_len, b_len)
        if len_ratio < 0.8:
            return None

    key = norm_map.get(matched_normalized)
    if not key:
        return None

    return calculate_optimal_choice_from_db(ctx, events_db[key])

def get_local_event_choice_with_count(ctx: UmamusumeContext, event_name: str):
    if not event_name or not event_name.strip():
        return None, 0

    events_db = load_events_database()
    if not events_db:
        return None, 0

    def _resolve(key):
        event_data = events_db[key]
        choice = calculate_optimal_choice_from_db(ctx, event_data)
        expected = len(event_data.get('choices', {})) if isinstance(event_data, dict) else 0
        return choice, expected

    if event_name in events_db:
        return _resolve(event_name)

    def normalize_string(text: str) -> str:
        if not text:
            return ""
        t = unicodedata.normalize('NFKD', str(text))
        t = t.lower().strip()
        t = re.sub(r"[^a-z0-9]+", " ", t)
        t = " ".join(t.split())
        return t

    query = normalize_string(event_name)

    norm_map = getattr(get_local_event_choice, "cache_normalized_key_map", None)
    if norm_map and query in norm_map:
        return _resolve(norm_map[query])

    choices = getattr(get_local_event_choice, "cache_choices", None)
    source_cache = getattr(get_local_event_choice, "cache_source", None)

    if choices is None or source_cache is not events_db or norm_map is None:
        norm_map = {}
        normalized_choices = []
        for original_key in events_db.keys():
            normalized_key = normalize_string(original_key)
            if normalized_key:
                norm_map[normalized_key] = original_key
                normalized_choices.append(normalized_key)
        setattr(get_local_event_choice, "cache_choices", normalized_choices)
        setattr(get_local_event_choice, "cache_source", events_db)
        setattr(get_local_event_choice, "cache_normalized_key_map", norm_map)
        choices = normalized_choices

    if not query or not choices:
        return None, 0

    match = process.extractOne(query, choices, scorer=fuzz.WRatio, score_cutoff=85, processor=None)
    if not match:
        return None, 0

    matched_normalized = match[0]
    score = match[1]
    if score < 95:
        a_len = len(query)
        b_len = len(matched_normalized) if matched_normalized else 0
        if a_len == 0 or b_len == 0:
            return None, 0
        len_ratio = min(a_len, b_len) / max(a_len, b_len)
        if len_ratio < 0.8:
            return None, 0

    key = norm_map.get(matched_normalized)
    if not key:
        return None, 0

    return _resolve(key)


def warmup_event_index():
    events_db = load_events_database()
    if not events_db:
        return False

    def normalize_string(text: str) -> str:
        if not text:
            return ""
        t = unicodedata.normalize('NFKD', str(text))
        t = t.lower().strip()
        t = re.sub(r"[^a-z0-9]+", " ", t)
        t = " ".join(t.split())
        return t

    norm_map = {}
    normalized_choices = []
    for original_key in events_db.keys():
        normalized_key = normalize_string(original_key)
        if normalized_key:
            norm_map[normalized_key] = original_key
            normalized_choices.append(normalized_key)

    setattr(get_local_event_choice, "cache_choices", normalized_choices)
    setattr(get_local_event_choice, "cache_source", events_db)
    setattr(get_local_event_choice, "cache_normalized_key_map", norm_map)
    return True


def calculate_optimal_choice_from_db(ctx: UmamusumeContext, event_data: dict) -> int:
    """Calculate optimal choice from database event data"""
    choices = event_data['choices']
    stats = event_data['stats']
    if not choices:
        return 1

    state = fetch_state()
    energy = state["energy"]
    year_text = state["year"] if state["year"] else "Unknown"
    mood_val = state["mood"]
    mood_text = f"Level {mood_val}" if mood_val is not None else "Unknown"
    log.info(f"HP: {energy}, Year: {year_text}, Mood: {mood_text}")

    custom_weights = None
    try:
        if hasattr(ctx, 'task') and hasattr(ctx.task, 'detail') and hasattr(ctx.task.detail, 'event_weights'):
            custom_weights = ctx.task.detail.event_weights
    except Exception:
        pass

    if custom_weights and isinstance(custom_weights, dict):
        if year_text == "Junior" and 'junior' in custom_weights:
            weights = dict(custom_weights['junior'])
        elif year_text == "Classic" and 'classic' in custom_weights:
            weights = dict(custom_weights['classic'])
        elif year_text == "Senior" and 'senior' in custom_weights:
            weights = dict(custom_weights['senior'])
        else:
            weights = {
                'Power': 10,
                'Speed': 10,
                'Guts': 20,
                'Stamina': 10,
                'Wisdom': 1,
                'Friendship': 15,
                'Mood': 9999,
                'Max Energy': 50,
                'HP': 16,
                'Skill': 10,
                'Skill Hint': 100,
                'Skill Pts': 10
            }
    else:
        weights = {
            'Power': 10,
            'Speed': 10,
            'Guts': 20,
            'Stamina': 10,
            'Wisdom': 1,
            'Friendship': 15,
            'Mood': 9999,
            'Max Energy': 50,
            'HP': 16,
            'Skill': 10,
            'Skill Hint': 100,
            'Skill Pts': 10
        }

        if year_text == "Junior":
            weights['Friendship'] = 35
        elif year_text == "Senior":
            weights['Friendship'] = 0
            weights['Max Energy'] = 0

    if mood_val == 5:
        weights['Mood'] = 0
        log.info("Mood already maxxed")

    if energy > 84:
        weights['HP'] = 0
        log.info("Energy already near full")
    elif 40 <= energy <= 60:
        weights['HP'] = 30
        log.info("Focusing on energy to avoid rest")
    else:
        if 'HP' not in weights:
            weights['HP'] = 16

    weight_str = ", ".join(f"{k}:{v}" for k, v in sorted(weights.items()))
    log.info(f"Event weights: {weight_str}")

    status_effects = event_data.get('status_effects', {})
    low_friendship_count = 0
    try:
        from module.umamusume.define import SupportCardFavorLevel, SupportCardType
        ti = ctx.cultivate_detail.turn_info
        seen_names = set()
        for tl in ti.training_info_list:
            for sc in getattr(tl, 'support_card_info_list', []) or []:
                ctype = getattr(sc, 'card_type', SupportCardType.SUPPORT_CARD_TYPE_UNKNOWN)
                if ctype in (SupportCardType.SUPPORT_CARD_TYPE_NPC, SupportCardType.SUPPORT_CARD_TYPE_UNKNOWN):
                    continue
                name = getattr(sc, 'name', '')
                if name in seen_names:
                    continue
                seen_names.add(name)
                favor = getattr(sc, 'favor', SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_UNKNOWN)
                if favor in (SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_1, SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_2):
                    low_friendship_count += 1
    except Exception:
        low_friendship_count = 5 if year_text == "Junior" else (3 if year_text == "Classic" else 1)

    best_choice = None
    best_score = -1

    for choice_num, choice_stats in stats.items():
        choice_num_int = int(choice_num)
        score = 0
        for stat, value in choice_stats.items():
            if stat in weights:
                score += value * weights[stat]
        effects = status_effects.get(choice_num, [])
        for eff in effects:
            sid = eff.get('id')
            is_random = eff.get('random', False)
            effect_score = 0
            if sid == 4:
                effect_score = -111
            elif sid == 7:
                if year_text == "Junior":
                    effect_score = 333
                elif year_text == "Classic":
                    effect_score = 250
                else:
                    effect_score = 222
            elif sid == 8:
                effect_score = 75 * low_friendship_count
            elif sid in (9, 10, 11):
                effect_score = 35
            if not is_random:
                effect_score = int(effect_score * 1.25)
            score += effect_score
        if score > best_score:
            best_score = score
            best_choice = choice_num_int

    if best_choice:
        log.info(f"Optimal choice: {best_choice} (Score: {best_score})")
        return best_choice

    if choices:
        first_choice = min(int(k) for k in choices.keys())
        log.info(f"Fallback choice: {first_choice}")
        return first_choice

    return 1


def get_event_choice(ctx: UmamusumeContext, event_name: str):
    if not event_name or not event_name.strip():
        return 0, "none", 0
    try:
        overrides = {}
        if hasattr(ctx, 'cultivate_detail') and hasattr(ctx.cultivate_detail, 'event_overrides'):
            if isinstance(ctx.cultivate_detail.event_overrides, dict):
                overrides = ctx.cultivate_detail.event_overrides or {}
        if not overrides and hasattr(ctx, 'task') and hasattr(ctx.task, 'detail') and hasattr(ctx.task.detail, 'event_overrides'):
            if isinstance(ctx.task.detail.event_overrides, dict):
                overrides = ctx.task.detail.event_overrides or {}
        if overrides:
            if event_name in overrides and isinstance(overrides[event_name], int):
                choice = int(overrides[event_name])
                if choice > 0:
                    log.info(f"User overwrite: Choice {choice}")
                    return choice, "override", 0
            try:
                keys = list(overrides.keys())
                matched = find_similar_text(event_name, keys, 0.85)
                if matched and matched in overrides and isinstance(overrides[matched], int):
                    choice = int(overrides[matched])
                    if choice > 0:
                        log.info(f"User overwrite: Choice {choice}")
                        return choice, "override", 0
            except Exception:
                pass
    except Exception:
        pass
    try:
        ENERGY_CONDITIONAL_EVENTS = {
            'extra training': (1, 2, 90),  # (high_energy_choice, low_energy_choice, threshold)
        }
        if event_name.strip().lower() in ENERGY_CONDITIONAL_EVENTS:
            high_choice, low_choice, threshold = ENERGY_CONDITIONAL_EVENTS[event_name.strip().lower()]
            energy = getattr(ctx.cultivate_detail.turn_info, 'cached_energy', 100)
            if energy > threshold:
                log.info(f"Energy conditional event '{event_name}': energy={energy}>{threshold}, choice {high_choice}")
                return high_choice, "hardcoded", 0
            else:
                log.info(f"Energy conditional event '{event_name}': energy={energy}<={threshold}, choice {low_choice}")
                return low_choice, "hardcoded", 0
    except Exception:
        pass
    try:
        POST_RACE_EVENTS = ('victory!', 'solid showing', 'defeat')
        if event_name.strip().lower() in POST_RACE_EVENTS:
            energy = getattr(ctx.cultivate_detail.turn_info, 'cached_energy', 100)
            if energy > 20:
                log.info(f"Post-race event '{event_name}' with energy={energy} - forcing choice 1")
                return 1, "hardcoded", 0
            else:
                log.info(f"Post-race event '{event_name}' with low energy={energy} - using normal logic")
    except Exception:
        pass
    event_name_normalized = find_similar_text(event_name, event_name_list, 0.8)
    if event_name_normalized != "":
        if event_name_normalized in event_map:
            opt = event_map[event_name_normalized]
            if type(opt) is int:
                log.info(f"Using predefined choice for event '{event_name}': {opt}")
                return opt, "hardcoded", 0
            if callable(opt):
                result = opt(ctx)
                return (result if isinstance(result, int) else 1), "hardcoded", 0
            else:
                log.warning("Event [%s] does not provide processing logic", event_name_normalized)
                return 1, "hardcoded", 0
    
    # Youth Cup events
    if event_name_normalized in ["aoharuhai_team_name_event"]:
        return event_map[event_name_normalized](ctx), "hardcoded", 0
    
    # Try local database
    log.info(f"Checking local database for event '{event_name}'...")
    local_choice, expected_count = get_local_event_choice_with_count(ctx, event_name)
    if local_choice is not None:
        return local_choice, "database", expected_count
    
    # Fallback to default choice
    return 2, "fallback", 0
