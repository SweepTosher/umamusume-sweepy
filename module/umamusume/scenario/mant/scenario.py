import cv2

from module.umamusume.scenario.ura_scenario import URAScenario
from module.umamusume.scenario.registry import register
from module.umamusume.asset import *
from module.umamusume.define import ScenarioType, SupportCardFavorLevel, SupportCardType
from module.umamusume.types import SupportCardInfo
from bot.recog.image_matcher import image_match, compare_color_equal
from bot.recog.training_stat_scanner import parse_training_result_template
from .handlers import get_mant_ui_handlers
from .hooks import mant_after_hook


import bot.base.log as logger
log = logger.get_logger(__name__)

STAT_AREAS_MANT = {
    "speed": (30, 770, 140, 826),
    "stamina": (140, 770, 250, 826),
    "power": (250, 770, 360, 826),
    "guts": (360, 770, 470, 826),
    "wits": (470, 770, 580, 826),
    "sp": (588, 770, 695, 826),
}

@register(ScenarioType.SCENARIO_TYPE_MANT)
class MANTScenario(URAScenario):
    def __init__(self):
        super().__init__()

    def scenario_type(self) -> ScenarioType:
        return ScenarioType.SCENARIO_TYPE_MANT

    def scenario_name(self) -> str:
        return "MANT"

    def get_date_img(self, img):
        return img[41:65, 0:219]

    def get_turn_to_race_img(self, img):
        return img[99:158, 13:140]

    def get_stat_areas(self) -> dict:
        return STAT_AREAS_MANT

    def parse_training_result(self, img) -> list[int]:
        return parse_training_result_template(img, scenario="ura")

    def get_ui_handlers(self) -> dict:
        return get_mant_ui_handlers()

    def after_hook(self, ctx, img):
        return mant_after_hook(ctx, img)

    def compute_scenario_bonuses(self, ctx, idx, support_card_info_list, date, period_idx, current_energy):
        return (0.0, 1.0, [], [])
