# Hexe Rebranding Completion Report

Status: Active
Completed on: 2026-03-20

## Completed Scope

- canonical Hexe rebranding guidance added for the node repository
- root README and node documentation titles updated to Hexe branding
- UI titles, onboarding copy, approval prompts, and setup status text updated to Hexe / Hexe Core wording
- runtime startup and console-facing log messages updated to Hexe AI Node wording
- capability displays now show human-readable task labels for operators while preserving task IDs internally
- systemd service descriptions updated to Hexe AI Node wording
- audit created for remaining legacy `Synthia` strings

## Compatibility Preserved

- MQTT topics remain under `synthia/...`
- `X-Synthia-*` headers remain unchanged
- service IDs and unit names remain `synthia-*`
- API root service identifier remains `synthia-ai-node-control-api`
- repository/path references to `SynthiaCore` remain where they point to the canonical Core repository

## Verification

- `PYTHONPATH=src .venv/bin/python -m unittest tests.test_main_entrypoint tests.test_node_control_fastapi tests.test_phase1a_bootstrap -v`
- `cd frontend && npm test`
- `cd frontend && npm run build`

## Follow-Up Boundary

Any future migration of topics, headers, service IDs, or repository names must be coordinated with the Core-owned namespace migration phase before this repository changes those identifiers.
