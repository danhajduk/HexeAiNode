# AI-Node UI Redesign Audit

Last updated: 2026-03-19

## Scope

This audit covers the current AI-Node frontend after the initial identity screen and documents the existing UI structure that will be reshaped for the redesign tasks.

Relevant implementation files:

- [App.jsx](/home/dan/Projects/HexeAiNode/frontend/src/App.jsx)
- [uiStateModel.js](/home/dan/Projects/HexeAiNode/frontend/src/uiStateModel.js)
- [api.js](/home/dan/Projects/HexeAiNode/frontend/src/api.js)
- [uiPrimitives.jsx](/home/dan/Projects/HexeAiNode/frontend/src/components/uiPrimitives.jsx)
- [main.jsx](/home/dan/Projects/HexeAiNode/frontend/src/main.jsx)

## Current Route Structure

The current frontend does not use a router library.

Implemented route handling today:

- `#/`
  - default single-page dashboard and onboarding surface
- `#/providers/openai`
  - dedicated provider-management page for OpenAI credentials, model selection, pricing, and resolved capability preview

Route state is stored in local component state:

- `routeHash` in [App.jsx](/home/dan/Projects/HexeAiNode/frontend/src/App.jsx)
- hash changes are observed through a `hashchange` listener

There is no explicit route separation for:

- setup flow
- operational dashboard
- diagnostics
- service/admin tools

Those concerns are instead conditionally rendered inside the same top-level component.

## Current Component Tree

Current runtime tree is shallow but very large:

- `main.jsx`
  - `App`
    - optional pricing modal overlay
    - optional hero/header card
    - one of:
      - provider setup page shell
      - unconfigured setup screen
      - mixed lifecycle/dashboard grid

Shared presentational components:

- `ThemeToggle`
- `CardHeader`
- `StatusBadge`
- `HealthIndicator`

Everything else is inline inside [App.jsx](/home/dan/Projects/HexeAiNode/frontend/src/App.jsx).

Major UI sections currently embedded in `App`:

- global hero/header
- initial identity setup screen
- provider setup page
- lifecycle card
- onboarding progress card
- capability setup form
- runtime health card
- core connection card
- capability summary card
- resolved node capabilities card
- service controls card
- admin capability diagnostics card
- generic diagnostics disclosure card
- modal pricing editor

## Current State Sources

Primary raw state in `App`:

- `backendStatus`
- `pendingApprovalUrl`
- `nodeId`
- `mqttHost`
- `nodeName`
- `providerCredentials`
- `openaiCatalogModels`
- `openaiModelCapabilities`
- `enabledOpenaiModelIds`
- `resolvedOpenaiCapabilities`
- `openaiModelFeatures`
- `resolvedNodeCapabilities`
- `latestOpenaiModels`
- `capabilityDiagnostics`
- local UI flags for saving, refreshing, restarting, popup state, copied state, etc.

Derived dashboard state:

- `uiState = buildDashboardUiState(...)` from [uiStateModel.js](/home/dan/Projects/HexeAiNode/frontend/src/uiStateModel.js)

Additional inline derived render logic in `App`:

- `isUnconfigured`
- `isPendingApproval`
- `isCapabilitySetupPending`
- `isProviderSetupRoute`
- `hasCapabilityRegistration`
- `canManageOpenAiCredentials`
- `showCorePanel`
- `usableResolvedModelIds`
- `blockedResolvedModels`
- `resolvedNodeTasks`
- pricing and feature helper maps

Important current behavior:

- lifecycle-to-mode resolution is scattered
- hash route state and lifecycle state are mixed together
- setup/operations/diagnostics are not modeled as separate UI layers

## Current Data Flow Summary

### Polling

The page performs one large polling fan-out every 7 seconds from `loadStatus()` in [App.jsx](/home/dan/Projects/HexeAiNode/frontend/src/App.jsx).

Requests made together:

- `/api/node/status`
- `/api/governance/status`
- `/api/providers/config`
- `/api/providers/openai/credentials`
- `/api/providers/openai/models/catalog`
- `/api/providers/openai/models/capabilities`
- `/api/providers/openai/models/enabled`
- `/api/providers/openai/models/latest?limit=200`
- `/api/providers/openai/capability-resolution`
- `/api/providers/openai/models/features`
- `/api/capabilities/node/resolved`
- `/api/capabilities/config`
- `/api/services/status`
- `/api/capabilities/diagnostics` via admin token path

Those results are then split into:

- raw component state setters
- one normalized `uiState` object for summary cards

### Mutation Flow

The same component also owns all write actions:

- onboarding start
- onboarding restart
- provider enablement save
- task family selection save
- capability declare
- provider model refresh
- OpenAI credential save
- OpenAI model preference save
- enabled-model toggle
- manual pricing save
- service restart
- admin diagnostics actions

Mutation handlers usually call `loadStatus()` after success and sometimes after failure.

### API Base Resolution

The API base is resolved centrally in [api.js](/home/dan/Projects/HexeAiNode/frontend/src/api.js):

- `VITE_API_BASE` if set
- otherwise `${window.location.protocol}//${window.location.hostname}:9002`

## Current Setup-Related Components/Sections

Setup-related UI currently includes:

- initial identity setup screen
  - shown when `backendStatus === "unconfigured"`
- onboarding progress card
- pending approval CTA in the hero area
- capability setup form
  - shown when `backendStatus === "capability_setup_pending"`
- provider setup page at `#/providers/openai`

Setup concerns currently mixed together:

- onboarding lifecycle
- provider credentials
- task-family selection
- capability declaration
- model discovery
- pricing remediation

## Current Operational / Dashboard-Related Components

Operational/dashboard concerns currently shown in the default grid:

- lifecycle card
- runtime card
- core connection card
- capability summary card
- resolved node capabilities card
- service controls card

These are shown not only for `operational` and `degraded`, but for most non-`unconfigured` states because the default render branch is shared.

## Current Diagnostics / Admin Components

Diagnostics/admin concerns currently rendered on the same page as normal operations:

- admin capability diagnostics card
- generic diagnostics disclosure card
- copy diagnostics action
- admin actions:
  - refresh provider models
  - recompute deterministic catalog
  - recompute capability graph
  - redeclare capabilities to Core

Diagnostics visibility is controlled only by presence of loaded diagnostics data, not by a dedicated diagnostics route or mode.

## API Dependencies

Read endpoints currently used:

- `GET /api/node/status`
- `GET /api/governance/status`
- `GET /api/providers/config`
- `GET /api/providers/openai/credentials`
- `GET /api/providers/openai/models/catalog`
- `GET /api/providers/openai/models/capabilities`
- `GET /api/providers/openai/models/enabled`
- `GET /api/providers/openai/models/latest?limit=200`
- `GET /api/providers/openai/capability-resolution`
- `GET /api/providers/openai/models/features`
- `GET /api/capabilities/node/resolved`
- `GET /api/capabilities/config`
- `GET /api/services/status`
- `GET /api/capabilities/diagnostics`

Write/admin endpoints currently used:

- `POST /api/onboarding/initiate`
- `POST /api/onboarding/restart`
- `POST /api/providers/config`
- `POST /api/capabilities/config`
- `POST /api/services/restart`
- `POST /api/capabilities/declare`
- `POST /api/capabilities/providers/refresh`
- `POST /api/providers/openai/credentials`
- `POST /api/providers/openai/preferences`
- `POST /api/providers/openai/models/enabled`
- `POST /api/providers/openai/pricing/manual`
- `POST /api/providers/openai/models/classification/refresh`
- `POST /api/capabilities/rebuild`
- `POST /api/capabilities/redeclare`

## Current Pain Points / Duplication

### Structural pain points

- One large `App.jsx` owns nearly all state, data fetching, mutation logic, and rendering.
- Setup UI, dashboard UI, provider management UI, and diagnostics UI are interleaved instead of separated.
- The provider page is the only route-like split, but it is still tightly coupled to the same global state and polling model.

### Mode-resolution pain points

- UI mode is inferred through multiple booleans instead of a canonical resolver.
- `backendStatus` drives major layout branches directly.
- route hash can override layout independently of lifecycle state.
- degraded state is not treated as its own operational mode; it falls into the same large branch as everything after `unconfigured`.

### Data-flow pain points

- One poll cycle fetches both primary operational data and advanced diagnostics every 7 seconds.
- Expensive or verbose data sets are loaded even when not needed for the main user task.
- `uiStateModel` normalizes part of the surface, but large parts of render logic still depend on raw payload shapes.

### UX pain points

- The default dashboard remains cluttered with setup, operational, and diagnostics concerns at once.
- Setup actions are spread between the hero card, onboarding card, capability summary card, provider page, and diagnostics actions.
- Diagnostics dominate the default page footprint relative to everyday operational information.
- Provider management is available only after capability registration, which creates an awkward dependency chain in the visible UI.

### Duplication pain points

- lifecycle/readiness concepts appear in both `uiState` and inline render booleans
- model/capability summaries are shown in both provider page and dashboard cards
- diagnostics include payloads that duplicate information already summarized elsewhere
- multiple handlers call `loadStatus()` after mutations rather than using narrower refresh ownership

## Reusable Components vs Components To Replace

### Reusable

- [api.js](/home/dan/Projects/HexeAiNode/frontend/src/api.js)
  - central fetch helpers and API base resolution are reusable
- [uiStateModel.js](/home/dan/Projects/HexeAiNode/frontend/src/uiStateModel.js)
  - useful starting point for normalized runtime summaries, though it should be narrowed to the new mode boundaries
- [uiPrimitives.jsx](/home/dan/Projects/HexeAiNode/frontend/src/components/uiPrimitives.jsx)
  - `CardHeader`, `StatusBadge`, `HealthIndicator`
- initial identity form content in [App.jsx](/home/dan/Projects/HexeAiNode/frontend/src/App.jsx)
  - preserve structure and behavior, but extract into its own screen/shell
- provider setup data/actions
  - reusable logic, but should move under a setup feature module instead of living in the top-level page

### Replace or Extract

- [App.jsx](/home/dan/Projects/HexeAiNode/frontend/src/App.jsx)
  - should be split into mode shells and feature sections
- inline lifecycle/mode booleans
  - replace with a canonical UI mode resolver
- hash-based ad hoc navigation
  - replace with explicit mode-aware routing/navigation structure
- always-on diagnostics loading
  - move behind a diagnostics route/tab/panel with lazy loading
- mixed setup + operational dashboard grid
  - replace with separate setup and operational layouts

## Recommended Boundary For Redesign

The redesign should treat the current UI as three hidden products that were merged into one page:

- identity bootstrap screen
- setup workflow
- operational dashboard plus diagnostics tools

Task 292 should formalize those as distinct UI layers with a single resolver deciding which one is primary at any given time.
