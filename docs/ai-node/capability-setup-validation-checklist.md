# Capability Setup Pending Validation Checklist

## Entry Conditions

- [ ] Trusted restart enters `trusted -> capability_setup_pending` without bootstrap fallback.
- [ ] Approved onboarding finalize enters `pending_approval -> trusted -> capability_setup_pending`.
- [ ] Degraded recovery targets `capability_setup_pending` when operational prerequisites are incomplete.

## Status Payload Contract

- [ ] `GET /api/node/status` includes `capability_setup`.
- [ ] `capability_setup.readiness_flags` includes trust, identity, provider selection, runtime context booleans.
- [ ] `capability_setup.provider_selection` includes configured/enabled/supported fields.
- [ ] `capability_setup.blocking_reasons` is stable list shape for UI polling.
- [ ] `capability_setup.declaration_allowed` reflects gate result.

## Restart Persistence

- [ ] Provider selection persists across backend restart.
- [ ] Trusted runtime context persists and is exposed after restart.
- [ ] Startup with valid trust state does not reload persisted bootstrap config path.

## Declaration Gating

- [ ] `POST /api/capabilities/declare` returns `409` with structured detail when prerequisites are unmet.
- [ ] `POST /api/capabilities/declare` returns success when state and prerequisites are valid.
- [ ] Gate failure logs include lifecycle state, blocking reasons, and readiness flags.

## UI Behavior

- [ ] Setup controls render only when lifecycle state is `capability_setup_pending`.
- [ ] UI shows backend readiness flags.
- [ ] UI shows backend blocking reasons.
- [ ] Declare button is disabled when backend reports `declaration_allowed=false`.
- [ ] Declare button becomes enabled when backend reports `declaration_allowed=true`.
