from module.umamusume.define import ScenarioType

REGISTRY = {}

def register(scenario_type):
    def decorator(cls):
        REGISTRY[scenario_type] = cls
        return cls
    return decorator

def create_scenario(scenario_type):
    if scenario_type in REGISTRY:
        return REGISTRY[scenario_type]()
    return None
