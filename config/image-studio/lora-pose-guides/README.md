# LoRA pose guides

This directory contains reusable ControlNet guide images for character LoRA datasets.

- `face/` contains the six guides used by the node-generated face LoRA workflow: neutral and smiling front views, left and right three-quarter views, and slight up/down views.
- `face/three_quarter_left_dense.png` is an exact single-pose crop from the dense facial-landmark reference sheet and is the active left three-quarter guide.
- `face/three_quarter_right_dense.png` is the matching exact crop and is the active right three-quarter guide. Left/right labels use the subject's anatomical direction, so the subject's left points toward the viewer's right and vice versa.
- `body/` contains a six-view reference pack for externally prepared upper-torso/body datasets: front, left and right three-quarter, left and right profile, and back views. Hexe exposes this catalog but does not generate upper-torso LoRA datasets on-node.

Run `scripts/generate-lora-pose-guides.py` to regenerate the deterministic body guides. If local 300W-LP control exports are available, the script also refreshes the packaged face guides from them.

Editable staged prompt catalogs live at `config/image-studio/face-lora-prompts.json` and
`config/image-studio/body-lora-prompts.json`. They are the active runtime source for
face/body LoRA pose prompts, variations, guide mappings, and prompt-specific negatives.
Set `HEXE_IMAGE_STUDIO_FACE_LORA_PROMPTS_PATH` or
`HEXE_IMAGE_STUDIO_BODY_LORA_PROMPTS_PATH` to load an alternate catalog path.
