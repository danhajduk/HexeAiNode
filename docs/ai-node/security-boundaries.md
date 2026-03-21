# Hexe AI Node — Security Boundaries (Phase 1)

Status: Planned
Implementation status: Not developed
Last updated: 2026-03-11

## Purpose

This document defines Phase 1 security boundaries for AI Node onboarding.

## Trust Model

AI Node starts with zero trust.

Trust is granted only after:

1. bootstrap discovery
2. registration request
3. explicit operator approval in Core UI
4. trust activation payload acceptance

## Bootstrap Security Boundary

Bootstrap MQTT on port `1884` is discovery-only.

Allowed function:

- discover Core and onboarding metadata

Not allowed:

- control commands
- telemetry
- authentication credentials
- policy distribution
- operational messaging

## Bootstrap Topic and Allowed Contract

Exact topic:

```text
hexe/bootstrap/core
```

Allowed payload fields:

- `topic`
- `bootstrap_version`
- `core_id`
- `core_name`
- `core_version`
- `api_base`
- `mqtt_host`
- `mqtt_port`
- `onboarding_endpoints.register_session`
- `onboarding_mode`
- `emitted_at`

Compatibility metadata that may also appear:

- `onboarding_endpoints.registrations`
- `onboarding_endpoints.register`
- `onboarding_endpoints.ai_node_register`
- `onboarding_contract`

Validation constraints:

- `topic == "hexe/bootstrap/core"`
- `bootstrap_version` is supported
- `onboarding_mode == "api"`

## Bootstrap Forbidden Data

Bootstrap must never include:

- `node_trust_token`
- `operational_mqtt_token`
- operational credential bundles
- baseline policy payloads
- telemetry payloads
- control-plane commands

## Anonymous MQTT Restrictions

Because bootstrap is anonymous:

- node may connect anonymously
- node may subscribe to exact bootstrap topic
- node must not publish to bootstrap
- node must not subscribe wildcard bootstrap topics

## Credential Issuance Boundary

Credentials are issued only after approval via trusted API response.

Canonical trust material:

- `node_trust_token`
- `operational_mqtt_identity`
- `operational_mqtt_token`
- `operational_mqtt_host`
- `operational_mqtt_port`
- `initial_baseline_policy`

## Channel Separation

| Channel | Purpose |
| --- | --- |
| bootstrap MQTT | anonymous discovery only |
| HTTP API | registration/approval/trust control plane |
| operational MQTT | trusted runtime communication |

## Logging Safety

Never log sensitive trusted fields.

Use redaction in logs and diagnostics.

## See Also

- [AI Node Architecture](../ai-node-architecture.md)
- [Phase 1 Overview](../phase1-overview.md)
- [Bootstrap Contract](./bootstrap-contract.md)
- [Registration Flow](./registration-flow.md)
- [Trust State](./trust-state.md)
