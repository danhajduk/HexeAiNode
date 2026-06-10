# ComfyUI Simple Avatar Generation Workflow

Status: Implemented in `config/comfyui/templates/avatar-body-depth-reference-transparent-realvisxl/api_workflow.json`.

The active ComfyUI template catalog contains only `template.avatar_body_depth_reference_transparent.realvisxl.v1`, displayed in the node UI as `Simple Avatar Generation`. The older prompt-only, img2img, scene, avatar-reference, avatar-identity, and non-transparent depth template files were removed to keep manual avatar testing focused on the PuLID identity plus Depth Anything ControlNet path.

## Purpose

This workflow generates a new transparent avatar image from a prompt, a face reference, and a body reference. It applies the face image through PuLID identity conditioning, then resizes and pads the body image to the requested output aspect ratio, extracts a Depth Anything V2 map, and applies SDXL depth ControlNet during sampling.

PuLID owns face/ID preservation, while the body reference controls pose, silhouette, and proportions. This is stronger than the older latent-only face reference path, but it is still not a trained identity LoRA or a true pose-from-text model.

## Pipeline

1. Load `RealVisXL_V5.0_fp16.safetensors`.
2. Apply `sdxl_lightning_4step_lora.safetensors`.
3. Create an empty latent canvas.
4. Encode positive and negative prompts.
5. Load the face reference and apply PuLID to the model with `face_strength` as the identity weight.
6. Load the body reference, resize and pad it to the output aspect ratio.
7. Run `DepthAnythingV2Preprocessor`.
8. Load `controlnet-depth-sdxl-1.0-fp16.safetensors`.
9. Apply `ControlNetApplyAdvanced` with `body_depth_strength`, `body_depth_start`, and `body_depth_end`.
10. Sample with the PuLID-patched model, decode, save an RGB fallback, remove the background, join alpha, and save the transparent PNG.

## Runtime Inputs

Required variables:

- `positive_prompt`
- `face_reference_image`
- `body_reference_image`

Common tuning variables:

- `face_strength`
- `pulid_fidelity`
- `pulid_start_at`
- `pulid_end_at`
- `body_depth_strength`
- `body_depth_start`
- `body_depth_end`
- `depth_resolution`
- `negative_prompt`
- `avatar_name`
- `width`
- `height`
- `seed`
- `steps`
- `cfg`
- `denoise`

Default output is `768x1152`, 4 steps, CFG `1.2`, denoise `1.0`, PuLID face strength `0.8`, PuLID fidelity `8`, and body depth strength `0.75`.

## Required Models And Nodes

- Checkpoint: `RealVisXL_V5.0_fp16.safetensors`
- LoRA: `sdxl_lightning_4step_lora.safetensors`
- PuLID model: `runtime/models/comfyui-gpu/pulid/ip-adapter_pulid_sdxl_fp16.safetensors`
- InsightFace model: `runtime/models/comfyui-gpu/insightface/models/antelopev2`
- ControlNet: `controlnet-depth-sdxl-1.0-fp16.safetensors`
- Depth preprocessor model: `depth_anything_v2_vits.pth`
- Background-removal model: `birefnet.safetensors`
- Custom nodes: `PuLID_ComfyUI` nodes (`PulidModelLoader`, `PulidEvaClipLoader`, `PulidInsightFaceLoader`, `ApplyPulidAdvanced`), `ResizeAndPadImage`, `DepthAnythingV2Preprocessor`, `ControlNetLoader`, `ControlNetApplyAdvanced`, `LoadBackgroundRemovalModel`, `RemoveBackground`, `InvertMask`, `JoinImageWithAlpha`, and `SaveImage`.

Build/rebuild the ComfyUI image after this template change so the packaged PuLID custom nodes are linked into the persistent runtime custom-node folder. Download the GPU PuLID assets with:

```bash
scripts/comfyui-control.sh gpu download-pulid
```

## Output

The template saves both outputs under the selected ComfyUI runtime output folder:

```text
hexe/avatar_body_depth_transparent/{{avatar_name}}_seed{{seed}}_rgb
hexe/avatar_body_depth_transparent/{{avatar_name}}_seed{{seed}}
```

The `_rgb` file is a fallback for background-removal OOM or node failure. If the transparent output is written successfully, the node cleans up the `_rgb` file and its LoRA sidecars from manual output listings.

## Manual Progress Status

The manual image status API exposes `latest_job.progress_detail` and mirrors it into
`generation_status.progress_detail` for the node UI. The detail payload includes the
current phase, readable node label, ComfyUI node id and class, queue counts, elapsed
time, update age, message, and failure reason when available.

Known node labels include PuLID identity loading/application, body depth map
generation, depth ControlNet application, sampling, VAE decode, background removal,
alpha joining, and output saving. If ComfyUI restarts or is OOM-killed after a manual
job is submitted and before an output is created, the job is marked `failed` with
`failure_reason: comfyui_runtime_oom` or `comfyui_runtime_restarted`.

Before submitting a new manual job, the node asks an idle ComfyUI queue to unload
models and free memory. This preflight cleanup is skipped when the queue is already
running or pending prompts.
