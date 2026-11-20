from __future__ import annotations

import gzip
import hashlib
import struct
from dataclasses import dataclass, field
from typing import Iterable, Sequence

WIRE_VARINT = 0
WIRE_FIXED64 = 1
WIRE_LEN = 2
WIRE_FIXED32 = 5

PROTO_MASK = 0x80000000

EMSG_MULTI = 1
EMSG_SERVICE_METHOD_RESPONSE = 147
EMSG_CLIENT_HEARTBEAT = 703
EMSG_CLIENT_LOGON_RESPONSE = 751
EMSG_CLIENT_GAME_CONNECT_TOKENS = 779
EMSG_CLIENT_GET_APP_OWNERSHIP_TICKET = 857
EMSG_CLIENT_GET_APP_OWNERSHIP_TICKET_RESPONSE = 858
EMSG_CLIENT_AUTH_LIST = 5432
EMSG_CLIENT_LOGON = 5514
EMSG_CLIENT_REQUEST_FREE_LICENSE = 5572
EMSG_CLIENT_REQUEST_FREE_LICENSE_RESPONSE = 5573
EMSG_CLIENT_AUTH_LIST_ACK = 5575
EMSG_SERVICE_METHOD_CALL_FROM_CLIENT_NON_AUTHED = 9804
EMSG_CLIENT_HELLO = 9805


class ProtoError(ValueError):
    pass


class UnsupportedPacketError(ProtoError):
    pass


def encode_varint(value: int) -> bytes:
    if isinstance(value, bool):
        return b"\x01" if value else b"\x00"
    if not isinstance(value, int):
        raise ProtoError(f"Expected int for varint, got {type(value).__name__}")
    if value < -(1 << 63) or value >= (1 << 64):
        raise ProtoError("Varint value out of 64-bit range")
    if value < 0:
        value &= 0xFFFFFFFFFFFFFFFF
    out = bytearray()
    while value > 0x7F:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value & 0x7F)
    return bytes(out)


def decode_varint(buf: bytes | bytearray | memoryview, pos: int = 0) -> tuple[int, int]:
    n = len(buf)
    result = 0
    shift = 0
    while True:
        if pos >= n:
            raise ProtoError("Truncated varint")
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            if shift == 63 and b > 1:
                raise ProtoError("Varint overflow above 64 bits")
            return result, pos
        shift += 7
        if shift > 63:
            raise ProtoError("Varint exceeds 10 bytes")


def to_int32(val: int) -> int:
    val &= 0xFFFFFFFF
    return val - 0x100000000 if val & 0x80000000 else val




def to_uint32(val: int) -> int:
    return val & 0xFFFFFFFF


def to_uint64(val: int) -> int:
    return val & 0xFFFFFFFFFFFFFFFF


def encode_tag(field_number: int, wire_type: int) -> bytes:
    if field_number <= 0 or wire_type not in (WIRE_VARINT, WIRE_FIXED64, WIRE_LEN, WIRE_FIXED32):
        raise ProtoError(f"Invalid tag ({field_number}, {wire_type})")
    return encode_varint((field_number << 3) | wire_type)


def encode_uint32(field_number: int, value: int) -> bytes:
    if value < 0 or value > 0xFFFFFFFF:
        raise ProtoError("uint32 out of range")
    return encode_tag(field_number, WIRE_VARINT) + encode_varint(value)


def encode_uint64(field_number: int, value: int) -> bytes:
    if value < 0 or value > 0xFFFFFFFFFFFFFFFF:
        raise ProtoError("uint64 out of range")
    return encode_tag(field_number, WIRE_VARINT) + encode_varint(value)


def encode_int32(field_number: int, value: int) -> bytes:
    if value < -(1 << 31) or value >= (1 << 31):
        raise ProtoError("int32 out of range")
    return encode_tag(field_number, WIRE_VARINT) + encode_varint(value)




def encode_bool(field_number: int, value: bool) -> bytes:
    return encode_tag(field_number, WIRE_VARINT) + (b"\x01" if bool(value) else b"\x00")


def encode_fixed32(field_number: int, value: int) -> bytes:
    if value < 0 or value > 0xFFFFFFFF:
        raise ProtoError("fixed32 out of range")
    return encode_tag(field_number, WIRE_FIXED32) + struct.pack("<I", value)


def encode_fixed64(field_number: int, value: int) -> bytes:
    if value < 0 or value > 0xFFFFFFFFFFFFFFFF:
        raise ProtoError("fixed64 out of range")
    return encode_tag(field_number, WIRE_FIXED64) + struct.pack("<Q", value)


def encode_float(field_number: int, value: float) -> bytes:
    return encode_tag(field_number, WIRE_FIXED32) + struct.pack("<f", float(value))


def encode_bytes(field_number: int, value: bytes | bytearray | memoryview) -> bytes:
    raw = bytes(value)
    return encode_tag(field_number, WIRE_LEN) + encode_varint(len(raw)) + raw


def encode_str(field_number: int, value: str) -> bytes:
    return encode_bytes(field_number, value.encode("utf-8"))


def encode_submessage(field_number: int, encoded_body: bytes) -> bytes:
    return encode_bytes(field_number, encoded_body)


def encode_repeated_varints(
    field_number: int,
    values: Iterable[int],
    *,
    packed: bool = False,
) -> bytes:
    items = list(values)
    if not items:
        return b""
    if packed:
        payload = b"".join(encode_varint(v) for v in items)
        return encode_bytes(field_number, payload)
    tag = encode_tag(field_number, WIRE_VARINT)
    return b"".join(tag + encode_varint(v) for v in items)


def encode_repeated_fixed32(
    field_number: int,
    values: Iterable[int],
    *,
    packed: bool = False,
) -> bytes:
    items = list(values)
    if not items:
        return b""
    if packed:
        payload = b"".join(struct.pack("<I", v & 0xFFFFFFFF) for v in items)
        return encode_bytes(field_number, payload)
    tag = encode_tag(field_number, WIRE_FIXED32)
    return b"".join(tag + struct.pack("<I", v & 0xFFFFFFFF) for v in items)


def encode_repeated_fixed64(
    field_number: int,
    values: Iterable[int],
    *,
    packed: bool = False,
) -> bytes:
    items = list(values)
    if not items:
        return b""
    if packed:
        payload = b"".join(struct.pack("<Q", v & 0xFFFFFFFFFFFFFFFF) for v in items)
        return encode_bytes(field_number, payload)
    tag = encode_tag(field_number, WIRE_FIXED64)
    return b"".join(tag + struct.pack("<Q", v & 0xFFFFFFFFFFFFFFFF) for v in items)


def encode_repeated_floats(
    field_number: int,
    values: Iterable[float],
    *,
    packed: bool = False,
) -> bytes:
    items = list(values)
    if not items:
        return b""
    if packed:
        payload = b"".join(struct.pack("<f", float(v)) for v in items)
        return encode_bytes(field_number, payload)
    tag = encode_tag(field_number, WIRE_FIXED32)
    return b"".join(tag + struct.pack("<f", float(v)) for v in items)


def decode_fields(data: bytes | bytearray | memoryview) -> dict[int, list[tuple[int, int | bytes]]]:
    view = memoryview(data)
    pos = 0
    n = len(view)
    fields: dict[int, list[tuple[int, int | bytes]]] = {}
    while pos < n:
        tag, pos = decode_varint(view, pos)
        field_number = tag >> 3
        wire_type = tag & 0x07
        if field_number <= 0:
            raise ProtoError("Invalid protobuf field number 0")
        if wire_type == WIRE_VARINT:
            val, pos = decode_varint(view, pos)
            fields.setdefault(field_number, []).append((WIRE_VARINT, val))
        elif wire_type == WIRE_FIXED64:
            if pos + 8 > n:
                raise ProtoError("Truncated fixed64 field")
            val = struct.unpack_from("<Q", view, pos)[0]
            pos += 8
            fields.setdefault(field_number, []).append((WIRE_FIXED64, val))
        elif wire_type == WIRE_LEN:
            length, pos = decode_varint(view, pos)
            if pos + length > n:
                raise ProtoError("Truncated length-delimited field")
            chunk = bytes(view[pos : pos + length])
            pos += length
            fields.setdefault(field_number, []).append((WIRE_LEN, chunk))
        elif wire_type == WIRE_FIXED32:
            if pos + 4 > n:
                raise ProtoError("Truncated fixed32 field")
            val = struct.unpack_from("<I", view, pos)[0]
            pos += 4
            fields.setdefault(field_number, []).append((WIRE_FIXED32, val))
        else:
            raise ProtoError(f"Unsupported protobuf wire type {wire_type}")
    return fields


def _last_varint(entries: Sequence[tuple[int, int | bytes]]) -> int | None:
    for wt, val in reversed(entries):
        if wt != WIRE_VARINT or not isinstance(val, int):
            raise ProtoError("Expected varint wire type")
        return val
    return None


def _last_fixed32(entries: Sequence[tuple[int, int | bytes]]) -> int | None:
    for wt, val in reversed(entries):
        if wt != WIRE_FIXED32 or not isinstance(val, int):
            raise ProtoError("Expected fixed32 wire type")
        return val
    return None


def _last_fixed64(entries: Sequence[tuple[int, int | bytes]]) -> int | None:
    for wt, val in reversed(entries):
        if wt != WIRE_FIXED64 or not isinstance(val, int):
            raise ProtoError("Expected fixed64 wire type")
        return val
    return None


def _last_float(entries: Sequence[tuple[int, int | bytes]]) -> float | None:
    raw = _last_fixed32(entries)
    if raw is None:
        return None
    return struct.unpack("<f", struct.pack("<I", raw))[0]


def _last_bytes(entries: Sequence[tuple[int, int | bytes]]) -> bytes | None:
    for wt, val in reversed(entries):
        if wt != WIRE_LEN or not isinstance(val, bytes):
            raise ProtoError("Expected length-delimited wire type")
        return val
    return None


def _last_str(entries: Sequence[tuple[int, int | bytes]]) -> str | None:
    raw = _last_bytes(entries)
    if raw is None:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProtoError("Invalid UTF-8 in protobuf string field") from exc


def decode_repeated_uint32(entries: Sequence[tuple[int, int | bytes]]) -> list[int]:
    out: list[int] = []
    for wt, val in entries:
        if wt == WIRE_VARINT and isinstance(val, int):
            out.append(to_uint32(val))
        elif wt == WIRE_LEN and isinstance(val, bytes):
            pos = 0
            while pos < len(val):
                item, pos = decode_varint(val, pos)
                out.append(to_uint32(item))
        else:
            raise ProtoError("Invalid wire type for repeated uint32")
    return out


def decode_repeated_fixed32(entries: Sequence[tuple[int, int | bytes]]) -> list[int]:
    out: list[int] = []
    for wt, val in entries:
        if wt == WIRE_FIXED32 and isinstance(val, int):
            out.append(val)
        elif wt == WIRE_LEN and isinstance(val, bytes):
            if len(val) % 4 != 0:
                raise ProtoError("Invalid packed fixed32 byte length")
            for offset in range(0, len(val), 4):
                out.append(struct.unpack_from("<I", val, offset)[0])
        else:
            raise ProtoError("Invalid wire type for repeated fixed32")
    return out


def decode_repeated_fixed64(entries: Sequence[tuple[int, int | bytes]]) -> list[int]:
    out: list[int] = []
    for wt, val in entries:
        if wt == WIRE_FIXED64 and isinstance(val, int):
            out.append(val)
        elif wt == WIRE_LEN and isinstance(val, bytes):
            if len(val) % 8 != 0:
                raise ProtoError("Invalid packed fixed64 byte length")
            for offset in range(0, len(val), 8):
                out.append(struct.unpack_from("<Q", val, offset)[0])
        else:
            raise ProtoError("Invalid wire type for repeated fixed64")
    return out


def decode_repeated_floats(entries: Sequence[tuple[int, int | bytes]]) -> list[float]:
    out: list[float] = []
    for wt, val in entries:
        if wt == WIRE_FIXED32 and isinstance(val, int):
            out.append(struct.unpack("<f", struct.pack("<I", val))[0])
        elif wt == WIRE_LEN and isinstance(val, bytes):
            if len(val) % 4 != 0:
                raise ProtoError("Invalid packed float byte length")
            for offset in range(0, len(val), 4):
                out.append(struct.unpack_from("<f", val, offset)[0])
        else:
            raise ProtoError("Invalid wire type for repeated float")
    return out


def decode_repeated_bytes(entries: Sequence[tuple[int, int | bytes]]) -> list[bytes]:
    out: list[bytes] = []
    for wt, val in entries:
        if wt != WIRE_LEN or not isinstance(val, bytes):
            raise ProtoError("Invalid wire type for repeated bytes")
        out.append(val)
    return out


def steam_machine_id(account_identifier: str) -> bytes:
    def cstring(value: bytes) -> bytes:
        return value + b"\x00"

    def digest(label: str) -> bytes:
        source = f"SteamUser Hash {label} {account_identifier}".encode("utf-8")
        return hashlib.sha1(source).hexdigest().encode("ascii")

    encoded = b"".join(
        (
            b"\x00",
            cstring(b"MessageObject"),
            b"\x01",
            cstring(b"BB3"),
            cstring(digest("BB3")),
            b"\x01",
            cstring(b"FF2"),
            cstring(digest("FF2")),
            b"\x01",
            cstring(b"3B3"),
            cstring(digest("3B3")),
            b"\x08\x08",
        )
    )
    if len(encoded) != 155:
        raise ProtoError(f"Unexpected machine_id length {len(encoded)}")
    return encoded


@dataclass
class CMsgProtoBufHeader:
    steamid: int | None = None
    client_sessionid: int | None = None
    routing_appid: int | None = None
    jobid_source: int | None = None
    jobid_target: int | None = None
    target_job_name: str | None = None
    eresult: int | None = None
    error_message: str | None = None
    realm: int | None = None

    def encode(self) -> bytes:
        parts: list[bytes] = []
        if self.steamid is not None:
            parts.append(encode_fixed64(1, self.steamid))
        if self.client_sessionid is not None:
            parts.append(encode_int32(2, self.client_sessionid))
        if self.routing_appid is not None:
            parts.append(encode_uint32(3, self.routing_appid))
        if self.jobid_source is not None:
            parts.append(encode_fixed64(10, self.jobid_source))
        if self.jobid_target is not None:
            parts.append(encode_fixed64(11, self.jobid_target))
        if self.target_job_name is not None:
            parts.append(encode_str(12, self.target_job_name))
        if self.eresult is not None:
            parts.append(encode_int32(13, self.eresult))
        if self.error_message is not None:
            parts.append(encode_str(14, self.error_message))
        if self.realm is not None:
            parts.append(encode_uint32(32, self.realm))
        return b"".join(parts)

    @classmethod
    def decode(cls, data: bytes) -> CMsgProtoBufHeader:
        f = decode_fields(data)
        csid = _last_varint(f.get(2, ()))
        r_app = _last_varint(f.get(3, ()))
        er = _last_varint(f.get(13, ()))
        rlm = _last_varint(f.get(32, ()))
        return cls(
            steamid=_last_fixed64(f.get(1, ())),
            client_sessionid=to_int32(csid) if csid is not None else None,
            routing_appid=to_uint32(r_app) if r_app is not None else None,
            jobid_source=_last_fixed64(f.get(10, ())),
            jobid_target=_last_fixed64(f.get(11, ())),
            target_job_name=_last_str(f.get(12, ())),
            eresult=to_int32(er) if er is not None else None,
            error_message=_last_str(f.get(14, ())),
            realm=to_uint32(rlm) if rlm is not None else None,
        )


@dataclass
class CMsgMulti:
    EMSG = EMSG_MULTI
    size_unzipped: int = 0
    message_body: bytes = b""

    def encode(self) -> bytes:
        parts: list[bytes] = []
        if self.size_unzipped:
            parts.append(encode_uint32(1, self.size_unzipped))
        if self.message_body:
            parts.append(encode_bytes(2, self.message_body))
        return b"".join(parts)

    @classmethod
    def decode(cls, data: bytes) -> CMsgMulti:
        f = decode_fields(data)
        sz = _last_varint(f.get(1, ()))
        body = _last_bytes(f.get(2, ()))
        return cls(
            size_unzipped=to_uint32(sz) if sz is not None else 0,
            message_body=body if body is not None else b"",
        )


@dataclass
class CMsgIPAddress:
    v4: int | None = None
    v6: bytes | None = None

    def encode(self) -> bytes:
        parts: list[bytes] = []
        if self.v4 is not None:
            parts.append(encode_fixed32(1, self.v4))
        if self.v6 is not None:
            parts.append(encode_bytes(2, self.v6))
        return b"".join(parts)

    @classmethod
    def decode(cls, data: bytes) -> CMsgIPAddress:
        f = decode_fields(data)
        return cls(
            v4=_last_fixed32(f.get(1, ())),
            v6=_last_bytes(f.get(2, ())),
        )


@dataclass
class CMsgClientHello:
    EMSG = EMSG_CLIENT_HELLO
    protocol_version: int = 65580

    def encode(self) -> bytes:
        return encode_uint32(1, self.protocol_version)

    @classmethod
    def decode(cls, data: bytes) -> CMsgClientHello:
        f = decode_fields(data)
        pv = _last_varint(f.get(1, ()))
        return cls(protocol_version=to_uint32(pv) if pv is not None else 65580)


@dataclass
class CMsgClientLogon:
    EMSG = EMSG_CLIENT_LOGON
    protocol_version: int = 65580
    client_language: str = "english"
    client_os_type: int = 4294967093
    should_remember_password: bool = True
    obfuscated_private_ip: CMsgIPAddress | None = field(
        default_factory=lambda: CMsgIPAddress(v4=0)
    )
    machine_id: bytes = b""
    chat_mode: int = 2
    machine_name: str = ""
    supports_rate_limit_response: bool = True
    access_token: str = ""

    def encode(self) -> bytes:
        parts: list[bytes] = [
            encode_uint32(1, self.protocol_version),
            encode_str(6, self.client_language),
            encode_uint32(7, self.client_os_type),
            encode_bool(8, self.should_remember_password),
        ]
        if self.obfuscated_private_ip is not None:
            parts.append(encode_submessage(11, self.obfuscated_private_ip.encode()))
        if self.machine_id:
            parts.append(encode_bytes(30, self.machine_id))
        parts.append(encode_uint32(33, self.chat_mode))
        parts.append(encode_str(96, self.machine_name))
        parts.append(encode_bool(102, self.supports_rate_limit_response))
        if self.access_token:
            parts.append(encode_str(108, self.access_token))
        return b"".join(parts)

    @classmethod
    def decode(cls, data: bytes) -> CMsgClientLogon:
        f = decode_fields(data)
        pv = _last_varint(f.get(1, ()))
        lang = _last_str(f.get(6, ()))
        os_type = _last_varint(f.get(7, ()))
        rem = _last_varint(f.get(8, ()))
        ip_raw = _last_bytes(f.get(11, ()))
        mid = _last_bytes(f.get(30, ()))
        cm = _last_varint(f.get(33, ()))
        mname = _last_str(f.get(96, ()))
        srl = _last_varint(f.get(102, ()))
        tok = _last_str(f.get(108, ()))
        return cls(
            protocol_version=to_uint32(pv) if pv is not None else 65580,
            client_language=lang if lang is not None else "english",
            client_os_type=to_uint32(os_type) if os_type is not None else 4294967093,
            should_remember_password=bool(rem) if rem is not None else True,
            obfuscated_private_ip=CMsgIPAddress.decode(ip_raw) if ip_raw is not None else None,
            machine_id=mid if mid is not None else b"",
            chat_mode=to_uint32(cm) if cm is not None else 2,
            machine_name=mname if mname is not None else "",
            supports_rate_limit_response=bool(srl) if srl is not None else True,
            access_token=tok if tok is not None else "",
        )


@dataclass
class CMsgClientLogonResponse:
    EMSG = EMSG_CLIENT_LOGON_RESPONSE
    eresult: int = 2
    legacy_out_of_game_heartbeat_seconds: int = 0
    heartbeat_seconds: int = 0

    def encode(self) -> bytes:
        parts = [encode_int32(1, self.eresult)]
        if self.legacy_out_of_game_heartbeat_seconds:
            parts.append(encode_int32(2, self.legacy_out_of_game_heartbeat_seconds))
        if self.heartbeat_seconds:
            parts.append(encode_int32(3, self.heartbeat_seconds))
        return b"".join(parts)

    @classmethod
    def decode(cls, data: bytes) -> CMsgClientLogonResponse:
        f = decode_fields(data)
        er = _last_varint(f.get(1, ()))
        hb_leg = _last_varint(f.get(2, ()))
        hb = _last_varint(f.get(3, ()))
        return cls(
            eresult=to_int32(er) if er is not None else 2,
            legacy_out_of_game_heartbeat_seconds=to_int32(hb_leg) if hb_leg is not None else 0,
            heartbeat_seconds=to_int32(hb) if hb is not None else 0,
        )


@dataclass
class CMsgClientHeartBeat:
    EMSG = EMSG_CLIENT_HEARTBEAT
    send_reply: bool = False

    def encode(self) -> bytes:
        if self.send_reply:
            return encode_bool(1, True)
        return b""

    @classmethod
    def decode(cls, data: bytes) -> CMsgClientHeartBeat:
        f = decode_fields(data)
        sr = _last_varint(f.get(1, ()))
        return cls(send_reply=bool(sr) if sr is not None else False)


@dataclass
class CMsgClientGameConnectTokens:
    EMSG = EMSG_CLIENT_GAME_CONNECT_TOKENS
    max_tokens_to_keep: int = 10
    tokens: list[bytes] = field(default_factory=list)

    def encode(self) -> bytes:
        parts = [encode_uint32(1, self.max_tokens_to_keep)]
        for tok in self.tokens:
            parts.append(encode_bytes(2, tok))
        return b"".join(parts)

    @classmethod
    def decode(cls, data: bytes) -> CMsgClientGameConnectTokens:
        f = decode_fields(data)
        mk = _last_varint(f.get(1, ()))
        return cls(
            max_tokens_to_keep=to_uint32(mk) if mk is not None else 10,
            tokens=decode_repeated_bytes(f.get(2, ())),
        )


@dataclass
class CMsgClientGetAppOwnershipTicket:
    EMSG = EMSG_CLIENT_GET_APP_OWNERSHIP_TICKET
    app_id: int = 3224770

    def encode(self) -> bytes:
        return encode_uint32(1, self.app_id)

    @classmethod
    def decode(cls, data: bytes) -> CMsgClientGetAppOwnershipTicket:
        f = decode_fields(data)
        aid = _last_varint(f.get(1, ()))
        return cls(app_id=to_uint32(aid) if aid is not None else 0)


@dataclass
class CMsgClientGetAppOwnershipTicketResponse:
    EMSG = EMSG_CLIENT_GET_APP_OWNERSHIP_TICKET_RESPONSE
    eresult: int = 2
    app_id: int = 0
    ticket: bytes = b""

    def encode(self) -> bytes:
        parts = [encode_uint32(1, self.eresult), encode_uint32(2, self.app_id)]
        if self.ticket:
            parts.append(encode_bytes(3, self.ticket))
        return b"".join(parts)

    @classmethod
    def decode(cls, data: bytes) -> CMsgClientGetAppOwnershipTicketResponse:
        f = decode_fields(data)
        er = _last_varint(f.get(1, ()))
        aid = _last_varint(f.get(2, ()))
        tkt = _last_bytes(f.get(3, ()))
        return cls(
            eresult=to_uint32(er) if er is not None else 2,
            app_id=to_uint32(aid) if aid is not None else 0,
            ticket=tkt if tkt is not None else b"",
        )


@dataclass
class CMsgClientRequestFreeLicense:
    EMSG = EMSG_CLIENT_REQUEST_FREE_LICENSE
    appids: list[int] = field(default_factory=list)

    def encode(self) -> bytes:
        return encode_repeated_varints(2, self.appids, packed=False)

    @classmethod
    def decode(cls, data: bytes) -> CMsgClientRequestFreeLicense:
        f = decode_fields(data)
        return cls(appids=decode_repeated_uint32(f.get(2, ())))


@dataclass
class CMsgClientRequestFreeLicenseResponse:
    EMSG = EMSG_CLIENT_REQUEST_FREE_LICENSE_RESPONSE
    eresult: int = 2
    granted_packageids: list[int] = field(default_factory=list)
    granted_appids: list[int] = field(default_factory=list)

    def encode(self) -> bytes:
        parts = [
            encode_uint32(1, self.eresult),
            encode_repeated_varints(2, self.granted_packageids, packed=False),
            encode_repeated_varints(3, self.granted_appids, packed=False),
        ]
        return b"".join(parts)

    @classmethod
    def decode(cls, data: bytes) -> CMsgClientRequestFreeLicenseResponse:
        f = decode_fields(data)
        er = _last_varint(f.get(1, ()))
        return cls(
            eresult=to_uint32(er) if er is not None else 2,
            granted_packageids=decode_repeated_uint32(f.get(2, ())),
            granted_appids=decode_repeated_uint32(f.get(3, ())),
        )


@dataclass
class CMsgAuthTicket:
    estate: int = 0
    eresult: int = 0
    steamid: int = 0
    gameid: int = 0
    h_steam_pipe: int = 0
    ticket_crc: int = 0
    ticket: bytes = b""
    server_secret: bytes = b""

    def encode(self) -> bytes:
        parts = [encode_uint32(1, self.estate)]
        if self.eresult:
            parts.append(encode_uint32(2, self.eresult))
        parts.extend(
            (
                encode_fixed64(3, self.steamid),
                encode_fixed64(4, self.gameid),
                encode_uint32(5, self.h_steam_pipe),
                encode_uint32(6, self.ticket_crc),
                encode_bytes(7, self.ticket),
            )
        )
        if self.server_secret:
            parts.append(encode_bytes(8, self.server_secret))
        return b"".join(parts)

    @classmethod
    def decode(cls, data: bytes) -> CMsgAuthTicket:
        f = decode_fields(data)
        est = _last_varint(f.get(1, ()))
        er = _last_varint(f.get(2, ()))
        sid = _last_fixed64(f.get(3, ()))
        gid = _last_fixed64(f.get(4, ()))
        pipe = _last_varint(f.get(5, ()))
        crc = _last_varint(f.get(6, ()))
        tkt = _last_bytes(f.get(7, ()))
        sec = _last_bytes(f.get(8, ()))
        return cls(
            estate=to_uint32(est) if est is not None else 0,
            eresult=to_uint32(er) if er is not None else 0,
            steamid=sid if sid is not None else 0,
            gameid=gid if gid is not None else 0,
            h_steam_pipe=to_uint32(pipe) if pipe is not None else 0,
            ticket_crc=to_uint32(crc) if crc is not None else 0,
            ticket=tkt if tkt is not None else b"",
            server_secret=sec if sec is not None else b"",
        )


@dataclass
class CMsgClientAuthList:
    EMSG = EMSG_CLIENT_AUTH_LIST
    tokens_left: int = 0
    last_request_seq: int = 0
    last_request_seq_from_server: int = 0
    tickets: list[CMsgAuthTicket] = field(default_factory=list)
    app_ids: list[int] = field(default_factory=list)
    message_sequence: int = 0

    def encode(self) -> bytes:
        parts = [
            encode_uint32(1, self.tokens_left),
            encode_uint32(2, self.last_request_seq),
            encode_uint32(3, self.last_request_seq_from_server),
        ]
        for item in self.tickets:
            parts.append(encode_submessage(4, item.encode()))
        parts.append(encode_repeated_varints(5, self.app_ids, packed=False))
        parts.append(encode_uint32(6, self.message_sequence))
        return b"".join(parts)

    @classmethod
    def decode(cls, data: bytes) -> CMsgClientAuthList:
        f = decode_fields(data)
        tl = _last_varint(f.get(1, ()))
        lrs = _last_varint(f.get(2, ()))
        lrss = _last_varint(f.get(3, ()))
        mseq = _last_varint(f.get(6, ()))
        tickets = [CMsgAuthTicket.decode(raw) for raw in decode_repeated_bytes(f.get(4, ()))]
        return cls(
            tokens_left=to_uint32(tl) if tl is not None else 0,
            last_request_seq=to_uint32(lrs) if lrs is not None else 0,
            last_request_seq_from_server=to_uint32(lrss) if lrss is not None else 0,
            tickets=tickets,
            app_ids=decode_repeated_uint32(f.get(5, ())),
            message_sequence=to_uint32(mseq) if mseq is not None else 0,
        )


@dataclass
class CMsgClientAuthListAck:
    EMSG = EMSG_CLIENT_AUTH_LIST_ACK
    ticket_crc: list[int] = field(default_factory=list)
    app_ids: list[int] = field(default_factory=list)
    message_sequence: int = 0

    def encode(self) -> bytes:
        return b"".join(
            (
                encode_repeated_varints(1, self.ticket_crc, packed=False),
                encode_repeated_varints(2, self.app_ids, packed=False),
                encode_uint32(3, self.message_sequence),
            )
        )

    @classmethod
    def decode(cls, data: bytes) -> CMsgClientAuthListAck:
        f = decode_fields(data)
        mseq = _last_varint(f.get(3, ()))
        return cls(
            ticket_crc=decode_repeated_uint32(f.get(1, ())),
            app_ids=decode_repeated_uint32(f.get(2, ())),
            message_sequence=to_uint32(mseq) if mseq is not None else 0,
        )


@dataclass
class CAuthentication_DeviceDetails:
    device_friendly_name: str = "Python Headless Client"
    platform_type: int = 1
    os_type: int = -700
    gaming_device_type: int = 1

    def encode(self) -> bytes:
        return b"".join(
            (
                encode_str(1, self.device_friendly_name),
                encode_uint32(2, self.platform_type),
                encode_int32(3, self.os_type),
                encode_uint32(4, self.gaming_device_type),
            )
        )

    @classmethod
    def decode(cls, data: bytes) -> CAuthentication_DeviceDetails:
        f = decode_fields(data)
        name = _last_str(f.get(1, ()))
        pt = _last_varint(f.get(2, ()))
        ost = _last_varint(f.get(3, ()))
        gdt = _last_varint(f.get(4, ()))
        return cls(
            device_friendly_name=name if name is not None else "Python Headless Client",
            platform_type=to_uint32(pt) if pt is not None else 1,
            os_type=to_int32(ost) if ost is not None else -700,
            gaming_device_type=to_uint32(gdt) if gdt is not None else 1,
        )


@dataclass
class BeginAuthSessionViaQR_Request:
    device_friendly_name: str = ""
    platform_type: int = 1
    device_details: CAuthentication_DeviceDetails | None = field(
        default_factory=CAuthentication_DeviceDetails
    )

    def encode(self) -> bytes:
        parts: list[bytes] = []
        if self.device_friendly_name:
            parts.append(encode_str(1, self.device_friendly_name))
        if self.platform_type:
            parts.append(encode_uint32(2, self.platform_type))
        if self.device_details is not None:
            parts.append(encode_submessage(3, self.device_details.encode()))
        return b"".join(parts)

    @classmethod
    def decode(cls, data: bytes) -> BeginAuthSessionViaQR_Request:
        f = decode_fields(data)
        name = _last_str(f.get(1, ()))
        pt = _last_varint(f.get(2, ()))
        dd_raw = _last_bytes(f.get(3, ()))
        return cls(
            device_friendly_name=name if name is not None else "",
            platform_type=to_uint32(pt) if pt is not None else 0,
            device_details=(
                CAuthentication_DeviceDetails.decode(dd_raw) if dd_raw is not None else None
            ),
        )


@dataclass
class BeginAuthSessionViaQR_Response:
    client_id: int = 0
    challenge_url: str = ""
    request_id: bytes = b""
    interval: float = 0.0

    def encode(self) -> bytes:
        parts: list[bytes] = [encode_uint64(1, self.client_id)]
        if self.challenge_url:
            parts.append(encode_str(2, self.challenge_url))
        if self.request_id:
            parts.append(encode_bytes(3, self.request_id))
        if self.interval:
            parts.append(encode_float(4, self.interval))
        return b"".join(parts)

    @classmethod
    def decode(cls, data: bytes) -> BeginAuthSessionViaQR_Response:
        f = decode_fields(data)
        cid = _last_varint(f.get(1, ()))
        url = _last_str(f.get(2, ()))
        rid = _last_bytes(f.get(3, ()))
        iv = _last_float(f.get(4, ()))
        return cls(
            client_id=to_uint64(cid) if cid is not None else 0,
            challenge_url=url if url is not None else "",
            request_id=rid if rid is not None else b"",
            interval=iv if iv is not None else 0.0,
        )


@dataclass
class GetPasswordRSAPublicKey_Request:
    account_name: str = ""

    def encode(self) -> bytes:
        return encode_str(1, self.account_name)

    @classmethod
    def decode(cls, data: bytes) -> GetPasswordRSAPublicKey_Request:
        f = decode_fields(data)
        acc = _last_str(f.get(1, ()))
        return cls(account_name=acc if acc is not None else "")


@dataclass
class GetPasswordRSAPublicKey_Response:
    publickey_mod: str = ""
    publickey_exp: str = ""
    timestamp: int = 0

    def encode(self) -> bytes:
        return b"".join(
            (
                encode_str(1, self.publickey_mod),
                encode_str(2, self.publickey_exp),
                encode_uint64(3, self.timestamp),
            )
        )

    @classmethod
    def decode(cls, data: bytes) -> GetPasswordRSAPublicKey_Response:
        f = decode_fields(data)
        mod = _last_str(f.get(1, ()))
        exp = _last_str(f.get(2, ()))
        ts = _last_varint(f.get(3, ()))
        return cls(
            publickey_mod=mod if mod is not None else "",
            publickey_exp=exp if exp is not None else "",
            timestamp=to_uint64(ts) if ts is not None else 0,
        )


@dataclass
class CAuthentication_AllowedConfirmation:
    confirmation_type: int = 0
    associated_message: str = ""

    def encode(self) -> bytes:
        parts = [encode_uint32(1, self.confirmation_type)]
        if self.associated_message:
            parts.append(encode_str(2, self.associated_message))
        return b"".join(parts)

    @classmethod
    def decode(cls, data: bytes) -> CAuthentication_AllowedConfirmation:
        f = decode_fields(data)
        ct = _last_varint(f.get(1, ()))
        msg = _last_str(f.get(2, ()))
        return cls(
            confirmation_type=to_uint32(ct) if ct is not None else 0,
            associated_message=msg if msg is not None else "",
        )


@dataclass
class BeginAuthSessionViaCredentials_Request:
    device_friendly_name: str = "Python Headless Client"
    account_name: str = ""
    encrypted_password: str = ""
    encryption_timestamp: int = 0
    remember_login: bool = True
    platform_type: int = 1
    persistence: int = 1
    website_id: str = "Client"
    device_details: CAuthentication_DeviceDetails | None = field(
        default_factory=CAuthentication_DeviceDetails
    )
    guard_data: str = ""

    def encode(self) -> bytes:
        parts = [
            encode_str(1, self.device_friendly_name),
            encode_str(2, self.account_name),
            encode_str(3, self.encrypted_password),
            encode_uint64(4, self.encryption_timestamp),
            encode_bool(5, self.remember_login),
            encode_uint32(6, self.platform_type),
            encode_int32(7, self.persistence),
            encode_str(8, self.website_id),
        ]
        if self.device_details is not None:
            parts.append(encode_submessage(9, self.device_details.encode()))
        if self.guard_data:
            parts.append(encode_str(10, self.guard_data))
        return b"".join(parts)

    @classmethod
    def decode(cls, data: bytes) -> BeginAuthSessionViaCredentials_Request:
        f = decode_fields(data)
        dfn = _last_str(f.get(1, ()))
        acc = _last_str(f.get(2, ()))
        enc = _last_str(f.get(3, ()))
        ets = _last_varint(f.get(4, ()))
        rem = _last_varint(f.get(5, ()))
        pt = _last_varint(f.get(6, ()))
        per = _last_varint(f.get(7, ()))
        wid = _last_str(f.get(8, ()))
        dd_raw = _last_bytes(f.get(9, ()))
        gd = _last_str(f.get(10, ()))
        return cls(
            device_friendly_name=dfn if dfn is not None else "Python Headless Client",
            account_name=acc if acc is not None else "",
            encrypted_password=enc if enc is not None else "",
            encryption_timestamp=to_uint64(ets) if ets is not None else 0,
            remember_login=bool(rem) if rem is not None else True,
            platform_type=to_uint32(pt) if pt is not None else 1,
            persistence=to_int32(per) if per is not None else 1,
            website_id=wid if wid is not None else "Client",
            device_details=(
                CAuthentication_DeviceDetails.decode(dd_raw) if dd_raw is not None else None
            ),
            guard_data=gd if gd is not None else "",
        )


@dataclass
class BeginAuthSessionViaCredentials_Response:
    client_id: int = 0
    request_id: bytes = b""
    interval: float = 0.0
    allowed_confirmations: list[CAuthentication_AllowedConfirmation] = field(
        default_factory=list
    )
    steamid: int = 0

    def encode(self) -> bytes:
        parts = [encode_uint64(1, self.client_id)]
        if self.request_id:
            parts.append(encode_bytes(2, self.request_id))
        if self.interval:
            parts.append(encode_float(3, self.interval))
        for item in self.allowed_confirmations:
            parts.append(encode_submessage(4, item.encode()))
        if self.steamid:
            parts.append(encode_uint64(5, self.steamid))
        return b"".join(parts)

    @classmethod
    def decode(cls, data: bytes) -> BeginAuthSessionViaCredentials_Response:
        f = decode_fields(data)
        cid = _last_varint(f.get(1, ()))
        rid = _last_bytes(f.get(2, ()))
        iv = _last_float(f.get(3, ()))
        confs = [
            CAuthentication_AllowedConfirmation.decode(raw)
            for raw in decode_repeated_bytes(f.get(4, ()))
        ]
        sid = _last_varint(f.get(5, ()))
        return cls(
            client_id=to_uint64(cid) if cid is not None else 0,
            request_id=rid if rid is not None else b"",
            interval=iv if iv is not None else 0.0,
            allowed_confirmations=confs,
            steamid=to_uint64(sid) if sid is not None else 0,
        )


@dataclass
class UpdateAuthSessionWithSteamGuardCode_Request:
    client_id: int = 0
    steamid: int = 0
    code: str = ""
    code_type: int = 0

    def encode(self) -> bytes:
        return b"".join(
            (
                encode_uint64(1, self.client_id),
                encode_fixed64(2, self.steamid),
                encode_str(3, self.code),
                encode_uint32(4, self.code_type),
            )
        )

    @classmethod
    def decode(cls, data: bytes) -> UpdateAuthSessionWithSteamGuardCode_Request:
        f = decode_fields(data)
        cid = _last_varint(f.get(1, ()))
        sid = _last_fixed64(f.get(2, ()))
        code = _last_str(f.get(3, ()))
        ct = _last_varint(f.get(4, ()))
        return cls(
            client_id=to_uint64(cid) if cid is not None else 0,
            steamid=sid if sid is not None else 0,
            code=code if code is not None else "",
            code_type=to_uint32(ct) if ct is not None else 0,
        )


@dataclass
class PollAuthSessionStatus_Request:
    client_id: int = 0
    request_id: bytes = b""

    def encode(self) -> bytes:
        return encode_uint64(1, self.client_id) + encode_bytes(2, self.request_id)

    @classmethod
    def decode(cls, data: bytes) -> PollAuthSessionStatus_Request:
        f = decode_fields(data)
        cid = _last_varint(f.get(1, ()))
        rid = _last_bytes(f.get(2, ()))
        return cls(
            client_id=to_uint64(cid) if cid is not None else 0,
            request_id=rid if rid is not None else b"",
        )


@dataclass
class PollAuthSessionStatus_Response:
    new_client_id: int = 0
    new_challenge_url: str = ""
    refresh_token: str = ""
    access_token: str = ""
    account_name: str = ""
    new_guard_data: str = ""
    had_remote_interaction: bool = False

    def encode(self) -> bytes:
        parts: list[bytes] = []
        if self.new_client_id:
            parts.append(encode_uint64(1, self.new_client_id))
        if self.new_challenge_url:
            parts.append(encode_str(2, self.new_challenge_url))
        if self.refresh_token:
            parts.append(encode_str(3, self.refresh_token))
        if self.access_token:
            parts.append(encode_str(4, self.access_token))
        if self.account_name:
            parts.append(encode_str(6, self.account_name))
        if self.new_guard_data:
            parts.append(encode_str(7, self.new_guard_data))
        if self.had_remote_interaction:
            parts.append(encode_uint64(5, 1))
        return b"".join(parts)

    @classmethod
    def decode(cls, data: bytes) -> PollAuthSessionStatus_Response:
        f = decode_fields(data)
        ncid = _last_varint(f.get(1, ()))
        ncurl = _last_str(f.get(2, ()))
        rtok = _last_str(f.get(3, ()))
        atok = _last_str(f.get(4, ()))
        remote = _last_varint(f.get(5, ()))
        acc = _last_str(f.get(6, ()))
        ngd = _last_str(f.get(7, ()))
        return cls(
            new_client_id=to_uint64(ncid) if ncid is not None else 0,
            new_challenge_url=ncurl if ncurl is not None else "",
            refresh_token=rtok if rtok is not None else "",
            access_token=atok if atok is not None else "",
            account_name=acc if acc is not None else "",
            new_guard_data=ngd if ngd is not None else "",
            had_remote_interaction=bool(remote),
        )


def pack_cm_packet(emsg: int, header: CMsgProtoBufHeader, body_bytes: bytes) -> bytes:
    header_bytes = header.encode()
    return (
        struct.pack("<II", (int(emsg) & 0x7FFFFFFF) | PROTO_MASK, len(header_bytes))
        + header_bytes
        + bytes(body_bytes)
    )


def unpack_cm_packet(raw: bytes | bytearray | memoryview) -> tuple[int, CMsgProtoBufHeader, bytes]:
    view = memoryview(raw)
    if len(view) < 8:
        raise ProtoError("CM packet shorter than 8-byte header")
    raw_emsg, hdr_len = struct.unpack_from("<II", view, 0)
    if not (raw_emsg & PROTO_MASK):
        raise UnsupportedPacketError(f"Unsupported non-protobuf CM packet (emsg={raw_emsg})")
    if 8 + hdr_len > len(view):
        raise ProtoError("CM packet header length exceeds frame")
    emsg = raw_emsg & 0x7FFFFFFF
    header = CMsgProtoBufHeader.decode(bytes(view[8 : 8 + hdr_len]))
    body = bytes(view[8 + hdr_len :])
    return emsg, header, body


def unpack_multi(multi: CMsgMulti) -> list[bytes]:
    if multi.size_unzipped > 0:
        try:
            payload = gzip.decompress(multi.message_body)
        except OSError as exc:
            raise ProtoError("Failed to gunzip CMsgMulti payload") from exc
        if len(payload) != multi.size_unzipped:
            raise ProtoError(
                f"CMsgMulti unzipped size mismatch ({len(payload)} != {multi.size_unzipped})"
            )
    else:
        payload = multi.message_body
    view = memoryview(payload)
    pos = 0
    total = len(view)
    packets: list[bytes] = []
    while pos < total:
        if pos + 4 > total:
            raise ProtoError("Truncated packet length inside CMsgMulti")
        pkt_len = struct.unpack_from("<I", view, pos)[0]
        pos += 4
        if pos + pkt_len > total:
            raise ProtoError("Truncated packet body inside CMsgMulti")
        packets.append(bytes(view[pos : pos + pkt_len]))
        pos += pkt_len
    return packets
