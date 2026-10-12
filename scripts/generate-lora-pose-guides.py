#!/usr/bin/env python3
"""Generate deterministic OpenPose-style body guides for character LoRA datasets."""

from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "config" / "image-studio" / "lora-pose-guides" / "body"
FACE_OUTPUT = ROOT / "config" / "image-studio" / "lora-pose-guides" / "face"
SIZE = (768, 1536)
COLORS = [
    "#ff0000", "#ff5500", "#ffaa00", "#ffff00", "#aaff00", "#55ff00",
    "#00ff00", "#00ff55", "#00ffaa", "#00ffff", "#00aaff", "#0055ff",
    "#0000ff", "#5500ff", "#aa00ff", "#ff00ff", "#ff00aa", "#ff0055",
]


POSES = {
    "front_neutral": [(384, 20), (270, 45), (205, 285), (148, 520), (498, 45), (563, 285), (620, 520), (384, 570), (315, 595), (285, 985), (270, 1345), (245, 1425), (292, 1425), (453, 595), (483, 985), (498, 1345), (476, 1425), (523, 1425)],
    # Strong shoulder/hip foreshortening makes axial body yaw legible to the
    # 2D OpenPose ControlNet. The far side sits close to the centerline while
    # the near side retains the wider silhouette.
    "three_quarter_left": [(384, 20), (250, 48), (205, 292), (170, 522), (420, 38), (442, 280), (458, 510), (382, 570), (302, 596), (282, 985), (272, 1345), (246, 1425), (292, 1425), (410, 584), (422, 978), (430, 1342), (410, 1425), (452, 1425)],
    "three_quarter_right": [(384, 20), (348, 38), (326, 280), (310, 510), (518, 48), (563, 292), (598, 522), (386, 570), (358, 584), (346, 978), (338, 1342), (316, 1425), (358, 1425), (466, 596), (486, 985), (496, 1345), (476, 1425), (522, 1425)],
    "profile_left": [(350, 20), (325, 48), (300, 290), (285, 515), (382, 42), (405, 282), (420, 510), (365, 570), (342, 598), (330, 985), (326, 1345), (303, 1425), (344, 1425), (390, 592), (400, 980), (405, 1342), (387, 1425), (426, 1425)],
    "profile_right": [(418, 20), (386, 42), (363, 282), (348, 510), (443, 48), (468, 290), (483, 515), (403, 570), (378, 592), (368, 980), (363, 1342), (342, 1425), (381, 1425), (426, 598), (438, 985), (442, 1345), (424, 1425), (465, 1425)],
    "back_neutral": [(384, 20), (498, 45), (563, 285), (620, 520), (270, 45), (205, 285), (148, 520), (384, 570), (453, 595), (483, 985), (498, 1345), (476, 1425), (523, 1425), (315, 595), (285, 985), (270, 1345), (245, 1425), (292, 1425)],
}

FACE_SOURCES = {
    "front_neutral": "front_neutral/front_neutral_001_idx00065_control.png",
    "front_smile": "front_neutral/front_neutral_001_idx00065_control.png",
    "three_quarter_left": "three_quarter_left/three_quarter_left_001_idx00007_control.png",
    "three_quarter_right": "three_quarter_right/three_quarter_right_003_idx00022_control.png",
}

# These exact crops come from the dense facial-landmark reference sheet. They
# are kept as packaged assets because the local 300W-LP exports above contain
# simplified contour guides rather than the dense landmark geometry.
DENSE_FACE_GUIDES = ("slight_down_dense.png", "slight_up_dense.png")


EDGES = [(0, 1), (1, 2), (2, 3), (0, 4), (4, 5), (5, 6), (0, 7), (7, 8), (8, 9), (9, 10), (10, 11), (10, 12), (7, 13), (13, 14), (14, 15), (15, 16), (15, 17)]


def render(name: str, points: list[tuple[int, int]]) -> None:
    elements = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{SIZE[0]}" height="{SIZE[1]}" viewBox="0 0 {SIZE[0]} {SIZE[1]}">', '<rect width="100%" height="100%" fill="black"/>']
    for index, (start, end) in enumerate(EDGES):
        x1, y1 = points[start]
        x2, y2 = points[end]
        elements.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{COLORS[index]}" stroke-width="18" stroke-linecap="round"/>')
    for index, point in enumerate(points):
        radius = 14 if index not in {11, 12, 16, 17} else 11
        elements.append(f'<circle cx="{point[0]}" cy="{point[1]}" r="{radius}" fill="{COLORS[index]}" stroke="black" stroke-width="4"/>')
    elements.append("</svg>")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    svg_path = OUTPUT / f"{name}.svg"
    png_path = OUTPUT / f"{name}.png"
    svg_path.write_text("\n".join(elements) + "\n", encoding="utf-8")
    subprocess.run(["convert", str(svg_path), str(png_path)], check=True)


def main() -> None:
    for name, points in POSES.items():
        render(name, points)
    source_root = ROOT / "runtime" / "manual" / "comfyui-gpu" / "input" / "references" / "pose" / "300w_lp"
    FACE_OUTPUT.mkdir(parents=True, exist_ok=True)
    for name, relative_source in FACE_SOURCES.items():
        source = source_root / relative_source
        target = FACE_OUTPUT / f"{name}.png"
        if source.is_file():
            shutil.copyfile(source, target)
        elif not target.is_file():
            raise SystemExit(f"missing face pose source and packaged guide: {source}")
    for filename in DENSE_FACE_GUIDES:
        target = FACE_OUTPUT / filename
        if not target.is_file():
            raise SystemExit(f"missing packaged dense face pose guide: {target}")


if __name__ == "__main__":
    main()
