# LoRA pose guides

This directory contains reusable ControlNet guide images for character LoRA datasets.

- `face/` contains the four active guides used by the node-generated face LoRA workflow: neutral and smiling front views plus left and right three-quarter views. Experimental vertical-angle assets remain available but are not part of the active dataset catalog.
- `face/three_quarter_left_dense.png` is an exact single-pose crop from the dense facial-landmark reference sheet and is the active left three-quarter guide.
- `face/three_quarter_right_dense.png` is the matching exact crop and is the active right three-quarter guide. Left/right labels use the subject's anatomical direction, so the subject's left points toward the viewer's right and vice versa.
- `face/slight_up_dense.png` and `face/slight_down_dense.png` are exact centered crops from the same dense facial-landmark sheet and are the active vertical-angle guides.
- `face/depth-source/` contains clean rendered head crops. The pitch-sensitive face workflow converts these RGB sources with Depth Anything V2 and applies depth guidance for the full short Lightning sampling window; vertical poses use depth instead of the ambiguous facial OpenPose guide.
- `body/` contains the six-view OpenPose pack for node-generated body LoRA datasets: front, left and right three-quarter, left and right profile, and back views. The body workflow combines these guides with Depth Anything guidance derived from the approved body reference, uses independent candidate seeds, and does not apply face PuLID conditioning.

Run `scripts/generate-lora-pose-guides.py` to regenerate the deterministic body guides. If local 300W-LP control exports are available, the script also refreshes the packaged face guides from them.

Editable staged prompt catalogs live at `config/image-studio/face-lora-prompts.json` and
`config/image-studio/body-lora-prompts.json`. They are the active runtime source for
face/body LoRA pose prompts, variations, guide mappings, and prompt-specific negatives.
Set `HEXE_IMAGE_STUDIO_FACE_LORA_PROMPTS_PATH` or
`HEXE_IMAGE_STUDIO_BODY_LORA_PROMPTS_PATH` to load an alternate catalog path.
