# AI-Node UI Information Architecture

Last updated: 2026-03-19

## Purpose

Define the canonical UI information architecture for the AI-Node redesign after the initial identity screen.

This structure is aligned with:

- [node-phase2-lifecycle-contract.md](/home/dan/Projects/SynthiaAiNode/docs/Core-Documents/nodes/node-phase2-lifecycle-contract.md)
- [node-capability-activation-architecture.md](/home/dan/Projects/SynthiaAiNode/docs/Core-Documents/nodes/node-capability-activation-architecture.md)
- [phase-2.md](/home/dan/Projects/SynthiaAiNode/docs/ai-node/phase-2.md)
- [ui-redesign-audit.md](/home/dan/Projects/SynthiaAiNode/docs/ai-node/ui-redesign-audit.md)

## Canonical UI Layers

The frontend must expose exactly three primary UI layers:

1. Identity
   - preserves the current initial node-name / Core-endpoint setup screen
   - used only before trusted onboarding has begun or when setup is explicitly reset

2. Setup
   - guided, stage-based onboarding and readiness flow
   - used for all unfinished onboarding and post-trust setup states
   - focused on progression, blockers, retries, and operator actions needed to reach readiness

3. Operational
   - dashboard-first runtime view
   - used for `operational` and `degraded`
   - diagnostics are available from here, but do not dominate the primary surface

## Route / State Map

The app should separate:

- primary UI mode
- in-mode navigation
- diagnostics visibility

Recommended route model:

- `#/`
  - primary entry
  - resolves automatically to `identity`, `setup`, or `operational`
- `#/setup`
  - explicit setup entry
  - allowed when trust/onboarding exists or when a setup-capable state is active
- `#/dashboard`
  - explicit operational dashboard entry
  - preferred default for `operational` and `degraded`
- `#/dashboard/capabilities`
  - operational capabilities view
- `#/dashboard/runtime`
  - runtime and service view
- `#/dashboard/activity`
  - activity / recent actions / future telemetry-oriented page
- `#/dashboard/diagnostics`
  - advanced diagnostics page or tab
- `#/setup/provider/openai`
  - optional deep-link into the provider stage content

Recommended mode resolution precedence:

1. explicit manual diagnostics/dashboard route if allowed by current mode
2. explicit setup route if setup mode is valid
3. automatic mode resolution from node/runtime state

## Canonical Mode Resolver Boundary

Mode resolution must use a single resolver, not scattered inline checks.

Implementation note:

- the current canonical resolver lives in [uiModeResolver.ts](/home/dan/Projects/SynthiaAiNode/frontend/src/features/node-ui/uiModeResolver.ts)
- canonical route helpers live in [uiRoutes.ts](/home/dan/Projects/SynthiaAiNode/frontend/src/features/node-ui/uiRoutes.ts)
- current resolver coverage lives in [uiModeResolver.test.ts](/home/dan/Projects/SynthiaAiNode/frontend/src/features/node-ui/uiModeResolver.test.ts)
- rendering coverage lives in [uiRendering.test.tsx](/home/dan/Projects/SynthiaAiNode/frontend/src/features/node-ui/uiRendering.test.tsx)

Resolver outputs:

- `identity`
- `setup`
- `operational`

Resolver inputs should include:

- lifecycle state from `/api/node/status`
- node-local setup readiness payload from `/api/node/status.capability_setup`
- Core-readiness summary when available
- current manual route intent

Canonical mapping:

### Identity

Show identity mode when:

- lifecycle is `unconfigured`
- or trusted onboarding state is missing and initial setup is required

### Setup

Show setup mode when onboarding or post-trust readiness is incomplete, including:

- `bootstrap_connecting`
- `bootstrap_connected`
- `core_discovered`
- `registration_pending`
- `pending_approval`
- `trusted`
- `capability_setup_pending`
- `capability_declaration_in_progress`
- `capability_declaration_failed_retry_pending`
- cases where node-local setup gating is incomplete even if lifecycle is still in a transitional post-trust state

### Operational

Show operational mode when:

- lifecycle is `operational`
- lifecycle is `degraded`

Important rule:

- `degraded` remains operational mode, not setup mode

Core/readiness rule:

- Core `operational_ready` is the canonical readiness projection when available
- node-local `capability_setup` fields remain the canonical operator-facing setup gating details

## Setup vs Operational Boundary

### Setup Owns

- onboarding progression
- registration / approval guidance
- trust activation confirmation
- provider configuration
- capability declaration readiness
- governance sync and readiness blockers
- finish / continue / retry actions

### Operational Owns

- current lifecycle and health summary
- runtime health indicators
- capability summary
- resolved usable vs blocked model summary
- service status and restart controls
- ongoing activity / execution visibility
- diagnostics entry points

### Not Allowed

- operational dashboard cards inside setup mode
- setup stepper/timeline inside operational mode as the dominant layout
- advanced diagnostics on the default setup or dashboard surface

If onboarding history is shown in operational mode, it must be compact and secondary.

## Page Hierarchy

### Identity Layer

- `IdentityScreen`
  - preserve existing node-name / Core-endpoint form
  - submit onboarding start
  - no operational dashboard content
  - current implementation lives in [IdentityScreen.jsx](/home/dan/Projects/SynthiaAiNode/frontend/src/features/node-ui/IdentityScreen.jsx)

### Setup Layer

- `SetupShell`
  - setup header
  - setup status summary
  - stepper/timeline
  - active stage panel
  - stage-aware action footer
- `SetupModeView`
  - wraps setup shell and completion handoff state
  - current implementation lives in [SetupModeView.jsx](/home/dan/Projects/SynthiaAiNode/frontend/src/features/setup/SetupModeView.jsx)

Setup stage panels:

- `SetupCoreConnectionPanel`
- `SetupRegistrationPanel`
- `SetupApprovalPanel`
- `SetupTrustActivationPanel`
- `SetupProviderPanel`
- `SetupCapabilityDeclarationPanel`
- `SetupGovernancePanel`
- `SetupReadyPanel`

### Operational Layer

- `OperationalShell`
  - health/status strip
  - operational navigation
  - content outlet
- `OperationalDashboard`
  - route-aware operational page composition
  - current implementation lives in [OperationalDashboard.jsx](/home/dan/Projects/SynthiaAiNode/frontend/src/features/operational/OperationalDashboard.jsx)

Operational sections:

- `Overview`
- `Capabilities`
- `Runtime`
- `Activity`
- `Diagnostics`

Operational support components:

- [DegradedStateBanner.tsx](/home/dan/Projects/SynthiaAiNode/frontend/src/features/operational/DegradedStateBanner.tsx)
- [OperationalActionsCard.tsx](/home/dan/Projects/SynthiaAiNode/frontend/src/features/operational/cards/OperationalActionsCard.tsx)
- [CompactChipList.tsx](/home/dan/Projects/SynthiaAiNode/frontend/src/features/operational/cards/CompactChipList.tsx)

## Setup Stage Model

Setup mode should present a canonical stage sequence:

1. Node Identity
2. Core Connection
3. Bootstrap Discovery
4. Registration
5. Approval
6. Trust Activation
7. AI Provider Setup
8. Capability Declaration
9. Governance Sync
10. Ready

Stage behavior rules:

- one active stage at a time
- previous stages may show completed state
- future stages may show pending/locked state
- stage text should be concise and user-oriented, not raw backend payloads

## Diagnostics Placement Rules

Diagnostics are advanced tools and must be separated from the main flow.

Rules:

- diagnostics do not live on the default setup screen
- diagnostics do not occupy major space on the default operational overview
- diagnostics live under a dedicated route/tab/page in operational mode
- raw payloads must stay collapsed by default
- advanced admin actions belong inside diagnostics, not in the default dashboard

Allowed exceptions:

- setup panels may show short blocker text
- setup panels may expose expandable “advanced details” only when directly relevant to the active stage

## Action Grouping Rules

Actions must be grouped by user intent and current stage.

### Identity Actions

- start onboarding
- restart setup only when explicitly in reset flow

### Setup Actions

- continue
- retry
- save provider setup
- declare capabilities
- refresh governance
- reopen provider configuration

Rules:

- only show actions relevant to the active stage
- primary progression action should be visually clear
- reset/restart actions must be visually separated
- no global wall of actions in setup mode

### Operational Actions

- open setup / reconfigure
- restart services
- refresh operational views
- open diagnostics

Rules:

- reconfiguration is available but secondary
- destructive or disruptive actions are separated from normal operational controls

### Diagnostics Actions

- provider refresh
- classification refresh
- capability rebuild
- redeclare capabilities
- copy diagnostics

Rules:

- admin/debug actions live only in diagnostics
- labels must explain the action clearly

## Component Ownership Rules

### App-Level Ownership

`App` should own only:

- top-level route intent
- resolved UI mode
- shared fetched node/runtime state
- global theme and global error boundary placement

### Feature Ownership

Identity feature owns:

- initial onboarding form
- identity-submit flow

Setup feature owns:

- setup shell
- stepper
- stage panels
- stage-aware action layout
- provider and capability setup flows

Current implementation references:

- [SetupShell.tsx](/home/dan/Projects/SynthiaAiNode/frontend/src/features/setup/SetupShell.tsx)
- [SetupStepper.tsx](/home/dan/Projects/SynthiaAiNode/frontend/src/features/setup/SetupStepper.tsx)
- [SetupStagePanels.jsx](/home/dan/Projects/SynthiaAiNode/frontend/src/features/setup/SetupStagePanels.jsx)

Operational feature owns:

- operational shell
- overview/capabilities/runtime/activity pages
- top health strip
- operational navigation

Current implementation references:

- [OperationalShell.tsx](/home/dan/Projects/SynthiaAiNode/frontend/src/features/operational/OperationalShell.tsx)
- [NodeHealthStrip.tsx](/home/dan/Projects/SynthiaAiNode/frontend/src/features/operational/NodeHealthStrip.tsx)
- [NodeOverviewCard.tsx](/home/dan/Projects/SynthiaAiNode/frontend/src/features/operational/cards/NodeOverviewCard.tsx)
- [CapabilitySummaryCard.tsx](/home/dan/Projects/SynthiaAiNode/frontend/src/features/operational/cards/CapabilitySummaryCard.tsx)
- [ResolvedTasksCard.tsx](/home/dan/Projects/SynthiaAiNode/frontend/src/features/operational/cards/ResolvedTasksCard.tsx)
- [RuntimeServicesCard.tsx](/home/dan/Projects/SynthiaAiNode/frontend/src/features/operational/cards/RuntimeServicesCard.tsx)
- [RecentActivityCard.tsx](/home/dan/Projects/SynthiaAiNode/frontend/src/features/operational/cards/RecentActivityCard.tsx)
- [DiagnosticsPage.tsx](/home/dan/Projects/SynthiaAiNode/frontend/src/features/diagnostics/DiagnosticsPage.tsx)
- [uiPrimitives.jsx](/home/dan/Projects/SynthiaAiNode/frontend/src/components/uiPrimitives.jsx)

Diagnostics feature owns:

- debug/admin data loading
- raw payload views
- advanced refresh/redeclare actions

### Data Ownership Rules

- shared baseline status fetch can remain centralized initially
- diagnostics fetching should become lazy and diagnostics-owned
- mode resolver should consume normalized state, not raw JSX-local booleans
- route decisions must not be embedded in individual panels

## Transition Rules

### Automatic Transitions

- `identity -> setup`
  - after successful onboarding initiation
  - current implementation also normalizes the root hash to `#/setup`
- `setup -> operational`
  - when runtime resolves to `operational` or `degraded`
  - current implementation normalizes the root hash to `#/dashboard`
- `operational -> setup`
  - only when operator explicitly reopens reconfiguration, or when lifecycle truly returns to a non-operational setup state

### Manual Transitions

- operational users may open setup safely for reconfiguration
- operational users may open diagnostics directly
- setup users should not be dropped into operational mode unless state allows it

## Immediate Implementation Guidance

Tasks 293 and later should implement this IA in this order:

1. add canonical UI mode resolver
2. preserve identity screen and route it through the resolver
3. build `SetupShell`
4. build setup stepper and stage panels
5. build `OperationalShell`
6. move diagnostics behind operational diagnostics navigation

## Acceptance Standard

The redesign IA is considered correctly implemented when:

- initial identity screen remains intact
- setup states render a setup-first experience
- `operational` and `degraded` render an operational dashboard, not a wizard
- diagnostics are separated from the default runtime view
- all major rendering decisions flow through one canonical mode resolver
