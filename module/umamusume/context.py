from bot.base.context import BotContext
from module.umamusume.scenario.registry import create_scenario
from module.umamusume.scenario import ura_scenario
from module.umamusume.scenario.aoharuhai import AoharuHaiScenario
from module.umamusume.scenario.mant import MANTScenario
from module.umamusume.task import UmamusumeTask, UmamusumeTaskType
from module.umamusume.define import *
from module.umamusume.types import TurnInfo
from module.umamusume.constants.scoring_constants import (
    DEFAULT_BASE_SCORES, DEFAULT_SPIRIT_EXPLOSION, DEFAULT_PAL_FRIENDSHIP_SCORES,
    DEFAULT_PAL_CARD_MULTIPLIER, DEFAULT_NPC_SCORE_VALUE,
    DEFAULT_SUMMER_SCORE_THRESHOLD, DEFAULT_STAT_VALUE_MULTIPLIER,
    DEFAULT_WIT_SPECIAL_MULTIPLIER
)
import bot.base.log as logger

log = logger.get_logger(__name__)

detected_skills_log = {}
detected_portraits_log = {}
detected_items_log = {}
detected_shop_items_log = {}

def log_detected_portrait(name, favor_level, is_npc=False):
    if not name or not favor_level:
        return
    existing = detected_portraits_log.get(name)
    if existing:
        existing["favor"] = favor_level
    else:
        detected_portraits_log[name] = {
            "name": name,
            "favor": favor_level,
            "is_npc": is_npc,
        }

def clear_detected_portraits():
    pass

def log_detected_skill(name, source, hint_level=0, cost=0, gold=False):
    if not name:
        return
    existing = detected_skills_log.get(name)
    if existing:
        if hint_level > existing.get("hint_level", 0):
            existing["hint_level"] = hint_level
        if source not in existing.get("source", ""):
            existing["source"] = existing["source"] + "+" + source
        if cost > 0:
            existing["cost"] = cost
    else:
        detected_skills_log[name] = {
            "name": name,
            "source": source,
            "hint_level": hint_level,
            "cost": cost,
            "gold": gold
        }

def clear_detected_skills():
    pass

def log_detected_items(items):
    from module.umamusume.scenario.mant.shop import WEBUI_EXCLUDED_PREFIXES
    current_items = set()
    for name, qty in items:
        if name in WEBUI_EXCLUDED_PREFIXES:
            continue
        detected_items_log[name] = {
            "name": name,
            "qty": qty,
        }
        current_items.add(name)
    for name in list(detected_items_log.keys()):
        if name not in current_items:
            del detected_items_log[name]

def clear_detected_items():
    pass

def log_detected_shop_items(items):
    for name, turns, buyable in items:
        if not buyable:
            continue
        detected_shop_items_log[name] = {
            "name": name,
            "turns": turns,
            "purchased": False,
        }

def add_detected_shop_items(names, turns):
    for name in names:
        existing = detected_shop_items_log.get(name)
        detected_shop_items_log[name] = {
            "name": name,
            "turns": turns,
            "purchased": existing.get("purchased", False) if existing else False,
            "race_reward": True,
        }

def clear_detected_shop_items():
    pass

class CultivateContextDetail:
    race_chain_map: dict[int, tuple[int, int]]
    turn_info: TurnInfo | None
    turn_info_history: list[TurnInfo]
    scenario: any
    expect_attribute: list[int] | None
    follow_support_card_name: str
    follow_support_card_level: int
    extra_race_list: list[int]
    learn_skill_list: list[list[str]]
    learn_skill_blacklist: list[str]
    learn_skill_done: bool
    learn_skill_selected: bool
    cultivate_finish: bool
    tactic_list: list[int]
    tactic_actions: list
    debut_race_win: bool
    clock_use_limit: int
    clock_used: int
    learn_skill_threshold: int
    learn_skill_only_user_provided: bool
    learn_skill_before_race: bool
    allow_recover_tp: bool
    parse_factor_done: bool
    extra_weight: list
    spirit_explosion: list
    learned_skill_names: set
    manual_purchase_completed: bool
    final_skill_sweep_active: bool
    user_provided_priority: bool
    use_last_parents: bool
    pal_event_stage: int
    pal_name: str
    pal_friendship_score: list[float]
    pal_card_multiplier: float
    npc_score_value: list
    base_score: list
    summer_score_threshold: float
    stat_value_multiplier: list
    wit_special_multiplier: list
    skip_double_circle_unless_high_hint: bool
    hint_boost_characters: list[str]
    hint_boost_multiplier: int
    friendship_score_groups: list
    score_history: list[float]
    percentile_history: list[float]
    energy_history: list[float]
    action_history: list[str]
    raw_stat_history: list[float]
    date_history: list[int]
    facility_clicks: dict[str, int]
    last_title: str
    same_title_count: int

    def __init__(self):
        self.race_chain_map = {}
        self.expect_attribute = None
        self.turn_info = TurnInfo()
        self.turn_info_history = []
        self.extra_race_list = []
        self.learn_skill_list = []
        self.learn_skill_blacklist = []
        self.learn_skill_done = False
        self.learn_skill_selected = False
        self.cultivate_finish = False
        self.tactic_list = []
        self.tactic_actions = []
        self.debut_race_win = False
        self.clock_use_limit = 0
        self.clock_used = 0
        self.allow_recover_tp = False
        self.parse_factor_done = False
        self.extra_weight = []
        self.spirit_explosion = [0.16, 0.16, 0.16, 0.06, 0.11]
        self.learned_skill_names = set()
        self.manual_purchase_completed = False
        self.final_skill_sweep_active = False
        self.mant_shop_items = []
        self.mant_shop_scanned_this_turn = False
        self.mant_shop_last_chunk = -1
        self.mant_afflictions = []
        self.mant_coins = 0
        self.mant_inventory_scanned = False
        self.mant_owned_items = []
        self.mant_max_energy = 100
        self.user_provided_priority = False
        self.event_overrides = {}
        self.use_last_parents = False
        self.pal_event_stage = 0
        self.pal_stage_detection_done_this_turn = False
        self.pal_name = ""
        self.pal_friendship_score = list(DEFAULT_PAL_FRIENDSHIP_SCORES)
        self.pal_card_multiplier = DEFAULT_PAL_CARD_MULTIPLIER
        self.npc_score_value = [list(row) for row in DEFAULT_NPC_SCORE_VALUE]
        self.base_score = list(DEFAULT_BASE_SCORES)
        self.summer_score_threshold = DEFAULT_SUMMER_SCORE_THRESHOLD
        self.stat_value_multiplier = list(DEFAULT_STAT_VALUE_MULTIPLIER)
        self.wit_special_multiplier = list(DEFAULT_WIT_SPECIAL_MULTIPLIER)
        self.group_card_enabled = False
        self.group_card_name = ""
        self.group_card_percentile = 26
        self.group_card_available_dates = []
        self.group_card_last_date = -1
        self.last_title = ""
        self.same_title_count = 0
        self.facility_clicks = {"speed": 0, "stamina": 0, "power": 0, "guts": 0, "wits": 0}


    def reset_skill_learn(self):
        self.learn_skill_done = False
        self.learn_skill_selected = False
        self.manual_purchase_completed = False
        if hasattr(self, 'manual_purchase_initiated'):
            delattr(self, 'manual_purchase_initiated')


class UmamusumeContext(BotContext):
    task: UmamusumeTask
    cultivate_detail: CultivateContextDetail

    def __init__(self, task, ctrl):
        super().__init__(task, ctrl)

    def is_task_finish(self) -> bool:
        return False


def build_context(task: UmamusumeTask, ctrl) -> UmamusumeContext:
    ctx = UmamusumeContext(task, ctrl)
    if task.task_type == UmamusumeTaskType.UMAMUSUME_TASK_TYPE_CULTIVATE:
        clear_detected_skills()
        clear_detected_portraits()
        clear_detected_items()
        clear_detected_shop_items()
        detail = CultivateContextDetail()
        detail.scenario = create_scenario(task.detail.scenario)
        if detail.scenario is None:
            pass
        detail.expect_attribute = task.detail.expect_attribute
        detail.follow_support_card_name = task.detail.follow_support_card_name
        detail.follow_support_card_level = task.detail.follow_support_card_level
        detail.extra_race_list = list(task.detail.extra_race_list or [])
        from module.umamusume.asset.race_data import compute_race_chains
        detail.race_chain_map = compute_race_chains(detail.extra_race_list)
        detail.learn_skill_list = [list(x) for x in (task.detail.learn_skill_list or [])]
        try:
            src = task.detail.learn_skill_list or []
            detail.user_provided_priority = any((isinstance(x, list) and x) for x in src)
        except Exception:
            detail.user_provided_priority = False
        detail.learn_skill_blacklist = list(task.detail.learn_skill_blacklist or [])
        detail.tactic_list = list(task.detail.tactic_list or [])
        detail.tactic_actions = list(getattr(task.detail, 'tactic_actions', []))
        detail.clock_use_limit = task.detail.clock_use_limit
        detail.learn_skill_threshold = task.detail.learn_skill_threshold
        detail.learn_skill_only_user_provided = task.detail.learn_skill_only_user_provided
        detail.allow_recover_tp = task.detail.allow_recover_tp
        try:
            detail.extra_weight = list(task.detail.extra_weight or [])
        except Exception:
            detail.extra_weight = []

        try:
            se = getattr(task.detail, 'spirit_explosion', DEFAULT_SPIRIT_EXPLOSION)
            detail.spirit_explosion = list(se) if se else list(DEFAULT_SPIRIT_EXPLOSION)
        except Exception:
            detail.spirit_explosion = list(DEFAULT_SPIRIT_EXPLOSION)


        detail.rest_threshold = getattr(task.detail, 'rest_threshold', getattr(task.detail, 'rest_treshold', getattr(task.detail, 'fast_path_energy_limit', 48)))
        detail.motivation_threshold_year1 = int(getattr(task.detail, 'motivation_threshold_year1', 3))
        detail.motivation_threshold_year2 = int(getattr(task.detail, 'motivation_threshold_year2', 4))
        detail.motivation_threshold_year3 = int(getattr(task.detail, 'motivation_threshold_year3', 4))
        detail.prioritize_recreation = getattr(task.detail, 'prioritize_recreation', False)
        detail.pal_name = getattr(task.detail, 'pal_name', "")
        detail.pal_thresholds = list(getattr(task.detail, 'pal_thresholds', []))

        detail.pal_friendship_score = list(getattr(task.detail, 'pal_friendship_score', DEFAULT_PAL_FRIENDSHIP_SCORES))
        detail.pal_card_multiplier = float(getattr(task.detail, 'pal_card_multiplier', DEFAULT_PAL_CARD_MULTIPLIER))
        npc_sv = getattr(task.detail, 'npc_score_value', None)
        if npc_sv and isinstance(npc_sv, list):
            detail.npc_score_value = [list(row) for row in npc_sv]
        else:
            detail.npc_score_value = [list(row) for row in DEFAULT_NPC_SCORE_VALUE]

        detail.score_value = getattr(task.detail, 'score_value', [
            [0.11, 0.10, 0.01, 0.09],
            [0.11, 0.10, 0.09, 0.09],
            [0.11, 0.10, 0.12, 0.09],
            [0.03, 0.05, 0.15, 0.09],
            [0, 0, 0.27, 0, 0]
        ])
        detail.compensate_failure = getattr(task.detail, 'compensate_failure', True)
        detail.use_last_parents = getattr(task.detail, 'use_last_parents', False)
        detail.base_score = list(getattr(task.detail, 'base_score', DEFAULT_BASE_SCORES))
        detail.summer_score_threshold = float(getattr(task.detail, 'summer_score_threshold', DEFAULT_SUMMER_SCORE_THRESHOLD))
        detail.stat_value_multiplier = list(getattr(task.detail, 'stat_value_multiplier', DEFAULT_STAT_VALUE_MULTIPLIER))
        detail.wit_special_multiplier = list(getattr(task.detail, 'wit_special_multiplier', DEFAULT_WIT_SPECIAL_MULTIPLIER))
        detail.skip_double_circle_unless_high_hint = getattr(task.detail, 'skip_double_circle_unless_high_hint', False)
        detail.hint_boost_characters = list(getattr(task.detail, 'hint_boost_characters', []))
        detail.hint_boost_multiplier = int(getattr(task.detail, 'hint_boost_multiplier', 100))
        detail.friendship_score_groups = list(getattr(task.detail, 'friendship_score_groups', []))
        detail.score_history = []
        detail.percentile_history = []
        detail.energy_history = []
        detail.action_history = []
        detail.raw_stat_history = []
        detail.date_history = []
        try:
            eo = getattr(task.detail, 'event_overrides', {})
            detail.event_overrides = eo if isinstance(eo, dict) else {}
        except Exception:
            detail.event_overrides = {}

        ctx.cultivate_detail = detail

        pcs = getattr(task.detail, 'pal_card_store', None)
        if isinstance(pcs, dict):
            for _key, _val in pcs.items():
                if not isinstance(_val, (dict, list)):
                    continue
                if isinstance(_val, dict):
                    _pal_type = _val.get('type', 'group' if _val.get('group') else 'friend')
                else:
                    _pal_type = 'friend'

                if _pal_type == 'group':
                    if not detail.group_card_enabled:
                        _group_name = _val.get('group', _key) if isinstance(_val, dict) else _key
                        _enabled = _val.get('enabled', False) if isinstance(_val, dict) else False
                        if _enabled:
                            detail.group_card_enabled = True
                            detail.group_card_name = _group_name
                            detail.group_card_percentile = int(_val.get('percentile', 26)) if isinstance(_val, dict) else 26
        if detail.prioritize_recreation and detail.pal_thresholds:
            detail.group_card_enabled = False
            detail.group_card_name = ""

        try:
            from module.umamusume.persistence import load_megaphone_state, load_afflictions, load_inventory, load_last_known_date
            mega_tier, mega_turns = load_megaphone_state()
            detail.mant_megaphone_tier = mega_tier
            detail.mant_megaphone_turns = mega_turns
            if mega_tier > 0 and mega_turns > 0:
                pass

            detail.mant_afflictions = load_afflictions()
            if detail.mant_afflictions:
                pass

            detail.mant_owned_items = load_inventory()
            if detail.mant_owned_items:
                pass

            detail._last_known_date_id = load_last_known_date()
        except Exception:
            detail.mant_megaphone_tier = 0
            detail.mant_megaphone_turns = 0

    return ctx
