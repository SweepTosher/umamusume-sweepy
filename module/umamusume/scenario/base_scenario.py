from abc import ABC, abstractmethod
from module.umamusume.define import ScenarioType
from module.umamusume.types import SupportCardInfo

class BaseScenario(ABC):
    def __init__(self):
        super().__init__()
    
    @abstractmethod
    def scenario_type(self) -> ScenarioType:
        pass

    @abstractmethod
    def scenario_name(self) -> str:
        pass

    @abstractmethod
    def get_date_img(self, img):
        pass

    @abstractmethod
    def get_turn_to_race_img(self, img):
        pass

    @abstractmethod
    def parse_training_result(self, img) -> list[int]:
        pass

    @abstractmethod
    def parse_training_support_card(self, img) -> list[SupportCardInfo]:
        pass

    @abstractmethod
    def get_stat_areas(self) -> dict:
        pass

    def get_ui_handlers(self) -> dict:
        return {}

    def after_hook(self, ctx, img):
        pass

    def compute_scenario_bonuses(self, ctx, idx, support_card_info_list, date, period_idx, current_energy):
        return (0.0, 1.0, [], [])
