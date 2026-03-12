# Synthia AI Node - Phase 2 Review and Handoff

Status: Active
Last updated: 2026-03-11

## Scope Review

This review covers implemented Phase 2 behavior from trusted resume through capability activation readiness.

Reviewed implementation areas:

- trusted resume handoff
- provider selection and persistence
- capability declaration build/submit/acceptance
- accepted capability profile persistence
- governance sync and freshness tracking
- operational MQTT readiness gating
- trusted status telemetry
- degraded and deterministic recovery
- phase2 consolidated state persistence
- diagnostics/logging and validation checklist

## Verified Implemented Behavior

### 1) Trusted startup continuation

- Trusted nodes resume into `capability_setup_pending` without re-entering bootstrap onboarding.
- Startup now performs a readiness-based fast path check:
  - resumes to `operational` when accepted capability + fresh governance + operational MQTT readiness are already valid
  - otherwise remains in `capability_setup_pending`
- Startup context is exposed in control status payload for diagnostics.

### 2) Capability activation path

- Capability declaration is constructed from canonical task families, provider capabilities, node features, and environment hints.
- Submission to Core is explicit and stateful (`in_progress`, `accepted`, `failed_retry_pending`).
- Accepted response metadata is persisted and reused on restart.

### 3) Governance synchronization

- Baseline governance is synced after accepted capability declaration.
- Governance bundle is persisted with policy version, issued timestamp, sync time, refresh expectations, and baseline rule groups.
- Governance freshness is explicitly tracked as `fresh`, `stale`, or `unknown`.

### 4) Operational readiness and telemetry

- Operational MQTT readiness is verified with trust-issued operational credentials.
- Operational transition is blocked until readiness succeeds.
- Trusted status telemetry is published via operational MQTT channel, not bootstrap MQTT.

### 5) Degraded and recovery behavior

- Temporary failures in capability submit, governance sync, operational readiness, or telemetry publish can transition to `degraded`.
- Recovery path is explicit (`POST /api/node/recover`) and deterministic:
  - to `operational` when accepted capability + fresh governance + ready operational MQTT
  - otherwise to `capability_setup_pending`

### 6) Persisted Phase 2 state

- Consolidated phase2 state persists:
  - provider selection
  - accepted capability metadata
  - active governance metadata
  - phase2 timestamps
- Migration-safe loading supports older field layout conversion.

## Deviations and Follow-up Notes

### Current deviations from full end-state expectations

- Governance sync endpoint contract is implemented with defensive normalization; final Core contract hardening may still require schema tightening.
- Trusted telemetry currently emits baseline status payloads for node state visibility; richer operational telemetry channels are deferred.
- Degraded recovery is currently manual trigger (`/api/node/recover`), not yet automated policy-driven recovery orchestration.
- Prompt/service registration and probation are now scaffolded in node-control APIs with persisted local state and execution authorization gate checks; Core-side registry integration is still pending.

### Deferred edge cases (intentionally out of Phase 2 scope)

- Prompt/service registration workflow
- Prompt probation lifecycle
- Execution gateway enforcement logic
- Full policy engine with prompt-level governance decisions
- Multi-provider runtime execution behavior

## Phase 2 Completion Check

Phase 2 completion criteria from architecture/task intent:

- trusted: yes
- capability-known/accepted: yes
- governance-synced: yes
- operational-readiness-gated: yes

Conclusion:

- Phase 2 activation layer is complete for current scope.
- Next work should focus on prompt/service registration and gateway preparation without reworking trust/bootstrap foundations.

## Handoff to Next Phase

### A) Prompt/service registration preparation

- Extend capability-known state with prompt/service registration contracts.
- Add explicit registration states and persisted prompt/service metadata.

### B) Prompt probation flow

- Add probation status model and lifecycle transitions.
- Persist probation markers and expose via control API.
- Emit operational telemetry for probation state changes.

### C) Execution gateway preparation

- Add gateway input/output contract scaffolding.
- Enforce separation between governance decision data and execution runtime state.
- Add deny-by-default behavior for unregistered/unauthorized prompt execution.

## References

- [Phase 2 Implementation Plan](./phase2-implementation-plan.md)
- [Phase 2 Validation Checklist](./phase2-validation-checklist.md)
- [Node Control API Contract](./node-control-api-contract.md)
- [AI Node Capability Declaration](../node-capability-declaration.md)
