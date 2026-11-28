from __future__ import annotations

import base64
import collections
import hashlib
import json
import math
import os
import queue
import secrets
import ssl
import stat
import struct
import threading
import time
import urllib.request
import zlib
from pathlib import Path
from typing import Sequence

from Crypto.Cipher import PKCS1_v1_5
from Crypto.PublicKey import RSA

from .cm_tcp import CMSocketClient
from urllib.parse import urlsplit
from .proto import (
    UnsupportedPacketError,
    BeginAuthSessionViaCredentials_Request,
    BeginAuthSessionViaCredentials_Response,
    BeginAuthSessionViaQR_Request,
    BeginAuthSessionViaQR_Response,
    CAuthentication_DeviceDetails,
    CMsgAuthTicket,
    CMsgClientAuthList,
    CMsgClientAuthListAck,
    CMsgClientGameConnectTokens,
    CMsgClientGetAppOwnershipTicket,
    CMsgClientGetAppOwnershipTicketResponse,
    CMsgClientHeartBeat,
    CMsgClientHello,
    CMsgClientLogon,
    CMsgClientLogonResponse,
    CMsgClientRequestFreeLicense,
    CMsgClientRequestFreeLicenseResponse,
    CMsgIPAddress,
    CMsgMulti,
    CMsgProtoBufHeader,
    EMSG_CLIENT_AUTH_LIST,
    EMSG_CLIENT_AUTH_LIST_ACK,
    EMSG_CLIENT_GAME_CONNECT_TOKENS,
    EMSG_CLIENT_GET_APP_OWNERSHIP_TICKET,
    EMSG_CLIENT_GET_APP_OWNERSHIP_TICKET_RESPONSE,
    EMSG_CLIENT_HEARTBEAT,
    EMSG_CLIENT_HELLO,
    EMSG_CLIENT_LOGON,
    EMSG_CLIENT_LOGON_RESPONSE,
    EMSG_CLIENT_REQUEST_FREE_LICENSE,
    EMSG_CLIENT_REQUEST_FREE_LICENSE_RESPONSE,
    EMSG_MULTI,
    EMSG_SERVICE_METHOD_CALL_FROM_CLIENT_NON_AUTHED,
    EMSG_SERVICE_METHOD_RESPONSE,
    GetPasswordRSAPublicKey_Request,
    GetPasswordRSAPublicKey_Response,
    PollAuthSessionStatus_Request,
    PollAuthSessionStatus_Response,
    ProtoError,
    UpdateAuthSessionWithSteamGuardCode_Request,
    pack_cm_packet,
    steam_machine_id,
    unpack_cm_packet,
    unpack_multi,
)
from .ws import WebSocketClient, WebSocketClosedError, WebSocketError

APP_ID = 3224770
SERVER_SECRET = b"str:unityauthenticationservice\x00"
TICKET_TYPE_WEBAPI = 5
MAX_REFRESH_TOKEN_BYTES = 16 * 1024
MAX_TICKET_BYTES = 2560
NO_JOB_ID = 0xFFFFFFFFFFFFFFFF

ERESULT_OK = 1
ERESULT_EXPIRED = 27
ERESULT_TRY_ANOTHER_CM = 48

AUTH_GUARD_NONE = 1
AUTH_GUARD_EMAIL_CODE = 2
AUTH_GUARD_DEVICE_CODE = 3
AUTH_GUARD_DEVICE_CONFIRMATION = 4
AUTH_GUARD_EMAIL_CONFIRMATION = 5

_GUARD_SLUGS = {
    AUTH_GUARD_EMAIL_CODE: "email_code",
    AUTH_GUARD_DEVICE_CODE: "device_code",
    AUTH_GUARD_DEVICE_CONFIRMATION: "device_confirm",
    AUTH_GUARD_EMAIL_CONFIRMATION: "email_confirm",
}

_FRIENDLY_ERESULTS = {
    5: "Incorrect Steam username or password",
    65: "Incorrect email Steam Guard code",
    84: "Too many Steam login attempts — wait before retrying",
    88: "Incorrect Steam Guard authenticator code",
    89: "Incorrect Steam Guard authenticator code",
}


def _friendly_eresult_message(method_name: str, eresult: int) -> str:
    return _FRIENDLY_ERESULTS.get(
        eresult,
        f"Steam authentication service rejected {method_name} (eresult={eresult})",
    )

CM_DISCOVERY_URL = (
    "https://api.steampowered.com/ISteamDirectory/GetCMListForConnect/v1/"
    "?cmtype=websockets&cellid=0"
)

METHOD_BEGIN_QR = "Authentication.BeginAuthSessionViaQR\x231"
METHOD_GET_RSA_KEY = "Authentication.GetPasswordRSAPublicKey\x231"
METHOD_BEGIN_CREDENTIALS = "Authentication.BeginAuthSessionViaCredentials\x231"
METHOD_UPDATE_GUARD = "Authentication.UpdateAuthSessionWithSteamGuardCode\x231"
METHOD_POLL_STATUS = "Authentication.PollAuthSessionStatus\x231"


class SteamTicketError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        stage: str = "unknown",
        result_code: int | None = None,
        safe_reason: str | None = None,
        transport: bool = False,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.result_code = result_code
        self.safe_reason = safe_reason
        self.transport = transport


def decode_steam_refresh_jwt(token: str) -> str:
    if not isinstance(token, str):
        raise SteamTicketError("Refresh token must be a string", stage="token", safe_reason="invalid_token")
    cleaned = token.strip()
    if not cleaned or "\n" in cleaned or "\r" in cleaned:
        raise SteamTicketError("Refresh token has invalid whitespace", stage="token", safe_reason="invalid_token")
    parts = cleaned.split(".")
    if len(parts) != 3 or not all(parts):
        raise SteamTicketError("Refresh token is not a 3-part JWT", stage="token", safe_reason="invalid_token")
    padded = parts[1] + ("=" * ((4 - len(parts[1]) % 4) % 4))
    try:
        raw_claims = base64.urlsafe_b64decode(padded.encode("ascii"))
        claims = json.loads(raw_claims.decode("utf-8"))
    except Exception as exc:
        raise SteamTicketError("Refresh token JWT payload is malformed", stage="token", safe_reason="invalid_token") from exc
    if not isinstance(claims, dict) or claims.get("iss") != "steam":
        raise SteamTicketError("Refresh token issuer must be 'steam'", stage="token", safe_reason="invalid_token")
    aud = claims.get("aud")
    if isinstance(aud, str):
        aud = [aud]
    if not isinstance(aud, list) or "client" not in aud or "derive" not in aud:
        raise SteamTicketError(
            "token audience missing client/derive",
            stage="token",
            safe_reason="invalid_token",
        )
    sub = str(claims.get("sub") or "").strip()
    if len(sub) != 17 or not sub.isdigit() or int(sub) <= 0:
        raise SteamTicketError(
            "token subject is not a SteamID64",
            stage="token",
            safe_reason="invalid_token",
        )
    return sub


def read_refresh_token_file(path: Path) -> tuple[str, str]:
    resolved = Path(os.path.abspath(os.path.expanduser(os.fspath(path))))
    if os.name == "posix" and hasattr(os, "O_NOFOLLOW"):
        flags = os.O_RDONLY | os.O_NOFOLLOW
        try:
            fd = os.open(resolved, flags)
        except FileNotFoundError as exc:
            raise SteamTicketError("Refresh token file does not exist", stage="token") from exc
        except OSError as exc:
            raise SteamTicketError("Refresh token file cannot be opened safely", stage="token") from exc
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise SteamTicketError("Refresh token path is not a regular file", stage="token")
            if hasattr(os, "getuid") and info.st_uid != os.getuid():
                raise SteamTicketError("Refresh token file is owned by another user", stage="token")
            if info.st_mode & 0o077:
                raise SteamTicketError("token file is not 0600", stage="token")
            if info.st_size <= 0 or info.st_size > MAX_REFRESH_TOKEN_BYTES:
                raise SteamTicketError("Refresh token file size is out of bounds", stage="token")
            chunks: list[bytes] = []
            rem = MAX_REFRESH_TOKEN_BYTES + 1
            while rem > 0:
                chunk = os.read(fd, min(4096, rem))
                if not chunk:
                    break
                chunks.append(chunk)
                rem -= len(chunk)
            raw = b"".join(chunks)
        finally:
            os.close(fd)
    else:
        try:
            info = resolved.lstat()
        except FileNotFoundError as exc:
            raise SteamTicketError("Refresh token file does not exist", stage="token") from exc
        except OSError as exc:
            raise SteamTicketError("Refresh token file cannot be inspected", stage="token") from exc
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise SteamTicketError("Refresh token path is not a regular file", stage="token")
        if info.st_size <= 0 or info.st_size > MAX_REFRESH_TOKEN_BYTES:
            raise SteamTicketError("Refresh token file size is out of bounds", stage="token")
        raw = resolved.read_bytes()

    try:
        token = raw.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise SteamTicketError("Refresh token file is not valid UTF-8", stage="token", safe_reason="invalid_token") from exc
    steam_id = decode_steam_refresh_jwt(token)
    return token, steam_id


_TCP_CM_CACHE: list[tuple[str, int]] = []
_TCP_CM_FETCHED_AT = 0.0
_TCP_CM_LOCK = threading.Lock()


def discover_tcp_cm_endpoints() -> list[tuple[str, int]]:
    global _TCP_CM_FETCHED_AT
    with _TCP_CM_LOCK:
        if _TCP_CM_CACHE and time.monotonic() - _TCP_CM_FETCHED_AT < 300:
            return list(_TCP_CM_CACHE)
    url = (
        "https://api.steampowered.com/ISteamDirectory/GetCMListForConnect/v1/"
        "?cellid=0&cmtype=tcp"
    )
    found: list[tuple[str, int]] = []
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        for row in (payload.get("response") or {}).get("serverlist") or []:
            if str(row.get("type") or "") != "netfilter":
                continue
            host, _, port_text = str(row.get("endpoint") or "").partition(":")
            if not host:
                continue
            found.append((host, int(port_text) if port_text.isdigit() else 27017))
    except Exception:
        found = []
    with _TCP_CM_LOCK:
        _TCP_CM_CACHE[:] = found
        _TCP_CM_FETCHED_AT = time.monotonic()
    return list(found)


def discover_cm_endpoints(proxy: str | None = None, timeout: float = 10.0) -> list[str]:
    proxies = {"http": proxy, "https": proxy} if proxy else {}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler(proxies))
    try:
        with opener.open(CM_DISCOVERY_URL, timeout=timeout) as resp:
            if getattr(resp, "status", 200) != 200:
                raise SteamTicketError("CM directory HTTP != 200", stage="connect")
            payload = json.loads(resp.read(512 * 1024).decode("utf-8"))
    except SteamTicketError:
        raise
    except Exception as exc:
        raise SteamTicketError(f"Steam WebSocket CM discovery failed: {exc}", stage="connect") from exc

    body = payload.get("response") if isinstance(payload, dict) else None
    if not isinstance(body, dict) or body.get("success") not in (1, True):
        raise SteamTicketError("bad CM directory payload", stage="connect")
    serverlist = body.get("serverlist")
    if not isinstance(serverlist, list):
        raise SteamTicketError("Steam CM directory returned no serverlist", stage="connect")

    candidates: list[tuple[float, str]] = []
    for entry in serverlist:
        if not isinstance(entry, dict):
            continue
        realm = entry.get("realm", "steamglobal")
        cm_type = entry.get("type", "websockets")
        if realm != "steamglobal" or cm_type != "websockets":
            continue
        endpoint = entry.get("endpoint")
        if not isinstance(endpoint, str) or ":" not in endpoint:
            continue
        host, raw_port = endpoint.rsplit(":", 1)
        host = host.strip()
        try:
            port = int(raw_port)
            load = float(entry.get("wtd_load", entry.get("load", 100.0)))
        except (TypeError, ValueError, OverflowError):
            continue
        if not host or not (1 <= port <= 65535) or not math.isfinite(load):
            continue
        candidates.append((load, f"wss://{host}:{port}/cmsocket/"))

    ordered: list[str] = []
    seen: set[str] = set()
    for _, ws_url in sorted(candidates, key=lambda item: item[0]):
        if ws_url not in seen:
            seen.add(ws_url)
            ordered.append(ws_url)
    if not ordered:
        raise SteamTicketError("no usable CM endpoints", stage="connect")
    return ordered


def build_webapi_auth_ticket(
    gc_token: bytes,
    sequence: int,
    elapsed_ms: int,
    *,
    random_bytes: bytes | None = None,
) -> bytes:
    nonce = secrets.token_bytes(8) if random_bytes is None else bytes(random_bytes)
    if len(nonce) != 8:
        raise SteamTicketError("Auth ticket random nonce must be 8 bytes", stage="auth_register")
    return (
        struct.pack("<I", len(gc_token))
        + bytes(gc_token)
        + struct.pack(
            "<III8sII",
            24,
            1,
            TICKET_TYPE_WEBAPI,
            nonce,
            int(elapsed_ms) & 0xFFFFFFFF,
            int(sequence) & 0xFFFFFFFF,
        )
    )


class _CMSession:
    def __init__(self, ws: WebSocketClient) -> None:
        self.ws = ws
        self.gc_tokens: collections.deque[bytes] = collections.deque()
        self.steam_id_64: int = 0
        self.client_sessionid: int = 0
        self.logged_on: bool = False
        self.heartbeat_seconds: float = 15.0

        self._cond = threading.Condition()
        self._job_waiters: dict[int, queue.Queue[tuple[int, CMsgProtoBufHeader, bytes]]] = {}
        self._emsg_waiters: dict[int, list[queue.Queue[tuple[int, CMsgProtoBufHeader, bytes]]]] = {}
        self._stop_event = threading.Event()
        self._alive = True
        self._reader_error: BaseException | None = None

        self.ws.settimeout(0.25)
        self._reader_thread = threading.Thread(
            target=self._reader_loop,
            name="steam-cm-reader",
            daemon=True,
        )
        self._heartbeat_thread: threading.Thread | None = None
        self._reader_thread.start()

    @property
    def alive(self) -> bool:
        return self._alive and not self._stop_event.is_set() and self.ws.connected

    def start_heartbeat(self, interval_seconds: float) -> None:
        self.heartbeat_seconds = max(5.0, float(interval_seconds or 15.0))
        if self._heartbeat_thread is not None and self._heartbeat_thread.is_alive():
            return
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name="steam-cm-heartbeat",
            daemon=True,
        )
        self._heartbeat_thread.start()

    def _heartbeat_loop(self) -> None:
        while not self._stop_event.wait(self.heartbeat_seconds):
            if not self.alive:
                break
            if not self.logged_on:
                continue
            try:
                self.send_proto(
                    EMSG_CLIENT_HEARTBEAT,
                    CMsgClientHeartBeat(send_reply=False).encode(),
                    authenticated=True,
                )
            except (WebSocketError, OSError, SteamTicketError):
                with self._cond:
                    self._alive = False
                    self._cond.notify_all()
                break

    def _reader_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                frame = self.ws.recv()
            except TimeoutError:
                continue
            except (WebSocketClosedError, WebSocketError, OSError) as exc:
                with self._cond:
                    self._reader_error = exc
                    self._alive = False
                    self._wake_all_waiters_locked()
                    self._cond.notify_all()
                return
            try:
                self._dispatch_packet(frame)
            except UnsupportedPacketError:
                continue
            except ProtoError as exc:
                with self._cond:
                    self._reader_error = exc
                    self._alive = False
                    self._wake_all_waiters_locked()
                    self._cond.notify_all()
                return

    def _wake_all_waiters_locked(self) -> None:
        sentinel_hdr = CMsgProtoBufHeader(eresult=0)
        for waiter in self._job_waiters.values():
            waiter.put((-1, sentinel_hdr, b""))
        for q_list in self._emsg_waiters.values():
            for waiter in q_list:
                waiter.put((-1, sentinel_hdr, b""))

    def _dispatch_packet(self, raw_packet: bytes) -> None:
        try:
            emsg, header, body = unpack_cm_packet(raw_packet)
        except UnsupportedPacketError:
            return
        if emsg == EMSG_MULTI:
            multi = CMsgMulti.decode(body)
            for inner in unpack_multi(multi):
                try:
                    self._dispatch_packet(inner)
                except ProtoError:
                    continue
            return

        with self._cond:
            if emsg == EMSG_CLIENT_LOGON_RESPONSE:
                if header.client_sessionid is not None:
                    self.client_sessionid = header.client_sessionid
                if header.steamid:
                    self.steam_id_64 = header.steamid

            if emsg == EMSG_CLIENT_GAME_CONNECT_TOKENS:
                msg = CMsgClientGameConnectTokens.decode(body)
                added = False
                for tok in msg.tokens:
                    if tok:
                        self.gc_tokens.append(bytes(tok))
                        added = True
                if added:
                    self._cond.notify_all()

            target_job = header.jobid_target
            if target_job is not None and target_job not in (0, NO_JOB_ID):
                waiter = self._job_waiters.get(target_job)
                if waiter is not None:
                    waiter.put((emsg, header, body))

            q_list = self._emsg_waiters.get(emsg)
            if q_list:
                for waiter in list(q_list):
                    waiter.put((emsg, header, body))

    def send_proto(
        self,
        emsg: int,
        body_bytes: bytes,
        *,
        header: CMsgProtoBufHeader | None = None,
        authenticated: bool = False,
    ) -> None:
        if not self.alive:
            raise SteamTicketError("Steam CM session is closed", stage="connect")
        if header is None:
            if authenticated:
                header = CMsgProtoBufHeader(
                    steamid=self.steam_id_64,
                    client_sessionid=self.client_sessionid,
                )
            else:
                header = CMsgProtoBufHeader(steamid=0, client_sessionid=0)
        raw = pack_cm_packet(emsg, header, body_bytes)
        try:
            self.ws.send_binary(raw)
        except (WebSocketError, OSError) as exc:
            with self._cond:
                self._reader_error = exc
                self._alive = False
                self._wake_all_waiters_locked()
                self._cond.notify_all()
            raise SteamTicketError(
                f"Steam CM send failed: {exc}",
                stage="connect",
                transport=True,
            ) from exc

    def send_and_wait_emsg(
        self,
        send_emsg: int,
        body_bytes: bytes,
        expect_emsg: int,
        *,
        header: CMsgProtoBufHeader | None = None,
        authenticated: bool = False,
        timeout: float = 15.0,
        stage: str = "unknown",
    ) -> tuple[CMsgProtoBufHeader, bytes]:
        waiter: queue.Queue[tuple[int, CMsgProtoBufHeader, bytes]] = queue.Queue()
        with self._cond:
            self._emsg_waiters.setdefault(expect_emsg, []).append(waiter)
        try:
            self.send_proto(send_emsg, body_bytes, header=header, authenticated=authenticated)
            try:
                got_emsg, got_hdr, got_body = waiter.get(timeout=timeout)
            except queue.Empty as exc:
                raise SteamTicketError(
                    f"Timed out waiting for Steam EMsg {expect_emsg}",
                    stage=stage,
                    safe_reason="timeout",
                ) from exc
            if got_emsg == -1:
                raise SteamTicketError(
                    f"CM closed while waiting for EMsg {expect_emsg}",
                    stage=stage,
                    transport=True,
                ) from self._reader_error
            return got_hdr, got_body
        finally:
            with self._cond:
                q_list = self._emsg_waiters.get(expect_emsg)
                if q_list and waiter in q_list:
                    q_list.remove(waiter)

    def call_service_non_authed(
        self,
        method_name: str,
        body_bytes: bytes,
        *,
        timeout: float = 15.0,
        stage: str = "unknown",
    ) -> tuple[CMsgProtoBufHeader, bytes]:
        job_id = secrets.randbelow((1 << 62) - 1) + 1
        waiter: queue.Queue[tuple[int, CMsgProtoBufHeader, bytes]] = queue.Queue()
        with self._cond:
            self._job_waiters[job_id] = waiter
        try:
            hdr = CMsgProtoBufHeader(
                steamid=0,
                client_sessionid=0,
                jobid_source=job_id,
                target_job_name=method_name,
                realm=1,
            )
            self.send_proto(
                EMSG_SERVICE_METHOD_CALL_FROM_CLIENT_NON_AUTHED,
                body_bytes,
                header=hdr,
                authenticated=False,
            )
            try:
                got_emsg, got_hdr, got_body = waiter.get(timeout=timeout)
            except queue.Empty as exc:
                raise SteamTicketError(
                    f"Steam service call timed out ({method_name})",
                    stage=stage,
                    safe_reason="timeout",
                ) from exc
            if got_emsg == -1:
                raise SteamTicketError(
                    f"Steam CM disconnected during {method_name}",
                    stage=stage,
                    safe_reason="timeout",
                    transport=True,
                ) from self._reader_error
            if got_emsg != EMSG_SERVICE_METHOD_RESPONSE:
                raise SteamTicketError(
                    f"Unexpected EMsg {got_emsg} for {method_name}",
                    stage=stage,
                    safe_reason="service_rejected",
                )
            er = got_hdr.eresult if got_hdr.eresult is not None else 0
            if er != ERESULT_OK:
                raise SteamTicketError(
                    _friendly_eresult_message(method_name, er),
                    stage=stage,
                    result_code=er,
                    safe_reason="service_rejected",
                )
            return got_hdr, got_body
        finally:
            with self._cond:
                self._job_waiters.pop(job_id, None)

    def wait_for_gc_token(self, timeout: float = 20.0) -> bytes:
        deadline = time.monotonic() + max(0.05, float(timeout))
        with self._cond:
            while not self.gc_tokens:
                if not self.alive:
                    raise SteamTicketError(
                        "CM closed before game-connect token",
                        stage="connect_token",
                    ) from self._reader_error
                rem = deadline - time.monotonic()
                if rem <= 0:
                    raise SteamTicketError(
                        "timeout waiting for ClientGameConnectTokens",
                        stage="connect_token",
                        safe_reason="timeout",
                    )
                self._cond.wait(timeout=rem)
            return self.gc_tokens.popleft()

    def close(self) -> None:
        self._stop_event.set()
        with self._cond:
            self._alive = False
            self._wake_all_waiters_locked()
            self._cond.notify_all()
        self.ws.close()
        if threading.current_thread() is not self._reader_thread:
            self._reader_thread.join(timeout=2.0)
        if (
            self._heartbeat_thread is not None
            and threading.current_thread() is not self._heartbeat_thread
        ):
            self._heartbeat_thread.join(timeout=2.0)


class SteamTicketProvider:
    def __init__(
        self,
        refresh_file: Path | str,
        proxy: str | None = None,
        *,
        cm_endpoints: Sequence[str] | None = None,
        ssl_context: ssl.SSLContext | None = None,
        f2p_retry_delay: float = 1.5,
        token: str | None = None,
    ) -> None:
        self.refresh_file = Path(os.path.abspath(os.path.expanduser(os.fspath(refresh_file))))
        self._memory_token: str = ""
        if token is not None:
            cleaned = str(token).strip()
            if cleaned:
                decode_steam_refresh_jwt(cleaned)
                self._memory_token = cleaned
        self.proxy = proxy.strip() if isinstance(proxy, str) and proxy.strip() else None
        self._cm_endpoints = list(cm_endpoints) if cm_endpoints is not None else None
        self._ssl_context = ssl_context
        self._f2p_retry_delay = float(f2p_retry_delay)

        self._lock = threading.RLock()
        self._session: _CMSession | None = None
        self._auth_cm: _CMSession | None = None
        self._qr_state: dict[str, object] | None = None
        self._cred_state: dict[str, object] | None = None

        self._steam_id: str = ""
        self._bound_steam_id_hash: str | None = None
        self._app_ownership_ticket: bytes = b""
        self._current_ticket: str = ""
        self._connect_mono: float = 0.0
        self._ticket_seq: int = 0
        self._auth_list_seq: int = 0
        self._last_server_seq: int = 0
        self._steam_pipe: int = secrets.randbelow(1_000_000) + 1
        self._closed: bool = False
        self.last_guard_data: str = ""

    def has_refresh_token(self) -> bool:
        if self._memory_token:
            return True
        try:
            self.refresh_file.lstat()
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise SteamTicketError("Refresh token path cannot be inspected", stage="token") from exc
        read_refresh_token_file(self.refresh_file)
        return True

    def current_token(self) -> str:
        with self._lock:
            if self._memory_token:
                return self._memory_token
        token, _ = read_refresh_token_file(self.refresh_file)
        return token

    def _adopt_token(self, candidate: str, *, stage: str) -> str:
        cleaned = str(candidate or "").strip()
        steam_id = decode_steam_refresh_jwt(cleaned)
        raw = cleaned.encode("utf-8")
        if not raw or len(raw) > MAX_REFRESH_TOKEN_BYTES:
            raise SteamTicketError("Refresh token byte length is invalid", stage=stage, safe_reason="invalid_token")
        with self._lock:
            self._memory_token = cleaned
        return steam_id

    def _resolve_token(self) -> tuple[str, str]:
        with self._lock:
            token = self._memory_token
        if token:
            return token, decode_steam_refresh_jwt(token)
        return read_refresh_token_file(self.refresh_file)

    def _resolve_cm_urls(self) -> list[str]:
        if self._cm_endpoints:
            urls: list[str] = []
            for item in self._cm_endpoints:
                text = str(item).strip()
                if text.startswith(("wss://", "ws://")):
                    urls.append(text)
                else:
                    urls.append(f"wss://{text}/cmsocket/")
            return urls
        return discover_cm_endpoints(proxy=self.proxy)

    def _connect_cm_hello(self, *, stage: str, transport: str = "ws") -> _CMSession:
        urls = self._resolve_cm_urls()
        last_exc: Exception | None = None
        targets: list[tuple[str, str, int]] = []
        if transport == "tcp":
            targets = [(f"{h}:{p}", h, p) for h, p in discover_tcp_cm_endpoints()[:4]]
            if not targets:
                seen: set[str] = set()
                for url in urls:
                    host = urlsplit(url).hostname or ""
                    if host and host not in seen:
                        seen.add(host)
                        targets.append((f"{host}:27017", host, 27017))
                    if len(seen) >= 3:
                        break
        else:
            targets = [(url, "", 0) for url in urls[:6]]
        for label, host, port in targets:
            ws = None
            cm = None
            try:
                if transport == "tcp":
                    ws = CMSocketClient(host, port, timeout=15.0).connect()
                else:
                    ws = WebSocketClient(
                        label,
                        proxy=self.proxy,
                        ssl_context=self._ssl_context,
                        timeout=15.0,
                    ).connect()
                cm = _CMSession(ws)
                cm.send_proto(
                    EMSG_CLIENT_HELLO,
                    CMsgClientHello(protocol_version=65580).encode(),
                    authenticated=False,
                )
                return cm
            except Exception as exc:
                last_exc = exc
                if cm is not None:
                    cm.close()
                elif ws is not None:
                    ws.close()
                continue
        raise SteamTicketError(
            f"Unable to connect to any Steam CM ({last_exc})",
            stage=stage,
        ) from last_exc

    def _close_auth_cm(self) -> None:
        auth_cm = self._auth_cm
        self._auth_cm = None
        if auth_cm is not None:
            auth_cm.close()

    def _ensure_auth_cm(self, *, stage: str) -> _CMSession:
        if self._auth_cm is not None and self._auth_cm.alive:
            return self._auth_cm
        self._close_auth_cm()
        self._auth_cm = self._connect_cm_hello(stage=stage)
        return self._auth_cm


    def _call_non_authed_retry(
        self,
        method_name: str,
        body_bytes: bytes,
        *,
        stage: str,
        attempts: int = 3,
    ) -> bytes:
        last_exc: SteamTicketError | None = None
        for attempt in range(max(1, attempts)):
            cm = self._ensure_auth_cm(stage=stage)
            try:
                _, resp_bytes = cm.call_service_non_authed(
                    method_name,
                    body_bytes,
                    stage=stage,
                )
                return resp_bytes
            except SteamTicketError as exc:
                last_exc = exc
                retryable = (
                    exc.result_code == ERESULT_TRY_ANOTHER_CM
                    or exc.safe_reason == "timeout"
                    or exc.transport
                    or "session is closed" in str(exc).lower()
                    or "connection closed" in str(exc).lower()
                    or "disconnected" in str(exc).lower()
                )
                if not retryable or attempt >= attempts - 1:
                    self._close_auth_cm()
                    raise
                self._close_auth_cm()
        assert last_exc is not None
        raise last_exc

    def start_qr_session(self) -> dict[str, object]:
        with self._lock:
            self._cred_state = None
            self._qr_state = None
            self._close_auth_cm()
            req = BeginAuthSessionViaQR_Request(
                device_friendly_name="",
                platform_type=1,
                device_details=CAuthentication_DeviceDetails(
                    device_friendly_name="Python Headless Client",
                    platform_type=1,
                    os_type=-700,
                    gaming_device_type=1,
                ),
            )
            resp_bytes = self._call_non_authed_retry(
                METHOD_BEGIN_QR,
                req.encode(),
                stage="qr_bootstrap",
            )
            resp = BeginAuthSessionViaQR_Response.decode(resp_bytes)
            challenge_url = resp.challenge_url.strip()
            if (
                resp.client_id <= 0
                or not resp.request_id
                or not challenge_url.startswith("https://s.team/q/")
            ):
                raise SteamTicketError(
                    "bad QR challenge",
                    stage="qr_bootstrap",
                    safe_reason="invalid_challenge",
                )
            interval = float(resp.interval or 5.0)
            self._qr_state = {
                "client_id": int(resp.client_id),
                "request_id": bytes(resp.request_id),
                "challenge_url": challenge_url,
                "interval": interval,
            }
            return {
                "client_id": int(resp.client_id),
                "request_id_hex": bytes(resp.request_id).hex(),
                "challenge_url": challenge_url,
                "interval": interval,
            }

    def poll_qr_session(self) -> dict[str, object]:
        with self._lock:
            if self._qr_state is None:
                return {
                    "status": "expired",
                    "challenge_url": None,
                    "steam_id": None,
                    "interval": None,
                }
            client_id = int(self._qr_state["client_id"])
            request_id = bytes(self._qr_state["request_id"])
            challenge_url = str(self._qr_state["challenge_url"])
            poll_stage = "qr_bootstrap" if challenge_url else "credentials_poll"

            poll_req = PollAuthSessionStatus_Request(client_id=client_id, request_id=request_id)
            try:
                resp_bytes = self._call_non_authed_retry(
                    METHOD_POLL_STATUS,
                    poll_req.encode(),
                    stage=poll_stage,
                )
            except SteamTicketError as exc:
                if exc.result_code == ERESULT_EXPIRED:
                    self._qr_state = None
                    self._cred_state = None
                    self._close_auth_cm()
                    return {
                        "status": "expired",
                        "challenge_url": None,
                        "steam_id": None,
                    }
                raise

            status = PollAuthSessionStatus_Response.decode(resp_bytes)
            if status.new_client_id > 0:
                client_id = int(status.new_client_id)
                self._qr_state["client_id"] = client_id
                if self._cred_state is not None:
                    self._cred_state["client_id"] = client_id
            if status.new_challenge_url.strip():
                new_url = status.new_challenge_url.strip()
                if not new_url.startswith("https://s.team/q/"):
                    raise SteamTicketError(
                        "bad QR replacement URL",
                        stage="qr_bootstrap",
                        safe_reason="invalid_challenge",
                    )
                challenge_url = new_url
                self._qr_state["challenge_url"] = challenge_url

            candidate = status.refresh_token.strip()
            if candidate:
                steam_id = self._adopt_token(candidate, stage=poll_stage)
                if status.new_guard_data:
                    self.last_guard_data = status.new_guard_data
                self._qr_state = None
                self._cred_state = None
                self._close_auth_cm()
                return {
                    "status": "approved",
                    "challenge_url": None,
                    "steam_id": steam_id,
                    "interval": None,
                }
            return {
                "status": "pending",
                "challenge_url": challenge_url or None,
                "steam_id": None,
                "interval": float(self._qr_state["interval"]),
                "had_remote_interaction": bool(status.had_remote_interaction),
            }

    def _begin_credentials_session(
        self,
        username: str,
        password: str,
        machine_token: str = "",
        *,
        stage: str,
    ) -> tuple[BeginAuthSessionViaCredentials_Response, str]:
        account_name = str(username or "").strip()
        secret_pw = str(password or "")
        guard_data = str(machine_token or "").strip()
        if not account_name or not secret_pw:
            raise SteamTicketError(
                "Steam username and password are required",
                stage=stage,
                safe_reason="credentials_unavailable",
            )

        self._qr_state = None
        self._cred_state = None
        self._close_auth_cm()

        rsa_bytes = self._call_non_authed_retry(
            METHOD_GET_RSA_KEY,
            GetPasswordRSAPublicKey_Request(account_name=account_name).encode(),
            stage=stage,
        )
        rsa_resp = GetPasswordRSAPublicKey_Response.decode(rsa_bytes)
        if not rsa_resp.publickey_mod or not rsa_resp.publickey_exp or int(rsa_resp.timestamp) <= 0:
            raise SteamTicketError(
                "Steam returned invalid RSA key",
                stage=stage,
                safe_reason="service_rejected",
            )
        try:
            modulus = int(rsa_resp.publickey_mod, 16)
            exponent = int(rsa_resp.publickey_exp, 16)
            pub_key = RSA.construct((modulus, exponent))
            cipher = PKCS1_v1_5.new(pub_key)
            encrypted_pw = base64.b64encode(cipher.encrypt(secret_pw.encode("utf-8"))).decode("ascii")
        except Exception as exc:
            raise SteamTicketError(
                "RSA password encryption failed",
                stage=stage,
                safe_reason="service_rejected",
            ) from exc

        begin_req = BeginAuthSessionViaCredentials_Request(
            device_friendly_name="Python Headless Client",
            account_name=account_name,
            encrypted_password=encrypted_pw,
            encryption_timestamp=int(rsa_resp.timestamp),
            remember_login=True,
            platform_type=1,
            persistence=1,
            website_id="Client",
            device_details=CAuthentication_DeviceDetails(
                device_friendly_name="Python Headless Client",
                platform_type=1,
                os_type=-700,
                gaming_device_type=1,
            ),
            guard_data=guard_data,
        )
        sess_bytes = self._call_non_authed_retry(
            METHOD_BEGIN_CREDENTIALS,
            begin_req.encode(),
            stage=stage,
        )
        sess = BeginAuthSessionViaCredentials_Response.decode(sess_bytes)
        steam_id = str(sess.steamid)
        if (
            sess.client_id <= 0
            or not sess.request_id
            or len(steam_id) != 17
            or not steam_id.isdigit()
        ):
            raise SteamTicketError(
                "Steam rejected account credentials",
                stage=stage,
                safe_reason="service_rejected",
            )
        return sess, steam_id

    def start_credentials_session(self, username: str, password: str) -> dict[str, object]:
        stage = "credentials_login"
        with self._lock:
            sess, steam_id = self._begin_credentials_session(
                username,
                password,
                stage=stage,
            )
            interval = float(sess.interval or 3.0)
            self._qr_state = {
                "client_id": int(sess.client_id),
                "request_id": bytes(sess.request_id),
                "challenge_url": "",
                "interval": interval,
            }
            self._cred_state = {
                "client_id": int(sess.client_id),
                "request_id": bytes(sess.request_id),
                "steam_id": steam_id,
                "code_type": AUTH_GUARD_DEVICE_CODE,
                "guard_type": None,
                "allowed_confirmations": list(sess.allowed_confirmations),
                "interval": interval,
            }
            types = [c.confirmation_type for c in sess.allowed_confirmations]
            if AUTH_GUARD_NONE in types:
                polled = self.poll_qr_session()
                if polled.get("status") == "approved":
                    return polled
            guard_types = list(dict.fromkeys(_GUARD_SLUGS[t] for t in types if t in _GUARD_SLUGS))
            hint = next(
                (c.associated_message for c in sess.allowed_confirmations if c.associated_message.strip()),
                "",
            )
            return {
                "status": "guard_required",
                "guard_types": guard_types,
                "hint": hint,
                "interval": interval,
                "steam_id": steam_id,
            }

    def submit_steam_guard_code(
        self,
        code: str,
        code_type_override: int | None = None,
    ) -> dict[str, object]:
        stage = "credentials_guard"
        cleaned_code = str(code or "").strip().upper()
        if not cleaned_code:
            raise SteamTicketError(
                "Enter your Steam Guard code",
                stage=stage,
                safe_reason="confirmation_required",
            )
        with self._lock:
            if self._cred_state is None or self._qr_state is None:
                raise SteamTicketError(
                    "Steam login session expired — sign in again",
                    stage=stage,
                    result_code=ERESULT_EXPIRED,
                )
            client_id = int(self._qr_state["client_id"])
            steam_id = str(self._cred_state["steam_id"])
            confs = self._cred_state.get("allowed_confirmations") or []
            conf_types = {getattr(c, "confirmation_type", 0) for c in confs}
            if code_type_override is not None:
                target_type = int(code_type_override)
            elif AUTH_GUARD_DEVICE_CODE in conf_types:
                target_type = AUTH_GUARD_DEVICE_CODE
            elif AUTH_GUARD_EMAIL_CODE in conf_types:
                target_type = AUTH_GUARD_EMAIL_CODE
            else:
                target_type = int(self._cred_state.get("code_type") or AUTH_GUARD_DEVICE_CODE)
            guard_req = UpdateAuthSessionWithSteamGuardCode_Request(
                client_id=client_id,
                steamid=int(steam_id),
                code=cleaned_code,
                code_type=target_type,
            )
            self._call_non_authed_retry(
                METHOD_UPDATE_GUARD,
                guard_req.encode(),
                stage=stage,
            )
            return self.poll_qr_session()

    def login_with_credentials(
        self,
        username: str,
        password: str,
        guard_code: str = "",
        machine_token: str = "",
    ) -> dict[str, object]:
        stage = "credential_bootstrap"
        code_str = str(guard_code or "").strip()
        with self._lock:
            sess, steam_id = self._begin_credentials_session(
                username,
                password,
                machine_token=machine_token,
                stage=stage,
            )

            conf_types = {c.confirmation_type for c in sess.allowed_confirmations}
            code_type: int | None = None
            guard_type: str | None = None
            if AUTH_GUARD_DEVICE_CODE in conf_types:
                code_type = AUTH_GUARD_DEVICE_CODE
                guard_type = "device"
            elif AUTH_GUARD_EMAIL_CODE in conf_types:
                code_type = AUTH_GUARD_EMAIL_CODE
                guard_type = "email"

            if code_type is not None and not code_str:
                self._cred_state = {
                    "client_id": int(sess.client_id),
                    "request_id": bytes(sess.request_id),
                    "steam_id": steam_id,
                    "code_type": code_type,
                    "guard_type": guard_type,
                    "interval": float(sess.interval or 2.0),
                }
                return {
                    "status": "needs_guard",
                    "guard_type": guard_type,
                    "steam_id": steam_id,
                }

            if code_type is not None and code_str:
                guard_req = UpdateAuthSessionWithSteamGuardCode_Request(
                    client_id=int(sess.client_id),
                    steamid=int(steam_id),
                    code=code_str,
                    code_type=code_type,
                )
                self._call_non_authed_retry(
                    METHOD_UPDATE_GUARD,
                    guard_req.encode(),
                    stage=stage,
                )

            return self._poll_credentials_until_token(
                client_id=int(sess.client_id),
                request_id=bytes(sess.request_id),
                expected_steam_id=steam_id,
                interval=float(sess.interval or 1.0),
                stage=stage,
            )

    def submit_guard_code(self, code: str) -> dict[str, object]:
        stage = "credential_bootstrap"
        cleaned_code = str(code or "").strip()
        if not cleaned_code:
            raise SteamTicketError(
                "Steam Guard code cannot be empty",
                stage=stage,
                safe_reason="confirmation_required",
            )
        with self._lock:
            if self._cred_state is None:
                raise SteamTicketError(
                    "no pending credential session",
                    stage=stage,
                )
            client_id = int(self._cred_state["client_id"])
            request_id = bytes(self._cred_state["request_id"])
            steam_id = str(self._cred_state["steam_id"])
            code_type = int(self._cred_state["code_type"])
            interval = float(self._cred_state["interval"])

            cm = self._ensure_auth_cm(stage=stage)
            guard_req = UpdateAuthSessionWithSteamGuardCode_Request(
                client_id=client_id,
                steamid=int(steam_id),
                code=cleaned_code,
                code_type=code_type,
            )
            cm.call_service_non_authed(
                METHOD_UPDATE_GUARD,
                guard_req.encode(),
                stage=stage,
            )
            result = self._poll_credentials_until_token(
                client_id=client_id,
                request_id=request_id,
                expected_steam_id=steam_id,
                interval=interval,
                stage=stage,
            )
            self._cred_state = None
            return result

    def _poll_credentials_until_token(
        self,
        *,
        client_id: int,
        request_id: bytes,
        expected_steam_id: str,
        interval: float,
        stage: str,
    ) -> dict[str, object]:
        deadline = time.monotonic() + 30.0
        poll_wait = min(5.0, max(0.05, float(interval or 0.5)))
        cur_client_id = client_id
        while time.monotonic() < deadline:
            cm = self._ensure_auth_cm(stage=stage)
            poll_req = PollAuthSessionStatus_Request(
                client_id=cur_client_id,
                request_id=request_id,
            )
            _, status_bytes = cm.call_service_non_authed(
                METHOD_POLL_STATUS,
                poll_req.encode(),
                stage=stage,
            )
            status = PollAuthSessionStatus_Response.decode(status_bytes)
            if status.new_client_id > 0:
                cur_client_id = int(status.new_client_id)
            candidate = status.refresh_token.strip()
            if candidate:
                token_steam_id = decode_steam_refresh_jwt(candidate)
                if token_steam_id != expected_steam_id:
                    raise SteamTicketError(
                        "bootstrap returned a different account",
                        stage=stage,
                        safe_reason="account_mismatch",
                    )
                self._adopt_token(candidate, stage=stage)
                if status.new_guard_data:
                    self.last_guard_data = status.new_guard_data
                self._close_auth_cm()
                return {
                    "status": "approved",
                    "guard_type": None,
                    "steam_id": expected_steam_id,
                }
            time.sleep(poll_wait)
        raise SteamTicketError(
            "timeout polling credential session",
            stage=stage,
            safe_reason="timeout",
        )

    def _validate_hash_binding(self, steam_id: str, expected_hash: str | None) -> str:
        actual_hash = hashlib.sha256(steam_id.encode("ascii")).hexdigest()
        if expected_hash is not None:
            norm = str(expected_hash).strip().lower()
            if len(norm) != 64 or any(c not in "0123456789abcdef" for c in norm):
                raise SteamTicketError(
                    "Invalid expected_steam_id_hash format",
                    stage="token",
                    safe_reason="invalid_token",
                )
            if actual_hash != norm:
                raise SteamTicketError(
                    "account != expected SteamID hash",
                    stage="token",
                    safe_reason="account_mismatch",
                )
        return actual_hash

    def _open_authenticated_cm(self, token: str, steam_id: str) -> _CMSession:
        if self._cm_endpoints:
            cm = self._connect_cm_hello(stage="connect")
        else:
            try:
                cm = self._connect_cm_hello(stage="connect", transport="tcp")
            except SteamTicketError:
                cm = self._connect_cm_hello(stage="connect")
        try:
            logon_hdr = CMsgProtoBufHeader(
                steamid=int(steam_id),
                client_sessionid=0,
                jobid_source=NO_JOB_ID,
                jobid_target=NO_JOB_ID,
            )
            logon_body = CMsgClientLogon(
                protocol_version=65580,
                client_language="english",
                client_os_type=4294967093,
                should_remember_password=True,
                obfuscated_private_ip=CMsgIPAddress(v4=0),
                machine_id=steam_machine_id(steam_id),
                chat_mode=2,
                machine_name="",
                supports_rate_limit_response=True,
                access_token=token,
            ).encode()
            resp_hdr, resp_bytes = cm.send_and_wait_emsg(
                EMSG_CLIENT_LOGON,
                logon_body,
                EMSG_CLIENT_LOGON_RESPONSE,
                header=logon_hdr,
                authenticated=False,
                timeout=30.0,
                stage="logon",
            )
            logon_resp = CMsgClientLogonResponse.decode(resp_bytes)
            if logon_resp.eresult != ERESULT_OK:
                raise SteamTicketError(
                    f"Steam ClientLogon failed (eresult={logon_resp.eresult})",
                    stage="logon",
                    result_code=logon_resp.eresult,
                    safe_reason="service_rejected",
                )
            if resp_hdr.steamid and str(resp_hdr.steamid) != steam_id:
                raise SteamTicketError(
                    "Steam CM logged on with unexpected SteamID64",
                    stage="logon",
                    safe_reason="account_mismatch",
                )
            cm.steam_id_64 = int(steam_id)
            cm.logged_on = True
            hb = logon_resp.heartbeat_seconds or logon_resp.legacy_out_of_game_heartbeat_seconds or 15
            cm.start_heartbeat(hb)
            self._connect_mono = time.monotonic()
            self._auth_list_seq = 0
            self._last_server_seq = 0
            self._ticket_seq = 0

            app_ticket = self._fetch_ownership_ticket_with_f2p_fallback(cm)
            self._app_ownership_ticket = app_ticket
            return cm
        except BaseException:
            cm.close()
            raise

    def _fetch_ownership_ticket_with_f2p_fallback(self, cm: _CMSession) -> bytes:
        req_bytes = CMsgClientGetAppOwnershipTicket(app_id=APP_ID).encode()
        _, resp_bytes = cm.send_and_wait_emsg(
            EMSG_CLIENT_GET_APP_OWNERSHIP_TICKET,
            req_bytes,
            EMSG_CLIENT_GET_APP_OWNERSHIP_TICKET_RESPONSE,
            authenticated=True,
            timeout=15.0,
            stage="ownership_ticket",
        )
        own = CMsgClientGetAppOwnershipTicketResponse.decode(resp_bytes)
        if own.eresult == ERESULT_OK and own.ticket:
            return bytes(own.ticket)

        free_req = CMsgClientRequestFreeLicense(appids=[APP_ID]).encode()
        _, free_bytes = cm.send_and_wait_emsg(
            EMSG_CLIENT_REQUEST_FREE_LICENSE,
            free_req,
            EMSG_CLIENT_REQUEST_FREE_LICENSE_RESPONSE,
            authenticated=True,
            timeout=15.0,
            stage="ownership_ticket",
        )
        free_resp = CMsgClientRequestFreeLicenseResponse.decode(free_bytes)
        if free_resp.eresult != ERESULT_OK:
            raise SteamTicketError(
                f"RequestFreeLicense failed (eresult={free_resp.eresult})",
                stage="ownership_ticket",
                result_code=free_resp.eresult,
                safe_reason="service_rejected",
            )
        if self._f2p_retry_delay > 0:
            time.sleep(self._f2p_retry_delay)

        _, retry_bytes = cm.send_and_wait_emsg(
            EMSG_CLIENT_GET_APP_OWNERSHIP_TICKET,
            req_bytes,
            EMSG_CLIENT_GET_APP_OWNERSHIP_TICKET_RESPONSE,
            authenticated=True,
            timeout=15.0,
            stage="ownership_ticket",
        )
        retry_own = CMsgClientGetAppOwnershipTicketResponse.decode(retry_bytes)
        if retry_own.eresult != ERESULT_OK or not retry_own.ticket:
            raise SteamTicketError(
                f"GetAppOwnershipTicket failed (eresult={retry_own.eresult})",
                stage="ownership_ticket",
                result_code=retry_own.eresult,
                safe_reason="service_rejected",
            )
        return bytes(retry_own.ticket)

    def _ensure_live_cm(self, expected_steam_id_hash: str | None = None) -> _CMSession:
        token, steam_id = self._resolve_token()
        actual_hash = self._validate_hash_binding(steam_id, expected_steam_id_hash)
        if self._bound_steam_id_hash is not None and actual_hash != self._bound_steam_id_hash:
            raise SteamTicketError(
                "token changed accounts",
                stage="lease",
                safe_reason="account_mismatch",
            )

        if (
            self._session is not None
            and self._session.alive
            and self._session.logged_on
            and self._app_ownership_ticket
        ):
            if self._steam_id != steam_id:
                raise SteamTicketError(
                    "Steam account mismatch on live CM session",
                    stage="lease",
                    safe_reason="account_mismatch",
                )
            return self._session

        self._current_ticket = ""
        if self._session is not None:
            self._session.close()
            self._session = None

        cm = self._open_authenticated_cm(token, steam_id)
        self._session = cm
        self._steam_id = steam_id
        self._bound_steam_id_hash = actual_hash
        self._closed = False
        return cm

    def _mint_from_live_cm(self, cm: _CMSession) -> str:
        try:
            gc_token = cm.wait_for_gc_token(timeout=20.0)
        except SteamTicketError:
            cm.close()
            self._session = None
            cm = self._ensure_live_cm(self._bound_steam_id_hash)
            gc_token = cm.wait_for_gc_token(timeout=20.0)

        self._ticket_seq += 1
        self._auth_list_seq += 1
        elapsed_ms = max(0, int((time.monotonic() - self._connect_mono) * 1000))
        auth_ticket = build_webapi_auth_ticket(gc_token, self._ticket_seq, elapsed_ms)
        crc = zlib.crc32(auth_ticket) & 0xFFFFFFFF

        ticket_entry = CMsgAuthTicket(
            estate=0,
            steamid=0,
            gameid=APP_ID,
            h_steam_pipe=self._steam_pipe,
            ticket_crc=crc,
            ticket=auth_ticket,
            server_secret=SERVER_SECRET,
        )
        auth_list = CMsgClientAuthList(
            tokens_left=len(cm.gc_tokens),
            last_request_seq=max(0, self._auth_list_seq - 1),
            last_request_seq_from_server=self._last_server_seq,
            tickets=[ticket_entry],
            app_ids=[APP_ID],
            message_sequence=self._auth_list_seq,
        )
        _, ack_bytes = cm.send_and_wait_emsg(
            EMSG_CLIENT_AUTH_LIST,
            auth_list.encode(),
            EMSG_CLIENT_AUTH_LIST_ACK,
            authenticated=True,
            timeout=15.0,
            stage="auth_register",
        )
        ack = CMsgClientAuthListAck.decode(ack_bytes)
        if crc not in ack.ticket_crc:
            raise SteamTicketError(
                "AuthListAck CRC mismatch",
                stage="auth_register",
                safe_reason="service_rejected",
            )
        self._last_server_seq = int(ack.message_sequence)
        final_ticket = (
            auth_ticket
            + struct.pack("<I", len(self._app_ownership_ticket))
            + self._app_ownership_ticket
        )
        if len(final_ticket) <= 0 or len(final_ticket) > MAX_TICKET_BYTES:
            raise SteamTicketError("Minted Steam WebAPI ticket size is invalid", stage="lease")
        self._current_ticket = final_ticket.hex().upper()
        return self._current_ticket

    def ensure_lease(self, expected_steam_id_hash: str | None = None) -> str:
        with self._lock:
            if self._closed:
                self._closed = False
            cm = self._ensure_live_cm(expected_steam_id_hash)
            if self._current_ticket and self.active:
                return self._current_ticket
            try:
                return self._mint_from_live_cm(cm)
            except SteamTicketError as exc:
                reconnecting = (
                    "session is closed" in str(exc).lower()
                    or "disconnected" in str(exc).lower()
                    or exc.safe_reason == "timeout"
                )
                if not reconnecting:
                    raise
                cm.close()
                self._session = None
                cm = self._ensure_live_cm(expected_steam_id_hash)
                return self._mint_from_live_cm(cm)

    def refresh(self) -> str:
        with self._lock:
            if self._closed:
                raise SteamTicketError("SteamTicketProvider is closed", stage="lease")
            cm = self._ensure_live_cm(self._bound_steam_id_hash)
            return self._mint_from_live_cm(cm)

    @property
    def active(self) -> bool:
        with self._lock:
            return (
                not self._closed
                and self._session is not None
                and self._session.alive
                and self._session.logged_on
                and bool(self._current_ticket)
            )

    @property
    def steam_id(self) -> str:
        with self._lock:
            if not self.active or not self._steam_id:
                raise SteamTicketError("SteamTicketProvider has no active lease", stage="lease")
            return self._steam_id

    @property
    def steam_session_ticket(self) -> str:
        with self._lock:
            if not self.active or not self._current_ticket:
                raise SteamTicketError("SteamTicketProvider has no active ticket", stage="lease")
            return self._current_ticket

    def close(self) -> None:
        with self._lock:
            self._close_auth_cm()
            self._qr_state = None
            self._cred_state = None
            cm = self._session
            self._session = None
            self._current_ticket = ""
            self._app_ownership_ticket = b""
            self._closed = True
            if cm is None:
                return
            try:
                if cm.alive and cm.logged_on:
                    self._auth_list_seq += 1
                    cancel = CMsgClientAuthList(
                        tokens_left=len(cm.gc_tokens),
                        last_request_seq=max(0, self._auth_list_seq - 1),
                        last_request_seq_from_server=self._last_server_seq,
                        tickets=[],
                        app_ids=[APP_ID],
                        message_sequence=self._auth_list_seq,
                    )
                    cm.send_and_wait_emsg(
                        EMSG_CLIENT_AUTH_LIST,
                        cancel.encode(),
                        EMSG_CLIENT_AUTH_LIST_ACK,
                        authenticated=True,
                        timeout=5.0,
                        stage="cleanup",
                    )
            except SteamTicketError:
                cm.logged_on = False
            finally:
                cm.close()

    def __enter__(self) -> SteamTicketProvider:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
