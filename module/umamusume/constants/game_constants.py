PRE_DEBUT_END = 12
JUNIOR_YEAR_END = 24
CLASSIC_YEAR_END = 48
SENIOR_YEAR_END = 72
MAX_DATE = 99

SUMMER_CAMP_1_START = 36
SUMMER_CAMP_1_END = 40
SUMMER_CAMP_2_START = 60
SUMMER_CAMP_2_END = 64

URA_QUALIFIER_ID = 2381
URA_SEMIFINAL_ID = 2382
URA_FINAL_IDS = [2385, 2386, 2387]
URA_RACE_IDS = [URA_QUALIFIER_ID, URA_SEMIFINAL_ID] + URA_FINAL_IDS


NEW_RUN_DETECTION_DATE = 2

def is_summer_camp_period(date):
    return (SUMMER_CAMP_1_START < date <= SUMMER_CAMP_1_END or 
            SUMMER_CAMP_2_START < date <= SUMMER_CAMP_2_END)


def is_ura_race(race_id):
    return race_id in URA_RACE_IDS


def get_date_period_index(date):
    if date <= JUNIOR_YEAR_END:
        return 0
    elif date <= CLASSIC_YEAR_END:
        return 1
    elif date <= SUMMER_CAMP_2_START:
        return 2
    elif date <= SENIOR_YEAR_END:
        return 3
    else:
        return 4
