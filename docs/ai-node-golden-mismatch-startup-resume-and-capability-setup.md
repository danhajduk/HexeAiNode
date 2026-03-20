# AI Node Golden Mismatch Report - Trusted Startup Resume and Capability Setup Contract

Status: Resolved
Generated: 2026-03-12
Scope:
- Local runtime code: `src/ai_node/main.py`, `src/ai_node/runtime/capability_declaration_runner.py`, `src/ai_node/runtime/node_control_api.py`
- Local docs: `docs/ai-node/capability-setup-pending-contract.md`, `docs/ai-node/phase2-review-handoff.md`
- Golden docs source: `/home/dan/Projects/Synthia/docs`

## Summary

- Total findings: 2
- Highest-risk drift: trusted startup can now fast-path to operational in code, but golden lifecycle docs do not yet document this conditional path.

Resolution note:

- As of 2026-03-19, the canonical Core docs under `docs/Core-Documents` now cover:
  - trusted startup fast-path continuation
  - readiness/lifecycle compatibility wording for `operational_ready`
  - node-local setup payload boundary

## Finding 1: Trusted startup fast-path operational resume missing in golden docs

Type:
- Missing documentation

What code shows:
- Startup calls `resume_operational_if_ready` during `trusted_resume`.
- When accepted capability + fresh governance + operational MQTT readiness are valid, lifecycle advances to `operational` during startup.

Golden docs currently:
- Define operational readiness criteria and Phase 2 lifecycle model.
- Do not explicitly document startup-time fast-path continuation from `capability_setup_pending` to `operational`.

Why this matters:
- Operators and reviewers may assume trusted restart always pauses in setup pending, which is no longer always true.

## Finding 2: Capability setup status payload shape expanded in code

Type:
- Missing documentation

What code shows:
- `capability_setup.readiness_flags` now includes `task_capability_selection_valid`.
- `capability_setup.task_capability_selection` block is now present in status payload.
- Declaration gate can block on `missing_or_invalid_task_capability_selection`.

Golden docs currently:
- Capture capability/gov readiness model but do not define this node-local setup payload detail.

Why this matters:
- UI/client behavior depending on setup readiness may drift without explicit contract coverage.

## Recommended Golden Doc Updates

- Update `/home/dan/Projects/Synthia/docs/node-phase2-lifecycle-contract.md` with trusted startup conditional resume note.
- Add/extend node-local setup readiness payload contract coverage where operational-status behavior references node setup gating.
