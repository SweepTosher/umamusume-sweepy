from __future__ import annotations

import gzip
import json
from typing import Any
import zlib

from curl_cffi import requests

from sweepy.config import validate_brain_url


MAX_RESPONSE_BYTES = 4 * 1024 * 1024

VALID_BRAIN_OPS = frozenset({
    "rpc_step",
    "race_macro",
    "race_resume_macro",
    "terminal_skills",
    "terminal_finish",
})

CLIENT_CONTRACT_VERSION = "1"

TERMINAL_OPS = frozenset({"terminal_skills", "terminal_finish"})


class BrainAPIError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, code: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = str(code).strip() if code else None


class ContractMismatch(BrainAPIError):
    pass


def verify_contract(meta: dict[str, Any]) -> list[str]:
    if not isinstance(meta, dict):
        raise ContractMismatch("meta is not an object")
    version = str(meta.get("contract_version") or "")
    if version != CLIENT_CONTRACT_VERSION:
        raise ContractMismatch(
            f"contract {version or 'unknown'} != {CLIENT_CONTRACT_VERSION}"
        )
    emitted = meta.get("emitted_ops")
    if not isinstance(emitted, list) or not emitted:
        raise ContractMismatch("meta has no emitted_ops")
    unexecutable = sorted(str(op) for op in emitted if str(op) not in VALID_BRAIN_OPS)
    if unexecutable:
        raise ContractMismatch(f"unsupported opcodes: {unexecutable}")

    warnings: list[str] = []
    if TERMINAL_OPS & {str(op) for op in emitted}:
        warnings.append(
            "terminal ops declared but unimplemented"
        )
    from sweepy.stripper import _ALLOWED_TOP_KEYS

    brain_keys = meta.get("state_keys")
    if isinstance(brain_keys, list):
        ours = {str(k) for k in _ALLOWED_TOP_KEYS}
        theirs = {str(k) for k in brain_keys}
        if theirs - ours:
            warnings.append(f"brain expects stripped keys: {sorted(theirs - ours)}")
        if ours - theirs:
            warnings.append(f"brain ignores sent keys: {sorted(ours - theirs)}")
    return warnings


def _gunzip_limited(raw_bytes: bytes) -> bytes:
    inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        data = inflater.decompress(raw_bytes, MAX_RESPONSE_BYTES + 1)
    except zlib.error as exc:
        raise BrainAPIError(f"bad gzip: {exc}") from exc
    if len(data) > MAX_RESPONSE_BYTES or inflater.unconsumed_tail:
        raise BrainAPIError("response too large after gunzip")
    if not inflater.eof:
        raise BrainAPIError("truncated gzip")
    if inflater.unused_data:
        raise BrainAPIError("gzip trailing data")
    return data


def _decode_response_bytes(raw_bytes: bytes) -> dict[str, Any]:
    if not raw_bytes:
        raise BrainAPIError("empty body")
    data = raw_bytes
    if len(data) >= 2 and data[:2] == b"\x1f\x8b":
        data = _gunzip_limited(data)
    if len(data) > MAX_RESPONSE_BYTES:
        raise BrainAPIError("response too large")
    try:
        parsed = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BrainAPIError(f"bad json: {exc}") from exc
    if not isinstance(parsed, dict):
        raise BrainAPIError("response root is not an object")
    return parsed


def _error_code_from_body(raw_bytes: bytes) -> str | None:
    if not raw_bytes:
        return None
    data = raw_bytes
    if len(data) >= 2 and data[:2] == b"\x1f\x8b":
        try:
            data = _gunzip_limited(data)
        except BrainAPIError:
            return None
    try:
        parsed = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if isinstance(parsed, dict):
        code = parsed.get("code")
        if isinstance(code, str) and code.strip():
            return code.strip()
        err = parsed.get("error")
        if isinstance(err, str) and err.strip():
            return err.strip()
        if isinstance(err, dict):
            inner = err.get("code")
            if isinstance(inner, str) and inner.strip():
                return inner.strip()
    return None


def _error_detail_from_body(raw_bytes: bytes) -> str:
    if not raw_bytes:
        return ""
    data = raw_bytes
    if len(data) >= 2 and data[:2] == b"\x1f\x8b":
        try:
            data = _gunzip_limited(data)
        except BrainAPIError:
            return ""
    try:
        parsed = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return ""
    if not isinstance(parsed, dict):
        return ""
    detail = parsed.get("detail")
    if isinstance(detail, dict):
        detail = detail.get("message") or detail.get("detail")
    if not isinstance(detail, str):
        return ""
    return " ".join(detail.split())[:200]


class BrainClient:
    def __init__(self, api_url: str, api_key: str, timeout: float = 15.0, on_key_refresh=None) -> None:
        try:
            self.api_url = validate_brain_url(api_url)
        except ValueError as exc:
            raise BrainAPIError(f"bad api_url {api_url!r}: {exc}") from exc
        self.api_key = str(api_key or "").strip()
        self.timeout = float(timeout)
        self.on_key_refresh = on_key_refresh
        self.session = requests.Session(
            trust_env=False,
            allow_redirects=False,
            max_redirects=0,
        )

    def _auth_headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Sweepy-Client": "2.0",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def meta(self) -> dict[str, Any]:
        url = f"{self.api_url}/v1/meta"
        try:
            resp = self.session.get(
                url, headers=self._auth_headers(), timeout=self.timeout,
                allow_redirects=False, max_redirects=0,
            )
        except Exception as exc:
            raise BrainAPIError(f"meta request failed ({url}): {exc}") from exc
        if resp.status_code != 200:
            preview = (resp.text or "")[:240].strip()
            raise BrainAPIError(
                f"meta: HTTP {resp.status_code}: {preview}",
                status_code=resp.status_code,
                code=_error_code_from_body(resp.content),
            )
        parsed = _decode_response_bytes(resp.content)
        if parsed.get("ok") is not True:
            raise BrainAPIError("meta missing ok")
        return parsed

    def health(self) -> dict[str, Any]:
        url = f"{self.api_url}/v1/health"
        try:
            resp = self.session.get(
                url,
                headers=self._auth_headers(),
                timeout=self.timeout,
                allow_redirects=False,
                max_redirects=0,
            )
        except Exception as exc:
            raise BrainAPIError(f"health request failed ({url}): {exc}") from exc
        if resp.status_code != 200:
            preview = (resp.text or "")[:240].strip()
            raise BrainAPIError(
                f"health: HTTP {resp.status_code}: {preview}",
                status_code=resp.status_code,
            )
        parsed = _decode_response_bytes(resp.content)
        if parsed.get("ok") is not True or not isinstance(parsed.get("model"), str) or not parsed["model"].strip():
            raise BrainAPIError("health payload missing model")
        return parsed

    def request_new_key(self) -> str:
        url = f"{self.api_url}/v1/keys"
        headers = self._auth_headers()
        headers.pop("Authorization", None)
        try:
            resp = self.session.post(url, headers=headers, timeout=self.timeout)
        except Exception as exc:
            raise BrainAPIError(f"key request failed ({url}): {exc}") from exc
        if resp.status_code != 200:
            raise BrainAPIError(
                f"key: HTTP {resp.status_code}: {(resp.text or '')[:200]}",
                status_code=resp.status_code,
                code=_error_code_from_body(resp.content),
            )
        payload = _decode_response_bytes(resp.content)
        secret = str(payload.get("api_key") or "").strip()
        if not secret:
            raise BrainAPIError("key response missing api_key")
        self.api_key = secret
        if callable(self.on_key_refresh):
            self.on_key_refresh(secret)
        return secret

    def decide(
        self,
        viewer_id_hash: str,
        state: dict[str, Any],
        delta: dict[str, Any],
        options: dict[str, Any],
    ) -> dict[str, Any]:
        if not self.api_key:
            raise BrainAPIError("no api key")
        if not isinstance(viewer_id_hash, str) or not viewer_id_hash.strip():
            raise BrainAPIError("viewer_id_hash is empty")
        if not isinstance(state, dict):
            raise BrainAPIError("state is not a dict")
        if not isinstance(delta, dict):
            raise BrainAPIError("delta is not a dict")
        if not isinstance(options, dict):
            raise BrainAPIError("options is not a dict")

        body_obj = {
            "viewer_id_hash": viewer_id_hash,
            "state": state,
            "delta": delta,
            "options": options,
        }
        raw_json = json.dumps(body_obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        compressed = gzip.compress(raw_json, compresslevel=6)
        headers = self._auth_headers()
        headers["Content-Type"] = "application/json"
        headers["Content-Encoding"] = "gzip"
        url = f"{self.api_url}/v1/gl/decide"

        for attempt in (0, 1):
            try:
                resp = self.session.post(
                    url,
                    data=compressed,
                    headers=headers,
                    timeout=self.timeout,
                    allow_redirects=False,
                    max_redirects=0,
                )
            except Exception as exc:
                raise BrainAPIError(f"decide request failed ({url}): {exc}") from exc
            if (
                attempt == 0
                and resp.status_code == 403
                and _error_code_from_body(resp.content) == "key_exhausted"
            ):
                self.request_new_key()
                headers = self._auth_headers()
                headers["Content-Type"] = "application/json"
                headers["Content-Encoding"] = "gzip"
                continue
            break

        if resp.status_code != 200:
            detail = _error_detail_from_body(resp.content)
            raise BrainAPIError(
                detail or f"decide: HTTP {resp.status_code}",
                status_code=resp.status_code,
                code=_error_code_from_body(resp.content),
            )

        parsed = _decode_response_bytes(resp.content)
        op = parsed.get("op")
        params = parsed.get("params")
        if op not in VALID_BRAIN_OPS or not isinstance(params, dict):
            raise BrainAPIError(f"bad decision: op={op!r}")
        return parsed

    def close_career(self, viewer_id_hash: str) -> dict[str, Any]:
        if not self.api_key:
            raise BrainAPIError("no api key")
        if not isinstance(viewer_id_hash, str) or not viewer_id_hash.strip():
            raise BrainAPIError("viewer_id_hash is empty")
        body_obj = {"viewer_id_hash": viewer_id_hash}
        raw_json = json.dumps(body_obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        headers = self._auth_headers()
        headers["Content-Type"] = "application/json"
        headers["Content-Encoding"] = "gzip"
        url = f"{self.api_url}/v1/gl/close"
        try:
            resp = self.session.post(
                url,
                data=gzip.compress(raw_json, compresslevel=6),
                headers=headers,
                timeout=self.timeout,
                allow_redirects=False,
                max_redirects=0,
            )
        except Exception as exc:
            raise BrainAPIError(f"close request failed ({url}): {exc}") from exc
        if resp.status_code != 200:
            preview = (resp.text or "")[:300].strip()
            raise BrainAPIError(
                f"close: HTTP {resp.status_code}: {preview}",
                status_code=resp.status_code,
                code=_error_code_from_body(resp.content),
            )
        parsed = _decode_response_bytes(resp.content)
        if parsed.get("ok") is not True:
            raise BrainAPIError("close missing ok")
        return parsed

    def close(self) -> None:
        self.session.close()
