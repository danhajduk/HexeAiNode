# ComfyUI Avatar Identity Transparent Workflow

Status: Implemented in `config/comfyui/templates/avatar-identity-reference-transparent-realvisxl/api_workflow.json`.

This workflow is a ComfyUI API-format template for generating a new transparent avatar image from a text prompt plus two reference images: one face reference and one body reference. It uses the SDXL RealVisXL checkpoint, the SDXL Lightning 4-step LoRA, ReferenceLatent conditioning, KSampler sampling, VAE decoding, background removal, alpha joining, and SaveImage output.

The template is registered in `config/comfyui/templates/catalog.json` as `template.avatar_identity_reference_transparent.realvisxl.v1`.

## Purpose

The workflow creates a new avatar composition rather than editing a source avatar image. Generation starts from an empty latent canvas, so the face and body images are not used as direct source pixels. Instead, they are scaled to the requested output dimensions, encoded into latents, and chained into the positive conditioning with `ReferenceLatent`. The decoded result is then post-processed into a transparent PNG.

It is intentionally not an InstantID, IPAdapter, or ControlNet workflow. `ReferenceLatent` provides weak reference-guided conditioning only. It is not robust face-ID or body-ID preservation, and its behavior depends on the ComfyUI node implementation and model support available in the selected runtime.

The workflow remains content-agnostic. Positive and negative prompt content must be supplied at runtime rather than hard-coded into the JSON template.

## Pipeline

1. Load the base SDXL checkpoint.
2. Apply the SDXL Lightning 4-step LoRA.
3. Create an empty latent canvas at the requested width and height.
4. Encode the positive and negative prompts through the LoRA-wrapped CLIP model.
5. Load, scale, VAE-encode, and attach the face reference image with `ReferenceLatent`.
6. Load, scale, VAE-encode, and chain the body reference image with a second `ReferenceLatent` node.
7. Run `KSampler` with the Lightning LoRA model, chained reference-conditioned positive conditioning, negative conditioning, and empty latent canvas.
8. Decode the sampled latent with the checkpoint VAE.
9. Load the background-removal model.
10. Remove the background from the decoded image.
11. Invert the generated mask.
12. Join the decoded RGB image with the alpha mask.
13. Save the transparent image under `hexe/avatar_identity_transparent/{{avatar_name}}_seed{{seed}}`.

## Node Summary

| Node | Class | Purpose |
| --- | --- | --- |
| 1 | `CheckpointLoaderSimple` | Loads `RealVisXL_V5.0_fp16.safetensors`. |
| 2 | `LoraLoader` | Applies `sdxl_lightning_4step_lora.safetensors` to the checkpoint model and CLIP. |
| 3 | `EmptyLatentImage` | Creates the new-composition canvas from `{{width}}`, `{{height}}`, and batch size `1`. Generation starts from noise rather than from either reference image directly. |
| 4 | `CLIPTextEncode` | Encodes `{{positive_prompt}}` with the CLIP output from the LoRA node. |
| 5 | `CLIPTextEncode` | Encodes `{{negative_prompt}}` with the same LoRA-wrapped CLIP. |
| 6 | `LoadImage` | Loads `{{face_reference_image}}`. |
| 7 | `ImageScale` | Scales the face reference to the target dimensions with Lanczos scaling and center crop. |
| 8 | `VAEEncode` | Encodes the scaled face reference into a latent. |
| 9 | `ReferenceLatent` | Applies face reference latent conditioning to the positive prompt conditioning. |
| 10 | `LoadImage` | Loads `{{body_reference_image}}`. |
| 11 | `ImageScale` | Scales the body reference to the target dimensions with Lanczos scaling and center crop. |
| 12 | `VAEEncode` | Encodes the scaled body reference into a latent. |
| 13 | `ReferenceLatent` | Applies body reference latent conditioning after the face reference conditioning. |
| 14 | `KSampler` | Samples the avatar using the model from node 2, positive conditioning from node 13, negative conditioning from node 5, empty latent from node 3, Euler, `sgm_uniform`, `{{seed}}`, `{{steps}}`, `{{cfg}}`, and denoise `1.0`. |
| 15 | `VAEDecode` | Decodes the sampled latent into an image. |
| 17 | `LoadBackgroundRemovalModel` | Loads `{{bg_removal_model}}`. |
| 18 | `RemoveBackground` | Runs background removal on the decoded image from node 15. |
| 20 | `InvertMask` | Inverts output 0 from node 18 for alpha use. This assumes the installed `RemoveBackground` node exposes a mask on output 0. |
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

The background-removal section depends on the exact custom nodes installed in the target ComfyUI environment. Confirm that `RemoveBackground` output 0 is a mask compatible with `InvertMask`. If output 0 is an image instead of a mask, the `InvertMask` and `JoinImageWithAlpha` section must be adjusted for that node implementation.

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

The catalog currently defaults this template to 4 steps and CFG `1.0`, but callers can pass explicit allowed overrides where the API path permits them.

## Limitations

This workflow does not perform true identity preservation. The face and body reference images are encoded as latents and attached using `ReferenceLatent`, which may influence the result but should not be treated as equivalent to InstantID, IPAdapter FaceID, PuLID, ReActor, or a trained character LoRA.

The body reference is not treated as a pose-control image. For stronger pose or body control, a future workflow should use OpenPose, Depth, Canny, or another ControlNet-style path.
