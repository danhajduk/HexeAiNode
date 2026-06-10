# ComfyUI Simple Avatar Generation Workflow

Status: Implemented in `config/comfyui/templates/avatar-body-depth-reference-transparent-realvisxl/api_workflow.json` and `config/comfyui/templates/avatar-profile-depth-pulid-realvisxl/api_workflow.json`.

The active ComfyUI template catalog contains `template.avatar_body_depth_reference_transparent.realvisxl.v1`, displayed in the node UI as `Simple Avatar Generation`, and `template.avatar_profile_depth_pulid.realvisxl.v1`, displayed as `Avatar Profile Generation`. The older prompt-only, img2img, scene, avatar-reference, avatar-identity, and non-transparent depth template files were removed to keep manual avatar testing focused on PuLID identity plus SDXL depth ControlNet paths.

## Purpose

This workflow generates a new transparent avatar image from a prompt, a face reference, and a body reference. It applies the face image through PuLID identity conditioning, then resizes and pads the body image to the requested output aspect ratio, extracts a Depth Anything V2 map, and applies SDXL depth ControlNet during sampling.

PuLID owns face/ID preservation, while the body reference controls pose, silhouette, and proportions. This is stronger than the older latent-only face reference path, but it is still not a trained identity LoRA or a true pose-from-text model.

`Avatar Profile Generation` is the preferred final-generation path after an avatar profile has a body depth profile. It uses the profile's selected PuLID face image, a saved `refs/body_depth_map/*` depth map, and a saved `refs/pose/*` OpenPose or pose-control image directly, which avoids rerunning Depth Anything during each final image generation and lets the selected pose image guide the composition.

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
- `body_reference_image` for `Simple Avatar Generation`
- `body_depth_image` for `Avatar Profile Generation`
- `pose_reference_image` for `Avatar Profile Generation`

Common tuning variables:

- `face_strength`
- `pulid_fidelity`
- `pulid_start_at`
- `pulid_end_at`
- `body_depth_strength`
- `body_depth_start`
- `body_depth_end`
- `pose_strength`
- `pose_start`
- `pose_end`
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

The Avatar Generation profile detail page includes a `Generation` tab that assembles prompt sections from the saved extraction and face profile. Operators can choose the template, PuLID face reference, body depth map, body reference, pose control image, prompt sections for identity/face/hair/body/pose/clothing/accessories/scene/style, negative prompt, sampler settings, batch count, seed randomization, face/body/pose strengths, strength jitter, and LoRA metadata sidecar output. Submissions are sent through `POST /api/manual-image-generation`.

## Avatar Profiles

The node UI includes an `Avatar Generation` menu with two tabs: `Create Profile`
and `Saved Profiles`. Profile creation stores one face image, one body image, an
editable character description, and the character name under the manual ComfyUI
input folder:

```text
runtime/manual/comfyui-gpu/input/avatar_profiles/<avatar_name>/
```

Each saved profile writes `profile.json`, a face image, and a body image. The JSON
includes ComfyUI input paths such as `avatar_profiles/<avatar_name>/face.png` and
`avatar_profiles/<avatar_name>/body.png`, so later body-depth, pose, and final-avatar
flows can reuse the profile assets without mixing them into normal operation output.

Saved profile cards support selecting the active profile, deleting the profile, and
extracting reusable profile data. Extraction reads the saved face and body images,
sends each one to the local vision runtime for detailed observations, then sends the
combined observations plus any manual description to the local LLM. The local LLM
returns structured JSON stored under `profile.json` as `extraction.structured` for
future prompt assembly. If the local LLM request times out or fails, extraction
falls back to a vision-only schema `2.0` profile and records the fallback reason
under `source_quality_notes`.

The extracted profile schema is versioned as `2.0` and separates stable identity
from editable generation choices:

- `permanent_identity`
- `body_profile`
- `removable_clothing`
- `accessories`
- `pose_reference`
- `preservation_notes`
- `prompt_sections`
- `negative_prompt_terms`

Extraction asks the vision runtime for dense face and body observations. The body
profile is expected to keep visible stable anatomy details, including shoulders,
torso, waist, hips, hands, fingers, legs, feet, bust/breasts, and buttocks/glutes,
while marking hidden or cropped traits as uncertain instead of inventing them.

The node normalizes the LLM output before saving it. `prompt_sections` is always
stored as a JSON object, and negative prompt terms that would erase normal anatomy
or identity, such as `no eyes`, `no face`, or `no hair`, are filtered out. Vision
and local LLM calls use the existing runtimes only when they are already available;
profile management does not start them implicitly.

Edited extraction data can be saved back through
`PUT /api/avatar-generation/profiles/{profile_id}/extraction`. The node runs the
edited JSON through the same schema normalizer before writing it to the profile.

Additional avatar analysis references can be uploaded under the selected profile
with `POST /api/avatar-generation/profiles/{profile_id}/references`. Supported
roles are `body_depth`, `body_depth_map`, `face`, and `pose`; files are stored in
`avatar_profiles/{profile_id}/refs/{role}/` and returned on the profile payload
under `references`.

The Face profile tab stores any number of `face` references. A saved face reference
can be marked as the PuLID primary with
`POST /api/avatar-generation/profiles/{profile_id}/face/primary`; the selected file
is exposed as `primary_face_reference_filename`, `primary_face_input_image`, and
`pulid_face_reference_image` on the profile payload. If no primary is selected,
PuLID falls back to the profile's original face image.

The same tab can extract a combined face profile with
`POST /api/avatar-generation/profiles/{profile_id}/face/extract`. The node sends
the selected face references to the vision runtime, asks the local LLM to merge the
observations into reusable identity JSON, stores the result under `face_profile`,
and mirrors the prompt-ready face fields into `extraction.structured`. Face-profile
extraction refuses to run while the manual ComfyUI Web UI/session or GPU ComfyUI
runtime is active, because those GPU workloads cannot coexist with the vision
runtime.

Face extraction keeps the full per-reference observations for review, but the
prompt fields are compacted before they are stored. If the local LLM merge fails,
the fallback now builds bounded `identity_prompt`, `face_prompt`, `hair_prompt`,
and `expression_prompt` fields from visible face traits instead of copying all raw
vision notes into the prompt. Body extraction also deduplicates repeated
preservation clauses, removes low-value health/damage/deformity loops, strips
markdown asterisks from body headings, normalizes malformed body-heading labels,
strips mixed-language fragments from prompt phrases, collapses awkward repeated
wording, and reduces generic leading `average` filler when a line already
contains more useful visible shape detail. The body
vision and local-LLM prompts ask for comparative silhouette language such as
shoulder-to-waist-to-hip ratio, torso-to-leg proportion, bust-waist-hip silhouette,
limb thickness, and occluded/uncertain markers instead of defaulting unclear
traits to `average`.

The Body Depth profile tab can submit a lightweight ComfyUI preprocessing job with
`POST /api/avatar-generation/profiles/{profile_id}/body-depth/generate`. For each
raw `body_depth` reference, the node runs:

```text
LoadImage -> ResizeAndPadImage -> RemoveBackground -> JoinImageWithAlpha
          -> SaveImage avatar_body_*.png
          -> DepthAnythingV2Preprocessor -> SaveImage avatar_body_depth_*.png
```

When the ComfyUI outputs appear, the node imports them back into the avatar
profile. The original raw body reference is replaced by a transparent
`avatar_body_*.png` reference with `background_removed: true`, while the generated
depth map is stored separately under `refs/body_depth_map/`. The profile JSON also
stores a `body_depth_profile` summary with status, generated count, body-reference
count, and depth-map count.

## Required Models And Nodes

- Checkpoint: `RealVisXL_V5.0_fp16.safetensors`
- LoRA: `sdxl_lightning_4step_lora.safetensors`
- PuLID model: `runtime/models/comfyui-gpu/pulid/ip-adapter_pulid_sdxl_fp16.safetensors`
- InsightFace model: `runtime/models/comfyui-gpu/insightface/models/antelopev2`
- ControlNet: `controlnet-depth-sdxl-1.0-fp16.safetensors`
- OpenPose ControlNet: `controlnet-openpose-sdxl-1.0.safetensors`
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
hexe/avatar_profile_generation/{{avatar_name}}_seed{{seed}}_rgb
hexe/avatar_profile_generation/{{avatar_name}}_seed{{seed}}
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
