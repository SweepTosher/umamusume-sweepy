import re
import cv2
import time

from .base_scenario import BaseScenario
from module.umamusume.asset import *
from module.umamusume.define import ScenarioType, SupportCardFavorLevel, SupportCardType
from module.umamusume.types import SupportCardInfo
from bot.recog.image_matcher import image_match, compare_color_equal
from module.umamusume.asset.template import *
from bot.recog.ocr import ocr_line, find_similar_text, ocr_digits

import bot.base.log as logger
log = logger.get_logger(__name__)


class AoharuHaiScenario(BaseScenario):
    def __init__(self):
        super().__init__()

    def scenario_type(self) -> ScenarioType:
        return ScenarioType.SCENARIO_TYPE_AOHARUHAI

    def scenario_name(self) -> str:
        return "青春杯"

    def get_date_img(self, img: any) -> any:
        return img[40:70, 160:370]

    def get_turn_to_race_img(self, img) -> any:
        return img[70:120, 30:90]

    def parse_training_result(self, img: any) -> list[int]:
        # Use digital OCR to achieve higher accuracy
        sub_img_speed_incr = img[800:830, 30:140]
        sub_img_speed_incr = cv2.copyMakeBorder(sub_img_speed_incr, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=(255, 255, 255))
        speed_incr_text = ocr_digits(sub_img_speed_incr)
        speed_incr_text = re.sub("\\D", "", speed_incr_text)

        sub_img_speed_incr_extra = img[760:800, 30:140]
        sub_img_speed_incr_extra = cv2.copyMakeBorder(sub_img_speed_incr_extra, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=(255, 255, 255))
        speed_incr_extra_text = ocr_digits(sub_img_speed_incr_extra)
        speed_incr_extra_text = re.sub("\\D", "", speed_incr_extra_text)

        sub_img_stamina_incr = img[800:830, 140:250]
        sub_img_stamina_incr = cv2.copyMakeBorder(sub_img_stamina_incr, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=(255, 255, 255))
        stamina_incr_text = ocr_digits(sub_img_stamina_incr)
        stamina_incr_text = re.sub("\\D", "", stamina_incr_text)

        sub_img_stamina_incr_extra = img[760:800, 140:250]
        sub_img_stamina_incr_extra = cv2.copyMakeBorder(sub_img_stamina_incr_extra, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=(255, 255, 255))
        stamina_incr_extra_text = ocr_digits(sub_img_stamina_incr_extra)
        stamina_incr_extra_text = re.sub("\\D", "", stamina_incr_extra_text)

        sub_img_power_incr = img[800:830, 250:360]
        sub_img_power_incr = cv2.copyMakeBorder(sub_img_power_incr, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=(255, 255, 255))
        power_incr_text = ocr_digits(sub_img_power_incr)
        power_incr_text = re.sub("\\D", "", power_incr_text)

        sub_img_power_incr_extra = img[760:800, 250:360]
        sub_img_power_incr_extra = cv2.copyMakeBorder(sub_img_power_incr_extra, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=(255, 255, 255))
        power_incr_extra_text = ocr_digits(sub_img_power_incr_extra)
        power_incr_extra_text = re.sub("\\D", "", power_incr_extra_text)

        sub_img_will_incr = img[800:830, 360:470]
        sub_img_will_incr = cv2.copyMakeBorder(sub_img_will_incr, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=(255, 255, 255))
        will_incr_text = ocr_digits(sub_img_will_incr)
        will_incr_text = re.sub("\\D", "", will_incr_text)

        sub_img_will_incr_extra = img[760:800, 360:470]
        sub_img_will_incr_extra = cv2.copyMakeBorder(sub_img_will_incr_extra, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=(255, 255, 255))
        will_incr_extra_text = ocr_digits(sub_img_will_incr_extra)
        will_incr_extra_text = re.sub("\\D", "", will_incr_extra_text)

        sub_img_intelligence_incr = img[800:830, 470:580]
        sub_img_intelligence_incr = cv2.copyMakeBorder(sub_img_intelligence_incr, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=(255, 255, 255))
        intelligence_incr_text = ocr_digits(sub_img_intelligence_incr)
        intelligence_incr_text = re.sub("\\D", "", intelligence_incr_text)

        sub_img_intelligence_incr_extra = img[760:800, 470:580]
        sub_img_intelligence_incr_extra = cv2.copyMakeBorder(sub_img_intelligence_incr_extra, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=(255, 255, 255))
        intelligence_incr_extra_text = ocr_digits(sub_img_intelligence_incr_extra)
        intelligence_incr_extra_text = re.sub("\\D", "", intelligence_incr_extra_text)

        sub_img_skill_point_incr = img[800:830, 588:695]
        sub_img_skill_point_incr = cv2.copyMakeBorder(sub_img_skill_point_incr, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=(255, 255, 255))
        skill_point_incr_text = ocr_digits(sub_img_skill_point_incr)
        skill_point_incr_text = re.sub("\\D", "", skill_point_incr_text)

        sub_img_skill_point_incr_extra = img[760:800, 588:695]
        sub_img_skill_point_incr_extra = cv2.copyMakeBorder(sub_img_skill_point_incr_extra, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=(255, 255, 255))
        skill_point_incr_extra_text = ocr_digits(sub_img_skill_point_incr_extra)
        skill_point_incr_extra_text = re.sub("\\D", "", skill_point_incr_extra_text)

        speed_icr = (0 if speed_incr_text == "" else int(speed_incr_text)) + (0 if speed_incr_extra_text == "" else int(speed_incr_extra_text))
        stamina_incr = (0 if stamina_incr_text == "" else int(stamina_incr_text)) + (0 if stamina_incr_extra_text == "" else int(stamina_incr_extra_text))
        power_incr = (0 if power_incr_text == "" else int(power_incr_text)) + (0 if power_incr_extra_text == "" else int(power_incr_extra_text))
        will_incr = (0 if will_incr_text == "" else int(will_incr_text)) + (0 if will_incr_extra_text == "" else int(will_incr_extra_text))
        intelligence_incr = (0 if intelligence_incr_text == "" else int(intelligence_incr_text)) + (0 if intelligence_incr_extra_text == "" else int(intelligence_incr_extra_text))
        skill_point_incr = (0 if skill_point_incr_text == "" else int(skill_point_incr_text)) + (0 if skill_point_incr_extra_text == "" else int(skill_point_incr_extra_text))

        return [speed_icr, stamina_incr, power_incr, will_incr, intelligence_incr, skill_point_incr]

    def parse_training_support_card(self, img: any) -> list[SupportCardInfo]:
        base_x = 550
        base_y = 177
        inc = 115
        support_card_list_info_result: list[SupportCardInfo] = []

        
        for i in range(5):
            roi = img[base_y:base_y + inc, base_x: base_x + 145]
            if roi is None or getattr(roi, 'size', 0) == 0:
                base_y += inc
                continue

            roi_gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            ay1 = 0
            ay2 = 37
            ax1 = 116
            ax2 = 141
            arrow_roi = roi_gray[ay1:ay2, ax1:ax2]

            arrow_roi3 = roi_gray[max(ay1 - 10, 0):ay2, ax1:ax2]

            can_incr_special_training = False
            for ref, sub_roi in (
                (REF_AOHARU_SPECIAL_TRAIN, arrow_roi),
                (REF_AOHARU_SPECIAL_TRAIN2, arrow_roi),
                (REF_AOHARU_SPECIAL_TRAIN3, arrow_roi3),
            ):
                try:
                    if image_match(sub_roi, ref).find_match:
                        can_incr_special_training = True
                        break
                except Exception:
                    pass

            spirit_explosion = False
            if not can_incr_special_training:
                for ref, sub_roi in (
                    (REF_SPIRIT_EXPLOSION, arrow_roi),
                    (REF_SPIRIT_EXPLOSION2, arrow_roi),
                    (REF_SPIRIT_EXPLOSION3, arrow_roi3),
                ):
                    try:
                        if image_match(sub_roi, ref).find_match:
                            spirit_explosion = True
                            break
                    except Exception:
                        pass

            # Favor detection (color)
            roi_rgb = cv2.cvtColor(roi, cv2.COLOR_BGR2RGB)
            favor_process_check_list = [roi_rgb[106, 56], roi_rgb[106, 60]]
            support_card_favor_process = SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_UNKNOWN
            for pix in favor_process_check_list:
                if compare_color_equal(pix, [255, 235, 120]):
                    support_card_favor_process = SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_4
                elif compare_color_equal(pix, [255, 173, 30]):
                    support_card_favor_process = SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_3
                elif compare_color_equal(pix, [162, 230, 30]):
                    support_card_favor_process = SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_2
                elif (compare_color_equal(pix, [42, 192, 255]) or compare_color_equal(pix, [109, 108, 117])):
                    support_card_favor_process = SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_1
                if support_card_favor_process != SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_UNKNOWN:
                    break

            # Support card type (template match for type icon only)
            support_card_type = SupportCardType.SUPPORT_CARD_TYPE_UNKNOWN
            match_center = None
            for ref, t in (
                (REF_SUPPORT_CARD_TYPE_SPEED, SupportCardType.SUPPORT_CARD_TYPE_SPEED),
                (REF_SUPPORT_CARD_TYPE_STAMINA, SupportCardType.SUPPORT_CARD_TYPE_STAMINA),
                (REF_SUPPORT_CARD_TYPE_POWER, SupportCardType.SUPPORT_CARD_TYPE_POWER),
                (REF_SUPPORT_CARD_TYPE_WILL, SupportCardType.SUPPORT_CARD_TYPE_WILL),
                (REF_SUPPORT_CARD_TYPE_INTELLIGENCE, SupportCardType.SUPPORT_CARD_TYPE_INTELLIGENCE),
                (REF_SUPPORT_CARD_TYPE_FRIEND, SupportCardType.SUPPORT_CARD_TYPE_FRIEND),
            ):
                r = image_match(roi_gray, ref)
                if r.find_match:
                    support_card_type = t
                    match_center = r.center_point
                    break

            if support_card_type == SupportCardType.SUPPORT_CARD_TYPE_UNKNOWN and support_card_favor_process != SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_UNKNOWN:
                support_card_type = SupportCardType.SUPPORT_CARD_TYPE_NPC

            h_local, w_local = roi.shape[:2]
            cx = base_x + (w_local // 2)
            cy = base_y + (h_local // 2)
            if isinstance(match_center, (tuple, list)) and len(match_center) >= 2:
                cx = base_x + int(match_center[0])
                cy = base_y + int(match_center[1])

            name_map = {
                SupportCardType.SUPPORT_CARD_TYPE_SPEED: "support_card_type_speed",
                SupportCardType.SUPPORT_CARD_TYPE_STAMINA: "support_card_type_stamina",
                SupportCardType.SUPPORT_CARD_TYPE_POWER: "support_card_type_power",
                SupportCardType.SUPPORT_CARD_TYPE_WILL: "support_card_type_will",
                SupportCardType.SUPPORT_CARD_TYPE_INTELLIGENCE: "support_card_type_intelligence",
                SupportCardType.SUPPORT_CARD_TYPE_FRIEND: "support_card_type_friend",
            }
            info = SupportCardInfo(
                name=name_map.get(support_card_type, "support_card"),
                card_type=support_card_type,
                favor=support_card_favor_process,
                can_incr_special_training=can_incr_special_training,
                spirit_explosion=spirit_explosion
            )
            info.center = (cx, cy)
            support_card_list_info_result.append(info)

            base_y += inc

        return support_card_list_info_result



def aoharu_train_not_full(support_card_icon) -> bool:
    support_card_icon = cv2.cvtColor(support_card_icon, cv2.COLOR_BGR2RGB)
    avatar_region_x_start = 5
    avatar_region_x_end = 45
    avatar_region_y_start = 70
    avatar_region_y_end = 110

    avatar_region = support_card_icon[avatar_region_y_start:avatar_region_y_end, avatar_region_x_start:avatar_region_x_end]

    total_pixels = avatar_region.shape[0] * avatar_region.shape[1]
    if total_pixels == 0:
        return False

    # Detect gray
    grey_lower = [100, 100, 100]
    grey_upper = [150, 150, 150]
    grey_pixels = 0

    for y in range(avatar_region.shape[0]):
        for x in range(avatar_region.shape[1]):
            pixel = avatar_region[y, x]
            if (grey_lower[0] <= pixel[0] <= grey_upper[0] and
                grey_lower[1] <= pixel[1] <= grey_upper[1] and
                grey_lower[2] <= pixel[2] <= grey_upper[2]):
                grey_pixels += 1

    grey_ratio = grey_pixels / total_pixels

    if grey_ratio > 0.05:
        status = True
    else:
        status = False

    return status
