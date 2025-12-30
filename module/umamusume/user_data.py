from bot.base.user_data import *
import json
import os
import glob

presets_path = "/umamusume/presets"
starter_presets_path = "/umamusume/starter_presets"


def read_presets():
    folder = base_path + presets_path
    starter_folder = base_path + starter_presets_path
    preset_list = []
    seen_names = set()
    
    # Read from regular presets first (user-created/modified take priority)
    if os.path.exists(folder):
        files = glob.glob(os.path.join(folder, '*.json'))
        for file in files:
            with open(file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                preset_list.append(data)
                seen_names.add(data['name'])
    
    # Read from starter presets (only if no user preset with same name exists)
    if os.path.exists(starter_folder):
        files = glob.glob(os.path.join(starter_folder, '*.json'))
        for file in files:
            with open(file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Only add starter preset if no user preset with same name exists
                if data['name'] not in seen_names:
                    preset_list.append(data)
    
    return preset_list


def write_preset(preset_json: str):
    preset_info = json.loads(preset_json)
    name = preset_info['name']
    
    # Check if this is overwriting a starter preset by searching through starter preset files
    starter_folder = base_path + starter_presets_path
    starter_preset_file = None
    
    if os.path.exists(starter_folder):
        files = glob.glob(os.path.join(starter_folder, '*.json'))
        for file in files:
            try:
                with open(file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if data.get('name') == name:
                        starter_preset_file = file
                        break
            except:
                continue
    
    if starter_preset_file:
        # Overwrite the starter preset file
        with open(starter_preset_file, 'w', encoding='utf-8') as f:
            json.dump(preset_info, f, indent=2, ensure_ascii=False)
    else:
        # Check if there's already a user preset with this name
        folder = base_path + presets_path
        user_filepath = os.path.join(folder, f"{name}.json")
        if os.path.exists(user_filepath):
            # Overwrite existing user preset
            write_file(presets_path+"/"+name+".json", preset_json)
        else:
            # Create new user preset
            write_file(presets_path+"/"+name+".json", preset_json)


def is_starter_preset(name: str):
    """Check if a preset name corresponds to a starter preset by searching through files"""
    starter_folder = base_path + starter_presets_path
    if not os.path.exists(starter_folder):
        return False
    
    files = glob.glob(os.path.join(starter_folder, '*.json'))
    for file in files:
        try:
            with open(file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if data.get('name') == name:
                    return True
        except:
            continue
    return False


def delete_preset_by_name(name: str):
    # Don't allow deletion of starter presets
    if is_starter_preset(name):
        return False
    
    folder = base_path + presets_path
    filepath = os.path.join(folder, f"{name}.json")
    if os.path.exists(filepath):
        os.remove(filepath)
        return True
    return False

PAL_DEFAULTS: dict = {
    "5 event chain (Defaults optimized for riko)": [[4, 75, 0.27], [4, 80, 0.27], [5, 80, 0.27], [5, 80, 0.27], [5, 75, 0.27]],
    "4 event chain": [[2, 43, 0.9], [3, 17, 0.5], [1, 3, 0.8], [5, 88, 0.0]],
    "3 event chain": [[2, 43, 0.9], [3, 17, 0.5], [1, 3, 0.8]],
}

def read_pal_defaults() -> dict:
    return dict(PAL_DEFAULTS)









