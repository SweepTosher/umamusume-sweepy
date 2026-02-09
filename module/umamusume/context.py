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
    DEFAULT_SUMMER_SCORE_THRESHOLD, DEFAULT_WIT_FALLBACK_THRESHOLD, DEFAULT_STAT_VALUE_MULTIPLIER
)
import bot.base.log as logger

log = logger.get_logger(__name__)
class CultivateContextDetail:
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
    wit_fallback_threshold: float
    stat_value_multiplier: list

    def __init__(self):
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
        self.manual_purchase_completed = False
        self.final_skill_sweep_active = False
        self.user_provided_priority = False
        self.event_overrides = {}
        self.use_last_parents = False
        self.pal_event_stage = 0
        self.pal_name = ""
        self.pal_friendship_score = list(DEFAULT_PAL_FRIENDSHIP_SCORES)
        self.pal_card_multiplier = DEFAULT_PAL_CARD_MULTIPLIER
        self.npc_score_value = [list(row) for row in DEFAULT_NPC_SCORE_VALUE]
        self.base_score = list(DEFAULT_BASE_SCORES)
        self.summer_score_threshold = DEFAULT_SUMMER_SCORE_THRESHOLD
        self.wit_fallback_threshold = DEFAULT_WIT_FALLBACK_THRESHOLD
        self.stat_value_multiplier = list(DEFAULT_STAT_VALUE_MULTIPLIER)

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
        detail = CultivateContextDetail()
        detail.scenario = create_scenario(task.detail.scenario)
        if detail.scenario is None:
            log.error("Unknown scenario")
        detail.expect_attribute = task.detail.expect_attribute
        detail.follow_support_card_name = task.detail.follow_support_card_name
        detail.follow_support_card_level = task.detail.follow_support_card_level
        detail.extra_race_list = list(task.detail.extra_race_list or [])
        detail.learn_skill_list = [list(x) for x in (task.detail.learn_skill_list or [])]
        try:
            src = task.detail.learn_skill_list or []
            detail.user_provided_priority = any((isinstance(x, list) and len(x) > 0) for x in src)
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
        
        # Support both spellings for backward compatibility (rest_threshold is correct)
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
        detail.wit_fallback_threshold = float(getattr(task.detail, 'wit_fallback_threshold', DEFAULT_WIT_FALLBACK_THRESHOLD))
        detail.stat_value_multiplier = list(getattr(task.detail, 'stat_value_multiplier', DEFAULT_STAT_VALUE_MULTIPLIER))
        try:
            eo = getattr(task.detail, 'event_overrides', {})
            detail.event_overrides = eo if isinstance(eo, dict) else {}
        except Exception:
            detail.event_overrides = {}
        
        ctx.cultivate_detail = detail
    return ctx
