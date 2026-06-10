# ComfyUI Simple Avatar Generation Workflow

Status: Implemented in `config/comfyui/templates/avatar-head-face-preview-realvisxl/api_workflow.json`, `config/comfyui/templates/avatar-body-depth-reference-transparent-realvisxl/api_workflow.json`, `config/comfyui/templates/avatar-profile-depth-pulid-realvisxl/api_workflow.json`, and `config/comfyui/templates/avatar-lustify-sdxl-inpaint/api_workflow.json`.

The active ComfyUI template catalog contains `template.avatar_head_face_preview.realvisxl.v1`, displayed as `Avatar Head Face Preview`; `template.avatar_body_depth_reference_transparent.realvisxl.v1`, displayed in the node UI as `Simple Avatar Generation`; `template.avatar_profile_depth_pulid.realvisxl.v1`, displayed as `Avatar Profile Generation`; `template.avatar_lustify_sdxl_inpaint.v1`, displayed as `Avatar Clothing Inpaint`; and `template.avatar_base_unclothed_lustify_inpaint.v1`, displayed as `Avatar Base Unclothed Inpaint`. The older prompt-only, img2img, scene, avatar-reference, avatar-identity, and non-transparent depth template files were removed to keep manual avatar testing focused on profile prompt previews, PuLID identity plus SDXL depth ControlNet paths, and the explicit masked inpaint pass.

## Purpose

This workflow generates a new transparent avatar image from a prompt, a face reference, and a body reference. It applies the face image through PuLID identity conditioning, then resizes and pads the body image to the requested output aspect ratio, extracts a Depth Anything V2 map, and applies SDXL depth ControlNet during sampling.

PuLID owns face/ID preservation, while the body reference controls pose, silhouette, and proportions. This is stronger than the older latent-only face reference path, but it is still not a trained identity LoRA or a true pose-from-text model.

`Avatar Head Face Preview` is the quick head/face workspace preview path. It samples a `512x512`, 4-step RealVisXL portrait from the current prompt and first saves an RGB image under `hexe/avatar_head_face_preview/*_rgb`. When that RGB file appears, the node unloads ComfyUI generation models through `/free`, submits a small second-pass BiRefNet background-removal workflow, joins the alpha mask, and saves the transparent preview under `hexe/avatar_head_face_preview/`.

`Avatar Profile Generation` is the preferred final-generation path after an avatar profile has a body depth profile. It uses the profile's selected PuLID face image, a saved `refs/body_depth_map/*` depth map, and a saved `refs/pose/*` OpenPose or pose-control image directly, which avoids rerunning Depth Anything during each final image generation and lets the selected pose image guide the composition.

`Avatar Clothing Inpaint` is a manual second-pass workflow for changing the masked area of an existing avatar image. It loads `lustifySDXLNSFW_v20-inpainting.safetensors`, reads the selected source image from `input_image`, reads a separate `mask_image` with `LoadImageMask`, encodes the image with `VAEEncodeForInpaint`, samples the masked area, and saves the result under `hexe/avatar_lustify_inpaint/`. The mask should match the source image dimensions; white pixels are repainted and black pixels are preserved. This template intentionally does not run background removal.

`Avatar Base Unclothed Inpaint` is a simpler local preset for creating a private synthetic-adult base avatar from the generated image `avatar_seed2923980995547288489_rgb_00001_.png`. The source image is copied into the manual ComfyUI input folder as:

```text
references/avatar/avatar_seed2923980995547288489_rgb_00001_source.png
```

The prepared black/white mask is:

```text
references/avatar/avatar_seed2923980995547288489_unclothed_mask.png
```

The mask repaints the bodysuit, straps, ankle straps, and heels, while preserving the face, hair, arms, legs, pose, and background outside the mask. Outputs are saved under `hexe/avatar_base_unclothed/`.

The same preset is also stored as a full ComfyUI Web UI canvas workflow in
`config/comfyui/templates/avatar-base-unclothed-lustify-inpaint/ui_workflow.json`.
For live tweaking in the ComfyUI Web UI, copy that file into:

```text
runtime/manual/comfyui-gpu/user/default/workflows/Avatar Base Unclothed Inpaint.json
```

The Web UI workflow exposes the source image, mask image, positive and negative
prompts, mask growth, seed behavior, steps, CFG, sampler, scheduler, denoise, and
save prefix as normal ComfyUI widgets.

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

- `positive_prompt` for all prompt-driven avatar templates, including `Avatar Head Face Preview`
- `face_reference_image`
- `body_reference_image` for `Simple Avatar Generation`
- `body_depth_image` for `Avatar Profile Generation`
- `pose_reference_image` for `Avatar Profile Generation`
- `input_image` and `mask_image` for `Avatar Clothing Inpaint`
- `source_image` and `mask_image` for `Avatar Base Unclothed Inpaint`

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
- `mask_channel`
- `grow_mask_by`
- `sampler_name`
- `scheduler`

Default output is `768x1152`, 4 steps, CFG `1.2`, denoise `1.0`, PuLID face strength `0.8`, PuLID fidelity `8`, and body depth strength `0.75`.

`Avatar Clothing Inpaint` defaults to 24 steps, CFG `6`, denoise `0.72`, `dpmpp_2m` with `karras`, `mask_channel: red`, and `grow_mask_by: 8`. Start lower on denoise when preserving the original body is more important; raise denoise when the clothing prompt is being ignored.

`Avatar Base Unclothed Inpaint` defaults to the same baseline as the ComfyUI Web UI workflow: 32 steps, CFG `7.5`, denoise `0.9`, `dpmpp_2m` with `karras`, `mask_channel: red`, and `grow_mask_by: 20`. Reduce denoise if the inpaint changes too much of the silhouette; raise it only if the garment remains visible.

The Avatar Generation profile detail page includes a `Generation` tab that assembles prompt sections from the saved extraction and face profile. Operators can choose the template, PuLID face reference, body depth map, body reference, pose control image, prompt sections for identity/face/hair/body/pose/clothing/accessories/scene/style, negative prompt, sampler settings, batch count, seed randomization, face/body/pose strengths, strength jitter, and LoRA metadata sidecar output. Submissions are sent through `POST /api/manual-image-generation`.

## Avatar Profiles

The node UI includes an `Avatar Generation` menu with two tabs: `Create Profile`
and `Saved Profiles`. Profile creation starts with typed character basics:
character name, gender, skin color, hair color, character type (`human`,
`humanlike`, or `non-human`), visual style (`cartoon`, `manga`,
`stylized-realistic`, or `real`), and an NSFW boolean. This first step does not
upload source images, generate assets, or run vision extraction.

```text
runtime/manual/comfyui-gpu/input/avatar_profiles/<avatar_name>/
```

Each saved profile writes `profile.json`. Metadata-only profiles intentionally omit
`face_image`, `body_image`, and ComfyUI input paths until later reference assets
are added through the profile detail tabs. Saved profile cards support selecting,
opening, and deleting profiles without requiring extracted image data first.
Profile creation also derives and stores `general_prompt`, a reusable baseline
ComfyUI prompt built from the saved character facts. The `Head / Face` workspace
is seeded from this general prompt at creation time.

Opening a profile shows the baseline facts captured during creation and staged
design tabs: `Head / Face`, `Upper Torso`, `Lower Torso`, and `Full Body`.
`Head / Face` is the first active workspace. It stores
`prompt_workspaces.head_face` in `profile.json`, including the current ComfyUI
prompt, editable `prompt_parts` such as `general`, `hair`, `nose`, `cheeks`,
`expression`, and `style_lighting`, negative prompt, local-LLM conversation
history, and preview request history.

`POST /api/avatar-generation/profiles/{profile_id}/head-face/refine` sends the
current head/face prompt plus the user's adjustment request to the local LLM. The
LLM returns updated prompt JSON, and the node persists both the prompt and the
conversation. `POST /api/avatar-generation/profiles/{profile_id}/head-face/previews`
submits `template.avatar_head_face_preview.realvisxl.v1` through the manual
ComfyUI runtime as a quick `512x512`, 4-step preview and records the prompt id,
template id, seed, prompt snapshot, and negative prompt in preview history. The
profile keeps only the latest 9 head/face preview history entries. When the
ComfyUI output file appears, the node copies it into
`avatar_profiles/<profile_id>/refs/head_face/preview/` and updates the preview
history entry with the profile-local `input_image` and API `url`. If the output
is still missing, the node writes a profile-local SVG placeholder in the same
folder and replaces it with the real PNG when the ComfyUI output becomes
available.

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

The legacy API can still extract a combined face profile with
`POST /api/avatar-generation/profiles/{profile_id}/face/extract`, but the node UI
no longer presents image extraction as part of profile creation. When called
directly, the endpoint sends selected face references to the vision runtime, asks
the local LLM to merge the observations into reusable identity JSON, stores the
result under `face_profile`, and mirrors the prompt-ready face fields into
`extraction.structured`. Face-profile extraction refuses to run while the manual
ComfyUI Web UI/session or GPU ComfyUI runtime is active, because those GPU
workloads cannot coexist with the vision runtime.

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

The legacy body-depth preprocessing API can submit a lightweight ComfyUI job with
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
- Inpaint checkpoint: `runtime/models/comfyui-gpu/checkpoints/lustifySDXLNSFW_v20-inpainting.safetensors`
- Custom nodes: `PuLID_ComfyUI` nodes (`PulidModelLoader`, `PulidEvaClipLoader`, `PulidInsightFaceLoader`, `ApplyPulidAdvanced`), `ResizeAndPadImage`, `DepthAnythingV2Preprocessor`, `ControlNetLoader`, `ControlNetApplyAdvanced`, `LoadBackgroundRemovalModel`, `RemoveBackground`, `InvertMask`, `JoinImageWithAlpha`, and `SaveImage`.

The Lustify inpaint checkpoint is hosted at `andro-flock/LUSTIFY-SDXL-NSFW-checkpoint-v2-0-INPAINTING` and the required file is `lustifySDXLNSFW_v20-inpainting.safetensors`.

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
hexe/avatar_lustify_inpaint/{{avatar_name}}_seed{{seed}}
hexe/avatar_base_unclothed/{{avatar_name}}_seed{{seed}}
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
