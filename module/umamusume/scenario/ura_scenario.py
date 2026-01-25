import re
import cv2

DIGITS_ONLY = re.compile(r"\D")

from .base_scenario import BaseScenario
from module.umamusume.asset import *
from module.umamusume.define import ScenarioType, SupportCardFavorLevel, SupportCardType
from module.umamusume.types import SupportCardInfo
from bot.recog.image_matcher import image_match, compare_color_equal
from bot.recog.ocr import ocr_line, find_similar_text, ocr_digits
from bot.recog.training_stat_scanner import parse_training_result_template, scan_facility_stats

import bot.base.log as logger
log = logger.get_logger(__name__)


class URAScenario(BaseScenario):
    def __init__(self):
        super().__init__()

    def scenario_type(self) -> ScenarioType:
        return ScenarioType.SCENARIO_TYPE_URA

    def scenario_name(self) -> str:
        return "URA"

    def get_date_img(self, img: any) -> any:
        return img[41:65, 0:219]

    def get_turn_to_race_img(self, img: any) -> any:
        return img[99:158, 13:140]

    def parse_training_result(self, img: any) -> list[int]:
        return parse_training_result_template(img, scenario="ura")

    def parse_training_support_card(self, img: any) -> list[SupportCardInfo]:
        if img is None or getattr(img, 'size', 0) == 0:
            return []
        base_x = 590
        base_y = 190
        inc = 120
        w, h = 105, 110
        support_card_list_info_result: list[SupportCardInfo] = []

        for i in range(5):
            support_card_icon = img[base_y:base_y + h, base_x: base_x + w]

            # Check favor level
            support_card_icon = cv2.cvtColor(support_card_icon, cv2.COLOR_BGR2RGB)
            favor_process_check_list = [support_card_icon[95, 16], support_card_icon[95, 20]]
            support_card_favor_process = SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_UNKNOWN
            for support_card_favor_process_pos in favor_process_check_list:
                if compare_color_equal(support_card_favor_process_pos, [255, 235, 120]):
                    support_card_favor_process = SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_4
                elif compare_color_equal(support_card_favor_process_pos, [255, 173, 30]):
                    support_card_favor_process = SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_3
                elif compare_color_equal(support_card_favor_process_pos, [162, 230, 30]):
                    support_card_favor_process = SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_2
                elif compare_color_equal(support_card_favor_process_pos, [42, 192, 255]) or compare_color_equal(support_card_favor_process_pos, [109, 108, 117]):
                    support_card_favor_process = SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_1
                if support_card_favor_process != SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_UNKNOWN:
                    break

            # Check if there's an event
            support_card_event_pos = support_card_icon[5, 83]
            support_card_event_available = False
            if (support_card_event_pos[0] >= 250
                and 55 <= support_card_event_pos[1] <= 90
                and 115 <= support_card_event_pos[2] <= 150):
                support_card_event_available = True

            # Check support card type
            support_card_type = SupportCardType.SUPPORT_CARD_TYPE_UNKNOWN
            support_card_icon = cv2.cvtColor(support_card_icon, cv2.COLOR_RGB2GRAY)
            match_center = None
            for ref, t in (
                (REF_SUPPORT_CARD_TYPE_SPEED,SupportCardType.SUPPORT_CARD_TYPE_SPEED),
                (REF_SUPPORT_CARD_TYPE_STAMINA,SupportCardType.SUPPORT_CARD_TYPE_STAMINA),
                (REF_SUPPORT_CARD_TYPE_POWER,SupportCardType.SUPPORT_CARD_TYPE_POWER),
                (REF_SUPPORT_CARD_TYPE_WILL,SupportCardType.SUPPORT_CARD_TYPE_WILL),
                (REF_SUPPORT_CARD_TYPE_INTELLIGENCE,SupportCardType.SUPPORT_CARD_TYPE_INTELLIGENCE),
                (REF_SUPPORT_CARD_TYPE_FRIEND,SupportCardType.SUPPORT_CARD_TYPE_FRIEND),
            ):
                r = image_match(support_card_icon, ref)
                if getattr(r, "find_match", False):
                    support_card_type = t
                    match_center = getattr(r, "center_point", None)
                    break

            if support_card_type == SupportCardType.SUPPORT_CARD_TYPE_UNKNOWN and support_card_favor_process != SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_UNKNOWN:
                support_card_type = SupportCardType.SUPPORT_CARD_TYPE_NPC

            h_local, w_local = support_card_icon.shape[:2]
            cx = base_x + (w_local // 2)
            cy = base_y + (h_local // 2)
            if isinstance(match_center, (tuple, list)) and len(match_center) >= 2:
                cx = base_x + int(match_center[0])
                cy = base_y + int(match_center[1])

            info = SupportCardInfo(
                card_type=support_card_type,
                favor=support_card_favor_process,
                has_event=support_card_event_available
            )
            info.center = (cx, cy)
            support_card_list_info_result.append(info)

            base_y += inc

        unknown_count = sum(1 for sc in support_card_list_info_result if sc.favor == SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_UNKNOWN)
        if unknown_count == len(support_card_list_info_result) and len(support_card_list_info_result) > 0:
            return []
        return support_card_list_info_result