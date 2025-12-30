class LocalizationMap:
    SCENARIO_TYPE_UNKNOWN = 'Unknown'
    SCENARIO_TYPE_URA = 'URA'
    SCENARIO_TYPE_AOHARUHAI = 'Aoharu Cup'

    SUPPORT_CARD_TYPE_UNKNOWN = 'Unknown'
    SUPPORT_CARD_TYPE_SPEED = 'Speed'
    SUPPORT_CARD_TYPE_STAMINA = 'Stamina'
    SUPPORT_CARD_TYPE_POWER = 'Power'
    SUPPORT_CARD_TYPE_WILL = 'Guts'
    SUPPORT_CARD_TYPE_INTELLIGENCE = 'Wisdom'
    SUPPORT_CARD_TYPE_FRIEND = 'Friend'
    SUPPORT_CARD_TYPE_GROUP = 'Group'
    SUPPORT_CARD_TYPE_NPC = 'NPC'

    SUPPORT_CARD_FAVOR_LEVEL_UNKNOWN = 'Unknown'
    SUPPORT_CARD_FAVOR_LEVEL_1 = 'Level 1'
    SUPPORT_CARD_FAVOR_LEVEL_2 = 'Level 2'
    SUPPORT_CARD_FAVOR_LEVEL_3 = 'Level 3'
    SUPPORT_CARD_FAVOR_LEVEL_4 = 'Level 4'

    TRAINING_TYPE_UNKNOWN = 'Unknown'
    TRAINING_TYPE_SPEED = 'Speed'
    TRAINING_TYPE_STAMINA = 'Stamina'
    TRAINING_TYPE_POWER = 'Power'
    TRAINING_TYPE_WILL = 'Guts'
    TRAINING_TYPE_INTELLIGENCE = 'Wisdom'

    MOTIVATION_LEVEL_UNKNOWN = 'Unknown'
    MOTIVATION_LEVEL_1 = 'Level 1'
    MOTIVATION_LEVEL_2 = 'Level 2'
    MOTIVATION_LEVEL_3 = 'Level 3'
    MOTIVATION_LEVEL_4 = 'Level 4'
    MOTIVATION_LEVEL_5 = 'Level 5'

    TURN_OPERATION_TYPE_UNKNOWN = 'Unknown'
    TURN_OPERATION_TYPE_TRAINING = 'Training'
    TURN_OPERATION_TYPE_REST = 'Rest'
    TURN_OPERATION_TYPE_MEDIC = 'Infirmary'
    TURN_OPERATION_TYPE_TRIP = 'Outing'
    TURN_OPERATION_TYPE_RACE = 'Race'

    SUPPORT_CARD_UMA_UNKNOWN = 'Unknown'
    SUPPORT_CARD_UMA_AKIKAWA = 'Chairman'
    SUPPORT_CARD_UMA_REPORTER = 'Reporter'

    RACE_TACTIC_TYPE_UNKNOWN = 'Unknown'
    RACE_TACTIC_TYPE_BACK = 'Stalker'
    RACE_TACTIC_TYPE_MIDDLE = 'Midfield'
    RACE_TACTIC_TYPE_FRONT = 'Front-runner'
    RACE_TACTIC_TYPE_ESCAPE = 'Pacesetter'

    TASK_STATUS_INVALID = 'Invalid Task'
    TASK_STATUS_PENDING = 'Task Paused'
    TASK_STATUS_RUNNING = 'Task Running'
    TASK_STATUS_INTERRUPT = 'Task Interrupted'
    TASK_STATUS_SUCCESS = 'Task Completed'
    TASK_STATUS_FAILED = 'Task Failed'
    TASK_STATUS_SCHEDULED = 'Task Scheduled'
    TASK_STATUS_CANCELED = 'Task Canceled'

    support_card = 'None'

localization_map = {attr: value for attr, value in vars(LocalizationMap).items()
                    if not callable(value) and not attr.startswith('_')}

localization_map.update({
    'True': 'Yes',
    'False': 'No'
})

def _localization_single(string):
    for name, value in localization_map.items():
        string = string.replace(name, value)
    return string


def localization(text):
    if isinstance(text, str):
        return _localization_single(text)
    if not isinstance(text, list):
        raise TypeError(f'localization failed: illegal type {type(text)}')
    for i, string in enumerate(text):
        if not isinstance(string, str):
            raise TypeError(f'localization failed: illegal type {type(string)}')
        text[i] = _localization_single(string)
    return text
