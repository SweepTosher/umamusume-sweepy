from __future__ import annotations

from typing import Callable


_VERSION_SPECS_M: dict[int, tuple[int, int, int, tuple[int, ...], int]] = {
    1: (16, 10, 1, (), 0),
    2: (28, 16, 1, (6, 18), 7),
    3: (44, 26, 1, (6, 22), 7),
    4: (64, 18, 2, (6, 26), 7),
    5: (86, 24, 2, (6, 30), 7),
    6: (108, 16, 4, (6, 34), 7),
}

_VERSION_SPECS_L: dict[int, tuple[int, int, int, tuple[int, ...], int]] = {
    1: (19, 7, 1, (), 0),
    2: (34, 10, 1, (6, 18), 7),
    3: (55, 15, 1, (6, 22), 7),
    4: (80, 20, 1, (6, 26), 7),
    5: (108, 26, 1, (6, 30), 7),
    6: (136, 18, 2, (6, 34), 7),
}

_GF_EXP = [0] * 512
_GF_LOG = [0] * 256


def _init_gf() -> None:
    val = 1
    for idx in range(255):
        _GF_EXP[idx] = val
        _GF_LOG[val] = idx
        val <<= 1
        if val & 0x100:
            val ^= 0x11D
    for idx in range(255, 512):
        _GF_EXP[idx] = _GF_EXP[idx - 255]


_init_gf()


def _gf_mul(left: int, right: int) -> int:
    if left == 0 or right == 0:
        return 0
    return _GF_EXP[_GF_LOG[left] + _GF_LOG[right]]


def _rs_generator(degree: int) -> list[int]:
    poly = [1]
    for idx in range(degree):
        root = _GF_EXP[idx]
        nxt = [0] * (len(poly) + 1)
        for pos, coeff in enumerate(poly):
            nxt[pos] ^= coeff
            nxt[pos + 1] ^= _gf_mul(coeff, root)
        poly = nxt
    return poly[1:]


def _rs_remainder(data: list[int], ec_len: int) -> list[int]:
    gen = _rs_generator(ec_len)
    rem = [0] * ec_len
    for byte in data:
        factor = byte ^ rem[0]
        rem = rem[1:] + [0]
        if factor != 0:
            for idx, coeff in enumerate(gen):
                rem[idx] ^= _gf_mul(coeff, factor)
    return rem


def _select_spec(byte_len: int) -> tuple[int, int, int, int, int, tuple[int, ...], int]:
    for version in range(3, 7):
        total_data, ec_per_block, blocks, align, rem_bits = _VERSION_SPECS_M[version]
        if byte_len + 2 <= total_data:
            return version, 0b00, total_data, ec_per_block, blocks, align, rem_bits
    for version in range(1, 3):
        total_data, ec_per_block, blocks, align, rem_bits = _VERSION_SPECS_M[version]
        if byte_len + 2 <= total_data:
            return version, 0b00, total_data, ec_per_block, blocks, align, rem_bits
    for version in range(5, 7):
        total_data, ec_per_block, blocks, align, rem_bits = _VERSION_SPECS_L[version]
        if byte_len + 2 <= total_data:
            return version, 0b01, total_data, ec_per_block, blocks, align, rem_bits
    raise ValueError(f"QR payload too long for Versions 1..6 ({byte_len} bytes)")


def _encode_data_codewords(payload: bytes, total_data: int) -> list[int]:
    bits: list[int] = [0, 1, 0, 0]
    length = len(payload)
    for shift in range(7, -1, -1):
        bits.append((length >> shift) & 1)
    for byte in payload:
        for shift in range(7, -1, -1):
            bits.append((byte >> shift) & 1)
    capacity_bits = total_data * 8
    term_len = min(4, capacity_bits - len(bits))
    bits.extend([0] * term_len)
    while len(bits) % 8 != 0:
        bits.append(0)
    codewords: list[int] = []
    for idx in range(0, len(bits), 8):
        val = 0
        for bit in bits[idx : idx + 8]:
            val = (val << 1) | bit
        codewords.append(val)
    pad_seq = (0xEC, 0x11)
    pad_idx = 0
    while len(codewords) < total_data:
        codewords.append(pad_seq[pad_idx & 1])
        pad_idx += 1
    return codewords


def _build_bitstream(
    data_codewords: list[int],
    ec_per_block: int,
    blocks: int,
    rem_bits: int,
) -> list[int]:
    block_size = len(data_codewords) // blocks
    data_blocks: list[list[int]] = []
    ec_blocks: list[list[int]] = []
    for blk in range(blocks):
        chunk = data_codewords[blk * block_size : (blk + 1) * block_size]
        data_blocks.append(chunk)
        ec_blocks.append(_rs_remainder(chunk, ec_per_block))
    interleaved: list[int] = []
    for pos in range(block_size):
        for blk in range(blocks):
            interleaved.append(data_blocks[blk][pos])
    for pos in range(ec_per_block):
        for blk in range(blocks):
            interleaved.append(ec_blocks[blk][pos])
    bits: list[int] = []
    for byte in interleaved:
        for shift in range(7, -1, -1):
            bits.append((byte >> shift) & 1)
    bits.extend([0] * rem_bits)
    return bits


def _place_finder(
    modules: list[list[bool]],
    is_func: list[list[bool]],
    top: int,
    left: int,
) -> None:
    size = len(modules)
    for dr in range(-1, 8):
        for dc in range(-1, 8):
            row = top + dr
            col = left + dc
            if 0 <= row < size and 0 <= col < size:
                in_outer = 0 <= dr <= 6 and 0 <= dc <= 6 and (dr in (0, 6) or dc in (0, 6))
                in_inner = 2 <= dr <= 4 and 2 <= dc <= 4
                modules[row][col] = in_outer or in_inner
                is_func[row][col] = True


def _place_alignment(
    modules: list[list[bool]],
    is_func: list[list[bool]],
    center_r: int,
    center_c: int,
) -> None:
    for dr in range(-2, 3):
        for dc in range(-2, 3):
            row = center_r + dr
            col = center_c + dc
            dist = max(abs(dr), abs(dc))
            modules[row][col] = dist != 1
            is_func[row][col] = True


def _write_format_bits(
    modules: list[list[bool]],
    is_func: list[list[bool]],
    ecc_bits: int,
    mask_id: int,
) -> None:
    size = len(modules)
    data5 = ((ecc_bits & 0x3) << 3) | (mask_id & 0x7)
    rem = data5 << 10
    for shift in range(14, 9, -1):
        if (rem >> shift) & 1:
            rem ^= 0x537 << (shift - 10)
    fmt = ((data5 << 10) | rem) ^ 0x5412

    def bit(idx: int) -> bool:
        return bool((fmt >> idx) & 1)

    tl_row_cols = (0, 1, 2, 3, 4, 5, 7, 8)
    for pos, col in enumerate(tl_row_cols):
        modules[8][col] = bit(14 - pos)
        is_func[8][col] = True
    tl_col_rows = (7, 5, 4, 3, 2, 1, 0)
    for pos, row in enumerate(tl_col_rows):
        modules[row][8] = bit(6 - pos)
        is_func[row][8] = True

    for idx in range(7):
        row = size - 1 - idx
        modules[row][8] = bit(14 - idx)
        is_func[row][8] = True
    modules[size - 8][8] = True
    is_func[size - 8][8] = True

    for idx in range(8):
        col = size - 8 + idx
        modules[8][col] = bit(7 - idx)
        is_func[8][col] = True


_MASKS: tuple[Callable[[int, int], bool], ...] = (
    lambda r, c: (r + c) % 2 == 0,
    lambda r, c: r % 2 == 0,
    lambda r, c: c % 3 == 0,
    lambda r, c: (r + c) % 3 == 0,
    lambda r, c: ((r // 2) + (c // 3)) % 2 == 0,
    lambda r, c: ((r * c) % 2 + (r * c) % 3) == 0,
    lambda r, c: (((r * c) % 2 + (r * c) % 3) % 2) == 0,
    lambda r, c: (((r + c) % 2 + (r * c) % 3) % 2) == 0,
)


def _penalty_score(grid: list[list[bool]]) -> int:
    size = len(grid)
    score = 0

    for row in range(size):
        run_val = grid[row][0]
        run_len = 1
        for col in range(1, size):
            if grid[row][col] == run_val:
                run_len += 1
            else:
                if run_len >= 5:
                    score += 3 + (run_len - 5)
                run_val = grid[row][col]
                run_len = 1
        if run_len >= 5:
            score += 3 + (run_len - 5)

    for col in range(size):
        run_val = grid[0][col]
        run_len = 1
        for row in range(1, size):
            if grid[row][col] == run_val:
                run_len += 1
            else:
                if run_len >= 5:
                    score += 3 + (run_len - 5)
                run_val = grid[row][col]
                run_len = 1
        if run_len >= 5:
            score += 3 + (run_len - 5)

    for row in range(size - 1):
        for col in range(size - 1):
            val = grid[row][col]
            if grid[row][col + 1] == val and grid[row + 1][col] == val and grid[row + 1][col + 1] == val:
                score += 3

    pat_a = [True, False, True, True, True, False, True, False, False, False, False]
    pat_b = [False, False, False, False, True, False, True, True, True, False, True]
    for row in range(size):
        line = grid[row]
        for col in range(size - 10):
            seg = line[col : col + 11]
            if seg == pat_a or seg == pat_b:
                score += 40
    for col in range(size):
        col_line = [grid[row][col] for row in range(size)]
        for row in range(size - 10):
            seg = col_line[row : row + 11]
            if seg == pat_a or seg == pat_b:
                score += 40

    dark = sum(1 for row in grid for cell in row if cell)
    total = size * size
    deviation = abs(dark * 20 - total * 10) // total
    score += deviation * 10
    return score


def encode_qr_matrix(text: str) -> list[list[bool]]:
    if not isinstance(text, str) or not text:
        raise ValueError("QR text is empty")
    payload = text.encode("utf-8")
    version, ecc_bits, total_data, ec_per_block, blocks, align_centers, rem_bits = _select_spec(len(payload))
    size = 17 + 4 * version
    base = [[False] * size for _ in range(size)]
    is_func = [[False] * size for _ in range(size)]

    _place_finder(base, is_func, 0, 0)
    _place_finder(base, is_func, 0, size - 7)
    _place_finder(base, is_func, size - 7, 0)

    for idx in range(8, size - 8):
        val = idx % 2 == 0
        base[6][idx] = val
        is_func[6][idx] = True
        base[idx][6] = val
        is_func[idx][6] = True

    for r_center in align_centers:
        for c_center in align_centers:
            near_tl = r_center <= 8 and c_center <= 8
            near_tr = r_center <= 8 and c_center >= size - 8
            near_bl = r_center >= size - 8 and c_center <= 8
            if not (near_tl or near_tr or near_bl):
                _place_alignment(base, is_func, r_center, c_center)

    _write_format_bits(base, is_func, ecc_bits, 0)

    codewords = _encode_data_codewords(payload, total_data)
    bitstream = _build_bitstream(codewords, ec_per_block, blocks, rem_bits)

    bit_idx = 0
    upward = True
    col = size - 1
    while col > 0:
        if col == 6:
            col -= 1
        row_iter = range(size - 1, -1, -1) if upward else range(size)
        for row in row_iter:
            for dc in (0, 1):
                cur_c = col - dc
                if not is_func[row][cur_c]:
                    if bit_idx < len(bitstream):
                        base[row][cur_c] = bool(bitstream[bit_idx])
                        bit_idx += 1
        upward = not upward
        col -= 2

    best_grid: list[list[bool]] | None = None
    best_score: int | None = None
    for mask_id, mask_fn in enumerate(_MASKS):
        cand = [row[:] for row in base]
        func_copy = [row[:] for row in is_func]
        for row in range(size):
            for cur_c in range(size):
                if not func_copy[row][cur_c] and mask_fn(row, cur_c):
                    cand[row][cur_c] = not cand[row][cur_c]
        _write_format_bits(cand, func_copy, ecc_bits, mask_id)
        score = _penalty_score(cand)
        if best_score is None or score < best_score:
            best_score = score
            best_grid = cand

    if best_grid is None:
        raise RuntimeError("QR mask evaluation failed")
    return best_grid


def render_qr_svg(text: str, border: int = 4) -> str:
    if border < 0 or border > 16:
        raise ValueError("border out of range")
    matrix = encode_qr_matrix(text)
    size = len(matrix)
    view_size = size + 2 * border
    parts: list[str] = []
    for row_idx, row in enumerate(matrix):
        y_pos = row_idx + border
        col_idx = 0
        while col_idx < size:
            if not row[col_idx]:
                col_idx += 1
                continue
            start_col = col_idx
            while col_idx < size and row[col_idx]:
                col_idx += 1
            run_width = col_idx - start_col
            x_pos = start_col + border
            parts.append(f"M{x_pos} {y_pos}h{run_width}v1h-{run_width}z")
    path_data = "".join(parts)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {view_size} {view_size}" '
        f'shape-rendering="crispEdges">'
        f'<rect width="{view_size}" height="{view_size}" fill="white"/>'
        f'<path d="{path_data}" fill="black"/>'
        f"</svg>"
    )
