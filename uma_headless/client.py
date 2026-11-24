from __future__ import annotations

import base64
import functools
import hashlib
import json
import os
import random
import re
import struct
import time
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

import msgpack
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from curl_cffi import requests

from .device import (
    DEFAULT_LOCALE,
    DEFAULT_RES_VER,
    HeadlessAuthError,
    compute_steam_id_hash,
    device_state_record,
    ensure_private_runtime_dir,
    read_device_state,
    runtime_device_fields,
    write_device_state,
)
from .steam_cm import SteamTicketError, SteamTicketProvider
from .timing_dna import (
    HARD_CALL_FLOOR_SECONDS,
    TimingDNA,
    make_race_out_button_info,
)

BASE_URL = "https://api.games.umamusume.com/umamusume/"
OFFICIAL_API_SCHEME = "https"
OFFICIAL_API_HOST = "api.games.umamusume.com"
OFFICIAL_API_PATH = "/umamusume/"
API_ENDPOINT_RE = re.compile(r"\A[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*\Z")

APP_LOOKUP_URL = "https://itunes.apple.com/lookup?id=6480433538"
APP_LOOKUP_TRACK_ID = 6480433538
APP_LOOKUP_BUNDLE_ID = "com.cygames.umamusume"
APP_LOOKUP_TIMEOUT_SECONDS = 5
APP_LOOKUP_MAX_BYTES = 64 * 1024

DEFAULT_APP_VER = "1.34.0"
DEFAULT_UNITY_VER = "2022.3.62f2"
PRE_DOWNLOAD_RESOURCE_VERSION_ENDPOINT = "tool/get_pre_download_resource_version"

_APP_VERSION_RE = re.compile(r"\A[0-9]+(?:\.[0-9]+)+\Z")
_RESOURCE_VERSION_RE = re.compile(r"\A[0-9]{1,32}\Z")

SALT = b"co!=Y;(UQCGxJ_n82"
HEAD = bytes.fromhex(
    "6b20e2ab6c311330f761d737ce3f3025750850665eea58b6372f8d2f57501eb3"
    "44bdb7270a9067f5b63cd61f152cfb986cbfbf7a"
)

SCENARIO_API_PREFIXES: dict[int, str] = {
    1: "single_mode",
    2: "single_mode_team",
    3: "single_mode_live",
    4: "single_mode_free",
}

READ_ONLY_RETRY_ENDPOINTS = frozenset(
    {
        "load/index",
        "read_info/index",
        "single_mode/load",
        "single_mode_team/load",
        "single_mode_live/load",
        "single_mode_free/load",
        "single_mode_live/get_choice_reward",
        "single_mode/get_choice_reward",
        "pre_single_mode/index",
        "account/get_by_social_account",
        "tool/pre_signup",
        PRE_DOWNLOAD_RESOURCE_VERSION_ENDPOINT,
    }
)

GLOBAL_208_RETRY_ENDPOINTS = frozenset(
    {
        "single_mode_live/master_square",
        "single_mode_free/master_square",
    }
)

STATE_CHANGING_OPERATIONS = frozenset(
    {
        "start",
        "exec_command",
        "check_event",
        "multi_item_use",
        "multi_item_exchange",
        "gain_skills",
        "factor_select",
        "finish",
        "end",
        "check_progress_log",
        "race_entry",
        "change_running_style",
        "race_start",
        "race_end",
        "race_out",
        "continue",
        "reserve_race",
        "reserve_square",
        "master_square",
        "live_start",
        "minigame_end",
        "recovery_trainer_point",
        "start_session",
        "signup",
    }
)


class StateRecoveryError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: int | None = None,
        endpoint: str | None = None,
        ambiguous: bool = False,
        recovery: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.endpoint = endpoint
        self.ambiguous = bool(ambiguous)
        self.recovery = recovery


@dataclass(frozen=True)
class RecoveryPolicy:
    retry_read_only: bool = False
    retry_endpoints: frozenset[str] = frozenset()
    ticket_refresh: bool = False
    recovery: str = "raise"
    max_retries: int = 0


RECOVERY_POLICIES: dict[int, RecoveryPolicy] = {
    205: RecoveryPolicy(
        retry_read_only=True,
        recovery="reconcile",
        max_retries=3,
    ),
    208: RecoveryPolicy(
        retry_read_only=True,
        retry_endpoints=GLOBAL_208_RETRY_ENDPOINTS,
        recovery="reconcile",
        max_retries=6,
    ),
    217: RecoveryPolicy(recovery="rebootstrap_and_reconcile"),
    394: RecoveryPolicy(
        retry_read_only=True,
        ticket_refresh=True,
        recovery="refresh_ticket_and_reconcile",
        max_retries=1,
    ),
    501: RecoveryPolicy(
        retry_read_only=True,
        ticket_refresh=True,
        recovery="refresh_ticket_and_reconcile",
        max_retries=1,
    ),
    709: RecoveryPolicy(recovery="replace_identity_and_rebootstrap"),
}


def sm5(data: bytes) -> bytes:
    h = hashlib.md5()
    h.update(data)
    h.update(SALT)
    return h.digest()


def make_sid(vid: int | str, udid: str) -> bytes:
    return sm5((str(vid) + str(udid)).encode("utf-8"))


def next_sid(sid: bytes | str) -> bytes:
    if isinstance(sid, (bytes, bytearray, memoryview)):
        return sm5(bytes(sid))
    return sm5(str(sid).encode("utf-8"))


def gen_key() -> bytes:
    out = bytearray()
    while len(out) < 32:
        out.extend(format(random.randint(0, 65535), "x").encode("ascii"))
    return bytes(out[:32])


def get_iv(udid: str) -> bytes:
    return udid.replace("-", "").lower()[:16].encode("ascii")


def get_raw_udid(udid: str) -> bytes:
    return bytes.fromhex(udid.replace("-", "").lower())


def issued_auth_from_header(header: bytes | bytearray | None) -> bytes | None:
    if (
        not isinstance(header, (bytes, bytearray))
        or len(header) != 164
        or bytes(header[: len(HEAD)]) != HEAD
    ):
        return None
    tail = bytes(header[-48:])
    if len(tail) != 48 or tail in (b"\x00" * 48, b"\xff" * 48):
        return None
    return tail


def _auth_from_response(response: Any) -> bytes | None:
    def visit(value: Any, depth: int = 0) -> bytes | None:
        if depth > 5:
            return None
        if isinstance(value, Mapping):
            for key, item in value.items():
                if re.search(r"auth.*key|newauthkey", str(key), re.IGNORECASE):
                    if isinstance(item, (bytes, bytearray)) and len(item) == 48:
                        raw = bytes(item)
                        if raw not in (b"\x00" * 48, b"\xff" * 48):
                            return raw
                    elif isinstance(item, str):
                        stripped = item.strip()
                        if re.fullmatch(r"[0-9a-fA-F]{96}", stripped):
                            raw = bytes.fromhex(stripped)
                            if raw not in (b"\x00" * 48, b"\xff" * 48):
                                return raw
                        try:
                            decoded = base64.b64decode(stripped, validate=True)
                        except (ValueError, TypeError):
                            decoded = b""
                        if len(decoded) == 48 and decoded not in (b"\x00" * 48, b"\xff" * 48):
                            return decoded
                found = visit(item, depth + 1)
                if found is not None:
                    return found
        elif isinstance(value, list):
            for item in value[:32]:
                found = visit(item, depth + 1)
                if found is not None:
                    return found
        return None

    return visit(response)


def pack(sid: bytes, udid_raw: bytes, auth: bytes, payload: Mapping[str, Any], udid: str) -> bytes:
    key = gen_key()
    packed = msgpack.packb(payload, use_bin_type=True)
    body = (
        AES.new(key, AES.MODE_CBC, get_iv(udid)).encrypt(
            pad(struct.pack("<I", len(packed)) + packed, 16)
        )
        + key
    )
    hdr = HEAD + bytes(sid) + bytes(udid_raw) + os.urandom(32)
    if auth:
        hdr += bytes(auth)
    return base64.b64encode(struct.pack("<I", len(hdr)) + hdr + body)


def unpack(
    text: str | bytes,
    udid: str,
    *,
    return_header: bool = False,
) -> Any:
    raw = base64.b64decode(text)
    protocol_header: bytes | None = None
    body_bytes = raw
    if len(raw) >= 4:
        header_len = struct.unpack_from("<I", raw, 0)[0]
        header_end = 4 + header_len
        if (
            len(HEAD) + 16 + 16 + 32 <= header_len <= 2048
            and header_end + 32 <= len(raw)
            and (len(raw) - header_end - 32) % 16 == 0
            and raw[4 : 4 + len(HEAD)] == HEAD
        ):
            protocol_header = raw[4:header_end]
            body_bytes = raw[header_end:]
    if len(body_bytes) < 48 or (len(body_bytes) - 32) % 16 != 0:
        raise StateRecoveryError("Malformed UMA envelope length")
    key, cipher = body_bytes[-32:], body_bytes[:-32]
    try:
        plain = unpad(AES.new(key, AES.MODE_CBC, get_iv(udid)).decrypt(cipher), 16)
    except ValueError as exc:
        raise StateRecoveryError("UMA payload decryption failed") from exc
    if len(plain) < 4:
        raise StateRecoveryError("UMA payload missing length prefix")
    msg_len = struct.unpack_from("<I", plain, 0)[0]
    if 4 + msg_len > len(plain):
        raise StateRecoveryError("UMA payload length exceeds frame")
    decoded = msgpack.unpackb(plain[4 : 4 + msg_len], raw=False, strict_map_key=False)
    if return_header:
        return decoded, protocol_header
    return decoded


def _validated_api_url(endpoint: str) -> str:
    base = urlsplit(BASE_URL)
    if (
        base.scheme.casefold() != OFFICIAL_API_SCHEME
        or (base.hostname or "").casefold() != OFFICIAL_API_HOST
        or base.port not in (None, 443)
        or base.path != OFFICIAL_API_PATH
        or base.query
        or base.fragment
        or base.username is not None
        or base.password is not None
    ):
        raise StateRecoveryError("API base URL is not the official HTTPS host")
    if not isinstance(endpoint, str) or not API_ENDPOINT_RE.fullmatch(endpoint):
        raise StateRecoveryError(f"Invalid relative API endpoint: {endpoint!r}")
    return BASE_URL + endpoint


def _valid_app_version(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or len(cleaned) > 64 or not _APP_VERSION_RE.fullmatch(cleaned):
        return None
    return cleaned


def _validated_resource_version(value: Any) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        value = str(value)
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not _RESOURCE_VERSION_RE.fullmatch(cleaned) or int(cleaned) <= 0:
        return None
    return cleaned


def _lookup_apple_app_version_fresh(proxy: str | None = None) -> tuple[bool, str]:
    proxies = {"http": proxy, "https": proxy} if proxy else {}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler(proxies))
    try:
        with opener.open(APP_LOOKUP_URL, timeout=APP_LOOKUP_TIMEOUT_SECONDS) as resp:
            if getattr(resp, "status", 200) != 200:
                return False, DEFAULT_APP_VER
            body = resp.read(APP_LOOKUP_MAX_BYTES + 1)
        if not body or len(body) > APP_LOOKUP_MAX_BYTES:
            return False, DEFAULT_APP_VER
        payload = json.loads(body.decode("utf-8"))
        if not isinstance(payload, dict) or payload.get("resultCount") != 1:
            return False, DEFAULT_APP_VER
        results = payload.get("results")
        if not isinstance(results, list) or len(results) != 1:
            return False, DEFAULT_APP_VER
        entry = results[0]
        if (
            not isinstance(entry, dict)
            or entry.get("trackId") != APP_LOOKUP_TRACK_ID
            or entry.get("bundleId") != APP_LOOKUP_BUNDLE_ID
        ):
            return False, DEFAULT_APP_VER
        valid = _valid_app_version(entry.get("version"))
        if valid is None:
            return False, DEFAULT_APP_VER
        return True, valid
    except Exception:
        return False, DEFAULT_APP_VER


_LAST_VERIFIED_APP_VERSION: str | None = None


@functools.lru_cache(maxsize=4)
def _cached_apple_lookup(proxy: str | None = None) -> tuple[bool, str]:
    return _lookup_apple_app_version_fresh(proxy)


def invalidate_app_version_cache() -> None:
    global _LAST_VERIFIED_APP_VERSION
    _cached_apple_lookup.cache_clear()
    _LAST_VERIFIED_APP_VERSION = None


def lookup_apple_app_version(*, force_refresh: bool = False, proxy: str | None = None) -> tuple[bool, str]:
    global _LAST_VERIFIED_APP_VERSION
    if force_refresh:
        _cached_apple_lookup.cache_clear()
        ok, ver = _cached_apple_lookup(proxy)
        if ok:
            _LAST_VERIFIED_APP_VERSION = ver
            return True, ver
        _cached_apple_lookup.cache_clear()
        if _LAST_VERIFIED_APP_VERSION is not None:
            return False, _LAST_VERIFIED_APP_VERSION
        return False, DEFAULT_APP_VER

    ok, ver = _cached_apple_lookup(proxy)
    if ok:
        _LAST_VERIFIED_APP_VERSION = ver
        return True, ver
    if _LAST_VERIFIED_APP_VERSION is not None:
        return True, _LAST_VERIFIED_APP_VERSION
    return False, DEFAULT_APP_VER


def _extract_resource_version_field(value: Any, *, _depth: int = 0) -> tuple[bool, Any]:
    if _depth > 4:
        return False, None
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).casefold())
            if normalized in {"resourceversion", "resversion", "resver"}:
                return True, item
        for subkey in ("data_headers", "data", "result", "payload"):
            if subkey in value:
                found, item = _extract_resource_version_field(value[subkey], _depth=_depth + 1)
                if found:
                    return True, item
    elif isinstance(value, list):
        for item in value[:32]:
            found, res = _extract_resource_version_field(item, _depth=_depth + 1)
            if found:
                return True, res
    return False, None


def _extract_app_version_hint(value: Any, *, _depth: int = 0) -> str | None:
    if _depth > 4:
        return None
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).casefold())
            if normalized in {
                "appver",
                "appversion",
                "requiredappver",
                "requiredappversion",
                "requiredversion",
                "clientversion",
            }:
                valid = _valid_app_version(item)
                if valid is not None:
                    return valid
        for subkey in ("data_headers", "data", "result", "payload"):
            if subkey in value:
                hint = _extract_app_version_hint(value[subkey], _depth=_depth + 1)
                if hint is not None:
                    return hint
    return None


_VERSION_MISMATCH_TERMS = (
    "version mismatch",
    "version invalid",
    "unsupported version",
    "version outdated",
)


def _version_issue(value: Any, *, _depth: int = 0) -> tuple[bool, bool]:
    if _depth > 4:
        return False, False
    app = resource = False
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).casefold())
            if normalized in {
                "invalidappver",
                "invalidappversion",
                "unsupportedappver",
                "unsupportedappversion",
            }:
                app = True
            elif normalized in {
                "invalidresver",
                "invalidresourceversion",
                "unsupportedresver",
                "unsupportedresourceversion",
            }:
                resource = True
            elif normalized in {"versionmismatch", "versionerror"}:
                app = resource = True
            elif isinstance(item, str):
                text = item.casefold()
                if "version" in text and any(t in text for t in _VERSION_MISMATCH_TERMS):
                    app = resource = True
            sub_app, sub_res = _version_issue(item, _depth=_depth + 1)
            app = app or sub_app
            resource = resource or sub_res
    elif isinstance(value, list):
        for item in value[:32]:
            sub_app, sub_res = _version_issue(item, _depth=_depth + 1)
            app = app or sub_app
            resource = resource or sub_res
    elif isinstance(value, str):
        text = value.casefold()
        if any(t in text for t in _VERSION_MISMATCH_TERMS):
            app = resource = True
    return app, resource


def build_common_envelope(
    *,
    viewer_id: int,
    device_id: str,
    device_name: str,
    graphics_device_name: str,
    ip_address: str,
    platform_os_version: str,
    steam_id: str,
    steam_session_ticket: str,
    locale: str = DEFAULT_LOCALE,
) -> dict[str, Any]:
    return {
        "viewer_id": viewer_id,
        "device": 4,
        "device_id": device_id,
        "device_name": device_name,
        "graphics_device_name": graphics_device_name,
        "ip_address": ip_address,
        "platform_os_version": platform_os_version,
        "carrier": "",
        "keychain": 0,
        "locale": locale or DEFAULT_LOCALE,
        "button_info": "",
        "dmm_viewer_id": None,
        "dmm_onetime_token": None,
        "steam_id": steam_id,
        "steam_session_ticket": steam_session_ticket,
    }


def _extract_viewer_id(response: Any) -> str | None:
    if not isinstance(response, Mapping):
        return None
    candidates: list[Any] = []
    for container in (response, response.get("data_headers"), response.get("data")):
        if isinstance(container, Mapping):
            for key in ("viewer_id", "ViewerId", "viewerId", "newViewerId", "new_viewer_id"):
                candidates.append(container.get(key))
    for val in candidates:
        if val in (None, "", 0, "0") or isinstance(val, bool):
            continue
        if isinstance(val, int):
            if val > 0:
                return str(val)
            continue
        if isinstance(val, str):
            stripped = val.strip()
            if stripped.isdigit() and int(stripped) > 0:
                return str(int(stripped))
    return None


def _build_proxies(proxy: str | None = None, proxies: Mapping[str, str] | None = None) -> dict[str, str]:
    if proxies:
        return {str(k): str(v) for k, v in proxies.items() if v}
    if isinstance(proxy, str) and proxy.strip():
        p = proxy.strip()
        return {"http": p, "https": p}
    return {}


class UmaClient:
    def __init__(
        self,
        cfg: Mapping[str, Any],
        *,
        provider: SteamTicketProvider | None = None,
        timing: TimingDNA | None = None,
        proxy: str | None = None,
        proxies: Mapping[str, str] | None = None,
        allow_unauthenticated: bool = False,
    ) -> None:
        self._steam_ticket_provider = provider or getattr(cfg, "steam_ticket_provider", None)
        self.timing = timing
        self.proxies = _build_proxies(proxy=proxy, proxies=proxies)

        required_device = (
            "udid",
            "device_id",
            "device_name",
            "graphics_device_name",
            "ip_address",
            "platform_os_version",
        )
        missing_dev = [k for k in required_device if cfg.get(k) in (None, "")]
        if missing_dev:
            raise HeadlessAuthError(
                "missing device fields: " + ", ".join(missing_dev)
            )

        if not allow_unauthenticated:
            required_auth = ("viewer_id", "auth_key", "steam_id", "steam_session_ticket")
            missing_auth = [k for k in required_auth if cfg.get(k) in (None, "")]
            if missing_auth:
                raise HeadlessAuthError(
                    "missing auth fields: " + ", ".join(missing_auth)
                )

        raw_vid = cfg.get("viewer_id", 0)
        if isinstance(raw_vid, bool):
            raise HeadlessAuthError("viewer_id cannot be bool")
        try:
            self.viewer_id = int(raw_vid)
        except (TypeError, ValueError, OverflowError) as exc:
            raise HeadlessAuthError("viewer_id must be an integer") from exc
        if not allow_unauthenticated and self.viewer_id <= 0:
            raise HeadlessAuthError("no viewer_id")

        self.udid_str = str(cfg["udid"]).strip()
        self.auth_key_hex = str(cfg.get("auth_key") or "").strip().lower()
        self.steam_id = str(cfg.get("steam_id") or "").strip()
        self.steam_ticket = str(cfg.get("steam_session_ticket") or "").strip()

        if self._steam_ticket_provider is not None and not allow_unauthenticated:
            self.steam_id = str(self._steam_ticket_provider.steam_id)
            self.steam_ticket = str(self._steam_ticket_provider.steam_session_ticket)

        self.device_id = str(cfg["device_id"])
        self.device_name = str(cfg["device_name"])
        self.graphics_device = str(cfg["graphics_device_name"])
        self.ip_address = str(cfg["ip_address"])
        self.platform_os = str(cfg["platform_os_version"])
        self.locale = str(cfg.get("locale") or DEFAULT_LOCALE)
        self.unity_ver = str(cfg.get("unity_ver") or DEFAULT_UNITY_VER)

        cfg_app_ver = cfg.get("app_ver")
        if cfg_app_ver not in (None, ""):
            self.app_ver = str(cfg_app_ver).strip()
        else:
            _, resolved_ver = lookup_apple_app_version(proxy=self._primary_proxy())
            self.app_ver = resolved_ver

        cfg_res_ver = cfg.get("res_ver")
        self.res_ver = (
            DEFAULT_RES_VER if cfg_res_ver is None else str(cfg_res_ver).strip()
        )

        initial_sid = cfg.get("sid")
        if isinstance(initial_sid, (bytes, bytearray)) and len(initial_sid) == 16:
            self.sid = bytes(initial_sid)
        else:
            self.sid = bytes(16)

        self.last_response_header: bytes | None = None
        self.cached_load_data: dict[str, Any] = {}
        self.tp_info: dict[str, Any] = {}
        self.coin_info: dict[str, Any] = {}
        self.item_map: dict[int, int] = {}
        self.current_scenario_id: int | None = None
        self.api_prefix: str | None = None
        self._last_raw_call_ts: float = 0.0
        self.on_api_log = None

        self.session = self._new_http_session()
        self._session_closed = False



    def _primary_proxy(self) -> str | None:
        return self.proxies.get("https") or self.proxies.get("http")

    def _new_http_session(self) -> requests.Session:
        sess = requests.Session(
            trust_env=False,
            proxies=self.proxies,
            allow_redirects=False,
            max_redirects=0,
        )
        sess.headers.update(
            {
                "User-Agent": f"UnityPlayer/{self.unity_ver} (UnityWebRequest/1.0, libcurl/8.10.1-DEV)",
                "X-Unity-Version": self.unity_ver,
                "Content-Type": "application/x-msgpack",
                "Accept": "*/*",
                "Accept-Encoding": "deflate, gzip",
            }
        )
        return sess

    def close(self) -> None:
        provider = self._steam_ticket_provider
        self._steam_ticket_provider = None
        if provider is not None:
            provider.close()
        if not self._session_closed:
            self._session_closed = True
            self.session.close()

    def __enter__(self) -> UmaClient:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def set_scenario(self, scenario_id: int) -> str:
        if isinstance(scenario_id, bool):
            raise ValueError("scenario_id cannot be bool")
        sid = int(scenario_id)
        if sid not in SCENARIO_API_PREFIXES:
            raise ValueError(f"Unsupported scenario_id: {scenario_id}")
        self.current_scenario_id = sid
        self.api_prefix = SCENARIO_API_PREFIXES[sid]
        return self.api_prefix

    def scenario_endpoint(self, operation: str) -> str:
        if self.current_scenario_id is None or self.api_prefix is None:
            raise StateRecoveryError(
                f"Scenario must be selected before calling {operation!r}"
            )
        return f"{self.api_prefix}/{str(operation).lstrip('/')}"

    def regen_sid(self) -> bytes:
        self.sid = make_sid(self.viewer_id, self.udid_str)
        return self.sid

    def auth_bytes(self) -> bytes:
        if not self.auth_key_hex:
            return b""
        return bytes.fromhex(self.auth_key_hex)

    def _current_steam_credentials(self) -> tuple[str, str]:
        provider = self._steam_ticket_provider
        if provider is None:
            return self.steam_id, self.steam_ticket
        try:
            if provider.active:
                self.steam_id = str(provider.steam_id)
                self.steam_ticket = str(provider.steam_session_ticket)
                return self.steam_id, self.steam_ticket
        except SteamTicketError:
            pass

        try:
            self.steam_ticket = provider.refresh()
        except SteamTicketError as exc:
            raise StateRecoveryError(
                f"Steam ticket lease recovery failed: {exc}",
                recovery="refresh_ticket_and_reconcile",
            ) from exc
        return self.steam_id, self.steam_ticket

    def common(self, *, viewer_override: int | None = None) -> dict[str, Any]:
        steam_id, steam_ticket = self._current_steam_credentials()
        vid = self.viewer_id if viewer_override is None else int(viewer_override)
        return build_common_envelope(
            viewer_id=vid,
            device_id=self.device_id,
            device_name=self.device_name,
            graphics_device_name=self.graphics_device,
            ip_address=self.ip_address,
            platform_os_version=self.platform_os,
            steam_id=steam_id,
            steam_session_ticket=steam_ticket,
            locale=self.locale,
        )

    def refresh_cached_account_state(self, data: Mapping[str, Any] | None) -> None:
        if not isinstance(data, Mapping):
            return
        self.cached_load_data.update(data)
        tp = data.get("tp_info")
        if isinstance(tp, dict):
            self.tp_info = dict(tp)
        coin = data.get("coin_info")
        if isinstance(coin, dict):
            self.coin_info = dict(coin)
        items = data.get("user_item") or data.get("user_item_array") or data.get("item_list")
        if isinstance(items, list):
            for entry in items:
                if isinstance(entry, Mapping):
                    iid = entry.get("item_id")
                    num = entry.get("number")
                    if iid is not None and num is not None:
                        self.item_map[int(iid)] = int(num)

    @staticmethod
    def _endpoint_operation(ep: str) -> str:
        return str(ep or "").rstrip("/").rsplit("/", 1)[-1]

    @classmethod
    def _is_state_changing_endpoint(cls, ep: str) -> bool:
        clean = str(ep or "").rstrip("/")
        if clean in READ_ONLY_RETRY_ENDPOINTS:
            return False
        op = cls._endpoint_operation(clean)
        if op in STATE_CHANGING_OPERATIONS:
            return True
        return clean not in READ_ONLY_RETRY_ENDPOINTS

    @staticmethod
    def _response_sid(res: Any) -> bytes | str | None:
        if not isinstance(res, Mapping):
            return None
        for container in (res.get("data_headers"), res):
            if not isinstance(container, Mapping):
                continue
            for key, value in container.items():
                if str(key).lower() != "sid":
                    continue
                if isinstance(value, (bytes, bytearray)) and value:
                    return bytes(value)
                if value is not None:
                    text = str(value).strip()
                    if text:
                        return text
        return None

    @staticmethod
    def _response_code(res: Any) -> int | None:
        if not isinstance(res, Mapping):
            return None
        dh = res.get("data_headers")
        nested = None
        if isinstance(dh, Mapping):
            for k, v in dh.items():
                if str(k).lower() == "result_code":
                    nested = v
                    break
        values: list[int] = []
        for candidate in (res.get("response_code"), res.get("result_code"), nested):
            if candidate is None or isinstance(candidate, bool):
                continue
            try:
                values.append(int(candidate))
            except (TypeError, ValueError, OverflowError):
                return None
        if not values or len(set(values)) != 1:
            return None
        return values[0]

    @staticmethod
    def _is_settle_probe(ep: str, payload: Mapping[str, Any]) -> bool:
        if not str(ep or "").endswith("/check_event"):
            return False
        raw_eid = payload.get("event_id")
        if isinstance(raw_eid, bool):
            return False
        try:
            return int(raw_eid or 0) == 0
        except (TypeError, ValueError):
            return False

    def _enforce_call_floor(self) -> None:
        if self.timing is not None:
            self.timing.enforce_floor(self._last_raw_call_ts)
        elif self._last_raw_call_ts > 0:
            elapsed = time.monotonic() - self._last_raw_call_ts
            remaining = HARD_CALL_FLOOR_SECONDS - elapsed
            if remaining > 0:
                time.sleep(remaining)
        self._last_raw_call_ts = time.monotonic()

    def _refresh_app_version(self, *, hint: str | None = None) -> str:
        if hint is not None and hint != self.app_ver:
            valid_hint = _valid_app_version(hint)
            if valid_hint is not None:
                self.app_ver = valid_hint
                return self.app_ver

        ok, refreshed = lookup_apple_app_version(
            force_refresh=True,
            proxy=self._primary_proxy(),
        )
        valid = _valid_app_version(refreshed) if ok else None
        if valid is not None:
            self.app_ver = valid
            return self.app_ver

        if hint is not None:
            fallback_hint = _valid_app_version(hint)
            if fallback_hint is not None:
                self.app_ver = fallback_hint
                return self.app_ver

        raise StateRecoveryError("App-version heal lookup failed")

    def probe_resource_version(self, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        saved_sid = self.sid
        saved_viewer = self.viewer_id
        saved_header = self.last_response_header

        probe_payload: dict[str, Any] = {
            "attestation_type": 0,
            "button_info": "",
            "carrier": "",
            "device_token": None,
            "dmm_onetime_token": None,
            "dmm_viewer_id": None,
            "device": 4,
            "device_id": self.device_id,
            "device_name": self.device_name,
            "graphics_device_name": self.graphics_device,
            "ip_address": self.ip_address,
            "platform_os_version": self.platform_os,
            "keychain": 0,
            "locale": self.locale,
            "viewer_id": 0,
        }
        if isinstance(payload, Mapping):
            for allowed_key in (
                "attestation_type",
                "button_info",
                "carrier",
                "device_token",
                "dmm_onetime_token",
                "dmm_viewer_id",
                "device",
                "device_id",
                "device_name",
                "graphics_device_name",
                "ip_address",
                "platform_os_version",
                "keychain",
                "locale",
                "steam_id",
                "steam_session_ticket",
            ):
                if allowed_key in payload:
                    probe_payload[allowed_key] = payload[allowed_key]
        probe_payload["viewer_id"] = 0

        try:
            self.sid = make_sid(0, self.udid_str)
            res = self.call(
                PRE_DOWNLOAD_RESOURCE_VERSION_ENDPOINT,
                probe_payload,
                _anonymous=True,
                _version_probe=True,
                _app_version_retry_budget=1,
                _resource_version_retry_budget=0,
            )
        finally:
            self.sid = saved_sid
            self.viewer_id = saved_viewer
            self.last_response_header = saved_header

        present, raw_ver = _extract_resource_version_field(res)
        refreshed = _validated_resource_version(raw_ver) if present else None
        if refreshed is not None:
            self.res_ver = refreshed
        return res

    def _refresh_resource_version(
        self,
        payload: Mapping[str, Any] | None = None,
        *,
        hint: Any = None,
    ) -> str:
        valid_hint = _validated_resource_version(hint)
        if valid_hint is not None and valid_hint != self.res_ver:
            self.res_ver = valid_hint
            return self.res_ver

        try:
            probe_res = self.probe_resource_version(payload)
        except Exception as exc:
            if valid_hint is not None:
                self.res_ver = valid_hint
                return self.res_ver
            raise StateRecoveryError("Resource-version heal failed") from exc

        present, raw_ver = _extract_resource_version_field(probe_res)
        refreshed = _validated_resource_version(raw_ver) if present else None
        if refreshed is None:
            if valid_hint is not None:
                self.res_ver = valid_hint
                return self.res_ver
            raise StateRecoveryError("Resource-version heal: no valid version")
        self.res_ver = refreshed
        return self.res_ver

    def _emit_log(self, direction: str, ep: str, data: Any, req_id: str) -> None:
        if callable(self.on_api_log):
            self.on_api_log(direction, ep, data, req_id)

    def call(
        self,
        ep: str,
        args: Mapping[str, Any] | None = None,
        *,
        retry_208: int = 6,
        retry_205: int = 3,
        transport_retries: int | None = None,
        _ticket_refresh_budget: int = 1,
        _payload_override: Mapping[str, Any] | None = None,
        _app_version_retry_budget: int = 1,
        _resource_version_retry_budget: int = 1,
        _version_probe: bool = False,
        _anonymous: bool = False,
        _auth_override: bytes | None = None,
        _viewer_header_override: str | None = None,
        _skip_common: bool = False,
    ) -> dict[str, Any]:
        if transport_retries is not None:
            if isinstance(transport_retries, bool) or not isinstance(transport_retries, int) or transport_retries < 0:
                raise ValueError("bad transport_retries")

        api_url = _validated_api_url(ep)
        self._enforce_call_floor()

        req_id = uuid.uuid4().hex[:8]
        if _payload_override is None:
            payload = dict(args or {})
            if not _anonymous and not _skip_common:
                payload.update(self.common())
            if not _anonymous and ep.endswith("/race_out") and not payload.get("button_info"):
                scen = self.current_scenario_id or 3
                payload["button_info"] = make_race_out_button_info(
                    self.viewer_id,
                    scen,
                    dna=self.timing,
                )
        else:
            payload = dict(_payload_override)

        headers: dict[str, str] = {
            "SID": self.sid.hex(),
            "Device": "4",
            "Device-SubType": "1",
            "APP-VER": self.app_ver,
            "RES-VER": self.res_ver,
        }
        if _viewer_header_override is not None:
            if _viewer_header_override != "":
                headers["ViewerID"] = str(_viewer_header_override)
        elif not _anonymous:
            headers["ViewerID"] = str(self.viewer_id)

        state_changing = self._is_state_changing_endpoint(ep)
        max_attempts = (
            transport_retries + 1
            if transport_retries is not None
            else (4 if not state_changing else 1)
        )

        auth_material = (
            b""
            if _anonymous
            else (self.auth_bytes() if _auth_override is None else bytes(_auth_override))
        )
        udid_raw = get_raw_udid(self.udid_str)

        self.last_response_header = None
        resp = None
        for attempt in range(max_attempts):
            wire_body = pack(self.sid, udid_raw, auth_material, payload, self.udid_str)
            self._emit_log("REQ", ep, {"payload": payload, "attempt": attempt + 1}, req_id)
            try:
                resp = self.session.post(
                    api_url,
                    data=wire_body,
                    headers=headers,
                    timeout=30,
                    proxies=self.proxies,
                    allow_redirects=False,
                    max_redirects=0,
                )
                break
            except Exception as exc:
                self._emit_log("ERR", ep, {"error": str(exc), "attempt": attempt + 1}, req_id)
                if attempt < max_attempts - 1:
                    wait_s = min(1.0 + attempt * 2.0, 10.0)
                    time.sleep(wait_s)
                    continue
                if state_changing:
                    raise StateRecoveryError(
                        f"transport failed on state-changing call {ep}: {exc}",
                        endpoint=ep,
                        ambiguous=True,
                        recovery="reconcile",
                    ) from exc
                raise StateRecoveryError(
                    f"Transport error on read-only endpoint {ep}: {exc}",
                    endpoint=ep,
                    ambiguous=False,
                    recovery="retry_read_only",
                ) from exc

        assert resp is not None
        if resp.status_code != 200:
            preview = (resp.text or "")[:500]
            app_issue, res_issue = _version_issue(preview)
            if resp.status_code == 202:
                app_issue = res_issue = True
            if (app_issue and _app_version_retry_budget > 0) or (
                res_issue and not _version_probe and _resource_version_retry_budget > 0
            ):
                next_app_budget = _app_version_retry_budget
                next_res_budget = _resource_version_retry_budget
                if app_issue and _app_version_retry_budget > 0:
                    self._refresh_app_version()
                    next_app_budget -= 1
                if res_issue and not _version_probe and _resource_version_retry_budget > 0:
                    self._refresh_resource_version(payload)
                    next_res_budget -= 1
                return self.call(
                    ep,
                    args,
                    retry_208=retry_208,
                    retry_205=retry_205,
                    transport_retries=transport_retries,
                    _ticket_refresh_budget=_ticket_refresh_budget,
                    _payload_override=payload,
                    _app_version_retry_budget=next_app_budget,
                    _resource_version_retry_budget=next_res_budget,
                    _version_probe=_version_probe,
                    _anonymous=_anonymous,
                    _auth_override=_auth_override,
                    _viewer_header_override=_viewer_header_override,
                    _skip_common=_skip_common,
                )
            raise StateRecoveryError(
                f"HTTP {resp.status_code} on {ep}: {preview}",
                code=resp.status_code,
                endpoint=ep,
                ambiguous=state_changing,
                recovery="reconcile" if state_changing else "raise",
            )

        res, proto_hdr = unpack(resp.text.strip(), self.udid_str, return_header=True)
        self.last_response_header = proto_hdr
        if not isinstance(res, dict):
            raise StateRecoveryError(f"Decoded UMA response on {ep} is not a dict", endpoint=ep)

        response_sid = self._response_sid(res)
        if response_sid:
            self.sid = next_sid(response_sid)

        self._emit_log("RES", ep, res, req_id)

        rc = self._response_code(res)
        dh = res.get("data_headers") if isinstance(res.get("data_headers"), dict) else {}
        data = res.get("data") if isinstance(res.get("data"), dict) else {}

        if ep in {PRE_DOWNLOAD_RESOURCE_VERSION_ENDPOINT, "tool/start_session", "load/index"} and rc == 1:
            present, raw_rv = _extract_resource_version_field(res)
            if present:
                valid_rv = _validated_resource_version(raw_rv)
                if valid_rv is None:
                    raise StateRecoveryError(
                        f"bad resource_version from {ep}",
                        endpoint=ep,
                    )
                self.res_ver = valid_rv

        if data:
            self.refresh_cached_account_state(data)
            chara_info = data.get("chara_info")
            if isinstance(chara_info, Mapping) and chara_info.get("scenario_id") in SCENARIO_API_PREFIXES:
                self.set_scenario(int(chara_info["scenario_id"]))

        if rc == 204 and _app_version_retry_budget > 0:
            app_hint = _extract_app_version_hint(res)
            self._refresh_app_version(hint=app_hint)
            return self.call(
                ep,
                args,
                retry_208=retry_208,
                retry_205=retry_205,
                transport_retries=transport_retries,
                _ticket_refresh_budget=_ticket_refresh_budget,
                _payload_override=payload,
                _app_version_retry_budget=_app_version_retry_budget - 1,
                _resource_version_retry_budget=_resource_version_retry_budget,
                _version_probe=_version_probe,
                _anonymous=_anonymous,
                _auth_override=_auth_override,
                _viewer_header_override=_viewer_header_override,
                _skip_common=_skip_common,
            )

        if rc == 214 and not _version_probe and _resource_version_retry_budget > 0:
            present_rv, raw_hint_rv = _extract_resource_version_field(res)
            self._refresh_resource_version(payload, hint=raw_hint_rv if present_rv else None)
            return self.call(
                ep,
                args,
                retry_208=retry_208,
                retry_205=retry_205,
                transport_retries=transport_retries,
                _ticket_refresh_budget=_ticket_refresh_budget,
                _payload_override=payload,
                _app_version_retry_budget=_app_version_retry_budget,
                _resource_version_retry_budget=_resource_version_retry_budget - 1,
                _version_probe=_version_probe,
                _anonymous=_anonymous,
                _auth_override=_auth_override,
                _viewer_header_override=_viewer_header_override,
                _skip_common=_skip_common,
            )

        app_issue, res_issue = _version_issue(res)
        if rc == 202:
            app_issue = res_issue = True
        if (app_issue and _app_version_retry_budget > 0) or (
            res_issue and not _version_probe and _resource_version_retry_budget > 0
        ):
            next_app_budget = _app_version_retry_budget
            next_res_budget = _resource_version_retry_budget
            if app_issue and _app_version_retry_budget > 0:
                self._refresh_app_version()
                next_app_budget -= 1
            if res_issue and not _version_probe and _resource_version_retry_budget > 0:
                self._refresh_resource_version(payload)
                next_res_budget -= 1
            return self.call(
                ep,
                args,
                retry_208=retry_208,
                retry_205=retry_205,
                transport_retries=transport_retries,
                _ticket_refresh_budget=_ticket_refresh_budget,
                _payload_override=payload,
                _app_version_retry_budget=next_app_budget,
                _resource_version_retry_budget=next_res_budget,
                _version_probe=_version_probe,
                _anonymous=_anonymous,
                _auth_override=_auth_override,
                _viewer_header_override=_viewer_header_override,
                _skip_common=_skip_common,
            )

        if rc in (394, 501) and _ticket_refresh_budget > 0 and self._steam_ticket_provider is not None:
            try:
                refreshed_ticket = self._steam_ticket_provider.refresh()
            except Exception as exc:
                raise StateRecoveryError(
                    f"Steam session ticket refresh failed on {ep}: {exc}",
                    code=rc,
                    endpoint=ep,
                    recovery="refresh_ticket_and_reconcile",
                ) from exc
            if not isinstance(refreshed_ticket, str) or not refreshed_ticket:
                raise StateRecoveryError(
                    f"empty ticket from session refresh {ep}",
                    code=rc,
                    endpoint=ep,
                    recovery="refresh_ticket_and_reconcile",
                )
            self.steam_ticket = refreshed_ticket
            retry_payload = dict(payload)
            if "steam_session_ticket" in retry_payload:
                retry_payload["steam_id"] = self.steam_id
                retry_payload["steam_session_ticket"] = refreshed_ticket
            if "authentication_token" in retry_payload:
                retry_payload["authentication_token"] = refreshed_ticket
            return self.call(
                ep,
                args,
                retry_208=retry_208,
                retry_205=retry_205,
                transport_retries=transport_retries,
                _ticket_refresh_budget=_ticket_refresh_budget - 1,
                _payload_override=retry_payload,
                _app_version_retry_budget=_app_version_retry_budget,
                _resource_version_retry_budget=_resource_version_retry_budget,
                _version_probe=_version_probe,
                _anonymous=_anonymous,
                _auth_override=_auth_override,
                _viewer_header_override=_viewer_header_override,
                _skip_common=_skip_common,
            )

        if rc is None:
            raise StateRecoveryError(
                f"Missing or contradictory result_code on {ep}",
                endpoint=ep,
            )

        if rc == 709:
            new_vid_str = _extract_viewer_id(res)
            if new_vid_str is not None:
                new_vid = int(new_vid_str)
                if new_vid > 0 and new_vid != self.viewer_id:
                    self.viewer_id = new_vid
                    self.regen_sid()
            raise StateRecoveryError(
                f"Viewer identity mismatch (rc=709) on {ep}",
                code=709,
                endpoint=ep,
                recovery="replace_identity_and_rebootstrap",
            )

        if rc != 1:
            if rc == 205 and self._is_settle_probe(ep, payload):
                return res

            if rc == 205 and retry_205 > 0 and not state_changing:
                if self.timing is not None:
                    self.timing.sleep_range(0.14, 0.19, 0.166, 0.0083)
                else:
                    time.sleep(0.16)
                return self.call(
                    ep,
                    args,
                    retry_208=retry_208,
                    retry_205=retry_205 - 1,
                    transport_retries=transport_retries,
                    _ticket_refresh_budget=_ticket_refresh_budget,
                    _payload_override=payload,
                    _app_version_retry_budget=_app_version_retry_budget,
                    _resource_version_retry_budget=_resource_version_retry_budget,
                    _version_probe=_version_probe,
                    _anonymous=_anonymous,
                    _auth_override=_auth_override,
                    _viewer_header_override=_viewer_header_override,
                    _skip_common=_skip_common,
                )

            if rc == 208 and retry_208 > 0 and (ep in GLOBAL_208_RETRY_ENDPOINTS or not state_changing):
                if retry_208 < 6:
                    if self.timing is not None:
                        self.timing.sleep_range(0.6, 1.4, 1.0, 0.1)
                    else:
                        time.sleep(0.8)
                return self.call(
                    ep,
                    args,
                    retry_208=retry_208 - 1,
                    retry_205=retry_205,
                    transport_retries=transport_retries,
                    _ticket_refresh_budget=_ticket_refresh_budget,
                    _payload_override=payload,
                    _app_version_retry_budget=_app_version_retry_budget,
                    _resource_version_retry_budget=_resource_version_retry_budget,
                    _version_probe=_version_probe,
                    _anonymous=_anonymous,
                    _auth_override=_auth_override,
                    _viewer_header_override=_viewer_header_override,
                    _skip_common=_skip_common,
                )

            err_msg = dh.get("error_message") or data.get("error_message") or ""
            policy = RECOVERY_POLICIES.get(rc)
            raise StateRecoveryError(
                f"UMA API error rc={rc} on {ep}" + (f" ({err_msg})" if err_msg else ""),
                code=rc,
                endpoint=ep,
                recovery=policy.recovery if policy is not None else "reconcile",
            )

        return res

    def read_info(self) -> dict[str, Any]:
        return self.call(
            "read_info/index",
            {
                "add_home_story_data_array": [],
                "add_short_episode_data_array": [],
                "add_home_poster_data_array": [],
                "add_tutorial_guide_data_array": [],
                "add_released_episode_data_array": [],
                "add_talk_gallery_data_array": [],
                "add_home_banner_data_array": [],
            },
        )

    def _safe_read_info_after_load(self) -> dict[str, Any] | None:
        try:
            return self.read_info()
        except StateRecoveryError as exc:
            if exc.code == 102 and exc.endpoint == "read_info/index":
                return None
            raise

    def login(self, max_retries: int = 3, *, read_info: bool = True) -> dict[str, Any]:
        if not isinstance(read_info, bool):
            raise TypeError("read_info must be a bool")
        if self.viewer_id <= 0 or not self.auth_key_hex:
            raise HeadlessAuthError("Login needs viewer_id and auth_key")

        self.session.close()
        self.session = self._new_http_session()
        self._session_closed = False

        for attempt in range(max_retries + 1):
            try:
                self.regen_sid()
                self.call("tool/start_session", {"attestation_type": 0, "device_token": None})
                res = self.call("load/index", {"adid": ""})
                self.refresh_cached_account_state(res.get("data"))
                if read_info:
                    self._safe_read_info_after_load()
                return res
            except StateRecoveryError as exc:
                if exc.code in (202, 709) and attempt < max_retries:
                    time.sleep(0.85)
                    continue
                raise
        raise StateRecoveryError("Login retries exhausted", endpoint="load/index")



    def pre_single_mode(self, exclude_viewer_ids: list[int] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if exclude_viewer_ids:
            payload["exclude_viewer_id_array"] = [int(v) for v in exclude_viewer_ids]
        return self.call("pre_single_mode/index", payload)

    def start_career(
        self,
        card_id: int,
        support_card_ids: list[int],
        friend_viewer_id: int,
        friend_card_id: int,
        parent_id_1: int,
        parent_id_2: int,
        scenario_id: int = 3,
        *,
        deck_id: int = 1,
        use_tp: int = 30,
        tp_info: Mapping[str, Any] | None = None,
        current_money: int = 0,
        succession_rank_point: int = 0,
        rental_viewer_id: int = 0,
        rental_trained_chara_id: int = 0,
        difficulty_id: int = 0,
        difficulty: int = 0,
        is_boost: int = 0,
        boost_story_event_id: int = 0,
    ) -> dict[str, Any]:
        self.set_scenario(scenario_id)
        resolved_tp = (
            dict(tp_info)
            if tp_info is not None
            else (
                dict(self.tp_info)
                if self.tp_info
                else {"current_tp": 100, "max_tp": 100, "max_recovery_time": 0}
            )
        )
        start_payload = {
            "start_chara": {
                "card_id": int(card_id),
                "support_card_ids": [int(s) for s in support_card_ids],
                "friend_support_card_info": {
                    "viewer_id": int(friend_viewer_id),
                    "support_card_id": int(friend_card_id),
                },
                "succession_trained_chara_id_1": int(parent_id_1),
                "succession_trained_chara_id_2": int(parent_id_2),
                "rental_succession_trained_chara": {
                    "viewer_id": int(rental_viewer_id),
                    "trained_chara_id": int(rental_trained_chara_id),
                    "is_circle_member": False,
                    "is_event_rental": False,
                },
                "scenario_id": int(scenario_id),
                "selected_difficulty_info": {
                    "difficulty_id": int(difficulty_id),
                    "difficulty": int(difficulty),
                    "is_boost": int(is_boost),
                },
                "select_deck_id": int(deck_id),
                "boost_story_event_id": int(boost_story_event_id),
                "is_play_training_challenge": False,
            },
            "tp_info": resolved_tp,
            "current_money": int(current_money),
            "use_tp": int(use_tp),
            "current_succession_rank_point": int(succession_rank_point),
        }
        return self.call(self.scenario_endpoint("start"), start_payload)

    def load_career(self, scenario_id: int | None = None) -> dict[str, Any]:
        if scenario_id is not None:
            self.set_scenario(scenario_id)
        elif self.current_scenario_id is None:
            self.set_scenario(3)
        return self.call(self.scenario_endpoint("load"), {})

    def recover_tp(self, count: int = 1, client_own_num: int | None = None) -> dict[str, Any]:
        if client_own_num is None:
            own_num = int(self.coin_info.get("fcoin", 0)) + int(self.coin_info.get("coin", 0))
        else:
            own_num = int(client_own_num)
        res = self.call(
            "user/recovery_trainer_point",
            {"count": int(count), "client_own_num": own_num},
            retry_208=0,
            retry_205=0,
            transport_retries=0,
            _ticket_refresh_budget=0,
            _app_version_retry_budget=0,
            _resource_version_retry_budget=0,
        )
        data = res.get("data")
        if isinstance(data, Mapping):
            self.refresh_cached_account_state(data)
        return res

    def exec_command(
        self,
        command_type: int,
        command_id: int,
        current_turn: int,
        current_vital: int,
        command_group_id: int = 0,
        select_id: int = 0,
    ) -> dict[str, Any]:
        return self.call(
            self.scenario_endpoint("exec_command"),
            {
                "command_type": int(command_type),
                "command_id": int(command_id),
                "command_group_id": int(command_group_id),
                "select_id": int(select_id),
                "current_turn": int(current_turn),
                "current_vital": int(current_vital),
            },
        )

    def check_event(
        self,
        event_id: int,
        current_turn: int,
        chara_id: int = 0,
        choice_number: int = 0,
    ) -> dict[str, Any]:
        payload = {
            "event_id": int(event_id),
            "chara_id": int(chara_id or 0),
            "choice_number": 0 if choice_number is None else int(choice_number),
            "current_turn": int(current_turn),
        }
        if int(event_id or 0) == 0:
            return self.call(self.scenario_endpoint("check_event"), payload, retry_205=0)
        return self.call(self.scenario_endpoint("check_event"), payload)

    def race_entry(
        self,
        program_id: int,
        current_turn: int,
        running_style: int | None = None,
    ) -> dict[str, Any]:
        if running_style is not None:
            return self.call(
                self.scenario_endpoint("change_running_style"),
                {
                    "program_id": int(program_id),
                    "running_style": int(running_style),
                    "current_turn": int(current_turn),
                },
            )
        return self.call(
            self.scenario_endpoint("race_entry"),
            {"program_id": int(program_id), "current_turn": int(current_turn)},
        )

    def race_start(self, is_short: int, current_turn: int) -> dict[str, Any]:
        return self.call(
            self.scenario_endpoint("race_start"),
            {"is_short": int(is_short), "current_turn": int(current_turn)},
        )

    def race_end(self, current_turn: int) -> dict[str, Any]:
        return self.call(
            self.scenario_endpoint("race_end"),
            {"current_turn": int(current_turn)},
        )

    def race_out(self, current_turn: int) -> dict[str, Any]:
        return self.call(
            self.scenario_endpoint("race_out"),
            {"current_turn": int(current_turn)},
        )

    def race_continue(self, current_turn: int, continue_type: int) -> dict[str, Any]:
        return self.call(
            self.scenario_endpoint("continue"),
            {"current_turn": int(current_turn), "continue_type": int(continue_type)},
        )

    def reserve_race(
        self,
        current_turn: int,
        add_race_array: list[Any] | None = None,
        cancel_race_array: list[Any] | None = None,
    ) -> dict[str, Any]:
        return self.call(
            self.scenario_endpoint("reserve_race"),
            {
                "current_turn": int(current_turn),
                "add_race_array": list(add_race_array or []),
                "cancel_race_array": list(cancel_race_array or []),
            },
        )

    def reserve_square(self, square_id: int, current_turn: int) -> dict[str, Any]:
        return self.call(
            self.scenario_endpoint("reserve_square"),
            {"square_id": int(square_id), "current_turn": int(current_turn)},
        )

    def master_square(self, square_id: int, current_turn: int) -> dict[str, Any]:
        return self.call(
            self.scenario_endpoint("master_square"),
            {"square_id": int(square_id), "current_turn": int(current_turn)},
        )

    def live_start(self, current_turn: int) -> dict[str, Any]:
        return self.call(
            self.scenario_endpoint("live_start"),
            {"current_turn": int(current_turn)},
        )

    def minigame_end(
        self,
        current_turn: int,
        result_state: int = 1,
        result_value: int = 0,
        result_detail_array: list[Any] | None = None,
    ) -> dict[str, Any]:
        return self.call(
            self.scenario_endpoint("minigame_end"),
            {
                "result": {
                    "result_state": int(result_state),
                    "result_value": int(result_value),
                    "result_detail_array": result_detail_array,
                },
                "current_turn": int(current_turn),
            },
        )

    def gain_skills(self, gain_skill_info_array: list[Mapping[str, Any]], current_turn: int) -> dict[str, Any]:
        normalized = [
            {
                "skill_id": int(item["skill_id"]),
                "level": int(item.get("level", item.get("skill_level", 1))),
            }
            for item in gain_skill_info_array
        ]
        return self.call(
            self.scenario_endpoint("gain_skills"),
            {"gain_skill_info_array": normalized, "current_turn": int(current_turn)},
        )

    def factor_select(
        self,
        skill_id_array: list[int] | None = None,
        current_turn: int | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"skill_id_array": skill_id_array}
        if current_turn is not None:
            payload["current_turn"] = int(current_turn)
        return self.call(self.scenario_endpoint("factor_select"), payload)

    def finish_career(
        self,
        current_turn: int,
        is_force_delete: bool = False,
        factor_lottery_id: int | None = 1,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "is_force_delete": bool(is_force_delete),
            "current_turn": int(current_turn),
        }
        if factor_lottery_id is not None:
            payload["factor_lottery_id"] = int(factor_lottery_id)
        return self.call(self.scenario_endpoint("finish"), payload)


def _validate_signup_consent(consent: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(consent, Mapping):
        raise HeadlessAuthError("signup_consent must be a mapping")
    for flag in ("terms_read", "privacy_read", "terms_accepted"):
        if consent.get(flag) is not True:
            raise HeadlessAuthError(
                "signup_consent needs terms accepted"
            )
    country = str(consent.get("country") or "").strip()
    if not country or len(country) > 128 or any(ord(c) < 0x20 or ord(c) == 0x7F for c in country):
        raise HeadlessAuthError("signup_consent country is invalid")

    birth = consent.get("optin_user_birth")
    if isinstance(birth, bool) or not isinstance(birth, int):
        raise HeadlessAuthError("optin_user_birth must be YYYYMM")
    birth_str = str(birth)
    if not re.fullmatch(r"(?:19|20)\d{2}(?:0[1-9]|1[0-2])", birth_str):
        raise HeadlessAuthError("optin_user_birth is not YYYYMM")
    datetime.strptime(birth_str, "%Y%m")

    dma_state = consent.get("dma_state", 0)
    if isinstance(dma_state, bool) or not isinstance(dma_state, int) or dma_state not in (0, 1):
        raise HeadlessAuthError("signup_consent dma_state must be 0 or 1")

    attestation_type = consent.get("attestation_type", 0)
    if isinstance(attestation_type, bool) or not isinstance(attestation_type, int) or not (0 <= attestation_type <= 3):
        raise HeadlessAuthError("signup_consent attestation_type is invalid")

    return {
        "credential": "",
        "error_code": int(consent.get("error_code", 0)),
        "error_message": str(consent.get("error_message", "")),
        "attestation_type": attestation_type,
        "optin_user_birth": birth,
        "dma_state": dma_state,
        "country": country,
    }


def _extract_server_auth(client: UmaClient, res: Mapping[str, Any]) -> bytes | None:
    return issued_auth_from_header(client.last_response_header) or _auth_from_response(res)


def _require_non_tutorial_start(res: Mapping[str, Any]) -> None:
    data = res.get("data")
    if not isinstance(data, Mapping) or "is_tutorial" not in data:
        raise HeadlessAuthError(
            "start_session: no is_tutorial",
            code=1,
            endpoint="tool/start_session",
        )
    is_tut = data.get("is_tutorial")
    if not isinstance(is_tut, bool):
        raise HeadlessAuthError(
            "start_session: is_tutorial not boolean",
            code=1,
            endpoint="tool/start_session",
        )
    if is_tut:
        raise HeadlessAuthError(
            "start_session: tutorial not initialized",
            code=1,
            endpoint="tool/start_session",
        )


def _require_valid_load_index(res: Mapping[str, Any]) -> None:
    data = res.get("data")
    if not isinstance(data, Mapping):
        raise HeadlessAuthError("load/index: no data", code=1, endpoint="load/index")
    user_info = data.get("user_info")
    if not isinstance(user_info, Mapping):
        raise HeadlessAuthError("load/index: no user_info", code=1, endpoint="load/index")
    tut_step = user_info.get("tutorial_step")
    if isinstance(tut_step, bool) or not isinstance(tut_step, int):
        raise HeadlessAuthError("load/index: tutorial_step not an integer", code=1, endpoint="load/index")


def bootstrap_headless_auth(
    runtime_dir: Path | str,
    provider: SteamTicketProvider,
    signup_consent: dict[str, Any] | None = None,
    proxy: str | None = None,
    device_state: dict[str, Any] | None = None,
    persist_device: bool = True,
) -> tuple[UmaClient, dict[str, Any]]:
    priv_dir = ensure_private_runtime_dir(runtime_dir)
    device_state_path = priv_dir / "headless_device.json"

    try:
        provider.ensure_lease()
        steam_id = str(provider.steam_id)
        steam_ticket = str(provider.steam_session_ticket)
    except SteamTicketError as exc:
        raise HeadlessAuthError(f"Steam ticket failed during bootstrap: {exc}") from exc

    steam_id_hash = compute_steam_id_hash(steam_id)
    if isinstance(device_state, dict):
        stable = device_state_record(
            udid=device_state.get("udid"),
            device_id=device_state.get("device_id"),
            viewer_id=device_state.get("viewer_id"),
            auth_key=device_state.get("auth_key"),
            steam_id_hash=device_state.get("steam_id_hash"),
            resource_version=device_state.get("resource_version"),
        )
        if stable["steam_id_hash"] != steam_id_hash:
            stable = None
    else:
        stable = read_device_state(device_state_path, expected_steam_id_hash=steam_id_hash)
    timing = TimingDNA(priv_dir / ".timing_dna")

    fresh_identity = stable is None
    if signup_consent is not None and not fresh_identity:
        raise HeadlessAuthError("signup_consent with established device state")

    if fresh_identity:
        udid = str(uuid.uuid4())
        device = runtime_device_fields(udid, None)
        res_ver = DEFAULT_RES_VER
        res_ver_needs_probe = True
        stable_viewer: str | None = None
        stable_auth: bytes = b""
    else:
        assert stable is not None
        udid = str(stable["udid"])
        device = runtime_device_fields(udid, str(stable["device_id"]))
        res_ver = str(stable["resource_version"])
        res_ver_needs_probe = not bool(stable.get("resource_version_known", True))
        stable_viewer = str(stable["viewer_id"])
        stable_auth = bytes.fromhex(str(stable["auth_key"]))

    _, app_ver = lookup_apple_app_version(proxy=proxy)
    cfg: dict[str, Any] = {
        **device,
        "udid": udid,
        "viewer_id": int(stable_viewer) if stable_viewer else 0,
        "auth_key": stable_auth.hex() if stable_auth else "",
        "steam_id": steam_id,
        "steam_session_ticket": steam_ticket,
        "app_ver": app_ver,
        "res_ver": res_ver,
    }

    client = UmaClient(
        cfg,
        provider=provider,
        timing=timing,
        proxy=proxy,
        allow_unauthenticated=True,
    )

    handoff_succeeded = False
    try:
        if res_ver_needs_probe:
            try:
                client.probe_resource_version(
                    {
                        **device,
                        "steam_id": client.steam_id,
                        "steam_session_ticket": client.steam_ticket,
                    }
                )
            except StateRecoveryError:
                client.res_ver = res_ver

        if fresh_identity:
            client.sid = make_sid("0", udid)
            social_payload = {
                "openid": client.steam_id,
                "openid_type": 5,
                "authentication_token": client.steam_ticket,
                "not_return_error": True,
                "steam_id": client.steam_id,
                "steam_session_ticket": client.steam_ticket,
            }
            try:
                social_res = client.call(
                    "account/get_by_social_account",
                    social_payload,
                    _auth_override=b"",
                    _viewer_header_override="0",
                    _skip_common=True,
                )
                social_viewer = _extract_viewer_id(social_res)
            except StateRecoveryError:
                social_viewer = None
            if social_viewer:
                client.sid = make_sid(social_viewer, udid)
                start_payload = client.common(viewer_override=0)
                start_payload.pop("viewer_id", None)
                start_payload.update({"attestation_type": 0, "device_token": None})
                try:
                    start_res = client.call(
                        "tool/start_session",
                        start_payload,
                        _auth_override=b"",
                        _viewer_header_override=social_viewer,
                        _skip_common=True,
                    )
                except StateRecoveryError as exc:
                    raise HeadlessAuthError(
                        f"Fresh start_session failed: {exc}",
                        code=exc.code,
                        endpoint="tool/start_session",
                    ) from exc
                _require_non_tutorial_start(start_res)
                issued_auth = _extract_server_auth(client, start_res)
                if issued_auth is None or len(issued_auth) != 48:
                    raise HeadlessAuthError(
                        "start_session: no 164-byte auth_key",
                        code=1,
                        endpoint="tool/start_session",
                    )
                issued_viewer = _extract_viewer_id(start_res) or social_viewer
            else:
                client.sid = make_sid("0", udid)
                steam_block = {
                    "steam_id": client.steam_id,
                    "steam_session_ticket": client.steam_ticket,
                }
                pre_payload = {
                    "attestation_type": 0,
                    "button_info": "",
                    "carrier": "",
                    "device_token": None,
                    "dmm_onetime_token": None,
                    "dmm_viewer_id": None,
                    **device,
                    "keychain": 0,
                    **steam_block,
                    "viewer_id": 0,
                }
                try:
                    pre_res = client.call(
                        "tool/pre_signup",
                        pre_payload,
                        _auth_override=b"",
                        _viewer_header_override="",
                        _skip_common=True,
                    )
                except StateRecoveryError as exc:
                    raise HeadlessAuthError(
                        f"pre_signup failed: {exc}",
                        code=exc.code,
                        endpoint="tool/pre_signup",
                    ) from exc
                pre_data = pre_res.get("data")
                if not isinstance(pre_data, Mapping) or pre_data.get("enable_steam_account") is not True:
                    raise HeadlessAuthError(
                        "pre_signup: enrollment not enabled",
                        code=1,
                        endpoint="tool/pre_signup",
                    )
                consent = (
                    dict(signup_consent)
                    if signup_consent is not None
                    else {
                        "terms_read": True,
                        "privacy_read": True,
                        "terms_accepted": True,
                        "optin_user_birth": 199001,
                        "dma_state": 0,
                    }
                )
                if not str(consent.get("country") or "").strip():
                    for entry in pre_data.get("country_list") or []:
                        value = (
                            str(entry.get("country") or "").strip()
                            if isinstance(entry, Mapping)
                            else str(entry).strip()
                        )
                        if value:
                            consent["country"] = value
                            break
                signup_fields = _validate_signup_consent(consent)
                client.sid = make_sid("0", udid)
                signup_payload = {
                    **signup_fields,
                    "viewer_id": 0,
                    **device,
                    **steam_block,
                }
                try:
                    signup_res = client.call(
                        "tool/signup",
                        signup_payload,
                        _auth_override=b"",
                        _viewer_header_override="0",
                        _skip_common=True,
                    )
                except StateRecoveryError as exc:
                    raise HeadlessAuthError(
                        f"signup failed: {exc}",
                        code=exc.code,
                        endpoint="tool/signup",
                    ) from exc
                signup_viewer = _extract_viewer_id(signup_res)
                signup_auth = _extract_server_auth(client, signup_res)
                if not signup_viewer or signup_auth is None or len(signup_auth) != 48:
                    raise HeadlessAuthError(
                        "signup: no viewer_id or 48-byte auth_key",
                        code=1,
                        endpoint="tool/signup",
                    )
                client.viewer_id = int(signup_viewer)
                client.auth_key_hex = signup_auth.hex()
                client.sid = make_sid(signup_viewer, udid)
                start_res = client.call(
                    "tool/start_session",
                    {"attestation_type": 0, "device_token": None},
                )
                _require_non_tutorial_start(start_res)
                rotated = _extract_server_auth(client, start_res)
                issued_auth = rotated if rotated is not None else signup_auth
                issued_viewer = _extract_viewer_id(start_res) or signup_viewer
        else:
            assert stable_viewer is not None
            client.viewer_id = int(stable_viewer)
            client.auth_key_hex = stable_auth.hex()
            client.regen_sid()
            try:
                start_res = client.call(
                    "tool/start_session",
                    {"attestation_type": 0, "device_token": None},
                )
            except StateRecoveryError as exc:
                raise HeadlessAuthError(
                    f"start_session failed: {exc}",
                    code=exc.code,
                    endpoint="tool/start_session",
                ) from exc
            returned_vid = _extract_viewer_id(start_res)
            rotated_auth = _extract_server_auth(client, start_res)
            if returned_vid is not None and returned_vid != stable_viewer:
                if rotated_auth is None or len(rotated_auth) != 48:
                    raise HeadlessAuthError(
                        "viewer_id changed without fresh auth_key",
                        code=1,
                        endpoint="tool/start_session",
                    )
                issued_viewer = returned_vid
                issued_auth = rotated_auth
            else:
                issued_viewer = returned_vid or stable_viewer
                issued_auth = rotated_auth if rotated_auth is not None else stable_auth

        client.viewer_id = int(issued_viewer)
        client.auth_key_hex = issued_auth.hex()

        rebootstrap_done = False
        while True:
            try:
                load_res = client.call("load/index", {"adid": ""})
                break
            except StateRecoveryError as exc:
                if not rebootstrap_done and exc.code == 709 and not fresh_identity:
                    rebootstrap_done = True
                    new_ticket = provider.refresh()
                    client.steam_ticket = new_ticket
                    client.regen_sid()
                    s2 = client.call(
                        "tool/start_session",
                        {"attestation_type": 0, "device_token": None},
                    )
                    _require_non_tutorial_start(s2)
                    a2 = _extract_server_auth(client, s2)
                    if a2 is None or len(a2) != 48 or a2 == issued_auth:
                        raise HeadlessAuthError(
                            "709 rebootstrap: no fresh 48-byte auth_key",
                            code=709,
                            endpoint="tool/start_session",
                        ) from exc
                    v2 = _extract_viewer_id(s2) or str(client.viewer_id)
                    issued_viewer = v2
                    issued_auth = a2
                    client.viewer_id = int(issued_viewer)
                    client.auth_key_hex = issued_auth.hex()
                    continue
                if not rebootstrap_done and exc.code == 217:
                    rebootstrap_done = True
                    client.regen_sid()
                    s2 = client.call(
                        "tool/start_session",
                        {"attestation_type": 0, "device_token": None},
                    )
                    a2 = _extract_server_auth(client, s2)
                    if a2 is not None and len(a2) == 48:
                        issued_auth = a2
                        client.auth_key_hex = issued_auth.hex()
                    continue
                raise HeadlessAuthError(
                    f"load/index failed: {exc}",
                    code=exc.code,
                    endpoint="load/index",
                ) from exc

        if fresh_identity or rebootstrap_done:
            _require_valid_load_index(load_res)

        load_auth = _extract_server_auth(client, load_res)
        load_vid = _extract_viewer_id(load_res)
        if load_vid is not None and load_vid != str(issued_viewer):
            if load_auth is None or len(load_auth) != 48:
                raise HeadlessAuthError(
                    "viewer_id changed without fresh auth_key",
                    code=1,
                    endpoint="load/index",
                )
            issued_viewer = load_vid
            issued_auth = load_auth
        elif load_auth is not None and len(load_auth) == 48:
            issued_auth = load_auth

        client.viewer_id = int(issued_viewer)
        client.auth_key_hex = issued_auth.hex()
        client.refresh_cached_account_state(load_res.get("data"))

        record = device_state_record(
            udid=udid,
            device_id=device["device_id"],
            viewer_id=issued_viewer,
            auth_key=issued_auth,
            steam_id_hash=steam_id_hash,
            resource_version=client.res_ver,
        )
        if persist_device and not isinstance(device_state, dict):
            write_device_state(
                device_state_path,
                udid=record["udid"],
                device_id=record["device_id"],
                viewer_id=record["viewer_id"],
                auth_key=record["auth_key"],
                steam_id_hash=record["steam_id_hash"],
                resource_version=record["resource_version"],
            )
        client.device_state = record
        handoff_succeeded = True
        return client, load_res
    finally:
        if not handoff_succeeded:
            client._steam_ticket_provider = None
            client.close()


