# Synthia AI Node — Bootstrap Contract

Status: Planned
Implementation status: Not developed
Last updated: 2026-03-11

## Purpose

The bootstrap contract defines how an untrusted AI Node discovers Synthia Core.

Bootstrap exists only for:

- Core discovery
- registration metadata delivery

Bootstrap does not exist for:

- control messages
- telemetry
- secrets
- operational policy
- prompt registration
- AI requests

Bootstrap is intentionally narrow.

## Bootstrap Connection Rules

An unregistered AI Node connects to the bootstrap broker using fixed rules:

- `host`: operator provided
- `port`: `1884`
- `authentication`: anonymous
- `client identity`: node name

Node name is bootstrap identity only. It is not a trusted credential.

## Bootstrap Topic

The node must subscribe to this exact topic:

```text
synthia/bootstrap/core
```

Rules:

- exact topic only
- wildcard subscribe is not allowed
- nodes must not publish to bootstrap
- nodes must treat bootstrap as read-only

## Core Bootstrap Publisher Role

Core publishes the bootstrap advertisement. Only Core should publish on the bootstrap topic.

Core should publish periodically so newly started nodes can discover Core without restart coupling.

## Bootstrap Payload

The bootstrap payload must contain only data required to begin API onboarding.

Required fields:

- `topic`
- `bootstrap_version`
- `core_id`
- `core_name`
- `core_version`
- `api_base`
- `mqtt_host`
- `mqtt_port`
- `onboarding_endpoints.register`
- `onboarding_mode`
- `emitted_at`

Example payload:

```json
{
  "topic": "synthia/bootstrap/core",
  "bootstrap_version": 1,
  "core_id": "core-main",
  "core_name": "Synthia Core",
  "core_version": "1.0.0",
  "api_base": "http://192.168.1.50:9001",
  "mqtt_host": "192.168.1.50",
  "mqtt_port": 1884,
  "onboarding_endpoints": {
    "register": "/api/nodes/register"
  },
  "onboarding_mode": "api",
  "emitted_at": "2026-03-11T18:21:00Z"
}
```

## Payload Requirements

Bootstrap payloads must be:

- minimal
- non-sensitive
- easy to validate
- stable enough for first-time onboarding

Bootstrap payloads must not include:

- node tokens
- MQTT passwords
- API secrets
- baseline policy
- prompt rules
- telemetry credentials
- trusted operational identity material

## Node Validation Rules

When a node receives bootstrap payload it must validate:

- payload is valid JSON
- all required fields are present
- `topic == "synthia/bootstrap/core"`
- `bootstrap_version` is supported
- `onboarding_mode == "api"`
- `api_base` is non-empty
- `onboarding_endpoints.register` is non-empty

If validation fails, node must ignore the message and continue listening.

## Bootstrap Freshness

Bootstrap messages are ephemeral discovery signals.

Node must not treat bootstrap as durable trust state. Durable trust begins only after successful registration, approval, and trust activation.

## Node Behavior Summary

An untrusted node sequence:

1. Connect anonymously to operator-provided MQTT host on port `1884`.
2. Subscribe to `synthia/bootstrap/core`.
3. Wait for valid Core bootstrap payload.
4. Validate payload fields and constraints.
5. Build registration URL from `api_base` + `onboarding_endpoints.register`.
6. Begin registration over API.

The node must never:

- publish on bootstrap
- send telemetry on bootstrap
- use bootstrap as operational message bus
- accept secrets from bootstrap

## Security Boundary

Bootstrap is discovery-only and must remain separate from trusted operational channels.

Allowed on bootstrap:

- Core identity and version context
- API base and onboarding endpoint metadata
- onboarding mode and compatibility metadata

Not allowed on bootstrap:

- secrets
- node auth material
- operational credentials
- telemetry
- control actions
- policy bundles

## See Also

- [AI Node Architecture](../ai-node-architecture.md)
- [Phase 1 Overview](../phase1-overview.md)
- [Registration Flow](./registration-flow.md)
- [Security Boundaries](./security-boundaries.md)
