"""Low-level readers for ECLIPSE binary records and ASCII GRDECL data."""

from __future__ import annotations

import math
import os
import re
import struct
import sys
from array import array
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Sequence


class EclFormatError(RuntimeError):
    """Raised when an ECLIPSE binary or GRDECL input is malformed."""


ECL_TYPE_SIZES = {
    "INTE": 4,
    "REAL": 4,
    "LOGI": 4,
    "DOUB": 8,
    "CHAR": 8,
    "C008": 8,
    "MESS": 0,
}


def _read_be_i4(handle) -> int:
    raw = handle.read(4)
    if len(raw) != 4:
        raise EclFormatError("Unexpected end of file in a Fortran record marker.")
    return struct.unpack(">i", raw)[0]


def _decode_payload(type_name: str, count: int, chunks: list[bytes]) -> Any:
    payload = b"".join(chunks)
    if type_name in {"CHAR", "C008"}:
        return [
            payload[offset : offset + 8].decode("ascii", "replace").rstrip()
            for offset in range(0, count * 8, 8)
        ]
    if type_name == "MESS":
        return []
    typecode = {"INTE": "i", "LOGI": "i", "REAL": "f", "DOUB": "d"}[type_name]
    result = array(typecode)
    result.frombytes(payload)
    if sys.byteorder == "little":
        result.byteswap()
    if len(result) != count:
        raise EclFormatError(
            f"Decoded {len(result)} values for {type_name}; expected {count}."
        )
    return result


def read_ecl_records(
    path: str | Path,
    *,
    load_keys: Iterable[str] | None = None,
    stop_after_keyword: str | None = None,
    stop_after_occurrences: int | None = None,
) -> list[dict[str, Any]]:
    """Read unformatted ECLIPSE keyword records.

    Values for unselected keywords are skipped in the file stream, so a large
    INIT or restart file can be inspected without allocating every array.
    """

    path = Path(path)
    selected = None if load_keys is None else {key.upper() for key in load_keys}
    stop_keyword = stop_after_keyword.upper() if stop_after_keyword else None
    records: list[dict[str, Any]] = []
    stop_count = 0
    with path.open("rb") as handle:
        while True:
            offset = handle.tell()
            marker = handle.read(4)
            if not marker:
                break
            if len(marker) != 4:
                raise EclFormatError(f"Truncated keyword marker at byte {offset}.")
            header_size = struct.unpack(">i", marker)[0]
            if header_size != 16:
                raise EclFormatError(
                    f"Expected a 16-byte keyword header at byte {offset}; got {header_size}."
                )
            header = handle.read(16)
            if len(header) != 16 or _read_be_i4(handle) != 16:
                raise EclFormatError(f"Malformed keyword header at byte {offset}.")
            keyword = header[:8].decode("ascii", "replace").strip().upper()
            count = struct.unpack(">i", header[8:12])[0]
            type_name = header[12:16].decode("ascii", "replace")
            if count < 0:
                raise EclFormatError(f"Negative item count for {keyword}.")
            if type_name not in ECL_TYPE_SIZES:
                raise EclFormatError(
                    f"Unsupported ECLIPSE type {type_name!r} for {keyword}."
                )

            expected_bytes = count * ECL_TYPE_SIZES[type_name]
            decode = selected is None or keyword in selected
            chunks: list[bytes] = []
            consumed = 0
            while consumed < expected_bytes:
                payload_size = _read_be_i4(handle)
                if payload_size <= 0:
                    raise EclFormatError(f"Invalid payload size for {keyword}.")
                if consumed + payload_size > expected_bytes:
                    raise EclFormatError(f"Payload is too large for {keyword}.")
                if decode:
                    payload = handle.read(payload_size)
                    if len(payload) != payload_size:
                        raise EclFormatError(f"Truncated payload for {keyword}.")
                    chunks.append(payload)
                else:
                    handle.seek(payload_size, os.SEEK_CUR)
                if _read_be_i4(handle) != payload_size:
                    raise EclFormatError(f"Mismatched payload marker for {keyword}.")
                consumed += payload_size
            value = _decode_payload(type_name, count, chunks) if decode else None
            records.append(
                {
                    "keyword": keyword,
                    "count": count,
                    "type": type_name,
                    "offset": offset,
                    "value": value,
                }
            )
            if stop_keyword and keyword == stop_keyword:
                stop_count += 1
                if stop_after_occurrences is None or stop_count >= stop_after_occurrences:
                    break
    return records


def first_values(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Return the first decoded occurrence of each keyword."""

    values: dict[str, Any] = {}
    for record in records:
        keyword = str(record["keyword"])
        if record.get("value") is not None and keyword not in values:
            values[keyword] = record["value"]
    return values


def local_to_map(x: float, y: float, axes: Sequence[float]) -> tuple[float, float]:
    """Apply the ECLIPSE MAPAXES local-to-map transformation."""

    if len(axes) != 6:
        return x, y
    y_axis = (float(axes[0]), float(axes[1]))
    origin = (float(axes[2]), float(axes[3]))
    x_axis = (float(axes[4]), float(axes[5]))
    x_direction = (x_axis[0] - origin[0], x_axis[1] - origin[1])
    y_direction = (y_axis[0] - origin[0], y_axis[1] - origin[1])
    x_length = math.hypot(*x_direction)
    y_length = math.hypot(*y_direction)
    if x_length == 0.0 or y_length == 0.0:
        raise EclFormatError("MAPAXES contains a zero-length axis.")
    return (
        origin[0] + x * x_direction[0] / x_length + y * y_direction[0] / y_length,
        origin[1] + x * x_direction[1] / x_length + y * y_direction[1] / y_length,
    )


def global_ijk(global_index: int, nx: int, ny: int) -> tuple[int, int, int]:
    plane = nx * ny
    k, remainder = divmod(global_index, plane)
    j, i = divmod(remainder, nx)
    return i + 1, j + 1, k + 1


def neighbor_global(
    global_index: int, direction: str, nx: int, ny: int, nz: int
) -> int | None:
    i, j, k = global_ijk(global_index, nx, ny)
    if direction == "X":
        return global_index + 1 if i < nx else None
    if direction == "Y":
        return global_index + nx if j < ny else None
    if direction == "Z":
        return global_index + nx * ny if k < nz else None
    raise ValueError(f"Unknown logical direction: {direction}")


def cell_corners(
    linear_index: int,
    nx: int,
    ny: int,
    coord: Sequence[float],
    zcorn: Sequence[float],
) -> tuple[list[tuple[float, float, float]], tuple[int, int, int]]:
    """Interpolate the eight COORD/ZCORN corners of one logical grid cell."""

    plane = nx * ny
    k, remainder = divmod(linear_index, plane)
    j, i = divmod(remainder, nx)
    vertices: list[tuple[float, float, float]] = []
    for kb in (0, 1):
        z_plane = (2 * k + kb) * (2 * ny) * (2 * nx)
        for jb in (0, 1):
            row = (2 * j + jb) * (2 * nx)
            for ib in (0, 1):
                depth = float(zcorn[z_plane + row + 2 * i + ib])
                pillar = ((j + jb) * (nx + 1) + i + ib) * 6
                x_top, y_top, z_top, x_bottom, y_bottom, z_bottom = (
                    float(coord[pillar + offset]) for offset in range(6)
                )
                fraction = (
                    0.0 if z_bottom == z_top else (depth - z_top) / (z_bottom - z_top)
                )
                vertices.append(
                    (
                        x_top + fraction * (x_bottom - x_top),
                        y_top + fraction * (y_bottom - y_top),
                        depth,
                    )
                )
    return vertices, (i + 1, j + 1, k + 1)


def parse_grdecl_property(path: str | Path) -> tuple[str, array, int]:
    """Read one numeric GRDECL keyword, including repeat syntax."""

    path = Path(path)
    text_value = path.read_text(encoding="utf-8", errors="replace")
    text_value = re.sub(r"--[^\r\n]*", " ", text_value)
    tokens = re.findall(r"/|[^\s/]+", text_value)
    if not tokens:
        raise EclFormatError(f"No GRDECL tokens in {path}.")
    keyword = tokens[0].upper()
    values = array("d")
    default_count = 0
    for token in tokens[1:]:
        if token == "/":
            break
        if "*" in token:
            repeat_text, value_text = token.split("*", 1)
            repeat = int(repeat_text) if repeat_text else 1
            if not value_text:
                default_count += repeat
                values.extend([math.nan] * repeat)
            else:
                value = float(value_text.replace("D", "E").replace("d", "e"))
                values.extend([value] * repeat)
        else:
            values.append(float(token.replace("D", "E").replace("d", "e")))
    return keyword, values, default_count


def parse_nnc(
    path: str | Path,
    nx: int,
    ny: int,
    nz: int,
    active_globals: Iterable[int] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int | float | None]]:
    """Read Petrel NNC rows and return zero-based global endpoints."""

    path = Path(path)
    active = None if active_globals is None else set(active_globals)
    rows: list[dict[str, Any]] = []
    pair_counts: Counter[tuple[int, int]] = Counter()
    invalid = inactive = self_count = nonpositive = 0
    pattern = re.compile(
        r"^\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+"
        r"([-+0-9.EeDd]+)\s*/"
    )
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = pattern.match(line)
        if not match:
            continue
        indices = [int(match.group(index)) for index in range(1, 7)]
        i1, j1, k1, i2, j2, k2 = indices
        transmissibility = float(match.group(7).replace("D", "E").replace("d", "e"))
        valid = (
            1 <= i1 <= nx
            and 1 <= i2 <= nx
            and 1 <= j1 <= ny
            and 1 <= j2 <= ny
            and 1 <= k1 <= nz
            and 1 <= k2 <= nz
        )
        if valid:
            global1 = (k1 - 1) * nx * ny + (j1 - 1) * nx + i1 - 1
            global2 = (k2 - 1) * nx * ny + (j2 - 1) * nx + i2 - 1
            pair_counts[tuple(sorted((global1, global2)))] += 1
            if active is not None and (global1 not in active or global2 not in active):
                inactive += 1
            if global1 == global2:
                self_count += 1
        else:
            global1 = global2 = -1
            invalid += 1
        if transmissibility <= 0.0:
            nonpositive += 1
        rows.append(
            {
                "i1": i1,
                "j1": j1,
                "k1": k1,
                "i2": i2,
                "j2": j2,
                "k2": k2,
                "global1": global1,
                "global2": global2,
                "transmissibility": transmissibility,
            }
        )
    positive = [row["transmissibility"] for row in rows if row["transmissibility"] > 0.0]
    stats: dict[str, int | float | None] = {
        "rows": len(rows),
        "positive": len(positive),
        "nonpositive": nonpositive,
        "invalid_index": invalid,
        "inactive_endpoint": inactive,
        "self_connection": self_count,
        "duplicate_pair": sum(count - 1 for count in pair_counts.values() if count > 1),
        "transmissibility_min_positive": min(positive) if positive else None,
        "transmissibility_max": max(positive) if positive else None,
    }
    return rows, stats


RESTART_KEYS = {
    "SEQNUM",
    "INTEHEAD",
    "DOUBHEAD",
    "ZCOMPS",
    "ZPHASE",
    "ZFLUID",
    "TEMP",
    "TEMPERATURE",
    "PRESSURE",
    "PCOINIT",
    "PCGINIT",
    "PCWINIT",
    "SGT",
    "SWT",
    "PGAS",
    "POIL",
    "PWAT",
    "PSAT",
    "SGAS",
    "SOIL",
    "SWAT",
    "DENG",
    "DENO",
    "DENW",
    "XMF1",
    "YMF1",
    "ZMF1",
}


def read_first_restart(path: str | Path) -> dict[str, Any]:
    """Read only the first solution block from a unified restart file."""

    records = read_ecl_records(
        path,
        load_keys=RESTART_KEYS,
        stop_after_keyword="ENDSOL",
        stop_after_occurrences=1,
    )
    return {
        "values": first_values(records),
        "headers": [
            {
                "keyword": record["keyword"],
                "count": record["count"],
                "type": record["type"],
                "offset": record["offset"],
            }
            for record in records
        ],
    }
