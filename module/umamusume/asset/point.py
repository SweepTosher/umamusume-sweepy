from bot.base.common import Coordinate
from bot.base.point import ClickPoint, ClickPointType
from module.umamusume.asset.template import *

# cultivate
TO_CULTIVATE_SCENARIO_CHOOSE = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(545, 1085), "Go to Scenario Selection", None)
TO_CULTIVATE_PREPARE_NEXT = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(355, 1080), "Cultivation Preparation - Next Step")
TO_CULTIVATE_PREPARE_AUTO_SELECT = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(518, 972), "Cultivation Preparation - Auto Select")
TO_CULTIVATE_PREPARE_INCLUDE_GUEST = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(279, 694), "Cultivation Preparation - Include Guest")
TO_CULTIVATE_PREPARE_CONFIRM = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(519, 831), "Cultivation Preparation - Confirm")
CULTIVATE_FINAL_CHECK_START = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(500, 1185), "Start Cultivation")
TO_FOLLOW_SUPPORT_CARD_SELECT = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(570, 680), "Borrow Support Card")
FOLLOW_SUPPORT_CARD_SELECT_REFRESH = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(650, 1010), "Borrow Support Card - Refresh")

TO_TRAINING_SELECT = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(355, 990), "Go to Training Selection", None)
CULTIVATE_REST = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(120, 995), "Rest", None)
CULTIVATE_SKILL_LEARN = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(600, 987), "Skills", None)
CULTIVATE_MEDIC = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(170, 1120), "Medical Room", None)
CULTIVATE_MEDIC_SUMMER = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(260, 1120), "Medical Room - Summer Camp", None)
CULTIVATE_TRIP = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(355, 1130), "Outing", None)
CULTIVATE_RACE = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(564, 1127), "Race", None)
CULTIVATE_RACE_SUMMER = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(460, 1125), "Race - Summer Camp", None)

RETURN_TO_CULTIVATE_MAIN_MENU = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(90, 1230), "Return to Training Main Menu", None)
CULTIVATE_GOAL_RACE_INTER_1 = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(391, 1081), "Enter Career Race Detail Interface", None)
CULTIVATE_GOAL_RACE_INTER_2 = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(360,1082), "Start Career Race", None)
CULTIVATE_GOAL_RACE_INTER_3 = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(520,920), "Start Career Race - Confirm", None)

BEFORE_RACE_CHANGE_TACTIC = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(575, 745), "Before Race - Change Tactics", None)
BEFORE_RACE_CHANGE_TACTIC_4 = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(585, 780), "Change Tactics - Front Runner", None)
BEFORE_RACE_CHANGE_TACTIC_3 = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(435, 780), "Change Tactics - Chaser", None)
BEFORE_RACE_CHANGE_TACTIC_2 = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(285, 780), "Change Tactics - Middle", None)
BEFORE_RACE_CHANGE_TACTIC_1 = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(125, 780), "Change Tactics - Closer", None)
TACTIC_LIST = [BEFORE_RACE_CHANGE_TACTIC_1, BEFORE_RACE_CHANGE_TACTIC_2, BEFORE_RACE_CHANGE_TACTIC_3, BEFORE_RACE_CHANGE_TACTIC_4]

BEFORE_RACE_CHANGE_TACTIC_CONFIRM = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(515, 920), "Change Tactics - Confirm", None)
BEFORE_RACE_START = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(465, 1175), "Before Race - Start Race", None)
BEFORE_RACE_SKIP = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(255, 1175), "Before Race - Skip Race", None)
IN_RACE_UMA_LIST_CONFIRM = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(360,1175), "Race Uma List - Confirm", None)

IN_RACE_SKIP = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(560,1225), "During Race - Skip", None)
SKIP = ClickPoint(ClickPointType.CLICK_POINT_TYPE_TEMPLATE, BTN_SKIP, None, "Skip", None)
SCENARIO_SKIP_OFF = ClickPoint(ClickPointType.CLICK_POINT_TYPE_TEMPLATE, BTN_SKIP_OFF, None, "Skip", None)
SCENARIO_SKIP_SPEED_1 = ClickPoint(ClickPointType.CLICK_POINT_TYPE_TEMPLATE, BTN_SKIP_SPEED_1, None, "Skip", None)

SCENARIO_SHORTEN_SET_2 = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(350,630), "Event Shorten Setting - All", None)
SCENARIO_SHORTEN_CONFIRM = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(360,925), "Event Shorten Setting - Confirm", None)
CULTIVATE_CATCH_DOLL_START = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(365,1117), "Crane Game - Start", None)
CULTIVATE_CATCH_DOLL_RESULT_CONFIRM = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(365,1185), "Crane Game - Result Confirm", None)

RACE_RESULT_CONFIRM = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(370,1150), "Race Result - Confirm", None)
RACE_REWARD_CONFIRM = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(520,1195), "Race Reward - Confirm", None)
GOAL_ACHIEVE_CONFIRM = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(370,1110), "Goal Achieved - Confirm", None)
GOAL_FAIL_CONFIRM = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(370,1190), "Goal Failed - Confirm", None)
NEXT_GOAL_CONFIRM = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(360,1110), "Next Goal - Confirm", None)

CULTIVATE_EXTEND_CONFIRM = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(360,915), "Factor Inheritance - Confirm", None)

TRAINING_SELECT_SPEED = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(105, 1085), "Training - Speed", None)
TRAINING_SELECT_STAMINA = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(235, 1085), "Training - Stamina", None)
TRAINING_SELECT_POWER = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(360, 1085), "Training - Power", None)
TRAINING_SELECT_WILL = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(490, 1085), "Training - Guts", None)
TRAINING_SELECT_INTELLIGENCE = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(620, 1085), "Training - Wit", None)
TRAINING_SELECT_GUTS = TRAINING_SELECT_WILL
TRAINING_SELECT_WIT = TRAINING_SELECT_INTELLIGENCE

TRAINING_POINT_LIST = [TRAINING_SELECT_SPEED, TRAINING_SELECT_STAMINA, TRAINING_SELECT_POWER,
                       TRAINING_SELECT_GUTS, TRAINING_SELECT_WIT]

INFO_SUMMER_REST_CONFIRM = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(520,835), "Rest - Summer Camp - Confirm", None)
NETWORK_ERROR_CONFIRM = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE,None, Coordinate(520,835), "Network Error - Confirm", None)
SKIP_CONFIRM = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE,None, Coordinate(520,835), "Skip - Confirm", None)
CULTIVATE_OPERATION_COMMON_CONFIRM = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(520, 835), "Cultivation Operation Common Confirm", None)
RACE_RECOMMEND_CONFIRM = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(365, 1185), "Race Recommendation Function Confirm", None)
CULTIVATE_TRIP_WITH_FRIEND = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(370, 455), "Outing Trip - Select Friend", None)
CULTIVATE_TRIP_WITH_FRIEND_COMPLETE = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(406, 597), "Outing Trip - Friend Complete", None)
RACE_FAIL_CONTINUE_USE_CLOCK = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE,None, Coordinate(520,905), "Use Clock - Confirm", None)
RACE_FAIL_CONTINUE_CANCEL = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE,None, Coordinate(200,905), "Use Clock - Cancel", None)
CULTIVATE_RECEIVE_CUP_CLOSE = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE,None, Coordinate(365,920), "Receive Cup - Close", None)

CULTIVATE_FINISH_LEARN_SKILL = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(215, 1050), "Cultivation Complete - Learn Skills", None)
CULTIVATE_FINISH_CONFIRM = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE,None, Coordinate(512,1050), "Cultivation Complete - Confirm", None)
CULTIVATE_FINISH_CONFIRM_AGAIN = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE,None, Coordinate(520,924), "Cultivation Complete - Confirm Again (Abandon remaining skill points)", None)
RACE_FAIL_CONFIRM = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(513, 919), "Race Fail - Try Again Confirmation", None)


GET_TITLE_CONFIRM = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE,None, Coordinate(350,1195), "Get Title - Confirm", None)
CULTIVATE_RESULT_CONFIRM = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE,None, Coordinate(360,1185), "Cultivation Result - Confirm", None)
CULTIVATE_RESULT_DIVISOR_CONFIRM = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE,None, Coordinate(525,1185), "Confirm Factor", None)
CULTIVATE_FINISH_RETURN_CONFIRM = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(190, 835), "Cultivation End - Return", None)
CULTIVATE_LEARN_SKILL_CONFIRM = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE,None, Coordinate(360,1082), "Skill Learning - Confirm", None)
CULTIVATE_LEARN_SKILL_CONFIRM_AGAIN = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE,None, Coordinate(516,1185), "Skill Learning - Confirm Again", None)
CULTIVATE_LEARN_SKILL_DONE_CONFIRM = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE,None, Coordinate(359,832), "Skill Learning - Confirm Again", None)
RETURN_TO_CULTIVATE_FINISH = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(90, 1190), "Return to Cultivation Interface", None)

CULTIVATE_FAN_NOT_ENOUGH_RETURN = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(200, 915), "Target Fan Count Insufficient - Return", None)
CULTIVATE_TOO_MUCH_RACE_WARNING_CONFIRM = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(525, 840), "Consecutive Race Participation - Confirm", None)

CULTIVATE_LEVEL_RESULT_CONFIRM = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(360, 1175), "Cultivation Level - Next Page", None)
CULTIVATE_FACTOR_RECEIVE_CONFIRM = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(360, 1175), "Factor Acquisition - Next Page", None)
HISTORICAL_RATING_UPDATE_CONFIRM = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(360, 1115), "Historical Rating Update - Next Page", None)
SCENARIO_RATING_UPDATE_CONFIRM = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(360, 1115), "Historical Rating Update - Next Page", None)

RECEIVE_GIFT = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(515, 1180), "Gift Box - Collect All", None)
RECEIVE_GIFT_SUCCESS_CLOSE = ClickPoint(ClickPointType.CLICK_POINT_TYPE_TEMPLATE, BTN_CLOSE, None, "Gift Box - Collection Success - Close", None)
UNLOCK_STORY_TO_HOME_PAGE = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(360, 835), "Unlock Character Story - Go to Home Page", None)
WIN_TIMES_NOT_ENOUGH_RETURN = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(200, 915), "Target Achievement Count Insufficient - Return", None)
ACTIVITY_STORY_UNLOCK_CONFIRM = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(360, 830), "Event Story Unlock - Close", None)

TO_RECOVER_TP = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(520, 830), "Recover Training Points", None)
USE_TP_DRINK = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(610, 320), "Use TP Drink", None)

USE_CARROT_RECOVER_TP = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(610, 180), "Use Carrot to Recover TP", None)
USE_CARROT_RECOVER_TP_ADD = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(520, 670), "Use Carrot +", None)

USE_TP_DRINK_CONFIRM = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(525, 920), "Use TP Drink - Confirm", None)
USE_CARROT_RECOVER_CONFIRM = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(525, 920), "Use Carrot - Confirm", None)
USE_TP_DRINK_RESULT_CLOSE = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(360, 835), "Recovery Complete - Close", None)

STORY_REWARDS_COLLECTED_CLOSE = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(360, 1180), "Story Rewards Collected - Close", None)
ESCAPE = ClickPoint(ClickPointType.CLICK_POINT_TYPE_COORDINATE, None, Coordinate(5, 715), "escape", None)