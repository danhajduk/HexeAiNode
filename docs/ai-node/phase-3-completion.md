# Hexe AI Node — Phase 3 Completion

Status: Complete except blocked Core integration follow-up
Last updated: 2026-03-20

## Completed Local Cleanup

- renamed local helper variables away from legacy `x_synthia_*` names while preserving wire-header aliases
- migrated frontend package metadata from `synthia-ai-node-frontend` to `hexe-ai-node-frontend`
- migrated theme persistence from `synthia_theme` to `hexe_theme` with one-way legacy preference cleanup
- updated active script messaging from `Synthia` wording to `Hexe` wording where the text is developer-facing rather than contract-sensitive
- refreshed the internal cleanup and audit docs to distinguish compatibility exceptions from local-only cleanup targets
- added an active-code guard at `scripts/check_legacy_references.py` with test coverage in `tests/test_legacy_reference_guard.py`

## Remaining Legacy References

These remain intentionally:

- `X-Synthia-Node-Id` and `X-Synthia-Admin-Token` header names because they are current wire contracts
- `synthia-ai-node-backend.service`, `synthia-ai-node-frontend.service`, and `synthia-ai-node-control-api` because they are runtime/service identifiers
- `SynthiaCore` repository names and `/home/dan/Projects/Synthia...` paths because they point to external canonical locations
- historical and audit documentation that records the migration itself
- bootstrap payload examples that still say `Synthia Core` until the Core-owned examples are revised

## Verification

- `PYTHONPATH=src .venv/bin/python -m unittest tests.test_node_control_fastapi tests.test_legacy_reference_guard -v`
- `python3 scripts/check_legacy_references.py`
- `cd frontend && npm test`
- `cd frontend && npm run build`

## Blockers

- Task 416 remains blocked by a live Core registration contract mismatch: bootstrap discovery now works against the real Core target, but Core rejects the node registration with `node_id_invalid`.
