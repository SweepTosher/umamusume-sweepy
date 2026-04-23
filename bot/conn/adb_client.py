import subprocess
import socket
import threading
import time
import os
from typing import Optional, List, Tuple

class AdbClient:
    def __init__(self, device_name: str, adb_path: str = os.path.join("deps", "adb", "adb.exe")):
        self.device_name = device_name
        self.adb_path = adb_path
        self.t_cmd = self.build_t_cmd(device_name)
        self.s_cmd = b'000eexec:screencap'
        self.psock: Optional[socket.socket] = None
        self.plock = threading.Lock()
        self.okay = b'OKAY'
        self.fail = b'FAIL'

    def build_t_cmd(self, device_name: str) -> bytes:
        cmd = f'host:transport:{device_name}'
        return f'{len(cmd):04x}{cmd}'.encode()

    def run_cmd(self, args: List[str], timeout: int = 15, capture_output: bool = True) -> subprocess.CompletedProcess:
        cmd = [self.adb_path, "-s", self.device_name] + args
        return subprocess.run(cmd, capture_output=capture_output, text=True, encoding='utf-8', errors='replace', timeout=timeout)

    def shell(self, cmd: str, sync: bool = True) -> Optional[bytes]:
        sock = self.create_socket()
        if not sock: return None
        try:
            payload = f'shell:{cmd}'.encode()
            sock.sendall(f'{len(payload):04x}'.encode() + payload)
            resp = sock.recv(4)
            if not resp or self.okay not in resp:
                sock.close()
                return None
            if not sync: return b''
            chunks = []
            while True:
                try:
                    chunk = sock.recv(4096)
                    if not chunk: break
                    chunks.append(chunk)
                except socket.timeout: break
            return b''.join(chunks)
        except Exception: return None
        finally:
            try: sock.close()
            except: pass

    def create_socket(self) -> Optional[socket.socket]:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5.0)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 2097152)
            sock.connect(('127.0.0.1', 5037))
            sock.sendall(self.t_cmd)
            resp = sock.recv(4)
            if not resp or b'OKAY' not in resp:
                sock.close()
                return None
            return sock
        except Exception: return None

    def capture_screen_raw(self) -> Optional[bytes]:
        with self.plock:
            sock = self.psock
            self.psock = None
        if sock is None: sock = self.create_socket()
        if not sock: return None
        raw = self.exec_screencap(sock)
        try: sock.close()
        except: pass
        self.prefill_pool()
        return raw

    def exec_screencap(self, sock: socket.socket) -> Optional[bytes]:
        try:
            sock.sendall(self.s_cmd)
            resp = sock.recv(4)
            if not resp or b'OKAY' not in resp: return None
            chunks = []
            while True:
                chunk = sock.recv(1048576)
                if not chunk: break
                chunks.append(chunk)
            return b''.join(chunks) if chunks else None
        except Exception: return None

    def prefill_pool(self):
        def _fill():
            sock = self.create_socket()
            if sock:
                with self.plock:
                    if self.psock: sock.close()
                    else: self.psock = sock
        threading.Thread(target=_fill, daemon=True).start()

    def kill_server(self):
        subprocess.run([self.adb_path, "kill-server"], capture_output=True, timeout=10)

    def start_server(self):
        subprocess.run([self.adb_path, "start-server"], capture_output=True, timeout=15)

    def connect(self):
        if ":" in self.device_name:
            subprocess.run([self.adb_path, "connect", self.device_name], capture_output=True, timeout=15)

    def disconnect(self):
        if ":" in self.device_name:
            subprocess.run([self.adb_path, "disconnect", self.device_name], capture_output=True, timeout=5)
