class AoharuConfig:

    preliminary_round_selections: list[int]
    aoharu_team_name_selection: int

    def __init__(self, config: dict):
        prs = config.get("preliminaryRoundSelections", config.get("preliminary_round_selections"))
        team = config.get("aoharuTeamNameSelection", config.get("aoharu_team_name_selection"))
        if prs is None or team is None:
            raise ValueError("Wrong configuration: must configure 'preliminaryRoundSelections'/'preliminary_round_selections' and 'aoharuTeamNameSelection'/'aoharu_team_name_selection'")
        self.preliminary_round_selections = prs
        self.aoharu_team_name_selection = team

    """ Get opponent index for specified round, index starts from 0, preliminary round 1 is 0 """
    def get_opponent(self, round_index: int) -> int:
        if round_index < 0 or round_index >= len(self.preliminary_round_selections):
            raise IndexError("Round index out of range")
        return self.preliminary_round_selections[round_index]
    
class MantConfig:
    item_tiers: dict
    tier_count: int
    whistle_threshold: int
    whistle_focus_summer: bool
    focus_summer_classic: int
    focus_summer_senior: int
    mega_small_threshold: int
    mega_medium_threshold: int
    mega_large_threshold: int
    training_weights_threshold: int
    bbq_unmaxxed_cards: int
    charm_threshold: int
    charm_failure_rate: int
    tier_thresholds: dict
    skip_race_percentile: int
    mega_race_penalty: int
    mega_summer_bonus: int

    def __init__(self, config: dict):
        self.item_tiers = config.get("item_tiers", {})
        self.tier_count = config.get("tier_count", 1)
        self.whistle_threshold = config.get("whistle_threshold", 20)
        self.whistle_focus_summer = config.get("whistle_focus_summer", True)
        self.focus_summer_classic = config.get("focus_summer_classic", 20)
        self.focus_summer_senior = config.get("focus_summer_senior", 10)
        self.mega_small_threshold = config.get("mega_small_threshold", 60)
        self.mega_medium_threshold = config.get("mega_medium_threshold", 70)
        self.mega_large_threshold = config.get("mega_large_threshold", 80)
        self.mega_race_penalty = config.get("mega_race_penalty", 5)
        self.mega_summer_bonus = config.get("mega_summer_bonus", 10)
        self.training_weights_threshold = config.get("training_weights_threshold", 60)
        self.bbq_unmaxxed_cards = config.get("bbq_unmaxxed_cards", 3)
        self.charm_threshold = config.get("charm_threshold", 70)
        self.charm_failure_rate = config.get("charm_failure_rate", 30)
        raw_thresholds = config.get("tier_thresholds", {})
        self.tier_thresholds = {int(k): v for k, v in raw_thresholds.items()}
        self.skip_race_percentile = config.get("skip_race_percentile", 81)


class ScenarioConfig:
    aoharu_config: AoharuConfig = None
    mant_config: MantConfig = None
    skill_event_weight: list = None
    reset_skill_event_weight_list: list = None
    
    def __init__(self, aoharu_config: AoharuConfig = None, mant_config: MantConfig = None,
                 skill_event_weight=None, reset_skill_event_weight_list=None):
        self.aoharu_config = aoharu_config
        self.mant_config = mant_config
        self.skill_event_weight = skill_event_weight if skill_event_weight is not None else [0, 0, 0]
        self.reset_skill_event_weight_list = reset_skill_event_weight_list if reset_skill_event_weight_list is not None else []

    def removeSkillFromResetList(self, skill: str):
        if skill in self.reset_skill_event_weight_list:
            self.reset_skill_event_weight_list.remove(skill)
            if len(self.reset_skill_event_weight_list) == 0:
                self.skill_event_weight = [0, 0, 0]

    def getSkillEventWeight(self, date: int) -> int:
        if date <= 24:
            return self.skill_event_weight[0]
        elif date <= 48:
            return self.skill_event_weight[1]
        else:
            return self.skill_event_weight[2]
