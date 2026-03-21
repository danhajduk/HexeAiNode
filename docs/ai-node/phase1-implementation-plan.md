# Hexe AI Node - Phase 1A Implementation Plan and Module Map

Status: Active
Implementation status: Phase 1 core + node identity tasks completed (Tasks 041-067)
Last updated: 2026-03-11

## Scope

This plan defines the concrete Phase 1A implementation boundary for AI Node:

- bootstrap discovery
- registration
- operator approval wait
- trust activation
- local trust persistence
- unique node identity persistence and migration
- lifecycle states
- basic status telemetry

Out of scope for this phase:

- provider configuration
- prompt handling
- capability declaration
- AI execution runtime

## Source-of-Truth Links

- [Phase 1 Overview](./phase1-overview.md)
- [Bootstrap Contract](./bootstrap-contract.md)
- [Lifecycle States](./lifecycle-states.md)
- [Registration Flow](./registration-flow.md)
- [Trust State](./trust-state.md)
- [Unique Node Identity](./node-identity.md)
- [Security Boundaries](./security-boundaries.md)

## Planned Runtime Flow

1. Load node bootstrap config and local trust state.
2. If trust state is valid, skip bootstrap and restore trusted state path.
3. If trust state is missing/invalid, connect to bootstrap MQTT.
4. Subscribe to `hexe/bootstrap/core` and validate payload.
5. Build registration URL and submit registration to Core API.
6. Wait on pending approval without re-register loops.
7. On approval, validate trust activation payload.
8. Persist trust state and transition lifecycle to trusted handoff states.
9. Emit minimal Phase 1 status events through non-bootstrap surfaces.

## Initial Module and File Map

The following file map is the implementation anchor for upcoming tasks.

```text
src/ai-node/
  config/
    bootstrapConfig.ts          # user bootstrap host + node name + fixed defaults
  lifecycle/
    nodeLifecycle.ts            # canonical states and transition helpers
  bootstrap/
    bootstrapClient.ts          # anonymous MQTT connect/reconnect, subscribe-only
    bootstrapParser.ts          # bootstrap payload parse + schema checks
  registration/
    registrationClient.ts       # register endpoint URL build + registration request
    approvalWaiter.ts           # pending approval status handling
  trust/
    trustActivationParser.ts    # approved trust payload parsing/validation
    trustStore.ts               # trust state persistence and load/validate
    trustedStartup.ts           # startup branch: trusted resume vs onboarding
  telemetry/
    statusEmitter.ts            # minimal lifecycle status events
  security/
    redaction.ts                # sensitive field redaction helpers
    boundaries.ts               # explicit bootstrap/trust guardrails
  runtime/
    onboardingOrchestrator.ts   # orchestration glue for phase-1 flow
```

## Implemented in This Phase 1A Slice

Current implementation files:

- `src/ai_node/config/bootstrap_config.py`
- `src/ai_node/lifecycle/node_lifecycle.py`
- `src/ai_node/bootstrap/bootstrap_client.py`
- `src/ai_node/bootstrap/bootstrap_parser.py`
- `src/ai_node/registration/registration_client.py`
- `src/ai_node/registration/approval_waiter.py`
- `src/ai_node/trust/trust_activation_parser.py`
- `src/ai_node/trust/trust_store.py`
- `src/ai_node/trust/trusted_startup.py`
- `src/ai_node/trust/operational_handoff.py`
- `src/ai_node/telemetry/status_emitter.py`
- `src/ai_node/runtime/connectivity_manager.py`
- `src/ai_node/security/boundaries.py`
- `src/ai_node/security/redaction.py`
- `src/ai_node/diagnostics/onboarding_logger.py`
- `src/ai_node/identity/node_identity_store.py`
- `src/ai_node/runtime/onboarding_runtime.py`
- `src/ai_node/runtime/node_control_api.py`
- `tests/test_phase1a_bootstrap.py`
- `tests/test_registration_client.py`
- `tests/test_approval_waiter.py`
- `tests/test_trust_activation_parser.py`
- `tests/test_trust_store.py`
- `tests/test_trusted_startup.py`
- `tests/test_operational_handoff.py`
- `tests/test_status_emitter.py`
- `tests/test_connectivity_manager.py`
- `tests/test_security_boundaries.py`
- `tests/test_onboarding_logger.py`
- `tests/test_node_identity_store.py`
- `tests/test_main_entrypoint.py`
- `tests/test_node_control_api.py`
- `tests/test_node_control_fastapi.py`
- `docs/ai-node/phase1-test-checklist.md`

## State and Security Guardrails

- Bootstrap MQTT remains discovery-only and subscribe-only.
- Node never publishes to bootstrap topic.
- Approval is mandatory before trust activation acceptance.
- Secrets/tokens are redacted from logs and diagnostics.
- Bootstrap payload data is never treated as trusted persistent state.

## Task-to-Module Mapping

- Task 041 -> `config/bootstrapConfig.ts`
- Task 042 -> `lifecycle/nodeLifecycle.ts`
- Task 043 -> `bootstrap/bootstrapClient.ts`
- Task 044 -> `bootstrap/bootstrapParser.ts` + subscription handling in `bootstrapClient.ts`
- Task 045 -> `bootstrap/bootstrapParser.ts` validation layer
