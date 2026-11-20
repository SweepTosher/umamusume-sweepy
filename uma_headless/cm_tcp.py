import os
import socket
import struct
import zlib

from Crypto.Cipher import AES, PKCS1_OAEP
from Crypto.Hash import SHA1
from Crypto.PublicKey import RSA
from Crypto.Util.Padding import pad, unpad

VT01_MAGIC = b"VT01"

EMSG_CHANNEL_ENCRYPT_REQUEST = 1303
EMSG_CHANNEL_ENCRYPT_RESPONSE = 1304
EMSG_CHANNEL_ENCRYPT_RESULT = 1305

UNIVERSE_PUBLIC_KEY = bytes.fromhex(
    "30819D300D06092A864886F70D010101050003818B0030818702818100"
    "DFEC1AD62C10662C17353A14B07C59117F9DD3D82B7AE3E015CD191E"
    "46E87B8774A2184631A9031479828EE945A24912A923687389CF69A1"
    "B16146BDC1BEBFD6011BD881D4DC90FBFE4F527366CB9570D7C58EBA"
    "1C7A3375A1623446BB60B78068FA13A77A8A374B9EC6F45D5F3A99F9"
    "9EC43AE963A2BB881928E0E714C04289020111"
)


class CMTransportError(Exception):
    pass


class CMSocketClient:
    def __init__(self, host: str, port: int, *, timeout: float = 15.0) -> None:
        self.host = host
        self.port = int(port)
        self.timeout = float(timeout)
        self._sock: socket.socket | None = None
        self._buf = bytearray()
        self._connected = False
        self._closed = False
        self._key: bytes | None = None

    @property
    def connected(self) -> bool:
        return self._connected and not self._closed and self._sock is not None

    def connect(self) -> "CMSocketClient":
        sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        sock.settimeout(self.timeout)
        self._sock = sock
        self._connected = True
        try:
            self._handshake()
        except BaseException:
            self.close()
            raise
        return self

    def settimeout(self, timeout: float | None) -> None:
        self.timeout = float(timeout or 0.0)
        if self._sock is not None:
            self._sock.settimeout(self.timeout)

    def _read_exact(self, length: int) -> bytes:
        if length <= 0:
            return b""
        while len(self._buf) < length:
            sock = self._sock
            if sock is None:
                raise CMTransportError("Steam CM socket is not connected")
            try:
                chunk = sock.recv(max(4096, length - len(self._buf)))
            except TimeoutError:
                raise
            except OSError as exc:
                self._connected = False
                raise CMTransportError(f"Steam CM socket read failed: {exc}") from exc
            if not chunk:
                self._connected = False
                raise CMTransportError("Steam CM closed the underlying connection")
            self._buf.extend(chunk)
        out = bytes(self._buf[:length])
        del self._buf[:length]
        return out

    def _read_frame(self) -> bytes:
        length = struct.unpack("<I", self._read_exact(4))[0]
        if length <= 0 or length > 16 * 1024 * 1024:
            raise CMTransportError(f"Steam CM frame length is invalid ({length})")
        if self._read_exact(4) != VT01_MAGIC:
            raise CMTransportError("Steam CM frame is missing the VT01 magic")
        payload = self._read_exact(length)
        if self._key is not None:
            payload = self._decrypt(payload)
        return payload

    def _encrypt(self, data: bytes) -> bytes:
        key = self._key
        if key is None:
            return data
        iv = os.urandom(16)
        prefix = AES.new(key, AES.MODE_ECB).encrypt(iv)
        return prefix + AES.new(key, AES.MODE_CBC, iv).encrypt(pad(data, 16))

    def _decrypt(self, data: bytes) -> bytes:
        key = self._key
        if key is None:
            return data
        if len(data) < 32:
            raise CMTransportError("Steam CM encrypted frame is too short")
        iv = AES.new(key, AES.MODE_ECB).decrypt(data[:16])
        try:
            return unpad(AES.new(key, AES.MODE_CBC, iv).decrypt(data[16:]), 16)
        except ValueError as exc:
            raise CMTransportError("Steam CM frame padding is invalid") from exc

    def _send_raw(self, payload: bytes) -> None:
        sock = self._sock
        if sock is None or not self._connected:
            raise CMTransportError("Steam CM socket is not connected")
        body = self._encrypt(payload)
        frame = struct.pack("<I", len(body)) + VT01_MAGIC + body
        try:
            sock.sendall(frame)
        except OSError as exc:
            self._connected = False
            raise CMTransportError(f"Steam CM socket write failed: {exc}") from exc

    def _handshake(self) -> None:
        request = self._read_frame()
        if len(request) < 24:
            raise CMTransportError(f"truncated channel encrypt request ({len(request)} bytes)")
        emsg = struct.unpack_from("<I", request, 0)[0]
        if emsg != EMSG_CHANNEL_ENCRYPT_REQUEST:
            raise CMTransportError(f"Unexpected Steam CM handshake EMsg {emsg}")
        protocol, _universe = struct.unpack_from("<II", request, 20)
        if protocol != 1:
            raise CMTransportError(f"Unsupported Steam CM channel protocol {protocol}")
        session_key = os.urandom(32)
        ciphertext = PKCS1_OAEP.new(RSA.import_key(UNIVERSE_PUBLIC_KEY), hashAlgo=SHA1).encrypt(
            session_key
        )
        reply = (
            struct.pack("<II", protocol, len(ciphertext))
            + ciphertext
            + struct.pack("<II", zlib.crc32(session_key) & 0xFFFFFFFF, 0)
        )
        self._send_raw(struct.pack("<IQQ", EMSG_CHANNEL_ENCRYPT_RESPONSE, 0, 0) + reply)
        result = self._read_frame()
        result_emsg = struct.unpack_from("<I", result, 0)[0]
        if result_emsg != EMSG_CHANNEL_ENCRYPT_RESULT:
            raise CMTransportError(f"Unexpected Steam CM handshake result EMsg {result_emsg}")
        eresult = struct.unpack_from("<I", result, 20)[0] if len(result) >= 24 else 2
        if eresult != 1:
            raise CMTransportError(f"Steam CM channel encryption failed (eresult={eresult})")
        self._key = session_key

    def recv(self) -> bytes:
        return self._read_frame()

    def send_binary(self, data: bytes) -> None:
        self._send_raw(bytes(data))

    def close(self) -> None:
        self._closed = True
        self._connected = False
        sock = self._sock
        self._sock = None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                self._connected = False
