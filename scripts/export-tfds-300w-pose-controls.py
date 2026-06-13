#!/usr/bin/env python3
"""Export TFDS the300w_lp examples as face-landmark pose-control PNGs."""

from __future__ import annotations

import argparse
import json
import math
import struct
import zlib
from pathlib import Path

import tensorflow_datasets as tfds


COLORS = {
    "jaw": (255, 255, 255),
    "brow": (255, 80, 220),
    "nose": (255, 70, 70),
    "eye": (70, 220, 255),
    "mouth": (255, 150, 40),
}


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
    width: int = 3,
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
    indexes: range,
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


def render_landmarks(points: list[list[float]], width: int, height: int, padding: int) -> list[list[tuple[int, int, int]]]:
    source = [(float(x), float(y)) for x, y in points]
    min_x = min(x for x, _y in source)
    max_x = max(x for x, _y in source)
    min_y = min(y for _x, y in source)
    max_y = max(y for _x, y in source)
    scale = min((width - padding * 2) / (max_x - min_x), (height - padding * 2) / (max_y - min_y))
    offset_x = (width - (max_x - min_x) * scale) / 2
    offset_y = (height - (max_y - min_y) * scale) / 2
    points = [((x - min_x) * scale + offset_x, (y - min_y) * scale + offset_y) for x, y in source]

    image = _blank(width, height)
    _polyline(image, points, range(0, 17), COLORS["jaw"], 3)
    _polyline(image, points, range(17, 22), COLORS["brow"], 3)
    _polyline(image, points, range(22, 27), COLORS["brow"], 3)
    _polyline(image, points, range(27, 31), COLORS["nose"], 3)
    _polyline(image, points, range(31, 36), COLORS["nose"], 3)
    _polyline(image, points, range(36, 42), COLORS["eye"], 3, True)
    _polyline(image, points, range(42, 48), COLORS["eye"], 3, True)
    _polyline(image, points, range(48, 60), COLORS["mouth"], 3, True)
    _polyline(image, points, range(60, 68), COLORS["mouth"], 2, True)
    return image


def jpeg_bytes(image_array) -> bytes:
    import io

    from PIL import Image

    image = Image.fromarray(image_array.numpy())
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=92)
    return buffer.getvalue()


def visual_bucket_for(pose_params: list[float]) -> str | None:
    pitch, yaw, roll = [math.degrees(float(value)) for value in pose_params[:3]]
    if abs(roll) > 18:
        return None
    if -8 <= yaw <= 8 and -8 <= pitch <= 8:
        return "front_neutral"
    # TFDS yaw sign is opposite of the visual image direction for our ComfyUI naming.
    if 35 <= yaw <= 55 and -15 <= pitch <= 12:
        return "three_quarter_left"
    if -55 <= yaw <= -35 and -15 <= pitch <= 12:
        return "three_quarter_right"
    if 60 <= yaw <= 80 and -15 <= pitch <= 15:
        return "profile_left"
    if -80 <= yaw <= -60 and -15 <= pitch <= 15:
        return "profile_right"
    if -8 <= yaw <= 8 and 18 <= pitch <= 35:
        return "slight_up"
    if -8 <= yaw <= 8 and -35 <= pitch <= -18:
        return "slight_down"
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--per-bucket", type=int, default=12)
    parser.add_argument("--max-scan", type=int, default=0)
    parser.add_argument("--width", type=int, default=512)
    parser.add_argument("--height", type=int, default=512)
    parser.add_argument("--padding", type=int, default=54)
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dataset = tfds.load("the300w_lp", split="train", data_dir=args.data_dir, shuffle_files=False)
    counts: dict[str, int] = {}
    manifest = []
    required_buckets = {
        "front_neutral",
        "three_quarter_left",
        "three_quarter_right",
        "profile_left",
        "profile_right",
        "slight_up",
        "slight_down",
    }

    for index, example in enumerate(dataset):
        if args.max_scan and index >= args.max_scan:
            break
        pose = example["pose_params"].numpy().tolist()
        bucket = visual_bucket_for(pose)
        if not bucket:
            continue
        counts.setdefault(bucket, 0)
        if counts[bucket] >= args.per_bucket:
            continue
        counts[bucket] += 1
        stem = f"{bucket}_{counts[bucket]:03d}_idx{index:05d}"
        bucket_dir = out_dir / bucket
        control_path = bucket_dir / f"{stem}_control.png"
        preview_path = bucket_dir / f"{stem}_preview.jpg"
        metadata_path = bucket_dir / f"{stem}.json"
        _write_png(
            control_path,
            render_landmarks(example["landmarks_3d"].numpy().tolist(), args.width, args.height, args.padding),
        )
        preview_path.write_bytes(jpeg_bytes(example["image"]))
        metadata = {
            "bucket": bucket,
            "index": index,
            "pose_params": pose,
            "pose_degrees": {
                "pitch": math.degrees(float(pose[0])),
                "yaw": math.degrees(float(pose[1])),
                "roll": math.degrees(float(pose[2])),
            },
            "roi": example["roi"].numpy().tolist(),
            "control": str(control_path),
            "preview": str(preview_path),
        }
        metadata_path.write_text(json.dumps(metadata, indent=2))
        manifest.append(metadata)
        if required_buckets.issubset(counts) and all(counts[bucket] >= args.per_bucket for bucket in required_buckets):
            break

    (out_dir / "manifest.json").write_text(json.dumps({"counts": counts, "items": manifest}, indent=2))
    print("counts", counts)
    print("out", out_dir)


if __name__ == "__main__":
    main()
