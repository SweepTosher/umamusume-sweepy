from enum import Enum
from module.umamusume.define import ScenarioType
from bot.base.task import Task, TaskExecuteMode
from module.umamusume.scenario.configs import *


class TaskDetail:
    cure_asap_conditions: str
    scenario: ScenarioType
    expect_attribute: list[int]
    follow_support_card_name: str
    follow_support_card_level: int
    extra_race_list: list[int]
    learn_skill_list: list[list[str]]
    learn_skill_blacklist: list[str]
    tactic_list: list[int]
    clock_use_limit: int
    learn_skill_threshold: int
    learn_skill_only_user_provided: bool
    allow_recover_tp: bool
    cultivate_progress_info: dict
    extra_weight: list
    spirit_explosion: list
    manual_purchase_at_end: bool
    override_insufficient_fans_forced_races: bool
    use_last_parents: bool
    # Motivation thresholds for trip logic
    motivation_threshold_year1: int
    motivation_threshold_year2: int
    motivation_threshold_year3: int
    prioritize_recreation: bool
    pal_name: str
    pal_thresholds: list
    pal_friendship_score: list[float]
    pal_card_multiplier: float
    score_value: list
    compensate_failure: bool
    event_weights: dict
    scenario_config: ScenarioConfig
    fujikiseki_show_mode: bool
    fujikiseki_show_difficulty: int
    do_tt_next: bool


class EndTaskReason(Enum):
    TP_NOT_ENOUGH = "训练值不足"
    DIFFICULTY_LOCKED = "难度未解锁"


class UmamusumeTask(Task):
    detail: TaskDetail

    def end_task(self, status, reason) -> None:
        super().end_task(status, reason)

    def start_task(self) -> None:
        if self.task_execute_mode == TaskExecuteMode.TASK_EXECUTE_MODE_FULL_AUTO:
            self.detail.do_tt_next = False
        super().start_task()


class UmamusumeTaskType(Enum):
    UMAMUSUME_TASK_TYPE_UNKNOWN = 0
    UMAMUSUME_TASK_TYPE_CULTIVATE = 1


def build_task(task_execute_mode: TaskExecuteMode, task_type: int,
               task_desc: str, cron_job_config: dict, attachment_data: dict) -> UmamusumeTask:
    td = TaskDetail()
    ut = UmamusumeTask(task_execute_mode=task_execute_mode,
                       task_type=UmamusumeTaskType(task_type), task_desc=task_desc, app_name="umamusume")
    ut.cron_job_config = cron_job_config
    td.scenario = ScenarioType(attachment_data['scenario'])
    td.expect_attribute = attachment_data['expect_attribute']
    td.follow_support_card_level = int(attachment_data['follow_support_card_level'])
    td.follow_support_card_name = attachment_data['follow_support_card_name']
    td.extra_race_list = attachment_data['extra_race_list']
    td.learn_skill_list = attachment_data['learn_skill_list']
    td.learn_skill_blacklist = attachment_data['learn_skill_blacklist']
    td.tactic_list = attachment_data['tactic_list']
    td.clock_use_limit = attachment_data['clock_use_limit']
    td.learn_skill_threshold = attachment_data['learn_skill_threshold']
    td.learn_skill_only_user_provided = attachment_data['learn_skill_only_user_provided']
    td.allow_recover_tp = attachment_data['allow_recover_tp']
    td.extra_weight = attachment_data['extra_weight']
    td.spirit_explosion = attachment_data.get('spirit_explosion', [0.9, 0.9, 0.9, 0.5, 0.5])
    td.compensate_failure = attachment_data.get('compensate_failure', True)
    td.manual_purchase_at_end = attachment_data['manual_purchase_at_end']
    td.override_insufficient_fans_forced_races = attachment_data.get('override_insufficient_fans_forced_races', False)
    td.use_last_parents = attachment_data.get('use_last_parents', False)
    td.cure_asap_conditions = attachment_data.get("cure_asap_conditions", "")
    td.rest_treshold = attachment_data.get('rest_treshold', attachment_data.get('fast_path_energy_limit', 48))
    td.summer_score_threshold = attachment_data.get('summer_score_threshold', 0.34)
    td.wit_fallback_threshold = attachment_data.get('wit_fallback_threshold', 0.01)
    
    td.motivation_threshold_year1 = attachment_data.get('motivation_threshold_year1', 3)
    td.motivation_threshold_year2 = attachment_data.get('motivation_threshold_year2', 4)
    td.motivation_threshold_year3 = attachment_data.get('motivation_threshold_year3', 4)
    td.prioritize_recreation = attachment_data.get('prioritize_recreation', False)
    td.pal_name = attachment_data.get('pal_name', "")
    td.pal_thresholds = attachment_data.get('pal_thresholds', [])

    td.pal_friendship_score = attachment_data.get('pal_friendship_score', [0.08, 0.057, 0.018])
    td.pal_card_multiplier = attachment_data.get('pal_card_multiplier', 0.1)

    td.score_value = attachment_data.get('score_value', [
        [0.11, 0.10, 0.01, 0.09],
        [0.11, 0.10, 0.09, 0.09],
        [0.11, 0.10, 0.12, 0.09],
        [0.03, 0.05, 0.15, 0.09],
        [0, 0, 0.15, 0, 0]
    ])
    
    td.cultivate_result = {}
    # 剧本相关设置
    td.scenario_config = ScenarioConfig(
        ura_config = None if (attachment_data['ura_config'] is None) else UraConfig(attachment_data['ura_config']),
        aoharu_config = None if (attachment_data['aoharu_config'] is None) else AoharuConfig(attachment_data['aoharu_config']))
    # 限时: 富士奇石的表演秀
    td.fujikiseki_show_mode = attachment_data['fujikiseki_show_mode']
    try:
        eo = attachment_data.get('event_overrides', attachment_data.get('event_choices', {}))
        td.event_overrides = eo if isinstance(eo, dict) else {}
    except Exception:
        td.event_overrides = {}
    
    try:
        ew = attachment_data.get('event_weights', None)
        td.event_weights = ew if isinstance(ew, dict) else None
    except Exception:
        td.event_weights = None

    td.fujikiseki_show_difficulty = attachment_data['fujikiseki_show_difficulty']
    td.do_tt_next = attachment_data.get('do_tt_next', False)
    
    ut.detail = td
    return ut



