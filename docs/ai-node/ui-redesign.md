# AI-Node UI Redesign

Last updated: 2026-03-19

## Purpose

Document the post-identity AI-Node UI structure after the Phase 3 frontend redesign.

This redesign follows the local Core references in:

- [node-phase2-lifecycle-contract.md](/home/dan/hexe/HexeAiNode/docs/Core-Documents/nodes/node-phase2-lifecycle-contract.md)
- [node-capability-activation-architecture.md](/home/dan/hexe/HexeAiNode/docs/Core-Documents/nodes/node-capability-activation-architecture.md)

## UI Modes

The frontend now has three explicit UI modes:

1. Identity
   - preserved initial node-name / Core-endpoint screen
   - rendered by [IdentityScreen.jsx](/home/dan/hexe/HexeAiNode/frontend/src/features/node-ui/IdentityScreen.jsx)

2. Setup
   - guided onboarding and readiness flow
   - rendered through [SetupModeView.jsx](/home/dan/hexe/HexeAiNode/frontend/src/features/setup/SetupModeView.jsx)
   - shell lives in [SetupShell.tsx](/home/dan/hexe/HexeAiNode/frontend/src/features/setup/SetupShell.tsx)

3. Operational
   - dashboard-first runtime view for `operational` and `degraded`
   - rendered through [OperationalDashboard.jsx](/home/dan/hexe/HexeAiNode/frontend/src/features/operational/OperationalDashboard.jsx)

Mode resolution remains centralized in:

- [uiModeResolver.ts](/home/dan/hexe/HexeAiNode/frontend/src/features/node-ui/uiModeResolver.ts)

## Route Layout

Canonical route helpers live in:

- [uiRoutes.ts](/home/dan/hexe/HexeAiNode/frontend/src/features/node-ui/uiRoutes.ts)

Supported routes:

- `#/`
- `#/setup`
- `#/setup/provider/openai`
- `#/dashboard`
- `#/dashboard/capabilities`
- `#/dashboard/runtime`
- `#/dashboard/activity`
- `#/dashboard/diagnostics`

## Header Layout

The shared page header now follows a simple two-row structure:

- row 1: `Hexe AI Node` title on the left and lifecycle status pill on the right
- row 2: theme control on the left and utility actions on the right

Secondary metadata stays compact beneath that header instead of dominating the page.

## Setup Flow

Setup mode keeps stage-focused content and grouped actions:

- current step actions
- secondary actions
- reset and recovery actions

The setup page now uses a split layout:

- left rail: setup progress
- right column: setup complete banner when present, node setup summary pills, and the active setup shell content

When onboarding reaches an operational-ready state while the user is still on the setup route, the UI now shows a deliberate completion handoff instead of forcing an abrupt dashboard jump.

## Operational Dashboard

Operational mode now separates information by primary home:

- health strip: lifecycle, trust, runtime connectivity, telemetry summary
- overview: identity and trusted pairing summary
- capabilities: provider, usable model, blocked model, and feature summary
- runtime: runtime health and service state
- activity: onboarding progress and recent events
- diagnostics: advanced payloads and admin maintenance

Degraded nodes remain in the dashboard and show a contextual warning banner with direct links into setup and diagnostics.

## Diagnostics Placement

Diagnostics now live only on the dedicated diagnostics route. The default overview no longer renders raw capability payloads or admin rebuild controls.

The diagnostics page lives in:

- [DiagnosticsPage.tsx](/home/dan/hexe/HexeAiNode/frontend/src/features/diagnostics/DiagnosticsPage.tsx)

## Shared Component Rules

Shared status and severity primitives live in:

- [uiPrimitives.jsx](/home/dan/hexe/HexeAiNode/frontend/src/components/uiPrimitives.jsx)

Rules:

- use shared severity wrappers for status/health/stage badges
- use grouped action sections instead of mixed button rows
- use chip lists with expand/collapse for long capability lists

## Action Grouping Rules

Setup actions:

- current step actions
- supporting actions
- reset/recovery actions

Operational actions:

- configuration and sync actions
- runtime restart controls

Admin actions:

- advanced maintenance stays on the diagnostics page
- diagnostics separates routine sync actions from rebuild/admin actions

## Status Badge Conventions

- `success`: operational, running, trusted, connected, ready
- `warning`: degraded, pending, bootstrap/setup transitional states
- `danger`: failed, blocked, offline, disconnected
- `meta`: configured, selected, available, informational labels

## Image Studio

Image creation is moving into a standalone workspace at `#/image-studio`.

- the operational navigation opens Image Studio in a separate named browser window
- creation begins by choosing Character, Location, or Scene
- Character then branches into Create New Character, Use Existing Character, or Edit Character Image before template selection
- template selection is filtered by that creation type
- Create New Character provides a structured identity brief, compiled master prompt, negative prompt, and an eight-stage interview whose local text LLM checks prose answers and asks focused follow-ups for missing visual details
- LLM review is stage-scoped and advisory: each stage also provides Continue anyway so model failure or an unwanted follow-up cannot block the interview
- the first interview stage requires gender, visual style, age group, and SFW/NSFW rating; NSFW is limited to characters explicitly marked Adult (18+)
- the first interview stage can persist its identity data as an incomplete avatar profile; Step 3 lists these drafts as clickable cards and resumes each at its first unfinished interview section
- draft saves update the Image Studio profile list directly from the save response and do not block on a full node-wide status refresh
- the standalone Image Studio owns a three-request data boundary for templates, service status, and character profiles; it does not start the dashboard status refresh fan-out
- the Face & Features interview stage provides grouped selectable traits for facial structure, skin, eyes, hair, facial hair, and distinctive details, plus a custom-details field and live combined description
- interview selectors use compact pictograms and color swatches inside a wide desktop dialog, with a responsive single-column layout on narrow screens
- face shape, eye shape, nose, and lip choices use locally generated image thumbnails inside each option button; the face interview uses a two-column feature-and-preview workspace
- every character-interview screen can save the incomplete profile; Check, Continue, and Finish persist the current answers before advancing
- the face workspace can submit a real head/face preview and shows the resulting image with live generation, queue, node, runtime, model, VRAM, prompt, and seed status
- after the approved face and body references, dedicated Face LoRA and Body LoRA dataset stages each generate ten controlled candidates for six OpenPose-guided views; the face stage retains the approved face seed as the identity anchor while deriving a stable sampling seed per candidate, the body stage reuses the approved body seed and prompt, and operators approve at least six candidates before advancing each pose
- the Body LoRA stage retains 768×1536 neck-to-toes framing, displays the approved body reference above the pose review, and keeps candidate images blurred until explicitly revealed
- Body & Proportions uses structured height, build, shoulder, torso, waist, hip, limb, and musculature selections, then requires one neutral 768×1536 neck-to-toes preview with the head and face outside the frame. The compiled prompt prioritizes a distant extreme-long-shot composition, while the pose guide places the neck beyond the top canvas edge, enforces a symmetrical front-facing neutral A-pose, and keeps the complete feet and toes inside visible margins. Pose conditioning ends before the final sampling phase so selected body morphology can control the silhouette; the body seed is saved before continuing
- each successfully imported body preview also refreshes `<profile>/refs/upper_torso/last.png` and its JSON sidecar as a stable pointer to the latest body image
- body Generate/Redo removes the previous `last.png`, sidecar, and `current_job.json` before submission; after ComfyUI accepts the request, `<profile>/refs/upper_torso/current_job.json` becomes the popup's authoritative record, the UI falls back to the placeholder while active, and successful import recreates `last.png` as the displayed preview
- each body-preview submission uses a unique ComfyUI output prefix, so Redo with a retained seed cannot be imported into an older pending preview that shares the same seed
- resuming an incomplete character restores both the saved face-feature and body-feature catalog selections, custom details, and combined descriptions
- when Image Studio opens, the face workspace restores the newest completed saved preview; a newly submitted job keeps that prior image visible until its replacement is ready
- face previews use a structured identity-reference prompt; after a preview returns, its seed can be locked and the local text LLM can apply a targeted prompt adjustment before regenerating with that same seed
- all face-feature buttons retain short labels in the UI but save descriptive prompt language for age, facial structure, skin, eyes, brows, nose, lips, hair, distinctive features, and facial hair
- incomplete character data includes a structured face-feature catalog containing selected option IDs, custom details, the expanded description, and the appended LLM refinement layer; preview prompts enforce exactly one face and repeat the selected face shape as a primary weighted constraint
- active face previews poll a lightweight generation-activity endpoint that omits the full manual output/reference inventory scan, so completed images and status updates are not blocked by a large output directory
- generation progress dialogs bind status, sampler progress, messages, and prompt labels to the submitted preview prompt ID; an older cached, completed, or failed global job cannot overwrite the active face/body popup state
- preview placeholders record a distinct creation time and are never reported as imported files; the popup exposes an import timestamp only after the final non-placeholder image is present
- imported body previews are blurred by default in both the body workspace and generation popup, require an explicit click to reveal, hide the full-image link until revealed, and automatically return to the blurred state for each new prompt ID
- the body-generation popup exposes editable pose strength, start, and end values for Redo; values are constrained to `0–1`, the start must not exceed the end, and the effective controls are saved with each preview
- each newly completed face preview publishes one `user.message` event to `hexe/events/user/message` with `endpoint_id: "all"`, QoS 1, and retain disabled; the persisted preview records successful delivery to prevent polling from republishing it
- final new-character generation remains gated until the required baseline face/body identity assets can be created or supplied
- the existing Manual Images implementation remains available as `Manual Images (Legacy)` during migration
- existing runtime references, profiles, and generated outputs are not migrated or deleted by the new shell
