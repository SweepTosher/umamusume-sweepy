from __future__ import annotations

import base64
import struct
import zlib
from typing import Any


_MAX_SCENARIO_BYTES = 16 * 1024 * 1024


def decode_player_rank(
    race_scenario_b64: str,
    race_horse_data: list[dict[str, Any]],
    single_mode_chara_id: int,
) -> int:
    if not isinstance(race_scenario_b64, str) or not race_scenario_b64.strip():
        raise ValueError("race_scenario_b64 is empty or not base64")
    if not isinstance(race_horse_data, list) or not race_horse_data:
        raise ValueError("race_horse_data is empty or not a list")

    target_chara_id = int(single_mode_chara_id)
    runner_idx: int | None = None
    for row in race_horse_data:
        if not isinstance(row, dict):
            continue
        raw_cid = row.get("single_mode_chara_id", -1)
        if raw_cid is None or isinstance(raw_cid, bool):
            continue
        if int(raw_cid) == target_chara_id:
            frame_order = int(row["frame_order"])
            runner_idx = frame_order - 1
            break

    if runner_idx is None:
        raise ValueError(f"Player single_mode_chara_id {target_chara_id} not found in race_horse_data")

    try:
        compressed = base64.b64decode(race_scenario_b64, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("race_scenario_b64 is not valid base64") from exc
    try:
        inflater = zlib.decompressobj(31)
        payload = inflater.decompress(compressed, _MAX_SCENARIO_BYTES + 1)
        payload += inflater.flush()
    except zlib.error as exc:
        raise ValueError("race_scenario_b64 is not gzip data") from exc
    if len(payload) > _MAX_SCENARIO_BYTES:
        raise ValueError(f"race_scenario payload exceeds {_MAX_SCENARIO_BYTES} bytes")
    total_len = len(payload)
    offset = 0

    def require_bytes(count: int, label: str) -> None:
        if count < 0 or offset + count > total_len:
            raise ValueError(f"Truncated {label} at offset {offset}")

    require_bytes(8, "version_header")
    header_length, _decoder_version = struct.unpack_from("<ii", payload, offset)
    offset += 8
    if header_length != 4:
        raise ValueError(f"Unsupported race_scenario header_length: {header_length}")

    require_bytes(16, "race_header")
    _distance_diff_max, horse_count, _horse_stride, result_stride = struct.unpack_from(
        "<fiii", payload, offset
    )
    offset += 16
    if horse_count <= 0 or horse_count > 128:
        raise ValueError(f"Invalid horse_count: {horse_count}")
    if result_stride < 4:
        raise ValueError(f"Invalid result_stride: {result_stride}")
    if runner_idx < 0 or runner_idx >= horse_count:
        raise ValueError(f"runner_idx {runner_idx} out of range for horse_count {horse_count}")

    require_bytes(4, "pad_before_frames_len")
    (pad_frames_len,) = struct.unpack_from("<i", payload, offset)
    offset += 4
    require_bytes(pad_frames_len, "pad_before_frames")
    offset += pad_frames_len

    require_bytes(8, "frame_section_header")
    frame_count, frame_stride = struct.unpack_from("<ii", payload, offset)
    offset += 8
    if frame_count < 0 or frame_stride < 0:
        raise ValueError("Negative frame section dimensions")
    frames_bytes = frame_count * frame_stride
    require_bytes(frames_bytes, "frame_section")
    offset += frames_bytes

    require_bytes(4, "pad_before_results_len")
    (pad_results_len,) = struct.unpack_from("<i", payload, offset)
    offset += 4
    require_bytes(pad_results_len, "pad_before_results")
    offset += pad_results_len

    require_bytes(horse_count * result_stride, "result_section")
    target_offset = offset + runner_idx * result_stride
    (finish_order,) = struct.unpack_from("<i", payload, target_offset)
    rank = int(finish_order) + 1
    if rank < 1 or rank > 18:
        raise ValueError(f"Decoded player rank out of bounds: {rank}")
    return rank
