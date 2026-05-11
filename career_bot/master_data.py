import json
import os
import sqlite3
from pathlib import Path


DIRECT_TABLES = [
    "skill_data",
    "single_mode_skill_need_point",
    "race",
    "race_course_set",
    "race_instance",
    "single_mode_program",
    "single_mode_scout_chara",
    "card_rarity_data",
    "available_skill_set",
    "support_card_data",
]

TEXT_DATA_CATEGORIES = {
    "cat_4_text": 4,
    "cat_28_text": 28,
    "cat_47_text": 47,
    "cat_75_text": 75,
    "cat_147_text": 147,
    "cat_181_text": 181,
}


def default_master_mdb_path():
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data).parent / "LocalLow" / "Cygames" / "Umamusume" / "master" / "master.mdb"
    return Path.home() / "AppData" / "LocalLow" / "Cygames" / "Umamusume" / "master" / "master.mdb"


def settings_path(base_dir):
    return Path(base_dir) / "settings.json"


def read_settings(base_dir):
    path = settings_path(base_dir)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_settings(base_dir, settings):
    path = settings_path(base_dir)
    path.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def configured_master_mdb_path(base_dir):
    settings = read_settings(base_dir)
    configured = (settings.get("master_data") or {}).get("master_mdb_path")
    return Path(configured).expanduser() if configured else default_master_mdb_path()


def set_master_mdb_path(base_dir, master_mdb_path):
    settings = read_settings(base_dir)
    master_settings = settings.setdefault("master_data", {})
    master_settings["master_mdb_path"] = str(Path(master_mdb_path).expanduser())
    write_settings(base_dir, settings)
    return status(base_dir)


def path_access(path):
    try:
        return path.exists(), None
    except OSError as exc:
        return False, str(exc)


def status(base_dir):
    db_path = configured_master_mdb_path(base_dir)
    exists, access_error = path_access(db_path)
    return {
        "success": True,
        "master_mdb_path": str(db_path),
        "exists": exists,
        "access_error": access_error,
        "requires_user_action": not exists,
    }


def dump_table(cursor, table):
    cursor.execute(f'SELECT * FROM "{table}";')
    cols = [desc[0] for desc in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


def dump_text_data_category(cursor, category):
    cursor.execute(
        'SELECT id, category, "index", text FROM text_data WHERE category = ?;',
        (category,),
    )
    cols = [desc[0] for desc in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def text_map(rows):
    return {int(row["index"]): row.get("text", "") for row in rows if row.get("index") is not None}


def display_name(name):
    name = str(name or "").strip()
    if name.startswith("[") and "] " in name:
        return name.split("] ", 1)[1].strip()
    return name


def master_rows(master_data, name):
    return master_data.get("tables", {}).get(name) or master_data.get("text", {}).get(name) or []


def synthesize_skill_data(base_dir, master_data):
    data_dir = Path(base_dir) / "data"
    skill_names = text_map(master_rows(master_data, "cat_47_text"))
    skill_costs = {
        int(row["id"]): int(row.get("need_skill_point") or 0)
        for row in master_rows(master_data, "single_mode_skill_need_point")
        if row.get("id") is not None
    }

    skills = {}
    for row in master_rows(master_data, "skill_data"):
        skill_id = int(row.get("id") or 0)
        if not skill_id:
            continue
        skills[str(skill_id)] = {
            "name": skill_names.get(skill_id, str(skill_id)),
            "rarity": int(row.get("rarity") or 0),
            "group_id": int(row.get("group_id") or 0),
            "grade_value": int(row.get("grade_value") or 0),
            "need_skill_point": skill_costs.get(skill_id, 0),
            "disable_singlemode": int(row.get("disable_singlemode") or 0),
        }

    write_json(data_dir / "skill_data.json", skills)
    return {"file": "skill_data.json", "skills": len(skills)}


def synthesize_chara_list(base_dir, master_data):
    data_dir = Path(base_dir) / "data"
    names = text_map(master_rows(master_data, "cat_4_text"))
    rows_by_card_id = {}
    for row in master_rows(master_data, "card_rarity_data"):
        card_id = int(row.get("card_id") or 0)
        name = display_name(names.get(card_id, ""))
        if card_id and name:
            rows_by_card_id[card_id] = name

    chara = {}
    name_counts = {}
    for card_id, name in sorted(rows_by_card_id.items()):
        name_counts[name] = name_counts.get(name, 0) + 1
        count = name_counts[name]
        if count == 1:
            display = name
        elif count == 2:
            display = f"{name} (Alt)"
        else:
            display = f"{name} (Alt {count - 1})"
        chara[str(card_id)] = display

    if chara:
        write_json(data_dir / "chara_list.json", chara)
    return {"file": "chara_list.json", "rows": len(chara)}


def synthesize_support_list(base_dir, master_data):
    data_dir = Path(base_dir) / "data"
    names = text_map(master_rows(master_data, "cat_75_text"))
    rarity_map = {
        1: "R",
        2: "SR",
        3: "SSR",
    }
    command_type_map = {
        101: "Speed",
        102: "Power",
        103: "Guts",
        105: "Stamina",
        106: "Wisdom",
    }
    support_card_type_map = {
        2: "Friends",
        3: "Group",
    }
    supports = {}
    for row in master_rows(master_data, "support_card_data"):
        support_id = int(row.get("id") or 0)
        if not support_id:
            continue
        key = str(support_id)
        support_type = support_card_type_map.get(int(row.get("support_card_type") or 0))
        if not support_type:
            support_type = command_type_map.get(int(row.get("command_id") or 0), "")
        supports[key] = {
            "name": display_name(names.get(support_id, str(support_id))),
            "rarity": rarity_map.get(int(row.get("rarity") or 0), ""),
            "type": support_type,
        }
    if supports:
        write_json(data_dir / "support_list.json", supports)
    return {"file": "support_list.json", "rows": len(supports)}


GRADE_LABELS = {
    100: "G1",
    200: "G2",
    300: "G3",
    400: "OP",
    700: "PRE-OP",
}

TRACK_LABELS = {
    10001: "Sapporo",
    10002: "Hakodate",
    10003: "Niigata",
    10004: "Fukushima",
    10005: "Nakayama",
    10006: "Tokyo",
    10007: "Chukyo",
    10008: "Kyoto",
    10009: "Hanshin",
    10010: "Kokura",
    10101: "Ooi",
}

MONTH_LABELS = [
    "",
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
]

YEAR_LABELS = {
    0: "Junior Year",
    24: "Classic Year",
    48: "Senior Year",
}


def distance_label(distance):
    distance = int(distance or 0)
    if distance <= 1400:
        return "Sprint"
    if distance <= 1800:
        return "Mile"
    if distance <= 2400:
        return "Medium"
    return "Long"


def year_offsets_for_permission(race_permission):
    return {
        1: [0],
        2: [24],
        3: [24, 48],
        4: [48],
    }.get(int(race_permission or 0), [])


def race_date_label(month, half, year_offset):
    period = "Early" if int(half or 0) == 1 else "Late"
    return f"{YEAR_LABELS[year_offset]} {period} {MONTH_LABELS[int(month or 0)]}"


def race_turn(month, half, year_offset):
    return int(year_offset or 0) + (int(month or 0) - 1) * 2 + int(half or 0)


def race_occurrence_id(program_id, year_offset):
    year_key = {
        0: 1,
        24: 2,
        48: 3,
    }.get(int(year_offset or 0), 9)
    return year_key * 100000 + int(program_id or 0)


def build_race_context(master_data):
    race_names = text_map(master_rows(master_data, "cat_28_text"))
    races = {int(row.get("id") or 0): row for row in master_rows(master_data, "race")}
    course_sets = {int(row.get("id") or 0): row for row in master_rows(master_data, "race_course_set")}
    instances = {int(row.get("id") or 0): row for row in master_rows(master_data, "race_instance")}
    programs = {}

    for row in master_rows(master_data, "single_mode_program"):
        program_id = int(row.get("id") or 0)
        race_instance_id = int(row.get("race_instance_id") or 0)
        if not program_id or not race_instance_id:
            continue
        instance = instances.get(race_instance_id, {})
        race = races.get(int(instance.get("race_id") or 0), {})
        course = course_sets.get(int(race.get("course_set") or 0), {})
        name = race_names.get(race_instance_id, str(race_instance_id))
        programs[program_id] = {
            "program": row,
            "race_instance_id": race_instance_id,
            "race": race,
            "course": course,
            "name": name,
        }
    return programs


def is_ui_selectable_race(info):
    program = info["program"]
    race = info["race"]
    name = info["name"]
    if int(program.get("base_program_id") or 0) != 0:
        return False
    if not year_offsets_for_permission(program.get("race_permission")):
        return False
    if int(race.get("grade") or 0) not in GRADE_LABELS:
        return False
    if "Make Debut" in name or "Maiden Race" in name:
        return False
    return True


def legacy_race_ids_by_occurrence(existing_meta):
    legacy = {}
    for key, value in (existing_meta or {}).items():
        try:
            race_id = int(key)
            program_id = int((value or {}).get("program_id") or 0)
            turn = int((value or {}).get("turn") or 0)
        except (TypeError, ValueError):
            continue
        if not race_id or not program_id or not turn:
            continue
        if race_id == program_id or race_id >= 100000:
            continue
        legacy.setdefault((program_id, turn), []).append(race_id)
    return {key: sorted(set(value)) for key, value in legacy.items()}


def synthesize_public_race_data(base_dir, race_context, existing_meta=None):
    races = []
    legacy_ids = legacy_race_ids_by_occurrence(existing_meta)
    for program_id, info in sorted(race_context.items()):
        if not is_ui_selectable_race(info):
            continue
        program = info["program"]
        race = info["race"]
        course = info["course"]
        month = int(program.get("month") or 0)
        half = int(program.get("half") or 0)
        for year_offset in year_offsets_for_permission(program.get("race_permission")):
            turn = race_turn(month, half, year_offset)
            row = {
                "id": race_occurrence_id(program_id, year_offset),
                "program_id": program_id,
                "turn": turn,
                "name": info["name"],
                "date": race_date_label(month, half, year_offset),
                "type": GRADE_LABELS.get(int(race.get("grade") or 0), ""),
                "terrain": "Dirt" if int(course.get("ground") or 0) == 2 else "Turf",
                "distance": distance_label(course.get("distance")),
                "venue": TRACK_LABELS.get(int(course.get("race_track_id") or 0), ""),
            }
            row_legacy_ids = legacy_ids.get((program_id, turn), [])
            if row_legacy_ids:
                row["legacy_ids"] = row_legacy_ids
            races.append(row)

    def sort_key(item):
        year_offset = next(offset for offset, label in YEAR_LABELS.items() if item["date"].startswith(label))
        month = MONTH_LABELS.index(item["date"].split()[-1])
        half = 1 if " Early " in item["date"] else 2
        return (year_offset + (month - 1) * 2 + half, item["type"], item["name"], item["id"])

    races.sort(key=sort_key)
    path = Path(base_dir) / "public" / "assets" / "data" / "uma_race_data.json"
    write_json(path, {"races": races})
    return {"file": "public/assets/data/uma_race_data.json", "rows": len(races)}


def synthesize_race_map(base_dir, master_data):
    data_dir = Path(base_dir) / "data"
    existing = read_json(data_dir / "race_map.json", {})
    existing_public = read_json(Path(base_dir) / "public" / "assets" / "data" / "uma_race_data.json", {})
    race_context = build_race_context(master_data)
    programs = {}
    instances = {}
    meta = {}

    for program_id, info in sorted(race_context.items()):
        row = info["program"]
        race_instance_id = info["race_instance_id"]
        month = int(row.get("month") or 0)
        half = int(row.get("half") or 0)
        programs[str(program_id)] = {
            "race_instance_id": race_instance_id,
            "month": month,
            "half": half,
            "name": info["name"],
        }
        instances.setdefault(str(race_instance_id), []).append(program_id)
        for year_offset in year_offsets_for_permission(row.get("race_permission")):
            occurrence_id = race_occurrence_id(program_id, year_offset)
            meta[str(occurrence_id)] = {
                "program_id": program_id,
                "race_instance_id": race_instance_id,
                "turn": race_turn(month, half, year_offset),
                "name": info["name"],
            }

    if programs:
        public_result = synthesize_public_race_data(base_dir, race_context, existing.get("meta") or {})
        current_public = read_json(Path(base_dir) / "public" / "assets" / "data" / "uma_race_data.json", {})
        generated_by_key = {
            (row["name"], row["date"]): row
            for row in current_public.get("races", [])
        }
        for row in existing_public.get("races", []):
            generated = generated_by_key.get((row.get("name"), row.get("date")))
            if not generated:
                continue
            legacy_id = int(row.get("id") or 0)
            program_id = int(generated.get("program_id") or generated.get("id") or 0)
            if not legacy_id or not program_id or legacy_id == program_id:
                continue
            info = race_context.get(program_id)
            if not info:
                continue
            program = info["program"]
            year_offset = next(offset for offset, label in YEAR_LABELS.items() if row["date"].startswith(label))
            turn = race_turn(program.get("month"), program.get("half"), year_offset)
            meta[str(legacy_id)] = {
                "program_id": program_id,
                "race_instance_id": info["race_instance_id"],
                "turn": turn,
                "name": info["name"],
            }

        for key, value in (existing.get("meta") or {}).items():
            if str(key) in meta:
                continue
            program_id = int((value or {}).get("program_id") or 0)
            if program_id in race_context:
                meta[str(key)] = value

        output = {
            "meta": meta,
            "program": programs,
            "instance": {key: sorted(value) for key, value in instances.items()},
        }
        write_json(data_dir / "race_map.json", output)
        return {
            "file": "race_map.json",
            "programs": len(programs),
            "instances": len(instances),
            "meta": len(meta),
            "public_races": public_result["rows"],
        }

    write_json(data_dir / "race_map.json", existing)
    return {"file": "race_map.json", "programs": 0, "instances": 0, "preserved_existing": bool(existing)}


def factor_category(factor_id):
    text = str(factor_id)
    if len(text) == 3:
        return "stat"
    if len(text) == 4:
        return "aptitude"
    if len(text) == 7:
        if text.startswith("1"):
            return "race"
        if text.startswith("2"):
            return "skill"
        if text.startswith("3"):
            return "scenario"
    if len(text) == 8:
        return "unique"
    return "other"


def synthesize_factor_map(base_dir, master_data):
    data_dir = Path(base_dir) / "data"
    factors = {}
    for row in master_rows(master_data, "cat_147_text"):
        factor_id = int(row.get("index") or 0)
        if not factor_id:
            continue
        factors[str(factor_id)] = {
            "name": row.get("text", ""),
            "stars": factor_id % 10,
            "category": factor_category(factor_id),
        }

    if factors:
        write_json(data_dir / "factor_map.json", factors)
    return {"file": "factor_map.json", "rows": len(factors)}


def synthesize_legacy_jsons(base_dir, master_data):
    generated = [
        synthesize_skill_data(base_dir, master_data),
        synthesize_chara_list(base_dir, master_data),
        synthesize_support_list(base_dir, master_data),
        synthesize_race_map(base_dir, master_data),
        synthesize_factor_map(base_dir, master_data),
    ]

    return {"generated": generated, "preserved": []}


def load_master_data(cursor, existing_tables):
    master_data = {"tables": {}, "text": {}}
    extracted = []
    skipped = []

    for table in DIRECT_TABLES:
        if table not in existing_tables:
            skipped.append(table)
            continue
        rows = dump_table(cursor, table)
        master_data["tables"][table] = rows
        extracted.append({"table": table, "rows": len(rows)})

    if "text_data" in existing_tables:
        for filename, category in TEXT_DATA_CATEGORIES.items():
            rows = dump_text_data_category(cursor, category)
            master_data["text"][filename] = rows
            extracted.append({"table": filename, "rows": len(rows)})
    else:
        skipped.extend(TEXT_DATA_CATEGORIES)

    return master_data, extracted, skipped


def generate(base_dir, master_mdb_path=None):
    db_path = Path(master_mdb_path).expanduser() if master_mdb_path else configured_master_mdb_path(base_dir)
    exists, access_error = path_access(db_path)
    if not exists:
        detail = f"master.mdb not found at {db_path}"
        if access_error:
            detail = f"master.mdb could not be accessed at {db_path}: {access_error}"
        return {
            **status(base_dir),
            "success": False,
            "detail": detail,
        }

    with sqlite3.connect(str(db_path)) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        existing_tables = {row[0] for row in cursor.fetchall()}
        master_data, extracted, skipped = load_master_data(cursor, existing_tables)

    legacy = synthesize_legacy_jsons(base_dir, master_data)
    return {
        **status(base_dir),
        "success": True,
        "extracted": extracted,
        "skipped": skipped,
        "legacy": legacy,
    }
