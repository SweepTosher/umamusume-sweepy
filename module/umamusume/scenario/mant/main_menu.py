import cv2
import re

from bot.recog.image_matcher import image_match
from bot.recog.ocr import ocr_line
from module.umamusume.asset.template import REF_MANT_ON_SALE
import bot.base.log as logger

log = logger.get_logger(__name__)

COIN_ROI_NORMAL = (1172, 1197, 402, 500)
COIN_ROI_SUMMER = (1172, 1199, 321, 417)
COIN_ROI_CLIMAX = (1125, 1148, 565, 654)

RIVAL_COLOR_1 = (0x4E, 0xFF, 0xFF)
RIVAL_COLOR_2 = (0x30, 0xAD, 0xEB)
RIVAL_TOLERANCE = 5


def read_shop_coins(img, is_summer, is_climax):
    if is_climax:
        y1, y2, x1, x2 = COIN_ROI_CLIMAX
    elif is_summer:
        y1, y2, x1, x2 = COIN_ROI_SUMMER
    else:
        y1, y2, x1, x2 = COIN_ROI_NORMAL
    roi = img[y1:y2, x1:x2]
    text = ocr_line(roi, lang="en")
    digits = re.sub(r'[^0-9]', '', text)
    if digits:
        return int(digits)
    return -1


def handle_mant_turn_start(ctx, current_date):
    from module.umamusume.scenario.mant.shop import is_shop_scan_turn
    if is_shop_scan_turn(current_date):
        ctx.cultivate_detail.mant_shop_items = []


def handle_mant_shop_scan(ctx, current_date):
    if ctx.cultivate_detail.mant_shop_scanned_this_turn:
        return False
    from module.umamusume.scenario.mant.shop import (
        is_shop_scan_turn, scan_mant_shop, buy_shop_items,
        SHOP_ITEM_COSTS, SLUG_TO_DISPLAY, display_to_slug
    )
    if is_shop_scan_turn(current_date):
        items_list, ratio, drag_ratio, first_item_gy = scan_mant_shop(ctx)
        ctx.cultivate_detail.mant_shop_items = items_list
        ctx.cultivate_detail.mant_shop_ratio = ratio
        ctx.cultivate_detail.mant_shop_drag_ratio = drag_ratio
        ctx.cultivate_detail.mant_shop_first_gy = first_item_gy
        ctx.cultivate_detail.mant_shop_scanned_this_turn = True

        bought = False
        mant_cfg = getattr(ctx.task.detail.scenario_config, 'mant_config', None)
        if mant_cfg and mant_cfg.item_tiers:
            tier1_slugs = [slug for slug, tier in mant_cfg.item_tiers.items() if tier == 1]
            shop_names = [name for name, _, _ in items_list]
            shop_slugs = [display_to_slug(n) for n in shop_names]
            targets = []
            for slug in tier1_slugs:
                if slug in shop_slugs:
                    display = SLUG_TO_DISPLAY.get(slug)
                    if display:
                        cost = SHOP_ITEM_COSTS.get(display, 9999)
                        if cost <= ctx.cultivate_detail.mant_coins:
                            targets.append(display)
            if targets:
                bought = buy_shop_items(ctx, targets, items_list, ratio, drag_ratio, first_item_gy)

        if not bought:
            from module.umamusume.scenario.mant.shop import BACK_BTN_X, BACK_BTN_Y
            import time as t
            ctx.ctrl.click(BACK_BTN_X, BACK_BTN_Y)
            t.sleep(1)

        ctx.cultivate_detail.turn_info.parse_main_menu_finish = False
        return True
    return False


def handle_mant_on_sale(img):
    img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    sale_result = image_match(img_gray, REF_MANT_ON_SALE)
    if sale_result.find_match:
        log.info("shop on sale")


def handle_mant_afflictions(ctx, img):
    from module.umamusume.constants.game_constants import is_summer_camp_period
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    current_date = getattr(ctx.cultivate_detail.turn_info, 'date', 0)
    if is_summer_camp_period(current_date):
        medic_px = img_rgb[1118, 100]
    else:
        medic_px = img_rgb[1125, 40]
    medic_lit = medic_px[0] > 200 and medic_px[1] > 200 and medic_px[2] > 200
    if not medic_lit:
        ctx.cultivate_detail.mant_afflictions = []
        return False
    if medic_lit and not ctx.cultivate_detail.mant_afflictions:
        from module.umamusume.scenario.mant.afflictions import detect_afflictions
        afflictions = detect_afflictions(ctx)
        ctx.cultivate_detail.mant_afflictions = afflictions
        ctx.cultivate_detail.turn_info.parse_main_menu_finish = False
        return True
    return False


def color_match(px, target, tol):
    return (abs(int(px[0]) - target[0]) <= tol and
            abs(int(px[1]) - target[1]) <= tol and
            abs(int(px[2]) - target[2]) <= tol)


def handle_mant_rival_race(ctx, img):
    if getattr(ctx.cultivate_detail.turn_info, 'mant_rival_checked', False):
        return
    from module.umamusume.constants.game_constants import is_summer_camp_period
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    current_date = getattr(ctx.cultivate_detail.turn_info, 'date', 0)
    rival_x = 497 if is_summer_camp_period(current_date) else 565
    px = img_rgb[1089, rival_x]
    if color_match(px, RIVAL_COLOR_1, RIVAL_TOLERANCE) or color_match(px, RIVAL_COLOR_2, RIVAL_TOLERANCE):
        log.info("rival race detected")
    ctx.cultivate_detail.turn_info.mant_rival_checked = True
