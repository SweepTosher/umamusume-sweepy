from module.umamusume.context import UmamusumeContext
from module.umamusume.types import SupportCardInfo, TurnInfo
from module.umamusume.define import TrainingType, SupportCardType, SupportCardFavorLevel
from module.umamusume.context import logger
DEFAULT = 0

import bot.base.log as logger
log = logger.get_logger(__name__)
def get_support_card_score(ctx: UmamusumeContext, info: SupportCardInfo):
    # log.info(f"SupportCard type: {info.card_type}")
    if info.name in SCORE_DICT[info.card_type]:
        score = SCORE_DICT[info.card_type][info.name](ctx, info)
    else:
        score = SCORE_DICT[info.card_type][DEFAULT](ctx, info)

    if getattr(info, 'can_incr_special_training', False):
        date = ctx.cultivate_detail.turn_info.date
        sv = getattr(ctx.cultivate_detail, 'score_value', [
            [0.11, 0.10, 0.01, 0.09],
            [0.11, 0.10, 0.09, 0.09],
            [0.11, 0.10, 0.12, 0.09],
            [0.03, 0.05, 0.15, 0.09],
            [0, 0, 0.27, 0, 0]
        ])
        special_defaults = [0.095, 0.095, 0.095, 0.095, 0]
        try:
            if date <= 24:
                period_idx = 0
            elif date <= 48:
                period_idx = 1
            elif date <= 60:
                period_idx = 2
            elif date <= 72:
                period_idx = 3
            else:
                period_idx = 4
            arr = sv[period_idx]
            if isinstance(arr, (list, tuple)) and len(arr) > 4:
                special_score = arr[4]
            else:
                special_score = special_defaults[period_idx]
        except Exception:
            special_score = special_defaults[0]
        score += special_score
    return score


def non_max_weight(date: int) -> float:
    if date <= 36:
        return 0.04
    elif date <= 64:
        return 0.03
    return 0.01


def default_speed_support_card_score(ctx: UmamusumeContext, info: SupportCardInfo) -> float:
    if (info.favor == SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_3 or
            info.favor == SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_4):
        return 0.01
    base = non_max_weight(ctx.cultivate_detail.turn_info.date)
    if info.favor == SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_1:
        base += 0.01
    return base


def default_stamina_support_card_score(ctx: UmamusumeContext, info: SupportCardInfo) -> float:
    if (info.favor == SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_3 or
            info.favor == SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_4):
        return 0.01
    base = non_max_weight(ctx.cultivate_detail.turn_info.date)
    if info.favor == SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_1:
        base += 0.01
    return base


def default_power_support_card_score(ctx: UmamusumeContext, info: SupportCardInfo) -> float:
    if (info.favor == SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_3 or
            info.favor == SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_4):
        return 0.01
    base = non_max_weight(ctx.cultivate_detail.turn_info.date)
    if info.favor == SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_1:
        base += 0.01
    return base


def default_will_support_card_score(ctx: UmamusumeContext, info: SupportCardInfo) -> float:
    if (info.favor == SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_3 or
            info.favor == SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_4):
        return 0.01
    base = non_max_weight(ctx.cultivate_detail.turn_info.date)
    if info.favor == SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_1:
        base += 0.01
    return base - 0.001


def default_intelligence_support_card_score(ctx: UmamusumeContext, info: SupportCardInfo) -> float:
    if (info.favor == SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_3 or
            info.favor == SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_4):
        return 0.01
    base = non_max_weight(ctx.cultivate_detail.turn_info.date)
    if info.favor == SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_1:
        base += 0.01
    return base + 0.001


def default_friend_support_card_score(ctx: UmamusumeContext, info: SupportCardInfo) -> float:
    if (info.favor == SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_3 or
            info.favor == SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_4):
        return 0.01
    base = non_max_weight(ctx.cultivate_detail.turn_info.date)
    if info.favor == SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_1:
        base += 0.01
    return base


def default_npc_support_card_score(ctx: UmamusumeContext, info: SupportCardInfo) -> float:
    if (info.favor == SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_3 or
            info.favor == SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_4):
        return 0.01
    base = non_max_weight(ctx.cultivate_detail.turn_info.date)
    if info.favor == SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_1:
        base += 0.01
    return base


def default_group_support_card_score(ctx: UmamusumeContext, info: SupportCardInfo) -> float:
    if (info.favor == SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_3 or
            info.favor == SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_4):
        return 0.01
    base = non_max_weight(ctx.cultivate_detail.turn_info.date)
    if info.favor == SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_1:
        base += 0.01
    return base


def default_unknown_support_card_score(ctx: UmamusumeContext, info: SupportCardInfo) -> float:
    if (info.favor == SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_3 or
            info.favor == SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_4):
        return 0.01
    base = non_max_weight(ctx.cultivate_detail.turn_info.date)
    if info.favor == SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_1:
        base += 0.01
    return base

SCORE_DICT: dict = {
    SupportCardType.SUPPORT_CARD_TYPE_SPEED: {
        DEFAULT: default_speed_support_card_score
    },
    SupportCardType.SUPPORT_CARD_TYPE_STAMINA: {
        DEFAULT: default_stamina_support_card_score
    },
    SupportCardType.SUPPORT_CARD_TYPE_POWER: {
        DEFAULT: default_power_support_card_score
    },
    SupportCardType.SUPPORT_CARD_TYPE_WILL: {
        DEFAULT: default_will_support_card_score
    },
    SupportCardType.SUPPORT_CARD_TYPE_INTELLIGENCE: {
        DEFAULT: default_intelligence_support_card_score
    },
    SupportCardType.SUPPORT_CARD_TYPE_FRIEND: {
        DEFAULT: default_friend_support_card_score
    },
    SupportCardType.SUPPORT_CARD_TYPE_NPC: {
        DEFAULT: default_npc_support_card_score
    },
    SupportCardType.SUPPORT_CARD_TYPE_GROUP: {
        DEFAULT: default_group_support_card_score
    },
    SupportCardType.SUPPORT_CARD_TYPE_UNKNOWN: {
        DEFAULT: default_unknown_support_card_score
    },
}


