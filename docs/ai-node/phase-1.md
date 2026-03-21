# Phase 1 — Bootstrap, Registration, and Trust Establishment

Status: Active
Implementation status: Implemented
Last updated: 2026-03-12

## Goal
Allow an AI Node to securely join the Hexe system.

## Core Components
- MQTT bootstrap discovery
- Node registration with Core
- Operator approval
- Trust activation payload
- Persistent trust state

## Flow

1. Node connects to MQTT bootstrap port `1884`
2. Node subscribes to `hexe/bootstrap/core`
3. Core broadcasts bootstrap message
4. Node receives API base + onboarding endpoint
5. Node submits registration request to Core
6. Operator approves node in Core UI
7. Core issues trust activation material
8. Node stores trust state locally

## Trust Material

Core issues:

- node_id
- node_trust_token
- operational MQTT credentials
- baseline governance policy
- paired core identity

## Lifecycle States

unconfigured → bootstrap_connecting → bootstrap_connected →
core_discovered → registration_pending → pending_approval → trusted

## Trusted Handoff Behavior

After trust activation is persisted, runtime continues into post-trust handoff:

- `trusted -> capability_setup_pending`

This handoff is implemented in startup and onboarding finalize paths and does not re-enter bootstrap onboarding when trust state is valid.

## Notes

- Phase 1 scope (bootstrap/registration/approval/trust persistence) is complete.
- Capability declaration/governance activation remains Phase 2 scope.

## See Also

- [Phase 1 Overview](./phase1-overview.md)
- [Phase 1 Test Checklist](./phase1-test-checklist.md)
- [Lifecycle States](./lifecycle-states.md)
- [Phase 2 Implementation Plan](./phase2-implementation-plan.md)
