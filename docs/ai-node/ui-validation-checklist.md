# Hexe AI Node - UI Validation Checklist

Status: Active
Last updated: 2026-03-11

This checklist validates implemented dashboard behavior for lifecycle-driven UI states and service controls.

## Lifecycle Scenarios

### 1) Unconfigured node

- [ ] Backend reports `status=unconfigured`.
- [ ] Setup form is visible.
- [ ] Lifecycle card is not shown in setup-only mode.
- [ ] Onboarding start form accepts MQTT host and node name.

### 2) Onboarding in progress

- [ ] Backend reports onboarding state (`bootstrap_connecting`, `registration_pending`, or similar pending state).
- [ ] Onboarding card shows progress badges for:
  - bootstrap discovery
  - registration
  - approval
  - trust activation
- [ ] Correct step is `in_progress`; completed prior steps are `completed`.

### 3) Pending approval

- [ ] Backend reports `status=pending_approval`.
- [ ] Approval button/link is visible when approval URL exists.
- [ ] Onboarding card shows approval step as in progress.

### 4) Trusted/capability setup pending

- [ ] Backend reports `status=capability_setup_pending`.
- [ ] Provider selection section is visible.
- [ ] Lifecycle card shows trusted status and core pairing details (if available).

### 5) Operational node

- [ ] Backend reports `status=operational`.
- [ ] Lifecycle card tone appears healthy.
- [ ] Runtime card shows healthy node and connectivity indicators.
- [ ] Capability summary shows declaration/governance fields when available.

### 6) Degraded node

- [ ] Backend reports `status=degraded`.
- [ ] Lifecycle card tone appears degraded.
- [ ] Runtime card health indicators reflect degraded/disconnected/stale where relevant.

## Color/Indicator Validation

- [ ] Lifecycle color mapping:
  - operational => green
  - pending states => yellow
  - degraded => orange
  - error/offline => red
- [ ] Shared status badges and health indicators render consistently across cards.

## Dynamic Refresh Validation

- [ ] UI refreshes approximately every 7 seconds.
- [ ] Last update timestamp changes over time.
- [ ] Partial endpoint failures appear in warning banner without hard-breaking page rendering.

## Service Control Validation

- [ ] Service card displays backend/frontend/node status (`running`, `stopped`, `failed`, or `unknown`).
- [ ] Restart Backend button triggers backend restart request.
- [ ] Restart Frontend button triggers frontend restart request.
- [ ] Restart Node button triggers combined restart request.
- [ ] Buttons are disabled while restart is in-flight.

## Diagnostics Panel Validation

- [ ] Diagnostics panel is collapsible.
- [ ] Panel shows:
  - lifecycle state
  - API base and endpoint list
  - last backend update timestamp
  - UI version
- [ ] Copy Diagnostics action copies safe (non-secret) content.

## Regression/Refresh Checks

- [ ] Refresh browser while trusted/operational and confirm cards repopulate correctly.
- [ ] Restart backend service and confirm UI reconnects without manual page rebuild.
- [ ] Confirm no secrets/tokens are displayed in any card or diagnostics panel.

## References

- [Phase 2 Validation Checklist](./phase2-validation-checklist.md)
- [Phase 2 Review and Handoff](./phase2-review-handoff.md)
