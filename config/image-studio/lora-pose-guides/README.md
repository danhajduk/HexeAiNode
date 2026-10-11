# LoRA pose guides

This directory contains reusable ControlNet guide images for character LoRA datasets.

- `face/` contains the six guides used by the node-generated face LoRA workflow: neutral and smiling front views, left and right three-quarter views, and slight up/down views.
- `body/` contains a six-view reference pack for externally prepared upper-torso/body datasets: front, left and right three-quarter, left and right profile, and back views. Hexe exposes this catalog but does not generate upper-torso LoRA datasets on-node.

Run `scripts/generate-lora-pose-guides.py` to regenerate the deterministic body guides. If local 300W-LP control exports are available, the script also refreshes the packaged face guides from them.

Editable staged prompt catalogs live at `config/image-studio/face-lora-prompts.json` and
`config/image-studio/body-lora-prompts.json`. They mirror the current hard-coded runtime
behavior but are intentionally not loaded by the backend yet (`runtime_enabled: false`).
