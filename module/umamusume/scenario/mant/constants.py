from enum import Enum


class MantItemType(Enum):
    STAT_BOOK_SMALL = "stat_book_small"
    STAT_BOOK_MEDIUM = "stat_book_medium"
    STAT_BOOK_LARGE = "stat_book_large"
    ENERGY_SMALL = "energy_small"
    ENERGY_MEDIUM = "energy_medium"
    ENERGY_LARGE = "energy_large"
    GREEN_JUICE = "green_juice"
    CAKE_SMALL = "cake_small"
    CAKE_LARGE = "cake_large"
    MAX_ENERGY_SMALL = "max_energy_small"
    MAX_ENERGY_MEDIUM = "max_energy_medium"
    MAX_ENERGY_LARGE = "max_energy_large"
    BBQ = "bbq"
    CAT_FOOD = "cat_food"
    HORSESHOE_SMALL = "horseshoe_small"
    HORSESHOE_LARGE = "horseshoe_large"
    GLOW_STICK = "glow_stick"
    FACILITY_BOOK = "facility_book"
    WHISTLE = "whistle"
    CHARM = "charm"
    MEGAPHONE_SMALL = "megaphone_small"
    MEGAPHONE_MEDIUM = "megaphone_medium"
    MEGAPHONE_LARGE = "megaphone_large"
    ANKLET = "anklet"
    HAND_MIRROR = "hand_mirror"
    PRACTISE_NOTEBOOK = "practise_notebook"
    SCHOLAR_HAT = "scholar_hat"
    GLASSES = "glasses"
    PANACEA = "panacea"
    REMEDY = "remedy"



class MantRaceSetType(Enum):
    TRIPLE_CROWN = "triple_crown"
    TRIPLE_CROWN_PLUS = "triple_crown_plus"
    FILLY_TRIPLE_CROWN = "filly_triple_crown"
    SPRING_TRIPLE_CROWN = "spring_triple_crown"
    AUTUMN_TRIPLE_CROWN = "autumn_triple_crown"
    MILE_SET = "mile_set"
    SPRINT_SET = "sprint_set"
    DIRT_5_WIN = "dirt_5_win"
    DIRT_G1_3_WIN = "dirt_g1_3_win"
    DIRT_G1_4_WIN = "dirt_g1_4_win"
    DIRT_G1_5_WIN = "dirt_g1_5_win"
    STANDARD_10_WIN = "standard_10_win"
    REGION_TOKYO = "region_tokyo"
    REGION_NAKAYAMA = "region_nakayama"
    REGION_HANSHIN = "region_hanshin"
    REGION_KYOTO = "region_kyoto"
    REGION_CHUKYO = "region_chukyo"
    REGION_SAPPORO = "region_sapporo"
    REGION_HAKODATE = "region_hakodate"
    REGION_FUKUSHIMA = "region_fukushima"
    REGION_NIIGATA = "region_niigata"
    REGION_KOKURA = "region_kokura"


MANT_SHOP_ITEMS = {
    MantItemType.STAT_BOOK_SMALL: {
        "cost": 10,
        "effect": {"stat": 3},
        "efficiency": 0.30,
    },
    MantItemType.STAT_BOOK_MEDIUM: {
        "cost": 15,
        "effect": {"stat": 7},
        "efficiency": 0.47,
    },
    MantItemType.STAT_BOOK_LARGE: {
        "cost": 30,
        "effect": {"stat": 15},
        "efficiency": 0.50,
    },
    MantItemType.ENERGY_SMALL: {
        "cost": 35,
        "effect": {"energy": 20},
        "efficiency": 0.29,
    },
    MantItemType.ENERGY_MEDIUM: {
        "cost": 55,
        "effect": {"energy": 40},
        "efficiency": 0.36,
    },
    MantItemType.ENERGY_LARGE: {
        "cost": 75,
        "effect": {"energy": 65},
        "efficiency": 0.43,
    },
    MantItemType.GREEN_JUICE: {
        "cost": 70,
        "effect": {"energy": 100, "mood": -1},
        "efficiency": 0.50,
    },
    MantItemType.CAKE_SMALL: {
        "cost": 30,
        "effect": {"mood": 1},
        "efficiency": 0.70,
    },
    MantItemType.CAKE_LARGE: {
        "cost": 55,
        "effect": {"mood": 2},
        "efficiency": 0.38,
    },
    MantItemType.MAX_ENERGY_SMALL: {
        "cost": 30,
        "effect": {"max_energy": 4, "energy": 5},
        "efficiency": 0.20,
    },
    MantItemType.MAX_ENERGY_MEDIUM: {
        "cost": 40,
        "effect": {"max_energy": 6, "energy": 10},
        "efficiency": 0.25,
    },
    MantItemType.MAX_ENERGY_LARGE: {
        "cost": 55,
        "effect": {"max_energy": 8, "energy": 15},
        "efficiency": 0.18,
    },
    MantItemType.BBQ: {
        "cost": 40,
        "effect": {"all_bond": 5},
        "efficiency": 0.50,
    },
    MantItemType.CAT_FOOD: {
        "cost": 10,
        "effect": {"akikawa_bond": 5},
        "efficiency": 0.10,
    },
    MantItemType.HORSESHOE_SMALL: {
        "cost": 25,
        "effect": {"race_bonus_multiplier": 1.20, "duration": 1},
        "efficiency": 0.25,
    },
    MantItemType.HORSESHOE_LARGE: {
        "cost": 40,
        "effect": {"race_bonus_multiplier": 1.35, "duration": 1},
        "efficiency": 0.27,
    },
    MantItemType.GLOW_STICK: {
        "cost": 15,
        "effect": {"fan_bonus_multiplier": 1.50, "duration": 1},
        "efficiency": 0.10,
    },
    MantItemType.FACILITY_BOOK: {
        "cost": 150,
        "effect": {"facility_level": 1},
        "efficiency": 0.30,
    },
    MantItemType.WHISTLE: {
        "cost": 20,
        "effect": {"reroll_training": 1},
        "efficiency": 1.00,
    },
    MantItemType.CHARM: {
        "cost": 40,
        "effect": {"failure_rate": 0, "duration": 1},
        "efficiency": 0.31,
    },
    MantItemType.MEGAPHONE_SMALL: {
        "cost": 40,
        "effect": {"training_bonus": 0.20, "duration": 4},
        "efficiency": 0.30,
    },
    MantItemType.MEGAPHONE_MEDIUM: {
        "cost": 55,
        "effect": {"training_bonus": 0.40, "duration": 3},
        "efficiency": 0.36,
    },
    MantItemType.MEGAPHONE_LARGE: {
        "cost": 70,
        "effect": {"training_bonus": 0.60, "duration": 2},
        "efficiency": 0.43,
    },
    MantItemType.ANKLET: {
        "cost": 50,
        "effect": {"training_bonus": 0.50, "energy_cost": 0.20, "duration": 1},
        "efficiency": 0.41,
    },
    MantItemType.HAND_MIRROR: {
        "cost": 150,
        "effect": {"buff": "charming"},
        "efficiency": 0.15,
    },
    MantItemType.PRACTISE_NOTEBOOK: {
        "cost": 150,
        "effect": {"buff": "practise_perfect"},
        "efficiency": 0.05,
    },
    MantItemType.SCHOLAR_HAT: {
        "cost": 280,
        "effect": {"buff": "fast_learner"},
        "efficiency": 0.24,
    },
    MantItemType.GLASSES: {
        "cost": 150,
        "effect": {"buff": "hot_topic"},
        "efficiency": 0.05,
    },
    MantItemType.PANACEA: {
        "cost": 40,
        "effect": {"cure": "all"},
        "efficiency": 0.20,
    },
    MantItemType.REMEDY: {
        "cost": 15,
        "effect": {"cure": "one"},
        "efficiency": 0.10,
    },
}


MANT_RACE_SETS = {
    MantRaceSetType.TRIPLE_CROWN: {
        "races": ["satsuki_sho", "japanese_derby", "kikuka_sho"],
        "reward": {"random_stat": 10, "count": 2},
    },
    MantRaceSetType.TRIPLE_CROWN_PLUS: {
        "races": ["satsuki_sho", "japanese_derby", "kikuka_sho", "japan_cup_or_arima_y2"],
        "reward": {"random_stat": 15, "count": 2},
    },
    MantRaceSetType.FILLY_TRIPLE_CROWN: {
        "races": ["oka_sho", "yushun_himba", "shuka_sho"],
        "reward": {"random_stat": 10, "count": 2},
    },
    MantRaceSetType.SPRING_TRIPLE_CROWN: {
        "races": ["osaka_hai", "tenno_sho_spring", "takarazuka_kinen"],
        "reward": {"random_stat": 10, "count": 2},
    },
    MantRaceSetType.AUTUMN_TRIPLE_CROWN: {
        "races": ["tenno_sho_autumn", "japan_cup", "arima_kinen_y3"],
        "reward": {"random_stat": 10, "count": 2},
    },
    MantRaceSetType.MILE_SET: {
        "races": ["nhk_mile_cup", "yasuda_kinen", "mile_championship"],
        "reward": {"random_stat": 15, "count": 2},
    },
    MantRaceSetType.SPRINT_SET: {
        "races": ["takamatsunomiya_kinen", "sprinters_stakes"],
        "reward": {"random_stat": 10, "count": 2},
    },
    MantRaceSetType.DIRT_5_WIN: {
        "races": ["any_dirt_5"],
        "reward": {"random_stat": 5, "count": 2},
    },
    MantRaceSetType.DIRT_G1_3_WIN: {
        "races": ["dirt_g1_3"],
        "reward": {"random_stat": 10, "count": 2},
    },
    MantRaceSetType.DIRT_G1_4_WIN: {
        "races": ["dirt_g1_4"],
        "reward": {"random_stat": 10, "count": 2},
    },
    MantRaceSetType.DIRT_G1_5_WIN: {
        "races": ["dirt_g1_5"],
        "reward": {"random_stat": 15, "count": 2},
    },
    MantRaceSetType.STANDARD_10_WIN: {
        "races": ["standard_distance_10"],
        "reward": {"random_stat": 10, "count": 2},
    },
}


MANT_REGIONAL_SETS = {
    MantRaceSetType.REGION_TOKYO: {"wins_required": 3, "reward": {"random_stat": 5, "count": 2}},
    MantRaceSetType.REGION_NAKAYAMA: {"wins_required": 3, "reward": {"random_stat": 5, "count": 2}},
    MantRaceSetType.REGION_HANSHIN: {"wins_required": 3, "reward": {"random_stat": 5, "count": 2}},
    MantRaceSetType.REGION_KYOTO: {"wins_required": 3, "reward": {"random_stat": 5, "count": 2}},
    MantRaceSetType.REGION_CHUKYO: {"wins_required": 3, "reward": {"random_stat": 5, "count": 2}},
    MantRaceSetType.REGION_SAPPORO: {"wins_required": 3, "reward": {"random_stat": 5, "count": 2}},
    MantRaceSetType.REGION_HAKODATE: {"wins_required": 3, "reward": {"random_stat": 5, "count": 2}},
    MantRaceSetType.REGION_FUKUSHIMA: {"wins_required": 3, "reward": {"random_stat": 5, "count": 2}},
    MantRaceSetType.REGION_NIIGATA: {"wins_required": 3, "reward": {"random_stat": 5, "count": 2}},
    MantRaceSetType.REGION_KOKURA: {"wins_required": 3, "reward": {"random_stat": 5, "count": 2}},
}


MANT_FIXED_EVENTS = {
    "classic_early_feb": {"turn": 13, "effect": {"mood": 1}},
    "classic_early_march": {"turn": 15, "effect": {"energy": 20}},
    "classic_late_september": {"turn": 28, "effect": {"mood": 1}},
    "senior_late_june": {"turn": 46, "effect": {"energy": 20}},
    "senior_late_october": {"turn": 52, "effect": {"mood": 1}},
    "senior_late_december": {"turn": 56, "effect": {"energy": 30}},
}


MANT_SHOP_REFRESH_TURNS = [1, 7, 13, 19, 25, 31, 37, 43, 49, 55]


MANT_RACE_CHAIN_PENALTIES = {
    1: {"mood_drop_chance": 0.00, "outbreak_chance": 0.00, "stat_loss": 0},
    2: {"mood_drop_chance": 0.15, "outbreak_chance": 0.0375, "stat_loss": 0},
    3: {"mood_drop_chance": 0.33, "outbreak_chance": 0.0825, "stat_loss": 0},
    4: {"mood_drop_chance": 0.60, "outbreak_chance": 0.15, "stat_loss": 0},
    5: {"mood_drop_chance": 0.93, "outbreak_chance": 0.3125, "stat_loss": 12},
}


MANT_ZERO_ENERGY_RACE_PENALTIES = {
    1: {"mood_drop_chance": 0.15, "outbreak_chance": 0.0375},
    2: {"mood_drop_chance": 0.33, "outbreak_chance": 0.0825},
    3: {"mood_drop_chance": 0.90, "outbreak_chance": 0.225},
}


MANT_ECONOMY_THRESHOLDS = {
    "healthy_minimum": 100,
    "pre_summer_minimum": 200,
    "debt_repay_g1": 20,
    "debt_repay_rival_g2g3": 40,
    "debt_repay_non_rival_g2g3": 50,
    "debt_repay_op": 70,
}


MANT_SUMMER_CAMP_TURNS = {
    "year2_summer": [31, 32, 33, 34],
    "year3_summer": [55, 56, 57, 58],
}


MANT_TRAINING_SCORE_MODIFIERS = {
    "main_facility": 0.7,
    "wit_training": 1.7,
    "hint": 1.0,
    "bond_gain": 1.0,
    "rainbow_multi": 1.5,
}


MANT_ITEM_PRIORITY = {
    "must_buy": [
        MantItemType.WHISTLE,
        MantItemType.BBQ,
        MantItemType.CHARM,
        MantItemType.MEGAPHONE_LARGE,
        MantItemType.ANKLET,
        MantItemType.CAKE_SMALL,
    ],
    "good_value": [
        MantItemType.MEGAPHONE_MEDIUM,
        MantItemType.GREEN_JUICE,
        MantItemType.STAT_BOOK_LARGE,
        MantItemType.ENERGY_LARGE,
        MantItemType.HORSESHOE_LARGE,
    ],
    "situational": [
        MantItemType.STAT_BOOK_MEDIUM,
        MantItemType.ENERGY_MEDIUM,
        MantItemType.ENERGY_SMALL,
        MantItemType.PANACEA,
        MantItemType.FACILITY_BOOK,
        MantItemType.SCHOLAR_HAT,
    ],
    "low_priority": [
        MantItemType.STAT_BOOK_SMALL,
        MantItemType.MEGAPHONE_SMALL,
        MantItemType.HORSESHOE_SMALL,
        MantItemType.CAKE_LARGE,
        MantItemType.MAX_ENERGY_SMALL,
        MantItemType.CAT_FOOD,
        MantItemType.GLOW_STICK,
    ],
    "avoid": [
        MantItemType.HAND_MIRROR,
        MantItemType.PRACTISE_NOTEBOOK,
        MantItemType.GLASSES,
        MantItemType.MAX_ENERGY_MEDIUM,
        MantItemType.MAX_ENERGY_LARGE,
    ],
}


MANT_BASELINE_EFFICIENCY = 0.30
MANT_SP_TO_STAT_RATIO = 0.25
MANT_EXPECTED_RACE_COUNT = 30
MANT_CURRENCY_PER_RACE = 100
