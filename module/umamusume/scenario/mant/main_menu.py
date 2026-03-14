import cv2

from bot.recog.image_matcher import image_match
from module.umamusume.asset.template import REF_MANT_ON_SALE
import bot.base.log as logger

log = logger.get_logger(__name__)

RIVAL_COLOR_1 = (0x4E, 0xFF, 0xFF)
RIVAL_COLOR_2 = (0x30, 0xAD, 0xEB)
RIVAL_TOLERANCE = 5


def handle_mant_turn_start(ctx, current_date):
    from module.umamusume.scenario.mant.shop import is_shop_scan_turn
    if is_shop_scan_turn(current_date):
        ctx.cultivate_detail.mant_shop_items = []


def handle_mant_shop_scan(ctx, current_date):
    if ctx.cultivate_detail.mant_shop_scanned_this_turn:
        return False
    from module.umamusume.scenario.mant.shop import is_shop_scan_turn, scan_mant_shop
    if is_shop_scan_turn(current_date):
        items = scan_mant_shop(ctx)
        ctx.cultivate_detail.mant_shop_items = items
        ctx.cultivate_detail.mant_shop_scanned_this_turn = True
        ctx.cultivate_detail.turn_info.parse_main_menu_finish = False
        return True
    return False


def handle_mant_on_sale(img):
    img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    sale_result = image_match(img_gray, REF_MANT_ON_SALE)
    if sale_result.find_match:
        log.info("shop on sale")


def handle_mant_afflictions(ctx, img):
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
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
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    px = img_rgb[1089, 565]
    if color_match(px, RIVAL_COLOR_1, RIVAL_TOLERANCE) or color_match(px, RIVAL_COLOR_2, RIVAL_TOLERANCE):
        log.info("rival race detected")
    ctx.cultivate_detail.turn_info.mant_rival_checked = True
