# Synthia AI Node - Phase 2 Validation Checklist

Status: Active
Last updated: 2026-03-11

This checklist validates current implemented Phase 2 behavior:

- trusted restart handoff
- provider selection persistence
- capability declaration flow
- governance sync and freshness handling
- operational MQTT readiness gating
- degraded and recovery transitions

Use alongside:

- [Phase 2 Implementation Plan](./phase2-implementation-plan.md)
- [Phase 1 Overview](./phase1-overview.md)

## Validation Matrix

### 1) Trusted restart path

- [ ] Precondition: valid trust state file exists.
- [ ] Start backend.
- [ ] Verify lifecycle transitions include `trusted -> capability_setup_pending`.
- [ ] Verify `startup_mode=trusted_resume` from `/api/node/status`.
- [ ] Verify bootstrap MQTT onboarding is not re-entered automatically.

Expected lifecycle result:

- `capability_setup_pending` (before capability declaration submit)

### 2) Provider selection persisted

- [ ] Call `POST /api/providers/config` with `{"openai_enabled": true}`.
- [ ] Restart backend.
- [ ] Verify `GET /api/providers/config` still reports `openai` enabled.
- [ ] Verify phase2 state includes `enabled_provider_selection`.

Expected lifecycle result:

- stays in `capability_setup_pending` until declaration is submitted

### 3) Capability manifest build and submit

- [ ] Trigger `POST /api/capabilities/declare`.
- [ ] Verify runner logs include capability manifest summary and submission result.
- [ ] Confirm capability accepted metadata persisted in capability state.
- [ ] Confirm phase2 state includes `accepted_capability`.

Expected lifecycle transitions:

- `capability_setup_pending -> capability_declaration_in_progress -> capability_declaration_accepted`

### 4) Governance synced and stored

- [ ] During successful declaration, verify governance sync runs.
- [ ] Verify governance state file contains:
  - `policy_version`
  - `issued_timestamp`
  - `synced_at`
  - `refresh_expectations`
- [ ] Verify phase2 state includes `active_governance` and governance sync timestamp.
- [ ] Verify `/api/governance/status` reports active version and freshness state.

Expected lifecycle result:

- `operational` only after governance sync + operational MQTT readiness succeed

### 5) Stale governance handling

- [ ] Force an old `synced_at` in governance state beyond `max_stale_seconds`.
- [ ] Call `POST /api/governance/refresh` with Core unavailable (temporary failure).
- [ ] Verify governance status reports stale freshness.
- [ ] Verify trusted status telemetry includes stale governance state when emitted.

Expected behavior:

- freshness explicitly reported as `stale`
- no silent freshness ambiguity

### 6) Trusted operational channel readiness

- [ ] Validate trusted state includes operational MQTT host/port/identity/token.
- [ ] Trigger `POST /api/capabilities/declare`.
- [ ] Verify operational readiness check is executed.
- [ ] Verify activation does not become operational if readiness fails.

Expected lifecycle behavior:

- readiness success: proceed to `operational`
- readiness failure: enter degraded path

### 7) Degraded and recovery behavior

- [ ] Induce failure in one path:
  - capability submit failure
  - governance sync failure
  - operational telemetry publish failure
- [ ] Verify lifecycle reaches `degraded`.
- [ ] Call `POST /api/node/recover`.
- [ ] Verify deterministic recovery target:
  - `operational` when accepted profile + fresh governance + ready operational MQTT
  - `capability_setup_pending` otherwise

Expected behavior:

- trust remains intact (no bootstrap reset)
- recovery path is explicit and logged

## Lifecycle Transition Audit (Per Scenario)

For each scenario, capture:

- observed transition sequence from logs
- final lifecycle state from `/api/node/status`
- relevant diagnostics entries:
  - `diag.phase2.post_trust_activation`
  - `diag.phase2.provider_selection`
  - `diag.phase2.capability_manifest`
  - `diag.phase2.capability_submission`
  - `diag.phase2.governance_sync`
  - `diag.phase2.governance_freshness`
  - `diag.phase2.degraded_recovery`

## Test Command Baseline

Run focused suite:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q \
  tests/test_capability_declaration_runner.py \
  tests/test_phase2_state_store.py \
  tests/test_governance_freshness.py \
  tests/test_operational_mqtt_readiness.py \
  tests/test_trusted_status_telemetry.py \
  tests/test_node_control_fastapi.py \
  tests/test_main_entrypoint.py
```
