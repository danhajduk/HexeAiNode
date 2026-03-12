# Capability Setup Pending Contract

This document defines the canonical node-side contract for lifecycle state `capability_setup_pending`.

## Entry Triggers

Node enters `capability_setup_pending` from `trusted` in these cases:

1. Trusted startup resume:
   - backend starts with valid trust state
   - startup path transitions `trusted -> capability_setup_pending`
   - if persisted accepted capability + fresh governance + operational MQTT readiness are all valid, startup may continue immediately to:
     - `capability_declaration_in_progress -> capability_declaration_accepted -> operational`
   - otherwise node remains in `capability_setup_pending`
2. Onboarding finalize approved:
   - node receives approved activation payload
   - trust state is persisted
   - lifecycle transitions `pending_approval -> trusted -> capability_setup_pending`
3. Degraded recovery:
   - node recovers from `degraded`
   - accepted profile/governance/readiness are not all operational-ready
   - recovery target is `capability_setup_pending`

## Required Data In This State

The status API (`GET /api/node/status`) exposes `capability_setup` with required readiness context:

- `readiness_flags.trust_state_valid`
- `readiness_flags.node_identity_valid`
- `readiness_flags.provider_selection_valid`
- `readiness_flags.task_capability_selection_valid`
- `readiness_flags.core_runtime_context_valid`
- `provider_selection.configured`
- `provider_selection.enabled_count`
- `provider_selection.enabled[]`
- `provider_selection.supported.{cloud,local,future}[]`
- `task_capability_selection.configured`
- `task_capability_selection.selected_count`
- `task_capability_selection.selected[]`
- `task_capability_selection.available[]`
- `blocking_reasons[]`
- `declaration_allowed`

## Disallowed Transitions

From `capability_setup_pending`, direct transition is only allowed to:

- `capability_declaration_in_progress`
- `degraded` (degradation path)

Direct transitions to earlier onboarding/bootstrap states are disallowed:

- `unconfigured`
- `bootstrap_connecting`
- `bootstrap_connected`
- `core_discovered`
- `registration_pending`
- `pending_approval`
- `trusted`

## Declaration Gate Contract

Before `POST /api/capabilities/declare`, backend enforces prerequisites:

- valid trust state
- valid node identity
- valid provider selection
- valid task capability selection
- valid trusted runtime context
- current lifecycle state is declaration-eligible

When prerequisites fail:

- response code: `409`
- response shape:
  - `detail.error_code = capability_setup_prerequisites_unmet`
  - `detail.message`
  - `detail.blocking_reasons[]`
  - `detail.readiness_flags`
