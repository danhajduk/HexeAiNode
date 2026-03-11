# Synthia AI Node — Phase 1 Overview

Status: Planned
Implementation status: Not developed
Last updated: 2026-03-11

## Purpose

Phase 1 establishes AI Node onboarding into Synthia.

Phase 1 covers:

- bootstrap discovery
- node registration with Core
- operator approval
- trust activation
- local trust-state persistence
- lifecycle status publication

Phase 1 excludes AI execution and provider runtime features.

## Phase 1 Responsibilities

1. Node bootstrap discovery via MQTT.
2. Node registration with Core API.
3. Operator approval in Core UI.
4. Trust activation payload acceptance.
5. Canonical trust-state persistence.
6. Lifecycle progression through trusted-to-operational handoff.

## Bootstrap Contract Snapshot

- Topic: `synthia/bootstrap/core`
- Port: `1884`
- Access: anonymous, subscribe-only
- Required payload fields:
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

## Canonical Lifecycle Path

```text
unconfigured
-> bootstrap_connecting
-> bootstrap_connected
-> core_discovered
-> registration_pending
-> pending_approval
-> trusted
-> capability_setup_pending
-> operational
```

## Out of Scope

- AI execution
- provider orchestration/runtime
- prompt governance/registration
- budget/routing features

## See Also

- [AI Node Architecture](../ai-node-architecture.md)
- [Phase 1 Overview (Canonical)](../phase1-overview.md)
- [Bootstrap Contract](./bootstrap-contract.md)
- [Registration Flow](./registration-flow.md)
- [Trust State](./trust-state.md)
- [Lifecycle States](./lifecycle-states.md)
- [Security Boundaries](./security-boundaries.md)
