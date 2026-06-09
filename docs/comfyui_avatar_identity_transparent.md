# ComfyUI Avatar Identity Transparent Workflow

Status: Implemented in `config/comfyui/templates/avatar-identity-reference-transparent-realvisxl/api_workflow.json`.

This workflow is a ComfyUI API-format template for generating a new transparent avatar image from text prompts plus one face reference image and one body reference image. It uses the SDXL RealVisXL checkpoint, the SDXL Lightning 4-step LoRA, ReferenceLatent conditioning, KSampler sampling, VAE decoding, background removal, alpha joining, and SaveImage output.

The template is registered in `config/comfyui/templates/catalog.json` as `template.avatar_identity_reference_transparent.realvisxl.v1`.

## Purpose

The workflow creates a new avatar composition rather than editing a source avatar image. The face and body images are encoded into latents and chained into the positive conditioning with `ReferenceLatent`, then the decoded result is post-processed into a transparent PNG.

It is intentionally not an InstantID, IPAdapter, or ControlNet workflow. `ReferenceLatent` provides weak reference-guided conditioning only. It is not robust face-ID or body-ID preservation, and its behavior depends on the ComfyUI node implementation and model support available in the selected runtime.

## Node Summary

| Node | Class | Purpose |
| --- | --- | --- |
| 1 | `CheckpointLoaderSimple` | Loads `RealVisXL_V5.0_fp16.safetensors`. |
| 2 | `LoraLoader` | Applies `sdxl_lightning_4step_lora.safetensors` to the checkpoint model and CLIP. |
| 3 | `EmptyLatentImage` | Creates the new-composition canvas from `{{width}}` and `{{height}}`. |
| 4 | `CLIPTextEncode` | Encodes `{{positive_prompt}}`. |
| 5 | `CLIPTextEncode` | Encodes `{{negative_prompt}}`. |
| 6 | `LoadImage` | Loads `{{face_reference_image}}`. |
| 7 | `ImageScale` | Scales the face reference to the target dimensions. |
| 8 | `VAEEncode` | Encodes the scaled face reference into a latent. |
| 9 | `ReferenceLatent` | Applies face reference latent conditioning to the positive prompt conditioning. |
| 10 | `LoadImage` | Loads `{{body_reference_image}}`. |
| 11 | `ImageScale` | Scales the body reference to the target dimensions. |
| 12 | `VAEEncode` | Encodes the scaled body reference into a latent. |
| 13 | `ReferenceLatent` | Applies body reference latent conditioning after the face reference conditioning. |
| 14 | `KSampler` | Samples the avatar using Euler, `sgm_uniform`, `{{seed}}`, `{{steps}}`, and `{{cfg}}`. |
| 15 | `VAEDecode` | Decodes the sampled latent into an image. |
| 17 | `LoadBackgroundRemovalModel` | Loads `{{bg_removal_model}}`. |
| 18 | `RemoveBackground` | Produces a foreground/background mask from the decoded image. |
| 20 | `InvertMask` | Inverts the background-removal mask for alpha use. |
| 19 | `JoinImageWithAlpha` | Joins the decoded image with the inverted mask as alpha. |
| 16 | `SaveImage` | Saves the final transparent image. |

## Required Runtime Inputs

The raw template preserves these placeholders as strings:

- `{{width}}`
- `{{height}}`
- `{{positive_prompt}}`
- `{{negative_prompt}}`
- `{{face_reference_image}}`
- `{{body_reference_image}}`
- `{{seed}}`
- `{{steps}}`
- `{{cfg}}`
- `{{bg_removal_model}}`
- `{{avatar_name}}`

When rendered for ComfyUI submission, the node runtime can coerce whole-placeholder values for `width`, `height`, `seed`, `steps`, and `cfg` to numeric values. The template file itself keeps the double-brace placeholders unchanged.

## Required Models And Nodes

- Checkpoint: `RealVisXL_V5.0_fp16.safetensors`
- LoRA: `sdxl_lightning_4step_lora.safetensors`
- Reference node: `ReferenceLatent`
- Background-removal nodes:
  - `LoadBackgroundRemovalModel`
  - `RemoveBackground`
  - `InvertMask`
  - `JoinImageWithAlpha`

The catalog default background-removal model is `birefnet.safetensors`. The runtime must have that model available in the ComfyUI background-removal model path when using the default.

## Output

The SaveImage prefix is:

```text
hexe/avatar_identity_transparent/{{avatar_name}}_seed{{seed}}
```

ComfyUI writes the transparent PNG under the `hexe/avatar_identity_transparent/` output subdirectory for the selected runtime output folder.

## Lightning Configuration

This workflow is configured around SDXL Lightning 4-step LoRA behavior:

- sampler: `euler`
- scheduler: `sgm_uniform`
- recommended default steps: `4`
- recommended default CFG: around `1.0` unless the calling app overrides it

The catalog currently defaults this template to 4 steps and a CFG value suitable for the node UI/runtime, but callers can pass explicit allowed overrides where the API path permits them.
