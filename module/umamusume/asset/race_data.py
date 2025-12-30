import csv
import os.path

from bot.base.resource import Template
from module.umamusume.asset import REF_SUITABLE_RACE

RACE_LIST: list[list] = []
UMAMUSUME_RACE_TEMPLATE_PATH = "/umamusume/race"


def load_race_data():
    for i in range(10000):
        RACE_LIST.append([])
    with open('resource/umamusume/data/race.csv', 'r', encoding="utf-8") as file:
        reader = csv.reader(file)
        for row in reader:
            race_id = row[1]
            path = "resource" + UMAMUSUME_RACE_TEMPLATE_PATH + "/" + str(race_id)+".png"
            if os.path.isfile(path):
                t = Template(str(race_id), UMAMUSUME_RACE_TEMPLATE_PATH)
                race_name = row[3]
                race_info = [race_id, race_name, t]
                RACE_LIST[int(race_id)] = race_info
    RACE_LIST[0] = [0, "suitable", REF_SUITABLE_RACE]

load_race_data()



# Race period mapping for new Global Server system
PERIOD_TO_RACES = {}

def get_races_for_period(time_period: int) -> list[int]:
    """Get all race IDs available for a specific time period"""
    return PERIOD_TO_RACES.get(time_period, [])

def load_period_mapping():
    """Load the time period to race ID mapping from race.csv"""
    global PERIOD_TO_RACES
    PERIOD_TO_RACES.clear()
    
    with open('resource/umamusume/data/race.csv', 'r', encoding="utf-8") as file:
        reader = csv.reader(file)
        for row in reader:
            if len(row) >= 4:
                time_period = int(row[0])
                race_id = int(row[1])
                
                if time_period not in PERIOD_TO_RACES:
                    PERIOD_TO_RACES[time_period] = []
                
                PERIOD_TO_RACES[time_period].append(race_id)

load_period_mapping()
