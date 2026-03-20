# AI-Node UI Redesign

Last updated: 2026-03-19

## Purpose

Document the post-identity AI-Node UI structure after the Phase 3 frontend redesign.

This redesign follows the local Core references in:

- [node-phase2-lifecycle-contract.md](/home/dan/Projects/SynthiaAiNode/docs/Core-Documents/nodes/node-phase2-lifecycle-contract.md)
- [node-capability-activation-architecture.md](/home/dan/Projects/SynthiaAiNode/docs/Core-Documents/nodes/node-capability-activation-architecture.md)

## UI Modes

The frontend now has three explicit UI modes:

1. Identity
   - preserved initial node-name / Core-endpoint screen
   - rendered by [IdentityScreen.jsx](/home/dan/Projects/SynthiaAiNode/frontend/src/features/node-ui/IdentityScreen.jsx)

2. Setup
   - guided onboarding and readiness flow
   - rendered through [SetupModeView.jsx](/home/dan/Projects/SynthiaAiNode/frontend/src/features/setup/SetupModeView.jsx)
   - shell lives in [SetupShell.tsx](/home/dan/Projects/SynthiaAiNode/frontend/src/features/setup/SetupShell.tsx)

3. Operational
   - dashboard-first runtime view for `operational` and `degraded`
   - rendered through [OperationalDashboard.jsx](/home/dan/Projects/SynthiaAiNode/frontend/src/features/operational/OperationalDashboard.jsx)

Mode resolution remains centralized in:

- [uiModeResolver.ts](/home/dan/Projects/SynthiaAiNode/frontend/src/features/node-ui/uiModeResolver.ts)

## Route Layout

Canonical route helpers live in:

- [uiRoutes.ts](/home/dan/Projects/SynthiaAiNode/frontend/src/features/node-ui/uiRoutes.ts)

Supported routes:

- `#/`
- `#/setup`
- `#/setup/provider/openai`
- `#/dashboard`
- `#/dashboard/capabilities`
- `#/dashboard/runtime`
- `#/dashboard/activity`
- `#/dashboard/diagnostics`

## Setup Flow

Setup mode keeps stage-focused content and grouped actions:

- current step actions
- secondary actions
- reset and recovery actions

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

- [DiagnosticsPage.tsx](/home/dan/Projects/SynthiaAiNode/frontend/src/features/diagnostics/DiagnosticsPage.tsx)

## Shared Component Rules

Shared status and severity primitives live in:

- [uiPrimitives.jsx](/home/dan/Projects/SynthiaAiNode/frontend/src/components/uiPrimitives.jsx)

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
