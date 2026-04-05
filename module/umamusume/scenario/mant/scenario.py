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
from .constants import MANT_FIXED_EVENTS


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

def get_incoming_energy(current_turn, lookahead=1):
    total = 0
    for data in MANT_FIXED_EVENTS.values():
        if current_turn < data["turn"] <= current_turn + lookahead:
            total += data["effect"].get("energy", 0)
    return total

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
        additive = 0.0
        multiplier = 1.0
        formula_parts = []
        mult_parts = []

        if current_energy is None:
            return (additive, multiplier, formula_parts, mult_parts)

        incoming = get_incoming_energy(date, lookahead=1)
        if incoming <= 0:
            return (additive, multiplier, formula_parts, mult_parts)

        til = ctx.cultivate_detail.turn_info.training_info_list[idx]
        energy_change_val = getattr(til, 'energy_change', 0.0)

        from module.umamusume.constants.scoring_constants import DEFAULT_SCORE_VALUE
        sv = getattr(ctx.cultivate_detail, 'score_value', DEFAULT_SCORE_VALUE)
        try:
            w_energy_change = sv[period_idx][2]
        except Exception:
            w_energy_change = 0.006

        max_energy = getattr(ctx.cultivate_detail, 'mant_max_energy', 100)
        overflow_without = max(0, current_energy + incoming - max_energy)
        overflow_with = max(0, (current_energy + energy_change_val) + incoming - max_energy)
        wasted_diff = overflow_with - overflow_without

        if wasted_diff != 0:
            penalty = wasted_diff * w_energy_change
            additive += penalty
            formula_parts.append(f"nrg_event(+{incoming},overflow:{wasted_diff:+.0f}):{penalty:+.3f}")

        return (additive, multiplier, formula_parts, mult_parts)
