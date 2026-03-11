# Synthia AI Node - Phase 1A Implementation Plan and Module Map

Status: Active
Implementation status: Partially implemented (Tasks 041-052)
Last updated: 2026-03-11

## Scope

This plan defines the concrete Phase 1A implementation boundary for AI Node:

- bootstrap discovery
- registration
- operator approval wait
- trust activation
- local trust persistence
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
- [Security Boundaries](./security-boundaries.md)

## Planned Runtime Flow

1. Load node bootstrap config and local trust state.
2. If trust state is valid, skip bootstrap and restore trusted state path.
3. If trust state is missing/invalid, connect to bootstrap MQTT.
4. Subscribe to `synthia/bootstrap/core` and validate payload.
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
- `tests/test_phase1a_bootstrap.py`
- `tests/test_registration_client.py`
- `tests/test_approval_waiter.py`
- `tests/test_trust_activation_parser.py`
- `tests/test_trust_store.py`
- `tests/test_trusted_startup.py`
- `tests/test_operational_handoff.py`

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
