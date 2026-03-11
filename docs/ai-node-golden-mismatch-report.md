# AI Node New Docs vs Golden Baseline Mismatch Report

Status: Completed (Regenerated)
Generated: 2026-03-11
Scope:
- Split docs: `docs/ai-node/*.md`
- Golden baseline docs: `docs/ai-node-architecture.md`, `docs/phase1-overview.md`
- Bootstrap contract authority for this phase gate: `docs/New_tasks.txt` Task 031/039 canonical field list

## Summary

- Total contradictory findings: 0
- Highest-risk architecture drift: none detected in this pass
- Verification status: documentation-alignment verification complete for tasks 030-039

## Resolution Checklist

1. Bootstrap topic standardized to `synthia/bootstrap/core` across split docs.
2. Bootstrap payload fields standardized to canonical set:
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
3. Registration request field standardized to `node_software_version`.
4. Trust activation payload standardized to canonical fields:
   - `node_id`
   - `paired_core_id`
   - `node_trust_token`
   - `initial_baseline_policy`
   - `operational_mqtt_identity`
   - `operational_mqtt_token`
   - `operational_mqtt_host`
   - `operational_mqtt_port`
5. Persisted trust-state keys aligned to canonical model.
6. Lifecycle model includes `capability_setup_pending` and canonical flow.
7. All split docs include metadata headers (`Status`, `Implementation status`, `Last updated`).
8. All split docs include `See also` cross-links.
9. Markdown fence defects corrected.

## Validation Notes

- This repository currently contains documentation/planning artifacts only; runtime code validation is out of scope for this pass.
- No contradictory field/state naming remains between split docs and the documented baseline used in tasks 030-039.
