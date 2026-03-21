# Hexe AI Node — Trust State

Status: Active
Implementation status: Implemented in backend runtime
Last updated: 2026-03-11

## Purpose

After approval, AI Node must persist local trust state to support deterministic restart and reconnect behavior.

Without persisted trust state, onboarding would repeat on every start.

## Trust State Storage Requirements

Trust state must be persistent across:

- node restarts
- container restarts
- system reboots

## Required Stored Fields

Canonical persisted keys:

| Field | Description |
| --- | --- |
| `node_id` | Unique system identifier issued by Core |
| `node_name` | Human-readable node name |
| `node_type` | Must be `ai-node` |
| `paired_core_id` | Paired Core identifier |
| `core_api_endpoint` | Core API endpoint used post-trust |
| `node_trust_token` | Trusted node auth token |
| `initial_baseline_policy` | Initial baseline policy object |
| `baseline_policy_version` | Baseline policy version marker |
| `operational_mqtt_identity` | Trusted MQTT identity |
| `operational_mqtt_token` | Trusted MQTT token |
| `operational_mqtt_host` | Trusted MQTT host |
| `operational_mqtt_port` | Trusted MQTT port |
| `bootstrap_mqtt_host` | Bootstrap host used during onboarding |
| `registration_timestamp` | Time trust activation was accepted |

## Example Stored Trust State

```json
{
  "node_id": "node-ai-001",
  "node_name": "main-ai-node",
  "node_type": "ai-node",
  "paired_core_id": "core-main",
  "core_api_endpoint": "http://192.168.1.50:9001",
  "node_trust_token": "REDACTED",
  "initial_baseline_policy": {
    "policy_version": "v1"
  },
  "baseline_policy_version": "v1",
  "operational_mqtt_identity": "main-ai-node",
  "operational_mqtt_token": "REDACTED",
  "operational_mqtt_host": "192.168.1.50",
  "operational_mqtt_port": 1883,
  "bootstrap_mqtt_host": "192.168.1.10",
  "registration_timestamp": "2026-03-11T18:21:00Z"
}
```

## Sensitive Data Handling

Sensitive fields include:

- `node_trust_token`
- `operational_mqtt_token`

These values must never be logged, emitted in telemetry, or exposed in debug output.

## Restart Behavior

If trust state exists:

1. Skip bootstrap discovery.
2. Load stored trust data and cross-check `trust_state.node_id` with local identity store.
3. Reconnect via trusted API/MQTT context.
4. Transition from `trusted` to `capability_setup_pending` and then `operational` when readiness criteria are met.

If trust state is missing:

- run onboarding: bootstrap -> registration -> approval -> trust activation

## Trust State Corruption

If required fields are missing/invalid:

1. Treat state as invalid.
2. Log non-sensitive validation error.
3. Restart onboarding from unconfigured bootstrap flow.

## Identity Consistency Rules

- `trust_state.node_id` must match `.run/node_identity.json` `node_id`.
- Mismatch is treated as startup validation failure.
- If identity file is missing and trust state is valid, node backfills identity from trust-state before startup continues.

## Trust Reset

If trust state is deleted, node becomes untrusted and must onboard again.

## See Also

- [AI Node Architecture](../ai-node-architecture.md)
- [Phase 1 Overview](../phase1-overview.md)
- [Registration Flow](./registration-flow.md)
- [Lifecycle States](./lifecycle-states.md)
- [Security Boundaries](./security-boundaries.md)
