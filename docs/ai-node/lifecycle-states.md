# Hexe AI Node — Lifecycle States

Status: Planned
Implementation status: Not developed
Last updated: 2026-03-11

## Purpose

AI Node uses a deterministic lifecycle state model for onboarding, trust progression, and recovery.

## Canonical Lifecycle States

| State | Description |
| --- | --- |
| `unconfigured` | Node has no usable local configuration or trust state |
| `bootstrap_connecting` | Node is connecting to bootstrap MQTT |
| `bootstrap_connected` | Node connected and subscribed to bootstrap topic |
| `core_discovered` | Node received and validated bootstrap payload |
| `registration_pending` | Node submitted registration request |
| `pending_approval` | Node is waiting for operator approval |
| `trusted` | Node accepted trust activation payload |
| `capability_setup_pending` | Node has trust but is not yet fully operational |
| `operational` | Node is trusted and operating in steady state |
| `degraded` | Node has temporary trust-channel or connectivity impairment |

## State Diagram

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

(any active state) -> degraded
degraded -> operational (after recovery)
```

## Transition Notes

- `trusted -> capability_setup_pending`: trust established; post-trust setup/handoff not yet complete.
- `capability_setup_pending -> operational`: Core has accepted capabilities and issued governance for the active node profile.
- `degraded` is non-terminal and should recover without re-onboarding when trust remains valid.

## Restart Behavior

If trust state exists, bootstrap is skipped and node resumes from trusted operational path.

If trust state does not exist, node starts from `unconfigured` and begins bootstrap discovery.

## Logging Requirements

Every lifecycle transition should be logged with non-sensitive context.

Example:

```text
[STATE] registration_pending
[STATE] pending_approval
[STATE] trusted
[STATE] capability_setup_pending
[STATE] operational
```

## See Also

- [AI Node Architecture](../ai-node-architecture.md)
- [Phase 1 Overview](../phase1-overview.md)
- [Bootstrap Contract](./bootstrap-contract.md)
- [Registration Flow](./registration-flow.md)
- [Trust State](./trust-state.md)
