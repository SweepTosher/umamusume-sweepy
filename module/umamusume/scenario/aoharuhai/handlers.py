import bot.base.log as logger
from bot.recog.image_matcher import image_match
from module.umamusume.asset.template import (
    UI_AOHARUHAI_RACE_1, UI_AOHARUHAI_RACE_2, UI_AOHARUHAI_RACE_3,
    UI_AOHARUHAI_RACE_4, UI_AOHARUHAI_RACE_5
)
from module.umamusume.asset.ui import (
    AOHARUHAI_RACE, AOHARUHAI_RACE_FINAL_START, AOHARUHAI_RACE_SELECT_OPPONENT,
    AOHARUHAI_RACE_INRACE, AOHARUHAI_RACE_END, AOHARUHAI_RACE_SCHEDULE
)

log = logger.get_logger(__name__)


def script_aoharuhai_race(ctx):
    img = ctx.ctrl.get_screen(to_gray=True)
    if image_match(img, UI_AOHARUHAI_RACE_1).find_match:
        race_index = 0
    elif image_match(img, UI_AOHARUHAI_RACE_2).find_match:
        race_index = 1
    elif image_match(img, UI_AOHARUHAI_RACE_3).find_match:
        race_index = 2
    elif image_match(img, UI_AOHARUHAI_RACE_4).find_match:
        race_index = 3
    elif image_match(img, UI_AOHARUHAI_RACE_5).find_match:
        race_index = 4
    else:
        ctx.ctrl.click(360, 1180, "Confirm race result")
        return
    
    ctx.cultivate_detail.turn_info.aoharu_race_index = race_index
    return


def script_aoharuhai_race_final_start(ctx):
    ctx.ctrl.click(360, 980, "Confirm final opponent")


def script_aoharuhai_race_select_oponent(ctx):
    return


def script_aoharuhai_race_inrace(ctx):
    ctx.ctrl.click(520, 1180, "View battle result")


def script_aoharuhai_race_end(ctx):
    ctx.ctrl.click(350, 1110, "Confirm race end")


def script_aoharuhai_race_schedule(ctx):
    ctx.ctrl.click(360, 1100, "End Youth Cup race")


def get_aoharuhai_ui_handlers():
    return {
        AOHARUHAI_RACE: script_aoharuhai_race,
        AOHARUHAI_RACE_FINAL_START: script_aoharuhai_race_final_start,
        AOHARUHAI_RACE_SELECT_OPPONENT: script_aoharuhai_race_select_oponent,
        AOHARUHAI_RACE_INRACE: script_aoharuhai_race_inrace,
        AOHARUHAI_RACE_END: script_aoharuhai_race_end,
        AOHARUHAI_RACE_SCHEDULE: script_aoharuhai_race_schedule,
    }
