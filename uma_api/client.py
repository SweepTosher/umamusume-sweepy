import base64
import json
import os
import time
import uuid
from curl_cffi import requests
import hashlib
import random
import struct
import msgpack
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
import subprocess
import platform
import socket
import shutil
from datetime import datetime
from pathlib import Path
from career_bot.delay import dna_sleep, dna_uniform, dna_gauss, dna_randint

class StateRecoveryError(Exception):
    pass

BASE_URL = 'https://api.games.umamusume.com/umamusume/'
DIR = str(Path(__file__).resolve().parent.parent)
LAST_TICKET_GEN_RESULT = None
LAST_SAVED_CONFIG = None


def runtime_output_root():
    override = os.environ.get("UMA_RUNTIME_DIR")
    if override:
        return Path(override).expanduser().resolve()

    here = Path(__file__).resolve()
    for candidate in here.parents:
        if (candidate / ".git").exists():
            return candidate / "uma_runtime"
    return here.parent.parent.parent / "uma_runtime"


TRACE_DIR = runtime_output_root() / "trace_logs"

TICKET_GEN_JS = """const SteamUser = require("steam-user");

const args = process.argv.slice(2);
let username = "";
let password = "";
let appid = 3224770;
let code = "";

for (let i = 0; i < args.length; i++) {
  if (args[i] === "--username") username = args[++i];
  else if (args[i] === "--password") password = args[++i];
  else if (args[i] === "--appid") appid = parseInt(args[++i]);
  else if (args[i] === "--code") code = args[++i];
}

if (!username || !password) {
  process.stderr.write(
    "Usage: node ticket_gen.js --username X --password Y [--code Z]\\n"
  );
  process.exit(1);
}

const client = new SteamUser();

const loginOpts = {
  accountName: username,
  password: password,
};

if (code) {
  loginOpts.twoFactorCode = code;
}

client.logOn(loginOpts);

client.on("steamGuard", (domain, callback) => {
  process.stderr.write(
    "NEED_GUARD:" + (domain || "2fa") + "\\n"
  );
  process.exit(2);
});

client.on("error", (err) => {
  process.stderr.write("ERROR:" + err.message + "\\n");
  process.exit(1);
});

client.on("loggedOn", () => {
  process.stderr.write(
    "Logged in as " + client.steamID.getSteamID64() + "\\n"
  );
  client.createAuthSessionTicket(appid, (err, sessionTicket) => {
    if (err) {
      process.stderr.write("Ticket error: " + err.message + "\\n");
      process.exit(1);
    }
    const buf = Buffer.isBuffer(sessionTicket) ? sessionTicket : sessionTicket.sessionTicket || sessionTicket;
    const result = {
      steam_id: client.steamID.getSteamID64(),
      session_ticket: Buffer.from(buf).toString("hex").toUpperCase(),
    };
    process.stdout.write(JSON.stringify(result) + "\\n");
    process.stderr.write(
      "Ticket generated (" + Buffer.from(buf).length + " bytes)\\n"
    );
    setTimeout(() => process.exit(0), 500);
  });
});
"""

SALT = b'co!=Y;(UQCGxJ_n82'
HEAD = bytes.fromhex('6b20e2ab6c311330f761d737ce3f3025750850665eea58b6372f8d2f57501eb344bdb7270a9067f5b63cd61f152cfb986cbfbf7a')
SENSITIVE_ERROR_KEYS = {"auth_key", "steam_session_ticket", "sid", "udid", "device_id"}


def redact_for_console(value, key=""):
    if key in SENSITIVE_ERROR_KEYS:
        return "<redacted>"
    if isinstance(value, dict):
        return {k: redact_for_console(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_for_console(item, key) for item in value[:20]]
    if isinstance(value, str) and len(value) > 160:
        return value[:160] + "...<truncated>"
    return value


def format_api_error(ep, rc, res):
    details = {
        "endpoint": ep,
        "response_code": res.get("response_code"),
        "result_code": rc,
        "data_headers": redact_for_console(res.get("data_headers") or {}),
    }
    data = res.get("data")
    if isinstance(data, dict):
        interesting = {}
        for key in (
            "error_code",
            "error_message",
            "message",
            "result_code",
            "viewer_id",
            "current_turn",
            "chara_info",
            "single_mode_chara_light",
        ):
            if key in data:
                interesting[key] = data[key]
        if interesting:
            details["data"] = redact_for_console(interesting)
    elif data is not None:
        details["data"] = redact_for_console(data)
    return json.dumps(details, ensure_ascii=False, default=str)

def sm5(data):
    h = hashlib.md5()
    h.update(data)
    h.update(SALT)
    return h.digest()

def make_sid(vid, udid):
    return sm5((str(vid) + udid).encode())

def next_sid(sid):
    return sm5(sid.encode())

def gen_key():
    out = b''
    while len(out) < 32:
        out += format(random.randint(0, 65535), 'x').encode()
    return out[:32]

def get_iv(udid):
    return udid.replace('-', '').lower()[:16].encode()

def get_raw_udid(udid):
    return bytes.fromhex(udid.replace('-', '').lower())

def pack(sid, udid_raw, auth, payload, udid):
    key = gen_key()
    p = msgpack.packb(payload, use_bin_type=True)
    body = AES.new(key, AES.MODE_CBC, get_iv(udid)).encrypt(pad(struct.pack('<I', len(p)) + p, 16)) + key
    h = HEAD + sid + udid_raw + os.urandom(32)
    if auth: h += auth
    return base64.b64encode(struct.pack('<I', len(h)) + h + body)

def unpack(text, udid):
    raw = base64.b64decode(text)
    key, cipher = raw[-32:], raw[:-32]
    p = unpad(AES.new(key, AES.MODE_CBC, get_iv(udid)).decrypt(cipher), 16)
    return msgpack.unpackb(p[4:4+struct.unpack('<I', p[:4])[0]], raw=False, strict_map_key=False)

def get_gpu():
    if platform.system() != "Windows":
        raise RuntimeError(f"Unsupported OS: {platform.system()}. Only Windows is supported for PC info consistency.")

    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Video") as video_key:
            for i in range(winreg.QueryInfoKey(video_key)[0]):
                adapter_guid = winreg.EnumKey(video_key, i)
                adapter_path = rf"SYSTEM\CurrentControlSet\Control\Video\{adapter_guid}\0000"
                try:
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, adapter_path) as adapter_key:
                        value, _ = winreg.QueryValueEx(adapter_key, "HardwareInformation.AdapterString")
                        if isinstance(value, bytes):
                            value = value.decode("utf-16-le", errors="ignore")
                        gpu_name = str(value).replace("\x00", "").strip()
                        if gpu_name:
                            return gpu_name
                except OSError:
                    continue
    except Exception as e:
        raise RuntimeError(f"Failed to fetch GPU info: {e}") from e

    raise RuntimeError("Failed to fetch GPU info: display adapter registry value empty")

def get_os():
    return f"Windows 11  ({platform.version()}) 64bit"

def get_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    ip = s.getsockname()[0]
    s.close()
    return ip

def get_hwid(seed_string="default"):
    guid = str(uuid.uuid4()).lower()
    
    if platform.system() != "Windows":
        raise RuntimeError(f"Unsupported OS: {platform.system()}. Only Windows is supported for HWID consistency.")
    
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\BIOS") as bios_key:
            device_name, _ = winreg.QueryValueEx(bios_key, "SystemProductName")
            device_name = str(device_name).strip()
            try:
                board_mfg, _ = winreg.QueryValueEx(bios_key, "BaseBoardManufacturer")
                if board_mfg:
                    device_name = f"{device_name} ({str(board_mfg).strip()})"
            except OSError:
                pass
        if not device_name:
            raise RuntimeError("System product name returned empty. Refusing to start.")
            
        machine_guid = ""
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as crypto_key:
                machine_guid, _ = winreg.QueryValueEx(crypto_key, "MachineGuid")
        except OSError:
            pass
            
    except Exception as e:
        raise RuntimeError(f"Failed to fetch system product name: {e}. Refusing to start.")

    hardware_string = f"{device_name}_{machine_guid}_{seed_string}"
    device_id = hashlib.sha1(hardware_string.encode()).hexdigest()

    return {
        'device_name': device_name,
        'graphics_device_name': get_gpu(),
        'platform_os_version': get_os(),
        'ip_address': get_ip(),
        'udid': guid,
        'device_id': device_id
    }

def check_deps():
    if not shutil.which('node'): raise Exception('node missing')
    if not os.path.exists(os.path.join(DIR, 'node_modules')):
        subprocess.run(['npm', 'install', '--silent'], check=True, cwd=DIR)

def get_ticket(u, p, c=''):
    global LAST_TICKET_GEN_RESULT
    check_deps()
    cmd = ['node', '-e', TICKET_GEN_JS, '--', '--dummy', '--username', u, '--password', p]
    if c: cmd += ['--code', c]
    
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=DIR)
    LAST_TICKET_GEN_RESULT = {
        'stdout': proc.stdout,
        'stderr': proc.stderr,
        'returncode': proc.returncode,
    }
    if proc.returncode == 2:
        raise Exception('STEAM_GUARD_REQUIRED')
        
    out = proc.stdout.strip()
    if not out or proc.returncode != 0:
        error_msg = proc.stderr.strip() or 'fail'
        raise Exception(error_msg)
        
    line = out.split('\n')[-1]
    try:
        d = json.loads(line)
        return d['steam_id'], d['session_ticket']
    except:
        raise Exception('bad json')

class UmaClient:

    def __init__(self, cfg, trace_enabled=True):
        profile = get_hwid(cfg.get('steam_password_seed', 'default'))

        self.viewer_id = cfg.get('viewer_id', 0)
        self.udid_str = cfg.get('udid') or profile['udid']
        self.auth_key_hex = cfg.get('auth_key', '')
        self.steam_id = str(cfg.get('steam_id', ''))
        self.steam_ticket = cfg.get('steam_session_ticket', '')
        
        self.device_id = cfg.get('device_id') or profile['device_id']
        self.device_name = cfg.get('device_name') or profile['device_name']
        self.graphics_device = cfg.get('graphics_device_name') or profile['graphics_device_name']
        self.ip_address = cfg.get('ip_address') or profile['ip_address']
        self.platform_os = cfg.get('platform_os_version') or profile['platform_os_version']
        self.locale = cfg.get('locale', 'JPN')
        
        self.unity_ver = cfg.get('unity_ver', '2022.3.62f2')
        self.app_ver = cfg.get('app_ver', '')
        self.res_ver = cfg.get('res_ver', '')

        if not self.app_ver or not self.res_ver:
             pass

        self.sid = bytes(16)
        self.cached_load_data = {}
        self.tp_info = {}
        self.coin_info = {}
        self.item_map = {}
        self.current_scenario_id = None
        self.session = requests.Session()
        self.update_headers()
        self.api_jitter = dna_uniform(-0.02, 0.02)

        self.on_api_log = None
        self.trace_file = None
        if trace_enabled:
            self._init_trace_log()

    def _init_trace_log(self):
        try:
            log_dir = TRACE_DIR / "api_payloads"
            log_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            suffix = uuid.uuid4().hex[:6]
            self.trace_file = log_dir / f"{ts}_{suffix}_payloads.jsonl"
        except Exception as e:
            print(f"Error initializing trace log: {e}")
            self.trace_file = None

    def api_log(self, direction, ep, data, req_id=None):
        log_entry = {
            "ts": time.time(),
            "direction": direction,
            "endpoint": ep,
            "data": data
        }
        if req_id:
            log_entry["req_id"] = req_id
            
        if callable(self.on_api_log):
            try:
                self.on_api_log(direction, ep, data, req_id)
            except Exception:
                pass
        
        if self.trace_file:
            try:
                def _json_default(obj):
                    if isinstance(obj, bytes):
                        return obj.hex()
                    return str(obj)

                with open(self.trace_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(log_entry, ensure_ascii=False, default=_json_default) + "\n")
            except Exception as e:
                print(f"Error writing to log: {e}")

    def api_payload_summary(self, ep, payload):
        payload = payload or {}
        summary = {"current_turn": payload.get("current_turn")}
        if ep == "single_mode_free/gain_skills":
            summary["gain_skill_info_array"] = payload.get("gain_skill_info_array") or []
        elif ep == "single_mode_free/multi_item_exchange":
            summary["exchange_item_info_array"] = payload.get("exchange_item_info_array") or []
        elif ep == "single_mode_free/multi_item_use":
            summary["use_item_info_array"] = payload.get("use_item_info_array") or []
        return summary

    def safe_payload(self, payload):
        return dict(payload or {})

    def response_summary(self, res):
        data = res.get("data") or {}
        headers = res.get("data_headers") or {}
        chara = data.get("chara_info") or data.get("single_mode_chara_light") or {}
        home = data.get("home_info") or {}
        events = data.get("unchecked_event_array") or []
        race = data.get("race_start_info") or {}
        summary = {
            "result_code": headers.get("result_code"),
            "keys": list(data.keys()),
        }
        if chara:
            summary["chara"] = {
                "turn": chara.get("turn"),
                "vital": chara.get("vital"),
                "max_vital": chara.get("max_vital"),
                "skill_point": chara.get("skill_point"),
                "fans": chara.get("fans"),
                "playing_state": chara.get("playing_state"),
            }
        if home:
            summary["commands"] = [
                {
                    "type": item.get("command_type"),
                    "id": item.get("command_id"),
                    "group": item.get("command_group_id"),
                    "enable": item.get("is_enable"),
                    "fail": item.get("failure_rate"),
                }
                for item in home.get("command_info_array") or []
            ]
        if events:
            summary["events"] = [
                {
                    "event_id": item.get("event_id"),
                    "chara_id": item.get("chara_id"),
                    "choices": len(((item.get("event_contents_info") or {}).get("choice_array") or [])),
                }
                for item in events
            ]
        if race:
            summary["race_start_info"] = {
                "program_id": race.get("program_id"),
                "race_instance_id": race.get("race_instance_id"),
                "is_short": race.get("is_short"),
            }
        return summary

    def auth_bytes(self):
        if not self.auth_key_hex or self.auth_key_hex == 'YOUR_AUTH_KEY_HERE':
            return b''
        return bytes.fromhex(self.auth_key_hex)

    def has_captured_auth(self):
        try:
            int(self.viewer_id)
            bytes.fromhex(str(self.auth_key_hex))
        except (TypeError, ValueError):
            return False
        return bool(
            self.viewer_id
            and self.udid_str
            and self.auth_key_hex
            and self.auth_key_hex != 'YOUR_AUTH_KEY_HERE'
            and self.steam_id
            and self.steam_ticket
        )

    def refresh_cached_account_state(self, data):
        if not data:
            return
        self.cached_load_data.update(data)
        if data.get('tp_info'):
            self.tp_info = data['tp_info']
        if data.get('coin_info'):
            self.coin_info = data['coin_info']

        item_list = data.get('user_item') or data.get('user_item_array') or data.get('item_list')
        if isinstance(item_list, list):
            for item in item_list:
                iid = item.get('item_id')
                num = item.get('number')
                if iid is not None and num is not None:
                    self.item_map[int(iid)] = int(num)

    def regen_sid(self):
        self.sid = make_sid(self.viewer_id, self.udid_str)

    def common(self):
        return {
            'viewer_id': self.viewer_id, 'device': 4, 'device_id': self.device_id,
            'device_name': self.device_name, 'graphics_device_name': self.graphics_device,
            'ip_address': self.ip_address, 'platform_os_version': self.platform_os,
            'carrier': '', 'keychain': 0, 'locale': self.locale,
            'button_info': '', 'dmm_viewer_id': None, 'dmm_onetime_token': None,
            'steam_id': self.steam_id,
            'steam_session_ticket': self.steam_ticket
        }

    def update_headers(self):
        self.session.headers.update({
            'User-Agent': f'UnityPlayer/{self.unity_ver} (UnityWebRequest/1.0, libcurl/8.10.1-DEV)',
            'Accept': '*/*', 'Accept-Encoding': 'deflate, gzip',
            'Content-Type': 'application/x-msgpack', 'X-Unity-Version': self.unity_ver
        })

    def call(self, ep, args=None, retry_208=6, retry_205=3):
        if not hasattr(self, '_last_raw_call_ts'):
            self._last_raw_call_ts = 0

        el = time.time() - self._last_raw_call_ts
        if el < 0.14:
            dna_sleep(0.14 - el, 0.14 - el)

        self._last_raw_call_ts = time.time()

        req_id = str(uuid.uuid4())[:8]
        payload = args or {}
        payload.update(self.common())
        
        if ep == 'single_mode_free/race_out':
            import ctypes
            try:
                user32 = ctypes.windll.user32
                user32.SetProcessDPIAware()
                screen_h = user32.GetSystemMetrics(1)
            except Exception:
                screen_h = 864
                
            window_w = int(screen_h * 9 / 16)
            scale_factor = 1080 / window_w
            
            ref_x = max(844, min(1150, int(dna_gauss(991, 62))))
            ref_y = max(55, min(255, int(dna_gauss(144, 33))))
            
            physical_x = int(ref_x / scale_factor)
            physical_y = int(ref_y / scale_factor)
            
            click_x = int(physical_x * scale_factor * 10000)
            click_y = int(physical_y * scale_factor * 10000)
            
            click_ts = int(time.time() - dna_uniform(3.0, 4.5))
            btn = {
                "ViewerId": self.viewer_id,
                "DeviceId": 4,
                "ScenarioId": self.current_scenario_id,
                "ClickPosX": click_x,
                "ClickPosY": click_y,
                "ClickServerTime": click_ts
            }
            payload['button_info'] = json.dumps(btn, separators=(',', ':'))

        body = pack(self.sid, get_raw_udid(self.udid_str), self.auth_bytes(), payload, self.udid_str)
        headers = {
            'SID': self.sid.hex(), 'Device': '4', 'ViewerID': str(self.viewer_id),
            'APP-VER': self.app_ver, 'RES-VER': self.res_ver,
        }
        

        self.api_log("REQ", ep, {
            "payload": payload,
        }, req_id)
        
        max_retries = 8
        for attempt in range(max_retries):
            try:
                resp = self.session.post(BASE_URL + ep, data=body, headers=headers, timeout=30)
                break
            except Exception as e:
                if attempt < max_retries - 1:
                    wait_time = min(1.0 + (attempt * 2.5), 15.0)
                    dna_sleep(wait_time, wait_time)
                    continue
                self.api_log("ERR", ep, {"error": str(e)}, req_id)
                raise Exception(f'Network error on {ep}: {e}')

        if resp.status_code != 200:
            body_preview = resp.text[:500] if resp.text else ""
            self.api_log("ERR", ep, {"http_status": resp.status_code, "body": body_preview}, req_id)
            print(f"HTTP error on {ep}: status={resp.status_code} body={body_preview}")
            raise Exception(f'HTTP {resp.status_code} on {ep}: {body_preview}')
            
        res = unpack(resp.text.strip(), self.udid_str)
        dh = res.get('data_headers', {})
        rc = dh.get('result_code', 0)
        
        self.api_log("RES", ep, res, req_id)
        
        data = res.get('data', {})
        if isinstance(data, dict):
            if data.get('tp_info'):
                self.tp_info = data['tp_info']
            if data.get('coin_info'):
                self.coin_info = data['coin_info']
            if data.get('chara_info') and data['chara_info'].get('scenario_id'):
                self.current_scenario_id = data['chara_info']['scenario_id']
            item_list = data.get('user_item') or data.get('user_item_array')
            if isinstance(item_list, list):
                for item in item_list:
                    iid = item.get('item_id')
                    num = item.get('number')
                    if iid is not None and num is not None:
                        self.item_map[int(iid)] = int(num)
        
        if rc == 709:
            new_vid = dh.get('viewer_id') or res.get('data', {}).get('viewer_id')
            if new_vid and new_vid != self.viewer_id:
                print(f"VIEWER ID MISMATCH on 709: {self.viewer_id} -> {new_vid}")
                self.viewer_id = new_vid
                self.regen_sid()
            raise Exception(f'709 on {ep}')
        if rc != 1:
            if rc == 205 and retry_205 > 0:
                print(f"205 on {ep}, retrying... ({retry_205} left)")
                dna_sleep(0.14, 0.19, 0.166, 0.0083)
                return self.call(ep, args, retry_208=retry_208, retry_205=retry_205 - 1)

            if rc == 208 and retry_208 > 0:
                if ep in {"single_mode_free/gain_skills", "single_mode_free/multi_item_exchange", "single_mode_free/multi_item_use"}:
                    return res

                if retry_208 < 6:
                    print(f"API error 208 (SERVER BUSY) on {ep}, sleeping and retrying... (attempts left: {retry_208-1})")
                    dna_sleep(0.6, 1.4, 1.0, 0.1)
                return self.call(ep, args, retry_208=retry_208 - 1)
            err_detail = format_api_error(ep, rc, res)
            err_msg = f'API error {rc} on {ep}: {err_detail}'
            if not (rc == 102 and ep in {"single_mode_free/race_end", "single_mode_free/race_out"}):
                print(err_msg)
            raise Exception(err_msg)
        if dh.get('sid') and isinstance(dh['sid'], str) and dh['sid'].strip():
            self.sid = next_sid(dh['sid'])
        
        return res

    def hard_reset(self):
        self.sid = bytes(16)
        self.regen_sid()
        self.session.close()
        self.session = requests.Session()
        self.update_headers()
        try:
            self.call('tool/start_session', {'attestation_type': 0, 'device_token': None})
            res = self.call('load/index', {
                'adid': ''
            })
            data = res.get('data', {})
            self.refresh_cached_account_state(data)
            self.read_info()
            
            try:
                sm_res = self.call('single_mode_free/load', {})
                chara = sm_res.get('data', {}).get('chara_info')
                if not chara:
                    raise StateRecoveryError("No chara_info returned in single_mode_free/load after hard reset.")
            except Exception as e:
                if isinstance(e, StateRecoveryError):
                    raise
                if "API error 201" in str(e) or "API error 102" in str(e):
                    raise StateRecoveryError(f"Cannot recover training state: {e}")
                print(f"single_mode_free/load during hard_reset failed: {e}")

            return res
        except StateRecoveryError:
            raise
        except Exception as e:
            print(f"Hard Reset Failure: {e}")
            raise

    def signup(self):
        self.regen_sid()
        self.call('tool/pre_signup')
        dna_sleep(0.83, 0.83)
        self.regen_sid()
        res = self.call('tool/signup', {
            'error_code': 0, 'error_message': '', 'attestation_type': 0, 
            'optin_user_birth': 199801, 'dma_state': 0, 'country': 'Canada', 'credential': ''
        })
        d = res.get('data', {})
        if d.get('viewer_id'): 
            self.viewer_id = d['viewer_id']
        if d.get('auth_key'): self.auth_key_hex = base64.b64decode(d['auth_key']).hex()
        self.save_config()
        return res

    def login(self, max_retries=3):
        using_existing_auth = self.has_captured_auth()
        if not using_existing_auth:
            self.signup()
            using_existing_auth = self.has_captured_auth()

        old_h = dict(self.session.headers)
        self.session.close()
        self.session = requests.Session()
        self.session.headers.update(old_h)

        for attempt in range(max_retries + 1):
            try:
                self.regen_sid()
                self.call('tool/start_session', {'attestation_type': 0, 'device_token': None})
                res = self.call('load/index', {'adid': ''})
                data = res.get('data', {})
                self.refresh_cached_account_state(data)
                self.read_info()
                return res
            except Exception as e:
                err = str(e)
                if '709' in err and attempt < max_retries:
                    dna_sleep(0.83, 0.83)
                    continue
                if '394' in err and attempt < max_retries:
                    dna_sleep(2.5, 2.5)
                    continue
                if '202' in err and attempt < max_retries:
                    dna_sleep(4.15, 4.15)
                    continue
                raise

    def recovery_tp(self, count=1):
        total_jewels = self.coin_info.get("fcoin", 0) + self.coin_info.get("coin", 0)
        result = self.call("user/recovery_trainer_point", {
            "count": count,
            "client_own_num": total_jewels,
        })
        data = result.get("data", {})
        tp = data.get("tp_info", {})
        if tp:
            self.tp_info = tp
        coin = data.get("coin_info", {})
        if coin:
            self.coin_info = coin
        return tp

    def read_info(self):
        return self.call('read_info/index', {
            'add_home_story_data_array': [],
            'add_short_episode_data_array': [],
            'add_home_poster_data_array': [],
            'add_tutorial_guide_data_array': [],
            'add_released_episode_data_array': [],
        })

    def finish_career(self, current_turn, is_force_delete=False):
        return self.call('single_mode_free/finish', {
            'is_force_delete': is_force_delete,
            'current_turn': current_turn
        })

    def load_career(self):
        return self.call('single_mode_free/load', {})

    def minigame_end(self, current_turn, result_state=1, result_value=0, result_detail_array=None):
        return self.call('single_mode_free/minigame_end', {
            'result': {
                'result_state': result_state,
                'result_value': result_value,
                'result_detail_array': result_detail_array,
            },
            'current_turn': current_turn,
        })
    
    def save_config(self, cfg_path=None):
        global LAST_SAVED_CONFIG
        LAST_SAVED_CONFIG = {
            "viewer_id": self.viewer_id,
            "udid": self.udid_str,
            "auth_key": self.auth_key_hex,
            "steam_id": self.steam_id,
            "steam_session_ticket": self.steam_ticket,
            "device_id": self.device_id,
            "device_name": self.device_name,
            "graphics_device_name": self.graphics_device,
            "ip_address": self.ip_address,
            "platform_os_version": self.platform_os,
        }

    def pre_single_mode(self, exclude_viewer_ids=None):
        payload = {}
        if exclude_viewer_ids:
            payload['exclude_viewer_id_array'] = exclude_viewer_ids
        return self.call('pre_single_mode/index', payload)

    def start_career(self, card_id, support_card_ids, friend_viewer_id, friend_card_id,
                     parent_id_1, parent_id_2, scenario_id, deck_id=1, use_tp=30,
                     tp_info=None, current_money=0, succession_rank_point=0,
                     rental_viewer_id=0, rental_trained_chara_id=0,
                     difficulty_id=0, difficulty=0, is_boost=0,
                     boost_story_event_id=0):
        if not tp_info:
            tp_info = {'current_tp': 100, 'max_tp': 100, 'max_recovery_time': 0}
        start_payload = {
            'start_chara': {
                'card_id': card_id,
                'support_card_ids': support_card_ids,
                'friend_support_card_info': {
                    'viewer_id': friend_viewer_id,
                    'support_card_id': friend_card_id
                },
                'succession_trained_chara_id_1': parent_id_1,
                'succession_trained_chara_id_2': parent_id_2,
                'rental_succession_trained_chara': {
                    'viewer_id': rental_viewer_id,
                    'trained_chara_id': rental_trained_chara_id,
                    'is_circle_member': False,
                    'is_event_rental': False
                },
                'scenario_id': scenario_id,
                'selected_difficulty_info': {
                    'difficulty_id': difficulty_id,
                    'difficulty': difficulty,
                    'is_boost': is_boost
                },
                'select_deck_id': deck_id,
                'boost_story_event_id': boost_story_event_id,
                'is_play_training_challenge': False
            },
            'tp_info': tp_info,
            'current_money': current_money,
            'use_tp': use_tp,
            'current_succession_rank_point': succession_rank_point
        }
        return self.call('single_mode_free/start', start_payload)

    def exec_command(self, command_type, command_id, current_turn, current_vital, command_group_id=0, select_id=0):
        return self.call('single_mode_free/exec_command', {
            'command_type': command_type,
            'command_id': command_id,
            'command_group_id': command_group_id,
            'select_id': select_id,
            'current_turn': current_turn,
            'current_vital': current_vital
        })

    def check_event(self, event_id, current_turn, chara_id=0, choice_number=0):
        payload = {
            'event_id': event_id,
            'chara_id': chara_id or 0,
            'choice_number': choice_number if choice_number is not None else 0,
            'current_turn': current_turn
        }
        return self.call('single_mode_free/check_event', payload)

    def use_items(self, use_item_info_array, current_turn):
        return self.call('single_mode_free/multi_item_use', {
            'use_item_info_array': use_item_info_array,
            'current_turn': current_turn
        })

    def exchange_items(self, exchange_item_info_array, current_turn):
        return self.call('single_mode_free/multi_item_exchange', {
            'exchange_item_info_array': exchange_item_info_array,
            'current_turn': current_turn
        })

    def gain_skills(self, gain_skill_info_array, current_turn):
        gain_skill_info_array = [
            {
                "skill_id": item.get("skill_id"),
                "level": item.get("level", item.get("skill_level", 1)),
            }
            for item in gain_skill_info_array
        ]
        return self.call('single_mode_free/gain_skills', {
            'gain_skill_info_array': gain_skill_info_array,
            'current_turn': current_turn
        })

    def race_entry(self, program_id, current_turn, running_style=None, retry_208=6, retry_205=3):
        if running_style is not None:
            payload = {
                'program_id': program_id,
                'running_style': running_style,
                'current_turn': current_turn
            }
            return self.call('single_mode_free/change_running_style', payload, retry_208=retry_208, retry_205=retry_205)
        else:
            payload = {
                'program_id': program_id,
                'current_turn': current_turn
            }
            return self.call('single_mode_free/race_entry', payload, retry_208=retry_208, retry_205=retry_205)

    def race_start(self, is_short, current_turn):
        return self.call('single_mode_free/race_start', {
            'is_short': is_short,
            'current_turn': current_turn
        })

    def race_end(self, current_turn):
        return self.call('single_mode_free/race_end', {
            'current_turn': current_turn
        })

    def race_out(self, current_turn):
        return self.call('single_mode_free/race_out', {
            'current_turn': current_turn
        })

    def race_continue(self, current_turn, continue_type):
        return self.call('single_mode_free/continue', {
            'current_turn': current_turn,
            'continue_type': continue_type
        })

    def reserve_race(self, current_turn, add_race_array=None, cancel_race_array=None):
        return self.call('single_mode_free/reserve_race', {
            'current_turn': current_turn,
            'add_race_array': add_race_array or [],
            'cancel_race_array': cancel_race_array or []
        })
