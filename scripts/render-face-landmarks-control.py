#!/usr/bin/env python3
"""Render MATLAB v5 68-point face landmarks into a ComfyUI control PNG."""

from __future__ import annotations

import argparse
import math
import struct
import zlib
from pathlib import Path


MI_COMPRESSED = 15
MI_MATRIX = 14
MI_DOUBLE = 9
MI_INT32 = 5
MI_UINT32 = 6


def _read_tag(data: bytes, offset: int) -> tuple[int, int, int, int]:
    raw = struct.unpack_from("<I", data, offset)[0]
    dtype = raw & 0xFFFF
    size = (raw >> 16) & 0xFFFF
    if size and dtype in {1, 2, 3, 4, 5, 6, 7, 9, 12, 13, 16, 17, 18}:
        return dtype, size, offset + 4, offset + 8
    dtype, size = struct.unpack_from("<II", data, offset)
    data_offset = offset + 8
    next_offset = data_offset + size + ((8 - size % 8) % 8)
    return dtype, size, data_offset, next_offset


def _read_numeric(data: bytes, dtype: int, offset: int, size: int) -> list[float]:
    formats = {MI_INT32: "i", MI_UINT32: "I", MI_DOUBLE: "d"}
    fmt = formats.get(dtype)
    if fmt is None:
        return []
    item_size = struct.calcsize("<" + fmt)
    count = size // item_size
    return list(struct.unpack_from("<" + fmt * count, data, offset))


def _parse_matrices(data: bytes) -> dict[str, tuple[list[int], list[float]]]:
    matrices: dict[str, tuple[list[int], list[float]]] = {}
    offset = 0
    while offset < len(data) - 8:
        dtype, size, data_offset, next_offset = _read_tag(data, offset)
        payload = data[data_offset : data_offset + size]
        if dtype == MI_COMPRESSED:
            matrices.update(_parse_matrices(zlib.decompress(payload)))
        elif dtype == MI_MATRIX:
            inner_offset = 0
            _dtype, _size, _data_offset, inner_offset = _read_tag(payload, inner_offset)
            dtype2, size2, data_offset2, inner_offset = _read_tag(payload, inner_offset)
            dims = [int(value) for value in _read_numeric(payload, dtype2, data_offset2, size2)]
            dtype3, size3, data_offset3, inner_offset = _read_tag(payload, inner_offset)
            name = payload[data_offset3 : data_offset3 + size3].decode("latin1")
            dtype4, size4, data_offset4, _inner_next = _read_tag(payload, inner_offset)
            matrices[name] = (dims, _read_numeric(payload, dtype4, data_offset4, size4))
        offset = next_offset
    return matrices


def load_pt2d(path: Path) -> list[tuple[float, float]]:
    data = path.read_bytes()
    matrices = _parse_matrices(data[128:])
    dims, values = matrices.get("pt2d", ([], []))
    if dims != [2, 68] or len(values) != 136:
        raise ValueError(f"{path} does not contain a 2x68 pt2d matrix")
    # MATLAB stores this column-major: x1,y1,x2,y2...
    return [(values[index], values[index + 1]) for index in range(0, len(values), 2)]


def _blank(width: int, height: int) -> list[list[tuple[int, int, int]]]:
    return [[(0, 0, 0) for _x in range(width)] for _y in range(height)]


def _put(image: list[list[tuple[int, int, int]]], x: float, y: float, color: tuple[int, int, int]) -> None:
    height = len(image)
    width = len(image[0])
    ix = int(round(x))
    iy = int(round(y))
    if 0 <= ix < width and 0 <= iy < height:
        image[iy][ix] = color


def _line(
    image: list[list[tuple[int, int, int]]],
    a: tuple[float, float],
    b: tuple[float, float],
    color: tuple[int, int, int],
    width: int,
) -> None:
    steps = max(abs(b[0] - a[0]), abs(b[1] - a[1]), 1)
    radius = max(1, width // 2)
    for step in range(int(steps) + 1):
        t = step / steps
        x = a[0] + (b[0] - a[0]) * t
        y = a[1] + (b[1] - a[1]) * t
        for yy in range(-radius, radius + 1):
            for xx in range(-radius, radius + 1):
                if xx * xx + yy * yy <= radius * radius:
                    _put(image, x + xx, y + yy, color)


def _polyline(
    image: list[list[tuple[int, int, int]]],
    points: list[tuple[float, float]],
    indexes: range | list[int],
    color: tuple[int, int, int],
    width: int = 3,
    closed: bool = False,
) -> None:
    selected = [points[index] for index in indexes]
    for a, b in zip(selected, selected[1:]):
        _line(image, a, b, color, width)
    if closed and len(selected) > 2:
        _line(image, selected[-1], selected[0], color, width)


def _write_png(path: Path, image: list[list[tuple[int, int, int]]]) -> None:
    height = len(image)
    width = len(image[0])
    raw = b"".join(b"\x00" + bytes(channel for pixel in row for channel in pixel) for row in image)

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def render(points: list[tuple[float, float]], width: int, height: int, padding: int) -> list[list[tuple[int, int, int]]]:
    min_x = min(x for x, _y in points)
    max_x = max(x for x, _y in points)
    min_y = min(y for _x, y in points)
    max_y = max(y for _x, y in points)
    scale = min((width - padding * 2) / (max_x - min_x), (height - padding * 2) / (max_y - min_y))
    offset_x = (width - (max_x - min_x) * scale) / 2
    offset_y = (height - (max_y - min_y) * scale) / 2
    normalized = [((x - min_x) * scale + offset_x, (y - min_y) * scale + offset_y) for x, y in points]

    image = _blank(width, height)
    jaw = (255, 255, 255)
    brow = (255, 80, 220)
    nose = (255, 70, 70)
    eye = (70, 220, 255)
    mouth = (255, 150, 40)

    _polyline(image, normalized, range(0, 17), jaw, 3)
    _polyline(image, normalized, range(17, 22), brow, 3)
    _polyline(image, normalized, range(22, 27), brow, 3)
    _polyline(image, normalized, range(27, 31), nose, 3)
    _polyline(image, normalized, range(31, 36), nose, 3)
    _polyline(image, normalized, range(36, 42), eye, 3, closed=True)
    _polyline(image, normalized, range(42, 48), eye, 3, closed=True)
    _polyline(image, normalized, range(48, 60), mouth, 3, closed=True)
    _polyline(image, normalized, range(60, 68), mouth, 2, closed=True)
    return image


def _read_jpeg_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    index = 2
    while index < len(data) - 9:
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        index += 2
        if marker in {0xD8, 0xD9}:
            continue
        size = struct.unpack(">H", data[index : index + 2])[0]
        if 0xC0 <= marker <= 0xC3:
            height = struct.unpack(">H", data[index + 3 : index + 5])[0]
            width = struct.unpack(">H", data[index + 5 : index + 7])[0]
            return width, height
        index += size
    raise ValueError(f"Cannot read JPEG dimensions from {path}")


def render_overlay(points: list[tuple[float, float]], image_path: Path) -> list[list[tuple[int, int, int]]]:
    # Keep this dependency-free: use the source dimensions and draw landmarks on black.
    # The WebUI control path only needs the landmark geometry; this mode validates alignment scale.
    width, height = _read_jpeg_size(image_path)
    image = _blank(width, height)
    jaw = (255, 255, 255)
    brow = (255, 80, 220)
    nose = (255, 70, 70)
    eye = (70, 220, 255)
    mouth = (255, 150, 40)
    _polyline(image, points, range(0, 17), jaw, 2)
    _polyline(image, points, range(17, 22), brow, 2)
    _polyline(image, points, range(22, 27), brow, 2)
    _polyline(image, points, range(27, 31), nose, 2)
    _polyline(image, points, range(31, 36), nose, 2)
    _polyline(image, points, range(36, 42), eye, 2, closed=True)
    _polyline(image, points, range(42, 48), eye, 2, closed=True)
    _polyline(image, points, range(48, 60), mouth, 2, closed=True)
    _polyline(image, points, range(60, 68), mouth, 1, closed=True)
    return image


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mat_file", type=Path)
    parser.add_argument("output_png", type=Path)
    parser.add_argument("--width", type=int, default=512)
    parser.add_argument("--height", type=int, default=512)
    parser.add_argument("--padding", type=int, default=56)
    parser.add_argument("--source-image", type=Path)
    args = parser.parse_args()
    points = load_pt2d(args.mat_file)
    image = render_overlay(points, args.source_image) if args.source_image else render(points, args.width, args.height, args.padding)
    _write_png(args.output_png, image)
    print(args.output_png)


if __name__ == "__main__":
    main()
