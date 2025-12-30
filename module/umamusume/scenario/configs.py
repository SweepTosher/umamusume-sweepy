class UraConfig:
    skill_event_weight: list[int]
    reset_skill_event_weight_list: list[str]

    def __init__(self, config: dict):
        se = config.get("skillEventWeight", config.get("skill_event_weight"))
        rs = config.get("resetSkillEventWeightList", config.get("reset_skill_event_weight_list"))
        if se is None or rs is None:
            raise ValueError("Wrong configuration: must configure 'skillEventWeight'/'skill_event_weight' and 'resetSkillEventWeightList'/'reset_skill_event_weight_list'")
        self.skill_event_weight = se
        self.reset_skill_event_weight_list = rs
    
    def removeSkillFromList(self, skill: str):
        if skill in self.reset_skill_event_weight_list:
            self.reset_skill_event_weight_list.remove(skill)
            # If skill list is empty, reset weights
            # If the list is empty from the beginning, this branch won't trigger, and weights won't be reset
            if len(self.reset_skill_event_weight_list) == 0:
                self.skill_event_weight = [0, 0, 0]
    
    def getSkillEventWeight(self, date: int) -> int:
        if date <= 24:
            return self.skill_event_weight[0]
        elif date <= 48:
            return self.skill_event_weight[1]
        else:
            return self.skill_event_weight[2]

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
    
class ScenarioConfig:
    """ Configuration for all scenarios """
    ura_config: UraConfig = None
    aoharu_config: AoharuConfig = None
    
    def __init__(self, ura_config: UraConfig = None, aoharu_config: AoharuConfig = None):
        self.ura_config = ura_config
        self.aoharu_config = aoharu_config
