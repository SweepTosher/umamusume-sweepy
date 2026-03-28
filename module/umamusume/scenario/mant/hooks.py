import bot.base.log as logger

log = logger.get_logger(__name__)


def mant_after_hook(ctx, img):
    from module.umamusume.context import detected_portraits_log
    from module.umamusume.persistence import set_ignore_cat_food, set_ignore_grilled_carrots

    favor = detected_portraits_log.get("President Akikawa", {}).get("favor", 0)
    if favor >= 3:
        set_ignore_cat_food(True)

    all_rainbow = True
    for info in detected_portraits_log.values():
        if not info.get('is_npc', False):
            if info.get('favor', 0) < 4:
                all_rainbow = False
                break
    if all_rainbow and detected_portraits_log:
        set_ignore_grilled_carrots(True)

    try:
        from module.umamusume.scenario.mant.race_reward_items import check_and_detect_race_reward_items
        screen = getattr(ctx, 'current_screen', None)
        if screen is not None:
            check_and_detect_race_reward_items(screen, img)
    except Exception:
        pass

    return False

