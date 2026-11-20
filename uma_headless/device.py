from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import secrets
import socket
import stat
import uuid
from pathlib import Path
from typing import Any

STATE_SCHEMA = 5
PORTABLE_WINDOWS_OS = "Windows 10  (10.0.19045) 64bit"
DEFAULT_LOCALE = "JPN"
DEFAULT_RES_VER = "10007550"

_DEVICE_ID_RE = re.compile(r"\A[0-9a-f]{40}\Z")
_AUTH_KEY_RE = re.compile(r"\A[0-9a-f]{96}\Z")
_STEAM_HASH_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_RES_VER_RE = re.compile(r"\A[0-9]{1,32}\Z")


class HeadlessAuthError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: int | None = None,
        endpoint: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.endpoint = endpoint


def compute_steam_id_hash(steam_id: str) -> str:
    text = str(steam_id or "").strip()
    if len(text) != 17 or not text.isdigit() or int(text) <= 0:
        raise HeadlessAuthError("not a 17-digit SteamID64")
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def _clean_text(value: Any, *, limit: int = 256) -> str:
    collapsed = " ".join(str(value or "").split())
    printable = "".join(ch for ch in collapsed if ch.isprintable()).strip()
    return printable[:limit]


def _read_small_sys_text(path: Path, limit: int = 4096) -> str:
    try:
        info = path.lstat()
    except OSError:
        return ""
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        return ""
    try:
        with path.open("rb") as fh:
            raw = fh.read(limit)
    except OSError:
        return ""
    return _clean_text(raw.decode("utf-8", errors="ignore"), limit=limit)


def derive_portable_device_id() -> str:
    parts: list[str] = []
    if platform.system() == "Linux":
        for sys_path in (
            Path("/sys/devices/virtual/dmi/id/board_serial"),
            Path("/sys/devices/virtual/dmi/id/bios_serial"),
            Path("/sys/devices/virtual/dmi/id/product_uuid"),
            Path("/etc/machine-id"),
        ):
            val = _read_small_sys_text(sys_path)
            if val:
                parts.append(f"{sys_path}:{val}")
    if not parts:
        node = _clean_text(platform.node())
        mach = _clean_text(platform.machine())
        sysname = _clean_text(platform.system())
        if node or mach:
            parts.append(f"host:{sysname}:{node}:{mach}")
        else:
            return secrets.token_hex(20)
    return hashlib.sha1("\x1f".join(parts).encode("utf-8")).hexdigest()


def _portable_device_name() -> str:
    if platform.system() == "Linux":
        product = _read_small_sys_text(Path("/sys/devices/virtual/dmi/id/product_name"))
        vendor = _read_small_sys_text(Path("/sys/devices/virtual/dmi/id/sys_vendor"))
        if product and vendor and product.casefold() != vendor.casefold():
            return _clean_text(f"{product} ({vendor})")
        if product:
            return product
    return _clean_text(platform.node()) or "Windows"


def _portable_graphics_name() -> str:
    proc = _clean_text(platform.processor())
    mach = _clean_text(platform.machine())
    return proc or mach or "Direct3D 11"


def _local_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("198.51.100.1", 80))
        addr = str(sock.getsockname()[0] or "").strip()
        return addr if addr else "127.0.0.1"
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def runtime_device_fields(udid: str, device_id: str | None = None) -> dict[str, Any]:
    try:
        normalized_udid = str(uuid.UUID(str(udid).strip()))
    except (ValueError, TypeError, AttributeError) as exc:
        raise HeadlessAuthError("udid must be a valid UUID string") from exc
    _ = normalized_udid

    if device_id is None or str(device_id).strip() == "":
        resolved_device_id = derive_portable_device_id()
    else:
        resolved_device_id = str(device_id).strip().lower()
        if not _DEVICE_ID_RE.fullmatch(resolved_device_id):
            raise HeadlessAuthError("bad device_id")

    return {
        "device": 4,
        "device_id": resolved_device_id,
        "device_name": _portable_device_name(),
        "graphics_device_name": _portable_graphics_name(),
        "ip_address": _local_ip(),
        "platform_os_version": PORTABLE_WINDOWS_OS,
        "carrier": "",
        "keychain": 0,
        "locale": DEFAULT_LOCALE,
        "button_info": "",
        "dmm_viewer_id": None,
        "dmm_onetime_token": None,
    }


def ensure_private_runtime_dir(runtime_dir: Path | str) -> Path:
    resolved = Path(os.path.abspath(os.path.expanduser(os.fspath(runtime_dir))))
    cursor = resolved
    existing_ancestors: list[Path] = []
    while True:
        if cursor.exists() or cursor.is_symlink():
            existing_ancestors.append(cursor)
        if cursor == cursor.parent:
            break
        cursor = cursor.parent
    for anc in existing_ancestors:
        info = anc.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise HeadlessAuthError(f"Runtime ancestor {anc} must not be a symlink")

    resolved.mkdir(mode=0o700, parents=True, exist_ok=True)
    dir_info = resolved.lstat()
    if stat.S_ISLNK(dir_info.st_mode) or not stat.S_ISDIR(dir_info.st_mode):
        raise HeadlessAuthError("Runtime directory is not a safe directory")
    if os.name == "posix":
        if hasattr(os, "getuid") and dir_info.st_uid != os.getuid():
            raise HeadlessAuthError("Runtime directory is owned by another user")
        if stat.S_IMODE(dir_info.st_mode) != 0o700:
            os.chmod(resolved, 0o700)
            dir_info = resolved.lstat()
            if stat.S_IMODE(dir_info.st_mode) != 0o700:
                raise HeadlessAuthError("Runtime directory must have 0700 permissions")
    return resolved


def _verify_parent_dir(path: Path) -> None:
    parent = path.parent
    try:
        p_info = parent.lstat()
    except FileNotFoundError as exc:
        raise HeadlessAuthError("Device state parent directory does not exist") from exc
    except OSError as exc:
        raise HeadlessAuthError("cannot stat device state dir") from exc

    if stat.S_ISLNK(p_info.st_mode) or not stat.S_ISDIR(p_info.st_mode):
        raise HeadlessAuthError("Device state parent path is unsafe")
    if os.name == "posix":
        if hasattr(os, "getuid") and p_info.st_uid != os.getuid():
            raise HeadlessAuthError("device state dir owned by another user")
        if stat.S_IMODE(p_info.st_mode) != 0o700:
            raise HeadlessAuthError("device state dir is not 0700")

    cursor = parent
    while cursor != cursor.parent:
        anc = cursor.lstat()
        if stat.S_ISLNK(anc.st_mode):
            raise HeadlessAuthError("Device state ancestor must not be a symlink")
        cursor = cursor.parent


def read_device_state(
    path: Path | str,
    *,
    expected_steam_id_hash: str | None = None,
) -> dict[str, Any] | None:
    resolved = Path(os.path.abspath(os.path.expanduser(os.fspath(path))))
    try:
        f_info = resolved.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise HeadlessAuthError("headless_device.json could not be inspected") from exc

    if stat.S_ISLNK(f_info.st_mode) or not stat.S_ISREG(f_info.st_mode):
        raise HeadlessAuthError("headless_device.json is not a regular file")
    _verify_parent_dir(resolved)

    if os.name == "posix" and hasattr(os, "O_NOFOLLOW"):
        if hasattr(os, "getuid") and f_info.st_uid != os.getuid():
            raise HeadlessAuthError("headless_device.json owned by another user")
        if stat.S_IMODE(f_info.st_mode) != 0o600:
            raise HeadlessAuthError("headless_device.json is not 0600")
        fd = os.open(resolved, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            fd_info = os.fstat(fd)
            if not stat.S_ISREG(fd_info.st_mode) or stat.S_IMODE(fd_info.st_mode) != 0o600:
                raise HeadlessAuthError("headless_device.json descriptor rejected")
            raw_bytes = os.read(fd, 65536)
        finally:
            os.close(fd)
    else:
        raw_bytes = resolved.read_bytes()

    try:
        state = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HeadlessAuthError("headless_device.json contains malformed JSON") from exc
    if not isinstance(state, dict):
        raise HeadlessAuthError("headless_device.json root must be an object")
    if state.get("schema") != STATE_SCHEMA:
        raise HeadlessAuthError(f"Unsupported headless_device.json schema: {state.get('schema')!r}")
    if state.get("phase") != "established":
        raise HeadlessAuthError("phase is not established")
    if state.get("provenance") != "server-issued":
        raise HeadlessAuthError("provenance is not server-issued")

    record = device_state_record(
        udid=state.get("udid"),
        device_id=state.get("device_id"),
        viewer_id=state.get("viewer_id"),
        auth_key=state.get("auth_key"),
        steam_id_hash=state.get("steam_id_hash"),
        resource_version=state.get("resource_version"),
    )
    if expected_steam_id_hash is not None and record["steam_id_hash"] != str(expected_steam_id_hash).strip().lower():
        raise HeadlessAuthError("device file belongs to another account")
    record["resource_version_known"] = str(state.get("resource_version") or "").strip() == record["resource_version"]
    return record


def device_state_record(
    *,
    udid: Any,
    device_id: Any,
    viewer_id: Any,
    auth_key: Any,
    steam_id_hash: Any,
    resource_version: Any = DEFAULT_RES_VER,
) -> dict[str, Any]:
    try:
        norm_udid = str(uuid.UUID(str(udid).strip()))
    except (ValueError, TypeError) as exc:
        raise HeadlessAuthError("Invalid udid for headless_device.json") from exc
    norm_device_id = str(device_id or "").strip().lower()
    if not _DEVICE_ID_RE.fullmatch(norm_device_id):
        raise HeadlessAuthError("Invalid device_id for headless_device.json")
    if isinstance(viewer_id, bool):
        raise HeadlessAuthError("Invalid viewer_id for headless_device.json")
    try:
        vid_int = int(viewer_id)
    except (TypeError, ValueError, OverflowError) as exc:
        raise HeadlessAuthError("Invalid viewer_id for headless_device.json") from exc
    if vid_int <= 0:
        raise HeadlessAuthError("viewer_id must be positive")
    if isinstance(auth_key, (bytes, bytearray, memoryview)):
        norm_auth = bytes(auth_key).hex()
    else:
        norm_auth = str(auth_key or "").strip().lower()
    if not _AUTH_KEY_RE.fullmatch(norm_auth):
        raise HeadlessAuthError("auth_key must be 48 bytes (96 hex chars)")
    norm_hash = str(steam_id_hash or "").strip().lower()
    if not _STEAM_HASH_RE.fullmatch(norm_hash):
        raise HeadlessAuthError("steam_id_hash must be 64 lowercase hex chars")
    norm_res_ver = str(resource_version or DEFAULT_RES_VER).strip()
    if not _RES_VER_RE.fullmatch(norm_res_ver) or int(norm_res_ver) <= 0:
        norm_res_ver = DEFAULT_RES_VER
    return {
        "schema": STATE_SCHEMA,
        "udid": norm_udid,
        "device_id": norm_device_id,
        "phase": "established",
        "viewer_id": str(vid_int),
        "auth_key": norm_auth,
        "steam_id_hash": norm_hash,
        "provenance": "server-issued",
        "resource_version": norm_res_ver,
    }


def write_device_state(
    path: Path | str,
    *,
    udid: str,
    device_id: str,
    viewer_id: int | str,
    auth_key: bytes | str,
    steam_id_hash: str,
    resource_version: str = DEFAULT_RES_VER,
    phase: str = "established",
    provenance: str = "server-issued",
) -> Path:
    if phase != "established":
        raise HeadlessAuthError("device state is not established")
    if provenance != "server-issued":
        raise HeadlessAuthError("provenance is not server-issued")

    payload = device_state_record(
        udid=udid,
        device_id=device_id,
        viewer_id=viewer_id,
        auth_key=auth_key,
        steam_id_hash=steam_id_hash,
        resource_version=resource_version,
    )

    resolved = Path(os.path.abspath(os.path.expanduser(os.fspath(path))))
    ensure_private_runtime_dir(resolved.parent)
    _verify_parent_dir(resolved)

    if resolved.exists() or resolved.is_symlink():
        t_info = resolved.lstat()
        if stat.S_ISLNK(t_info.st_mode) or not stat.S_ISREG(t_info.st_mode):
            raise HeadlessAuthError("existing device file is unsafe")
        if os.name == "posix" and hasattr(os, "getuid") and t_info.st_uid != os.getuid():
            raise HeadlessAuthError("existing device file owned by another user")

    encoded = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")

    temp_path = resolved.parent / f".headless_device.{os.getpid()}.{secrets.token_hex(8)}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    fd: int | None = None
    try:
        fd = os.open(temp_path, flags, 0o600)
        view = memoryview(encoded)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("Short write saving headless_device.json")
            view = view[written:]
        os.fsync(fd)
        os.close(fd)
        fd = None
        os.replace(temp_path, resolved)
        if os.name == "posix":
            os.chmod(resolved, 0o600)
    except BaseException as exc:
        if fd is not None:
            os.close(fd)
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        if isinstance(exc, HeadlessAuthError):
            raise
        raise HeadlessAuthError("Failed to persist headless_device.json") from exc
    return resolved
