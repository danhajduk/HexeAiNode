# Hexe AI Node - Phase 1 Test Checklist

Status: Active
Implementation status: Validation checklist and pass log
Last updated: 2026-03-11

## Scope

This checklist validates Phase 1 onboarding behavior against canonical docs.

## Checklist

1. First-time bootstrap success
- Expected flow: `unconfigured -> bootstrap_connecting -> bootstrap_connected -> core_discovered`
- Validation: Covered by bootstrap config/client/parser tests.

2. Malformed bootstrap ignored
- Expected flow: remain listening; no promotion to trusted states.
- Validation: Invalid JSON and invalid payload cases are rejected by parser/client path.

3. Registration pending approval
- Expected flow: `core_discovered -> registration_pending -> pending_approval`
- Validation: Registration client and pending-approval waiter tests verify transition and metadata capture.

4. Approval accepted
- Expected flow: `pending_approval -> approved decision -> trust activation parse`
- Validation: Approval decision handler returns approved handoff payload and trust parser accepts canonical payload.

5. Approval rejected
- Expected flow: `pending_approval -> rejected` with onboarding stop.
- Validation: Rejection path raises explicit `ApprovalRejectedError`.

6. Trust state persisted
- Expected flow: trusted payload fields written and validated from local storage.
- Validation: Trust store save/load/validate tests pass, including required field checks.

7. Reboot with valid trust state
- Expected flow: skip bootstrap, resume `trusted -> capability_setup_pending`.
- Validation: Trusted startup manager tests confirm trusted resume path.

8. Core/API temporary outage after trust
- Expected flow: `operational -> degraded -> operational` on recovery.
- Validation: Connectivity manager recovery tests confirm degraded transition and restoration.

## Validation Pass (Current)

- Command: `PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v`
- Result: PASS
- Total tests: 34
- Failures: 0

## Notes

- Status telemetry is emitted only over trusted/internal channels, never bootstrap.
- Security guardrails reject trust-like data in bootstrap payloads.
