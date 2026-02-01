from module.umamusume.context import *
from module.umamusume.types import TurnOperation
import cv2
from module.umamusume.asset.template import UI_CULTIVATE_URA_RACE_1, UI_CULTIVATE_URA_RACE_2, UI_CULTIVATE_URA_RACE_3
from bot.recog.image_matcher import image_match
from bot.conn.fetch import fetch_state
log = logger.get_logger(__name__)

_race_cache = {}

DATE_JUNIOR_END = 24
DATE_CLASSIC_END = 48
DATE_SPRING_END = 60
ENERGY_FAST_MEDIC = 80
ENERGY_FAST_TRIP = 80
ENERGY_MEDIC_GENERAL = 85
ENERGY_TRIP_GENERAL = 90
ENERGY_REST_EXTRA_DAY = 65
MIN_SUPPORT_GOOD_TRAINING_URA = 2
MIN_SUPPORT_GOOD_TRAINING = 3
SUMMER_CONSERVE_DATES = (35, 36, 59, 60)
SUMMER_CONSERVE_ENERGY = 60
URA_RACE_WINDOWS = [
    ((73, 75), 2381, UI_CULTIVATE_URA_RACE_1),
    ((76, 78), 2382, UI_CULTIVATE_URA_RACE_2),
    ((79, 99), 2385, UI_CULTIVATE_URA_RACE_3),
]

def weights_for_date(date):
    if date <= DATE_JUNIOR_END:
        return 0.11, 0.10
    elif date <= DATE_CLASSIC_END:
        return 0.11, 0.10
    elif date <= DATE_SPRING_END:
        return 0.11, 0.10
    else:
        return 0.03, 0.05

def get_ura_race_id_and_template(date):
    for rng, rid, tpl in URA_RACE_WINDOWS:
        if rng[0] <= date <= rng[1]:
            return rid, tpl
    return None, None

def _get_races_for_period_cached(period: int) -> list[int]:
    if period not in _race_cache:
        from module.umamusume.asset.race_data import get_races_for_period
        _race_cache[period] = get_races_for_period(period)
    return _race_cache[period]


def get_operation(ctx: UmamusumeContext) -> TurnOperation | None:
    turn_operation = TurnOperation()
    if not ctx.cultivate_detail.debut_race_win:
        if not hasattr(ctx.cultivate_detail.turn_info, 'race_search_attempted'):
            turn_operation.turn_operation_type = TurnOperationType.TURN_OPERATION_TYPE_RACE
    state = fetch_state()
    energy = state.get("energy", 0)
    mood_raw = state.get("mood")
    mood_val = mood_raw if mood_raw is not None else 4

    date_for_threshold = ctx.cultivate_detail.turn_info.date
    if date_for_threshold <= 36:
        mood_threshold = ctx.cultivate_detail.motivation_threshold_year1
    elif date_for_threshold <= 60:
        mood_threshold = ctx.cultivate_detail.motivation_threshold_year2
    else:
        mood_threshold = ctx.cultivate_detail.motivation_threshold_year3
        
    if ctx.cultivate_detail.turn_info.medic_room_available and energy <= ENERGY_FAST_MEDIC:
        log.info(f"🏥 Fast path: Low stamina ({energy}) - prioritizing medic")
        turn_operation.turn_operation_type = TurnOperationType.TURN_OPERATION_TYPE_MEDIC
        return turn_operation

    if (mood_raw is not None) and energy < ENERGY_FAST_TRIP and mood_val < mood_threshold:
        if getattr(ctx.cultivate_detail, 'prioritize_recreation', False) and ctx.cultivate_detail.pal_event_stage > 0:
            try:
                img = ctx.current_screen
                if img is not None:
                    img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                    from module.umamusume.asset.template import UI_RECREATION_FRIEND_NOTIFICATION
                    result = image_match(img_gray, UI_RECREATION_FRIEND_NOTIFICATION)
                    if result.find_match:
                        log.info("mood fast path - PAL notification detected, returning TRIP")
                        turn_operation.turn_operation_type = TurnOperationType.TURN_OPERATION_TYPE_TRIP
                        return turn_operation
                    else:
                        log.info("mood fast path - PAL notification NOT detected, skipping TRIP")
            except Exception:
                pass
        else:
            log.info("mood fast path - regular trip (PAL not configured)")
            turn_operation.turn_operation_type = TurnOperationType.TURN_OPERATION_TYPE_TRIP
            return turn_operation

    limit = getattr(ctx.cultivate_detail, 'rest_treshold', getattr(ctx.cultivate_detail, 'fast_path_energy_limit', 48))
    if limit == 0:
        energy = 100
    if energy <= limit:
        if getattr(ctx.cultivate_detail, 'prioritize_recreation', False) and ctx.cultivate_detail.pal_event_stage > 0:
            try:
                img = ctx.current_screen
                if img is not None:
                    img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                    from module.umamusume.asset.template import UI_RECREATION_FRIEND_NOTIFICATION
                    result = image_match(img_gray, UI_RECREATION_FRIEND_NOTIFICATION)
                    if result.find_match:
                        pal_thresholds = ctx.cultivate_detail.pal_thresholds
                        if pal_thresholds:
                            stage = ctx.cultivate_detail.pal_event_stage
                            if stage <= len(pal_thresholds):
                                thresholds = pal_thresholds[stage - 1]
                                mood_threshold = thresholds[0]
                                energy_threshold = thresholds[1]
                                
                                mood_below = mood_val <= mood_threshold
                                energy_below = energy <= energy_threshold
                                
                                log.info(f"PAL outing check - Stage {stage}:")
                                log.info(f"Mood: {mood_val} vs {mood_threshold} - {'<=' if mood_below else '>'}")
                                log.info(f"Energy: {energy} vs {energy_threshold} - {'<=' if energy_below else '>'}")
                                
                                if mood_below and energy_below:
                                    log.info("Both conditions met - using pal outing instead of rest")
                                    turn_operation.turn_operation_type = TurnOperationType.TURN_OPERATION_TYPE_TRIP
                                    return turn_operation
            except Exception:
                pass
        log.info(f"rest threshold: energy={energy}, threshold={limit} - prioritizing rest")
        turn_operation.turn_operation_type = TurnOperationType.TURN_OPERATION_TYPE_REST
        return turn_operation

    cached_screen = None
    if ctx.current_screen is not None:
        cached_screen = cv2.cvtColor(ctx.current_screen, cv2.COLOR_BGR2GRAY)

    turn_info = ctx.cultivate_detail.turn_info
    date = turn_info.date

    try:
        support_card_max = max(len(ti.support_card_info_list) for ti in turn_info.training_info_list)
    except Exception:
        support_card_max = 0

    from module.umamusume.define import SupportCardType, SupportCardFavorLevel, TrainingType
    type_map = [
        SupportCardType.SUPPORT_CARD_TYPE_SPEED,
        SupportCardType.SUPPORT_CARD_TYPE_STAMINA,
        SupportCardType.SUPPORT_CARD_TYPE_POWER,
        SupportCardType.SUPPORT_CARD_TYPE_WILL,
        SupportCardType.SUPPORT_CARD_TYPE_INTELLIGENCE,
    ]

    w_lv1, w_lv2 = weights_for_date(date)

    training_score = [0.0, 0.0, 0.0, 0.0, 0.0]
    for idx in range(5):
        til = turn_info.training_info_list[idx]
        target_type = type_map[idx]
        score = 0.0
        for sc in (getattr(til, "support_card_info_list", []) or []):
            favor = getattr(sc, "favor", SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_UNKNOWN)
            ctype = getattr(sc, "card_type", SupportCardType.SUPPORT_CARD_TYPE_UNKNOWN)
            if ctype == SupportCardType.SUPPORT_CARD_TYPE_NPC:
                score += 0.05
                continue
            if ctype == SupportCardType.SUPPORT_CARD_TYPE_UNKNOWN:
                continue
            if favor == SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_UNKNOWN:
                continue
            if favor in (SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_3, SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_4) and ctype == target_type:
                continue
            if favor == SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_1:
                score += w_lv1
            elif favor == SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_2:
                score += w_lv2
        training_score[idx] = score

    if getattr(ctx.cultivate_detail, 'compensate_failure', True):
        try:
            for idx in range(5):
                fr = int(getattr(turn_info.training_info_list[idx], 'failure_rate', -1))
                if fr >= 0:
                    mult = max(0.0, 1.0 - (float(fr) / 50.0))
                    training_score[idx] *= mult
        except Exception:
            pass

    log.debug("Overall training score: " + str(training_score))

    if ctx.cultivate_detail.debut_race_win:
        from module.umamusume.asset.race_data import get_races_for_period
        ura_race_id = None
        if ctx.task.detail.scenario == ScenarioType.SCENARIO_TYPE_URA:
            date_now = ctx.cultivate_detail.turn_info.date
            rid, tpl = get_ura_race_id_and_template(date_now)
            ura_race_id = rid
            if ura_race_id and cached_screen is not None:
                ura_race_available = image_match(cached_screen, tpl).find_match
                if not ura_race_available:
                    ura_race_id = None
            elif ura_race_id and cached_screen is None:
                ura_race_id = None
        if ura_race_id:
            log.info(f"🏆 Detected URA championship race: {ura_race_id} at date {date}")
            medic = False
            if ctx.cultivate_detail.turn_info.medic_room_available and energy <= ENERGY_MEDIC_GENERAL:
                medic = True
            trip = False
            if not ctx.cultivate_detail.turn_info.medic_room_available and (
                (ctx.cultivate_detail.turn_info.date <= 36 and mood_val < ctx.cultivate_detail.motivation_threshold_year1 and energy < ENERGY_TRIP_GENERAL and not support_card_max >= MIN_SUPPORT_GOOD_TRAINING_URA)
                or (40 < ctx.cultivate_detail.turn_info.date <= 60 and mood_val < ctx.cultivate_detail.motivation_threshold_year2 and energy < ENERGY_TRIP_GENERAL)
                or (64 < ctx.cultivate_detail.turn_info.date <= 99 and mood_val < ctx.cultivate_detail.motivation_threshold_year3 and energy < ENERGY_TRIP_GENERAL)
            ):
                try:
                    best_idx = max(range(5), key=lambda i: training_score[i]) if len(training_score) == 5 else 0
                    best_score = training_score[best_idx] if len(training_score) == 5 else 0.0
                except Exception:
                    best_score = 0.0
                if best_score > 0.3:
                    log.info("No recreation as good training detected")
                    trip = False
                else:
                    trip = True
            rest = False
            if energy <= limit:
                rest = True
            elif (ctx.cultivate_detail.turn_info.date == 36 or ctx.cultivate_detail.turn_info.date == 60) and energy < ENERGY_REST_EXTRA_DAY:
                rest = True
            if rest:
                if getattr(ctx.cultivate_detail, 'prioritize_recreation', False) and ctx.cultivate_detail.pal_event_stage > 0:
                    try:
                        if cached_screen is not None:
                            from module.umamusume.asset.template import UI_RECREATION_FRIEND_NOTIFICATION
                            result = image_match(cached_screen, UI_RECREATION_FRIEND_NOTIFICATION)
                            if result.find_match:
                                pal_thresholds = ctx.cultivate_detail.pal_thresholds
                                if pal_thresholds:
                                    stage = ctx.cultivate_detail.pal_event_stage
                                    if stage <= len(pal_thresholds):
                                        thresholds = pal_thresholds[stage - 1]
                                        mood_threshold = thresholds[0]
                                        energy_threshold = thresholds[1]
                                        
                                        mood_below = mood_val <= mood_threshold
                                        energy_below = energy <= energy_threshold
                                        
                                        log.info(f"PAL outing check - Stage {stage}:")
                                        log.info(f"Mood: {mood_val} vs {mood_threshold} - {'<=' if mood_below else '>'}")
                                        log.info(f"Energy: {energy} vs {energy_threshold} - {'<=' if energy_below else '>'}")
                                        
                                        if mood_below and energy_below:
                                            log.info("Both conditions met - using pal outing instead of rest")
                                            turn_operation.turn_operation_type = TurnOperationType.TURN_OPERATION_TYPE_TRIP
                                            return turn_operation
                    except Exception:
                        pass
                log.info(f"🏥 Low stamina ({energy}) - prioritizing rest over URA race")
                turn_operation.turn_operation_type = TurnOperationType.TURN_OPERATION_TYPE_REST
                return turn_operation
            elif trip:
                log.info(f"🏖️ Low stamina/motivation - prioritizing trip over URA race")
                turn_operation.turn_operation_type = TurnOperationType.TURN_OPERATION_TYPE_TRIP
                return turn_operation
            elif medic:
                log.info(f"🏥 Low stamina - prioritizing medic over URA race")
                turn_operation.turn_operation_type = TurnOperationType.TURN_OPERATION_TYPE_MEDIC
                return turn_operation
            else:
                log.info(f"🏆 Proceeding with URA race - stamina: {energy}")
                turn_operation.turn_operation_type = TurnOperationType.TURN_OPERATION_TYPE_RACE
                turn_operation.race_id = ura_race_id
                return turn_operation
        available_races = _get_races_for_period_cached(ctx.cultivate_detail.turn_info.date)
        extra_race_this_turn = [race_id for race_id in ctx.cultivate_detail.extra_race_list if race_id in available_races]
        if len(extra_race_this_turn) != 0:
            turn_operation.turn_operation_type = TurnOperationType.TURN_OPERATION_TYPE_RACE
            turn_operation.race_id = extra_race_this_turn[0]
            return turn_operation

    medic = False
    if ctx.cultivate_detail.turn_info.medic_room_available and energy <= ENERGY_MEDIC_GENERAL:
        medic = True

    trip = False
    if not ctx.cultivate_detail.turn_info.medic_room_available and (ctx.cultivate_detail.turn_info.date <= 36 and mood_val < ctx.cultivate_detail.motivation_threshold_year1 and energy < ENERGY_TRIP_GENERAL and not support_card_max >= MIN_SUPPORT_GOOD_TRAINING
                                                                    or 40 < ctx.cultivate_detail.turn_info.date <= 60 and mood_val < ctx.cultivate_detail.motivation_threshold_year2 and energy < ENERGY_TRIP_GENERAL
                                                                    or 64 < ctx.cultivate_detail.turn_info.date <= 99 and mood_val < ctx.cultivate_detail.motivation_threshold_year3 and energy < ENERGY_TRIP_GENERAL):
        try:
            best_idx = max(range(5), key=lambda i: training_score[i]) if len(training_score) == 5 else 0
            best_score = training_score[best_idx] if len(training_score) == 5 else 0.0
        except Exception:
            best_score = 0.0
        if best_score > 0.3:
            log.info("No recreation as good training detected")
            trip = False
        else:
            if getattr(ctx.cultivate_detail, 'prioritize_recreation', False) and ctx.cultivate_detail.pal_event_stage > 0:
                try:
                    if cached_screen is not None:
                        from module.umamusume.asset.template import UI_RECREATION_FRIEND_NOTIFICATION
                        result = image_match(cached_screen, UI_RECREATION_FRIEND_NOTIFICATION)
                        if result.find_match:
                            log.info("Recreation conditions met and PAL notification detected")
                            trip = True
                        else:
                            log.info("Recreation conditions met but PAL notification NOT detected - skipping trip")
                            trip = False
                    else:
                        trip = False
                except Exception:
                    trip = False
            else:
                log.info("Recreation conditions met - regular trip (PAL not configured)")
                trip = True

    if trip and limit < 90 and energy > 26:
        log.info("Checking if outing is better than rest")

    rest = False
    pal_outing_available = False
    if energy <= limit:
        if trip and limit < 90 and energy > 26:
            rest = False
        elif getattr(ctx.cultivate_detail, 'prioritize_recreation', False) and ctx.cultivate_detail.pal_event_stage > 0:
            try:
                if cached_screen is not None:
                    from module.umamusume.asset.template import UI_RECREATION_FRIEND_NOTIFICATION
                    result = image_match(cached_screen, UI_RECREATION_FRIEND_NOTIFICATION)
                    if result.find_match:
                        pal_thresholds = ctx.cultivate_detail.pal_thresholds
                        if pal_thresholds:
                            stage = ctx.cultivate_detail.pal_event_stage
                            if stage <= len(pal_thresholds):
                                thresholds = pal_thresholds[stage - 1]
                                mood_threshold = thresholds[0]
                                energy_threshold = thresholds[1]
                                
                                mood_below = mood_val <= mood_threshold
                                energy_below = energy <= energy_threshold
                                
                                log.info(f"PAL outing check - Stage {stage}:")
                                log.info(f"Mood: {mood_val} vs {mood_threshold} - {'<=' if mood_below else '>'}")
                                log.info(f"Energy: {energy} vs {energy_threshold} - {'<=' if energy_below else '>'}")
                                
                                if mood_below and energy_below:
                                    log.info("Both conditions met - using pal outing instead of rest")
                                    pal_outing_available = True
                                    trip = True
                                    rest = False
                                else:
                                    rest = True
                            else:
                                rest = True
                        else:
                            rest = True
                    else:
                        rest = True
                else:
                    rest = True
            except Exception:
                rest = True
        else:
            rest = True
    elif (ctx.cultivate_detail.turn_info.date == 36 or ctx.cultivate_detail.turn_info.date == 60) and energy < ENERGY_REST_EXTRA_DAY:
        rest = True

    expect_operation_type = TurnOperationType.TURN_OPERATION_TYPE_UNKNOWN

    if medic and expect_operation_type is TurnOperationType.TURN_OPERATION_TYPE_UNKNOWN:
        expect_operation_type = TurnOperationType.TURN_OPERATION_TYPE_MEDIC
    elif trip and expect_operation_type is TurnOperationType.TURN_OPERATION_TYPE_UNKNOWN:
        expect_operation_type = TurnOperationType.TURN_OPERATION_TYPE_TRIP
    elif rest and expect_operation_type is TurnOperationType.TURN_OPERATION_TYPE_UNKNOWN:
        expect_operation_type = TurnOperationType.TURN_OPERATION_TYPE_REST

    if expect_operation_type is TurnOperationType.TURN_OPERATION_TYPE_UNKNOWN:
        date_num = ctx.cultivate_detail.turn_info.date
        if date_num in SUMMER_CONSERVE_DATES:
            try:
                best_idx = max(range(5), key=lambda i: training_score[i]) if len(training_score) == 5 else 0
                best_score = training_score[best_idx] if len(training_score) == 5 else 0.0
            except Exception:
                best_score = 0.0
            summer_threshold = getattr(ctx.cultivate_detail, 'summer_score_threshold', 0.34)
            if best_score < summer_threshold:
                log.info(f"Low training score before summer, conserving energy (score < {summer_threshold:.2f})")
                if energy < SUMMER_CONSERVE_ENERGY:
                    expect_operation_type = TurnOperationType.TURN_OPERATION_TYPE_REST
                else:
                    expect_operation_type = TurnOperationType.TURN_OPERATION_TYPE_TRAINING
                    turn_operation.training_type = TrainingType.TRAINING_TYPE_INTELLIGENCE

    if expect_operation_type is TurnOperationType.TURN_OPERATION_TYPE_UNKNOWN:
        expect_operation_type = TurnOperationType.TURN_OPERATION_TYPE_TRAINING

    if turn_operation.turn_operation_type != TurnOperationType.TURN_OPERATION_TYPE_UNKNOWN:
        turn_operation.turn_operation_type_replace = expect_operation_type
    else:
        turn_operation.turn_operation_type = expect_operation_type
    return turn_operation
