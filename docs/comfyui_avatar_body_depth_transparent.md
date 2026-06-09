# ComfyUI Avatar Body Depth Transparent Workflow

Status: Implemented in `config/comfyui/templates/avatar-body-depth-reference-transparent-realvisxl/api_workflow.json`.

The active ComfyUI template catalog contains only `template.avatar_body_depth_reference_transparent.realvisxl.v1`. The older prompt-only, img2img, scene, avatar-reference, avatar-identity, and non-transparent depth template files were removed to keep manual avatar testing focused on the Depth Anything plus ControlNet path.

## Purpose

This workflow generates a new transparent avatar image from a prompt, a face reference, and a body reference. It uses the face image as weak identity conditioning through `ReferenceLatent`, then resizes and pads the body image to the requested output aspect ratio, extracts a Depth Anything V2 map, and applies SDXL depth ControlNet during sampling.

The body reference controls pose, silhouette, and proportions more strongly than the older latent-only templates, but it is still not a trained identity LoRA or a true pose-from-text model.

## Pipeline

1. Load `RealVisXL_V5.0_fp16.safetensors`.
2. Apply `sdxl_lightning_4step_lora.safetensors`.
3. Create an empty latent canvas.
4. Encode positive and negative prompts.
5. Load and scale the face reference, encode it, and attach it to positive conditioning.
6. Load the body reference, resize and pad it to the output aspect ratio.
7. Run `DepthAnythingV2Preprocessor`.
8. Load `controlnet-depth-sdxl-1.0-fp16.safetensors`.
9. Apply `ControlNetApplyAdvanced` with `body_depth_strength`, `body_depth_start`, and `body_depth_end`.
10. Sample, decode, save an RGB fallback, remove the background, join alpha, and save the transparent PNG.

## Runtime Inputs

Required variables:

- `positive_prompt`
- `face_reference_image`
- `body_reference_image`

Common tuning variables:

- `face_strength`
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

Default output is `768x1152`, 4 steps, CFG `1.2`, denoise `1.0`, face strength `0.8`, and body depth strength `0.75`.

## Required Models And Nodes

- Checkpoint: `RealVisXL_V5.0_fp16.safetensors`
- LoRA: `sdxl_lightning_4step_lora.safetensors`
- ControlNet: `controlnet-depth-sdxl-1.0-fp16.safetensors`
- Depth preprocessor model: `depth_anything_v2_vits.pth`
- Background-removal model: `birefnet.safetensors`
- Custom nodes: `ReferenceLatent`, `ConditioningAverage`, `ResizeAndPadImage`, `DepthAnythingV2Preprocessor`, `ControlNetLoader`, `ControlNetApplyAdvanced`, `LoadBackgroundRemovalModel`, `RemoveBackground`, `InvertMask`, `JoinImageWithAlpha`, and `SaveImage`.

## Output

The template saves both outputs under the selected ComfyUI runtime output folder:

```text
hexe/avatar_body_depth_transparent/{{avatar_name}}_seed{{seed}}_rgb
hexe/avatar_body_depth_transparent/{{avatar_name}}_seed{{seed}}
```

The `_rgb` file is a fallback for background-removal OOM or node failure. If the transparent output is written successfully, the node cleans up the `_rgb` file and its LoRA sidecars from manual output listings.
