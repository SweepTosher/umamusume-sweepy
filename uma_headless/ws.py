from __future__ import annotations

import base64
import hashlib
import os
import socket
import ssl
import struct
import threading
from urllib.parse import unquote, urlsplit

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

OPCODE_CONTINUATION = 0x0
OPCODE_TEXT = 0x1
OPCODE_BINARY = 0x2
OPCODE_CLOSE = 0x8
OPCODE_PING = 0x9
OPCODE_PONG = 0xA

MAX_HTTP_HEADER_BYTES = 65536
MAX_FRAME_PAYLOAD_BYTES = 64 * 1024 * 1024


class WebSocketError(OSError):
    pass


class WebSocketClosedError(WebSocketError):
    def __init__(self, message: str = "WebSocket closed", *, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


def xor_mask_bytes(payload: bytes, mask: bytes) -> bytes:
    if len(mask) != 4:
        raise WebSocketError("WebSocket mask must be 4 bytes")
    n = len(payload)
    if n == 0:
        return b""
    repeated = (mask * ((n // 4) + 1))[:n]
    masked_int = int.from_bytes(payload, "big") ^ int.from_bytes(repeated, "big")
    return masked_int.to_bytes(n, "big")


def compute_accept_key(sec_key: str) -> str:
    digest = hashlib.sha1((sec_key + WS_GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


def build_masked_frame(
    opcode: int,
    payload: bytes = b"",
    *,
    fin: bool = True,
    mask_key: bytes | None = None,
) -> bytes:
    if opcode < 0 or opcode > 0x0F:
        raise WebSocketError(f"Invalid WebSocket opcode {opcode}")
    raw = bytes(payload)
    length = len(raw)
    mask = os.urandom(4) if mask_key is None else bytes(mask_key)
    if len(mask) != 4:
        raise WebSocketError("Invalid 4-byte mask")
    first = (0x80 if fin else 0x00) | (opcode & 0x0F)
    header = bytearray([first])
    if length < 126:
        header.append(0x80 | length)
    elif length < 65536:
        header.append(0x80 | 126)
        header.extend(struct.pack(">H", length))
    else:
        header.append(0x80 | 127)
        header.extend(struct.pack(">Q", length))
    header.extend(mask)
    header.extend(xor_mask_bytes(raw, mask))
    return bytes(header)


class WebSocketClient:
    def __init__(
        self,
        url: str,
        *,
        proxy: str | None = None,
        ssl_context: ssl.SSLContext | None = None,
        timeout: float = 15.0,
    ) -> None:
        parsed = urlsplit(url)
        scheme = parsed.scheme.lower()
        if scheme not in ("wss", "ws"):
            raise WebSocketError(f"Unsupported WebSocket URL scheme: {parsed.scheme!r}")
        if not parsed.hostname:
            raise WebSocketError("WebSocket URL missing hostname")
        self.scheme = scheme
        self.host = parsed.hostname
        self.port = parsed.port or (443 if scheme == "wss" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        self.resource_path = path
        self.proxy = proxy.strip() if isinstance(proxy, str) and proxy.strip() else None
        self.ssl_context = ssl_context
        self.timeout = float(timeout)
        self._sock: socket.socket | ssl.SSLSocket | None = None
        self._send_lock = threading.Lock()
        self._read_buf = bytearray()
        self._connected = False
        self._close_sent = False
        self._closed = False
        self.last_pong_payload: bytes | None = None

    @property
    def connected(self) -> bool:
        return self._connected and not self._closed and self._sock is not None

    def _open_tcp_or_proxy(self) -> socket.socket:
        if not self.proxy:
            sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
            sock.settimeout(self.timeout)
            return sock

        p_url = urlsplit(self.proxy)
        p_scheme = p_url.scheme.lower()
        if p_scheme not in ("http", "https") or not p_url.hostname:
            raise WebSocketError("proxy must be http(s)://")
        p_port = p_url.port or (443 if p_scheme == "https" else 80)
        raw_sock = socket.create_connection((p_url.hostname, p_port), timeout=self.timeout)
        raw_sock.settimeout(self.timeout)
        sock: socket.socket = raw_sock
        try:
            if p_scheme == "https":
                p_ctx = ssl.create_default_context()
                sock = p_ctx.wrap_socket(raw_sock, server_hostname=p_url.hostname)
            target = f"{self.host}:{self.port}"
            lines = [
                f"CONNECT {target} HTTP/1.1",
                f"Host: {target}",
                "Proxy-Connection: Keep-Alive",
            ]
            if p_url.username is not None:
                user = unquote(p_url.username)
                pw = unquote(p_url.password or "")
                cred = base64.b64encode(f"{user}:{pw}".encode("utf-8")).decode("ascii")
                lines.append(f"Proxy-Authorization: Basic {cred}")
            req_bytes = ("\r\n".join(lines) + "\r\n\r\n").encode("ascii")
            sock.sendall(req_bytes)

            resp_hdr = bytearray()
            while b"\r\n\r\n" not in resp_hdr:
                if len(resp_hdr) >= MAX_HTTP_HEADER_BYTES:
                    raise WebSocketError("HTTP CONNECT proxy response header too large")
                b = sock.recv(1)
                if not b:
                    raise WebSocketError("proxy closed before response")
                resp_hdr.extend(b)
            status_line = resp_hdr.split(b"\r\n", 1)[0].decode("iso-8859-1")
            parts = status_line.split(" ", 2)
            if len(parts) < 2 or parts[1] != "200":
                raise WebSocketError(f"HTTP CONNECT proxy rejected tunnel: {status_line}")
            return sock
        except BaseException:
            sock.close()
            raise

    def connect(self) -> WebSocketClient:
        if self._connected:
            return self
        raw_sock = self._open_tcp_or_proxy()
        sock: socket.socket | ssl.SSLSocket = raw_sock
        try:
            if self.scheme == "wss":
                ctx = self.ssl_context if self.ssl_context is not None else ssl.create_default_context()
                sock = ctx.wrap_socket(raw_sock, server_hostname=self.host)
                sock.settimeout(self.timeout)
            default_port = 443 if self.scheme == "wss" else 80
            host_hdr = self.host if self.port == default_port else f"{self.host}:{self.port}"
            sec_key = base64.b64encode(os.urandom(16)).decode("ascii")
            req_lines = [
                f"GET {self.resource_path} HTTP/1.1",
                f"Host: {host_hdr}",
                "Upgrade: websocket",
                "Connection: Upgrade",
                f"Sec-WebSocket-Key: {sec_key}",
                "Sec-WebSocket-Version: 13",
            ]
            sock.sendall(("\r\n".join(req_lines) + "\r\n\r\n").encode("ascii"))

            buf = bytearray()
            while b"\r\n\r\n" not in buf:
                if len(buf) >= MAX_HTTP_HEADER_BYTES:
                    raise WebSocketError("upgrade header too large")
                chunk = sock.recv(4096)
                if not chunk:
                    raise WebSocketError("Connection closed during WebSocket upgrade")
                buf.extend(chunk)

            sep_idx = buf.index(b"\r\n\r\n")
            hdr_bytes = bytes(buf[:sep_idx])
            self._read_buf = bytearray(buf[sep_idx + 4 :])

            lines = hdr_bytes.decode("iso-8859-1").split("\r\n")
            status_parts = lines[0].split(" ", 2)
            if len(status_parts) < 2 or status_parts[1] != "101":
                raise WebSocketError(f"WebSocket upgrade failed: {lines[0]}")

            headers: dict[str, str] = {}
            for line in lines[1:]:
                if ":" not in line:
                    continue
                k, v = line.split(":", 1)
                lk = k.strip().lower()
                if lk in headers:
                    headers[lk] = f"{headers[lk]}, {v.strip()}"
                else:
                    headers[lk] = v.strip()

            if headers.get("upgrade", "").lower() != "websocket":
                raise WebSocketError("Missing or invalid Upgrade: websocket header")
            conn_tokens = {tok.strip().lower() for tok in headers.get("connection", "").split(",")}
            if "upgrade" not in conn_tokens:
                raise WebSocketError("Missing Upgrade token in Connection header")
            expected_accept = compute_accept_key(sec_key)
            if headers.get("sec-websocket-accept") != expected_accept:
                raise WebSocketError("Sec-WebSocket-Accept verification failed")

            self._sock = sock
            self._connected = True
            self._closed = False
            self._close_sent = False
            return self
        except BaseException:
            sock.close()
            raise

    def settimeout(self, timeout: float | None) -> None:
        self.timeout = 0.0 if timeout is None else float(timeout)
        if self._sock is not None:
            self._sock.settimeout(timeout)

    def _read_exact(self, length: int) -> bytes:
        if length == 0:
            return b""
        sock = self._sock
        if sock is None:
            raise WebSocketClosedError("WebSocket is not connected")
        while len(self._read_buf) < length:
            need = max(4096, length - len(self._read_buf))
            try:
                chunk = sock.recv(need)
            except TimeoutError:
                raise
            except OSError as exc:
                self._connected = False
                raise WebSocketError(f"WebSocket socket read failed: {exc}") from exc
            if not chunk:
                self._connected = False
                self._closed = True
                raise WebSocketClosedError("WebSocket peer closed underlying connection")
            self._read_buf.extend(chunk)
        out = bytes(self._read_buf[:length])
        del self._read_buf[:length]
        return out

    def _peek_exact(self, length: int) -> bytes:
        if length <= 0:
            return b""
        sock = self._sock
        if sock is None:
            raise WebSocketClosedError("WebSocket is not connected")
        while len(self._read_buf) < length:
            need = max(4096, length - len(self._read_buf))
            try:
                chunk = sock.recv(need)
            except TimeoutError:
                raise
            except OSError as exc:
                self._connected = False
                raise WebSocketError(f"WebSocket socket read failed: {exc}") from exc
            if not chunk:
                self._connected = False
                raise WebSocketClosedError("WebSocket peer closed underlying connection")
            self._read_buf.extend(chunk)
        return bytes(self._read_buf[:length])

    def _discard(self, length: int) -> None:
        del self._read_buf[:length]

    def _send_frame(self, opcode: int, payload: bytes = b"", *, fin: bool = True) -> None:
        frame = build_masked_frame(opcode, payload, fin=fin)
        with self._send_lock:
            sock = self._sock
            if sock is None or not self._connected:
                raise WebSocketClosedError("WebSocket is not connected")
            try:
                sock.sendall(frame)
            except OSError as exc:
                self._connected = False
                raise WebSocketError(f"WebSocket send failed: {exc}") from exc

    def send_binary(self, data: bytes) -> None:
        self._send_frame(OPCODE_BINARY, bytes(data), fin=True)

    def send_pong(self, data: bytes = b"") -> None:
        if len(data) > 125:
            raise WebSocketError("control frame > 125 bytes")
        self._send_frame(OPCODE_PONG, bytes(data), fin=True)

    def _read_single_frame(self) -> tuple[bool, int, bytes]:
        head = self._peek_exact(2)
        b0, b1 = head[0], head[1]
        if b0 & 0x70:
            self._force_close_socket()
            raise WebSocketError(f"Non-zero WebSocket RSV bits: 0x{b0:02x}")
        fin = bool(b0 & 0x80)
        opcode = b0 & 0x0F
        masked = bool(b1 & 0x80)
        length = b1 & 0x7F
        if opcode >= 0x8:
            if not fin:
                self._force_close_socket()
                raise WebSocketError("fragmented control frame")
            if length > 125:
                self._force_close_socket()
                raise WebSocketError("WebSocket control frame exceeds 125 bytes")
        offset = 2
        if length == 126:
            offset += 2
            length = struct.unpack(">H", self._peek_exact(offset)[2:4])[0]
        elif length == 127:
            offset += 8
            length = struct.unpack(">Q", self._peek_exact(offset)[2:10])[0]
        if length > MAX_FRAME_PAYLOAD_BYTES:
            self._force_close_socket()
            raise WebSocketError(f"WebSocket frame payload exceeds limit ({length})")
        mask_bytes = None
        if masked:
            mask_bytes = self._peek_exact(offset + 4)[offset : offset + 4]
            offset += 4
        frame = self._peek_exact(offset + length)
        self._discard(offset + length)
        payload = frame[offset:]
        if mask_bytes is not None:
            payload = xor_mask_bytes(payload, mask_bytes)
        return fin, opcode, payload

    def recv(self) -> bytes:
        fragments: list[bytes] | None = None
        fragment_bytes = 0
        while True:
            fin, opcode, payload = self._read_single_frame()
            if opcode == OPCODE_PING:
                if not self._close_sent and self._connected:
                    self.send_pong(payload)
                continue
            if opcode == OPCODE_PONG:
                self.last_pong_payload = payload
                continue
            if opcode == OPCODE_CLOSE:
                code = struct.unpack(">H", payload[:2])[0] if len(payload) >= 2 else None
                if not self._close_sent and self._connected:
                    reply = struct.pack(">H", code) if code is not None else b""
                    self._close_sent = True
                    try:
                        self._send_frame(OPCODE_CLOSE, reply, fin=True)
                    except OSError:
                        self._connected = False
                self._force_close_socket()
                raise WebSocketClosedError("WebSocket closed by peer", code=code)
            if opcode in (OPCODE_BINARY, OPCODE_TEXT):
                if fragments is not None:
                    raise WebSocketError("new data frame before continuation finished")
                if fin:
                    return payload
                fragments = [payload]
                fragment_bytes = len(payload)
                continue
            if opcode == OPCODE_CONTINUATION:
                if fragments is None:
                    raise WebSocketError("continuation without initial frame")
                fragment_bytes += len(payload)
                if fragment_bytes > MAX_FRAME_PAYLOAD_BYTES:
                    self._force_close_socket()
                    raise WebSocketError(f"WebSocket message exceeds limit ({fragment_bytes} bytes)")
                fragments.append(payload)
                if fin:
                    message = b"".join(fragments)
                    fragments = None
                    return message
                continue
            raise WebSocketError(f"Unsupported WebSocket opcode 0x{opcode:x}")

    def _force_close_socket(self) -> None:
        self._connected = False
        self._closed = True
        sock = self._sock
        self._sock = None
        if sock is not None:
            sock.close()

    def close(self, code: int = 1000, reason: bytes = b"") -> None:
        if self._closed:
            return
        if self._connected and self._sock is not None and not self._close_sent:
            payload = struct.pack(">H", int(code) & 0xFFFF) + bytes(reason)[:123]
            self._close_sent = True
            try:
                self._send_frame(OPCODE_CLOSE, payload, fin=True)
            except OSError:
                self._connected = False
        self._force_close_socket()

    def __enter__(self) -> WebSocketClient:
        return self.connect()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
