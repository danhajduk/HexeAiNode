# Hexe AI Node Standard Alignment Task List

Last Updated: 2026-04-04 US/Pacific

## Purpose

This document tracks the work required to bring `HexeAiNode` into explicit alignment with the Hexe Node Standard under:

- `/home/dan/Projects/Hexe/docs/standards/Node/`

This is a repo-specific alignment task list for `HexeAiNode`, not a platform-wide standard document.

## Overall Assessment

`HexeAiNode` is already strong on:

- modular backend structure
- modular backend domain separation
- scripts baseline
- test coverage depth
- capability/governance/readiness implementation depth

The biggest gaps are not foundational architecture gaps. They are mostly:

- documentation alignment gaps
- standards-to-repo mapping gaps
- frontend modularity cleanup gaps
- provider-boundary documentation gaps
- scheduler/background-task visibility and documentation gaps
- runtime-path and operational naming normalization gaps

## Alignment Principles

Use these principles while executing this task list:

- preserve the existing modular backend structure
- avoid unnecessary rewrites of working runtime code
- prefer explicit standards mapping over speculative refactors
- keep repo-specific docs in this repo and shared standards in Hexe Core docs
- treat compact or legacy areas as candidates for targeted cleanup, not blanket rewrites

## Priority Order

1. Standards mapping and documentation alignment
2. Frontend modularity cleanup
3. Provider-boundary and scheduler-boundary clarity
4. Runtime-path and operations normalization
5. Formal repo compliance appendix and verification

## Phase 1. Create Standards Mapping Inside This Repo

### Goal

Make it obvious how this repo maps to the Hexe Node Standard.

### Tasks

- Add a new repo-local standards alignment overview doc that maps this repo to:
  - core node model
  - backend standard
  - API standard
  - frontend standard
  - onboarding/trust/readiness standard
  - scripts/operations standard
  - scheduler/background-task standard
  - persistence/config/security standard
  - provider boundary standard
  - testing/documentation requirements
- Update [index.md](/home/dan/Projects/HexeAiNode/docs/index.md) to include:
  - repo-specific standards alignment entrypoint
  - repo-specific provider-boundary documentation
  - repo-specific scheduler/background-task documentation
- Update [README.md](/home/dan/Projects/HexeAiNode/docs/README.md) so the documentation policy explicitly points to the Hexe node standards set, not only the older Core-Documents symlink guidance.
- Add a repo-specific compliance summary doc for this node that answers:
  - aligned already
  - partially aligned
  - not yet aligned

### Why this matters

The repo is close to the standard structurally, but that alignment is not easy to verify from docs today.

## Phase 2. Add Repo-Specific Provider Boundary Documentation

### Goal

Make the current provider model explicit in repo docs.

### Tasks

- Create a dedicated repo doc describing this node’s provider boundary:
  - what is node-generic
  - what is provider-specific
  - where provider-specific code lives
  - how provider setup fits into post-trust setup
  - how provider intelligence and model enablement affect capability declaration
- Document current provider modules under:
  - `src/ai_node/providers/`
  - `src/ai_node/runtime/provider_*`
  - `src/ai_node/config/provider_*`
- Document which APIs are provider-specific versus node-generic.
- Document the current OpenAI-specific implementation as:
  - one provider implementation
  - not the definition of the node itself

### Why this matters

The code already has a provider boundary, but the repo docs do not currently present it as a first-class standard-alignment concept.

## Phase 3. Add Repo-Specific Scheduler And Background-Task Documentation

### Goal

Make recurring work and scheduler-adjacent behavior explicit and operator-readable.

### Tasks

- Create a repo doc describing current recurring and long-lived runtime work:
  - provider refresh loop behavior
  - status telemetry behavior
  - capability/governance-related refresh behavior
  - scheduler lease integration behavior
  - startup timeout and connectivity monitors
- Document which recurring work is:
  - node-local recurring work
  - lease-based Core-scheduled execution compatibility work
  - provider-specific refresh behavior
- Document current persisted scheduler-like state and status surfaces.
- Document which recurring work affects readiness and which does not.

### Why this matters

The repo implements multiple recurring or long-lived runtime behaviors, but they are spread across runtime docs and code rather than documented as one scheduler/background-task story.

## Phase 4. Tighten Frontend Modularity

### Goal

Bring the frontend closer to the modular-first standard.

### Tasks

- Audit [App.jsx](/home/dan/Projects/HexeAiNode/frontend/src/App.jsx) and identify domains that still need extraction into:
  - setup
  - operational
  - diagnostics
  - provider management
  - shared status/state formatting helpers
- Move remaining large inline UI/domain logic out of `App.jsx` into feature modules where that improves ownership clarity.
- Move reusable formatting, status mapping, and UI-state derivation logic into dedicated feature or shared modules where still mixed into the top-level app.
- Add or extend frontend tests for any extracted modules so the modular split is verifiable.

### Why this matters

The frontend is already partly modular, but the top-level app still carries too much coordination and domain-specific UI logic for the target standard.

## Phase 5. Tighten API Documentation Against The Standard

### Goal

Make the repo API easier to review against the Hexe node API standard.

### Tasks

- Produce a repo API map grouped by standard route families:
  - health
  - node status/bootstrap/config
  - onboarding
  - capability configuration and declaration
  - governance/readiness
  - provider-specific routes
  - service control
  - runtime/task execution routes
- Mark which routes are canonical for this repo and which are compatibility or convenience routes.
- Add explicit notes for any route family that differs from the preferred standard namespace.
- Link the repo API map from [index.md](/home/dan/Projects/HexeAiNode/docs/index.md).

### Why this matters

The repo has strong API functionality and tests, but it does not yet present its API surface in the same grouped shape as the Hexe node standard.

## Phase 6. Normalize Runtime Path And State Documentation

### Goal

Make mutable state and runtime path ownership explicit.

### Tasks

- Update repo docs to explicitly explain the current split between:
  - `.run/`
  - `data/`
  - `logs/`
- Document why the repo currently uses `.run/` instead of the template-style `runtime/` root.
- Decide whether to:
  - keep current runtime paths and document them as an allowed variant
  - or introduce a migration plan toward a more standardized runtime directory layout
- Document which files are:
  - operator config or bootstrap config
  - trusted identity or trust state
  - capability state
  - governance state
  - provider state
  - diagnostics artifacts

### Why this matters

The repo is already state-rich, but the standard expects state ownership and runtime paths to be easy to understand.

## Phase 7. Tighten Scripts And Operations Alignment

### Goal

Bring repo operations closer to the scripts/operations standard.

### Tasks

- Add a lightweight `status.sh` helper or explicitly document why `stack-control.sh status` is the standard status path for this repo.
- Audit current script names and docs for consistency with the standard operations vocabulary.
- Document the current systemd template naming and any remaining compatibility-era naming in one place.
- Ensure [operations.md](/home/dan/Projects/HexeAiNode/docs/operations.md) clearly maps:
  - bootstrap
  - run-from-env
  - stack control
  - restart
  - logs
  - service units

### Why this matters

The repo already has a strong script baseline, so this is mostly a clarity and consistency task rather than a structural change.

## Phase 8. Tighten Security And Sensitive-State Documentation

### Goal

Make sensitive-state handling easier to review against the standard.

### Tasks

- Expand repo docs around:
  - trust tokens
  - provider credentials
  - debug capture paths
  - masked versus unmasked state
- Document the boundaries for:
  - safe API summaries
  - safe logs
  - diagnostics artifacts that may contain sensitive data
- Cross-check repo docs against the actual security/redaction helpers under:
  - `src/ai_node/security/`

### Why this matters

The repo appears to implement safe handling in code, but the standards alignment should be visible in docs too.

## Phase 9. Tighten Formal Compliance Evidence

### Goal

Make standards compliance auditable for this repo.

### Tasks

- Create a repo-local appendix mapping current code/modules to the standard’s formal compliance checklist sections.
- For each major standards file, record:
  - aligned
  - partially aligned
  - follow-up required
- Link evidence to actual repo locations where helpful:
  - backend modules
  - frontend modules
  - scripts
  - tests
  - docs
- Add a final “not yet aligned” list for any remaining work after the above phases.

### Why this matters

This repo is likely close to compliant already, but without an appendix the alignment remains implicit.

## Suggested File Deliverables In This Repo

- `docs/ai-node-standards-alignment.md`
- `docs/provider-boundary.md`
- `docs/scheduler-and-background-tasks.md`
- `docs/api-map.md`
- `docs/runtime-state-map.md`
- `docs/ai-node-standard-compliance-appendix.md`

These file names may be adjusted, but the deliverables themselves should exist.

## Work That Is Probably Not Needed Right Now

- full backend architectural rewrite
- major package relocation
- replacing the existing modular backend with a new layout
- rewriting all API routes to a new namespace immediately
- replacing all runtime paths immediately without a migration reason

## Acceptance Criteria

This repo can be considered aligned to the Hexe node standard when:

- repo docs clearly map to the standard
- provider boundary is documented clearly
- scheduler/background-task behavior is documented clearly
- API groups are documented in standard shape
- runtime-state ownership is documented clearly
- frontend modularity gaps have a concrete cleanup pass
- scripts/operations behavior is clearly documented against the standard
- compliance evidence exists in a repo-local appendix
