
from __future__ import annotations
from typing import TYPE_CHECKING

from module.umamusume.define import *
import bot.base.log as logger

if TYPE_CHECKING:
    from module.umamusume.scenario import base_scenario

log = logger.get_logger(__name__)

class SupportCardInfo:
    name: str
    card_type: SupportCardType
    favor: SupportCardFavorLevel
    has_event: bool
    # Youth Cup section
    can_incr_special_training: bool
    spirit_explosion: bool

    def __init__(self,
                name: str = "support_card",
                card_type: SupportCardType = SupportCardType.SUPPORT_CARD_TYPE_UNKNOWN,
                favor: SupportCardFavorLevel = SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_UNKNOWN,
                has_event: bool = False,
                can_incr_special_training: bool = False,
                spirit_explosion: bool = False,
                center: tuple[int, int] | None = None):
        self.name = name
        self.card_type = card_type
        self.favor = favor
        self.has_event = has_event
        self.can_incr_special_training = can_incr_special_training
        self.spirit_explosion = spirit_explosion
        self.center = center


class TrainingInfo:
    support_card_info_list: list[SupportCardInfo]
    speed_incr: int
    stamina_incr: int
    power_incr: int
    will_incr: int
    intelligence_incr: int
    skill_point_incr: int
    failure_rate: int
    # not maxxed or rainbow
    relevant_count: int

    def __init__(self):
        self.speed_incr = 0
        self.stamina_incr = 0
        self.power_incr = 0
        self.will_incr = 0
        self.intelligence_incr = 0
        self.skill_point_incr = 0
        self.failure_rate = -1
        self.support_card_info_list = []
        self.relevant_count = 0

    def log_training_info(self, scenario_type: ScenarioType):
        #useless for now
        return


class UmaAttribute:
    speed: int
    stamina: int
    power: int
    will: int
    intelligence: int
    skill_point: int

    def __init__(self):
        self.speed = 0
        self.stamina = 0
        self.power = 0
        self.will = 0
        self.intelligence = 0
        self.skill_point = 0


class TurnOperation:
    turn_operation_type: TurnOperationType
    turn_operation_type_replace: TurnOperationType
    training_type: TrainingType
    race_id: int

    def __init__(self):
        self.turn_operation_type = TurnOperationType.TURN_OPERATION_TYPE_UNKNOWN
        self.turn_operation_type_replace = TurnOperationType.TURN_OPERATION_TYPE_UNKNOWN
        self.training_type = TrainingType.TRAINING_TYPE_UNKNOWN
        self.race_id = 0

    def log_turn_operation(self):
        log.info("Current turn operation: %s", self.turn_operation_type.name)
        log.info("Current turn alternative operation: %s", self.turn_operation_type_replace.name)
        if self.turn_operation_type == TurnOperationType.TURN_OPERATION_TYPE_TRAINING:
            log.info("Training type: %s", self.training_type.name)


class TurnInfo:
    date: int

    parse_train_info_finish: bool
    training_info_list: list[TrainingInfo]
    parse_main_menu_finish: bool
    uma_attribute: UmaAttribute
    remain_stamina: int
    motivation_level: MotivationLevel
    medic_room_available: bool
    race_available: bool

    turn_operation: TurnOperation | None
    turn_info_logged: bool
    turn_learn_skill_done: bool

    # Youth Cup
    aoharu_race_index: int

    def __init__(self):
        self.date = -1
        self.parse_train_info_finish = False
        self.training_info_list = [TrainingInfo(), TrainingInfo(), TrainingInfo(), TrainingInfo(), TrainingInfo()]
        self.parse_main_menu_finish = False
        self.uma_attribute = UmaAttribute()
        self.remain_stamina = -1
        self.motivation_level = MotivationLevel.MOTIVATION_LEVEL_UNKNOWN
        self.medic_room_available = False
        self.race_available = False
        self.turn_operation = None
        self.turn_info_logged = False
        self.turn_learn_skill_done = False
        self.aoharu_race_index = 0

    def log_turn_info(self, scenario_type: ScenarioType):
        log.info("Current turn time " + str(self.date))
        log.info(
            "Current attribute values Speed: %s, Stamina: %s, Power: %s, Guts: %s, Wit: %s, Skill Points: %s",
            self.uma_attribute.speed,
            self.uma_attribute.stamina,
            self.uma_attribute.power,
            self.uma_attribute.will,
            self.uma_attribute.intelligence,
            self.uma_attribute.skill_point,
        )
        log.info("Speed training results:")
        self.training_info_list[0].log_training_info(scenario_type)
        log.info("Stamina training results:")
        self.training_info_list[1].log_training_info(scenario_type)
        log.info("Power training results:")
        self.training_info_list[2].log_training_info(scenario_type)
        log.info("Guts training results:")
        self.training_info_list[3].log_training_info(scenario_type)
        log.info("Wit training results:")
        self.training_info_list[4].log_training_info(scenario_type)


class CultivateContextDetail:
    turn_info: TurnInfo | None
    turn_info_history: list[TurnInfo]
    scenario : "base_scenario.BaseScenario"
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
    motivation_threshold_year1: int
    motivation_threshold_year2: int
    motivation_threshold_year3: int
    prioritize_recreation: bool
    pal_name: str
    pal_thresholds: list
    pal_friendship_score: list[float]
    pal_card_multiplier: float

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
        self.debut_race_win = False
        self.clock_use_limit = 0
        self.clock_used = 0
        self.allow_recover_tp = False
        self.parse_factor_done = False
        self.extra_weight = []
        self.spirit_explosion = [0.16, 0.16, 0.16, 0.06, 0.11]
        self.motivation_threshold_year1 = 3  # Default values
        self.motivation_threshold_year2 = 4
        self.motivation_threshold_year3 = 4
        self.prioritize_recreation = False
        self.pal_name = ""
        self.pal_thresholds = []
        self.pal_friendship_score = [0.08, 0.057, 0.018]
        self.pal_card_multiplier = 0.1

    def reset_skill_learn(self):
        self.learn_skill_done = False
        self.learn_skill_selected = False
