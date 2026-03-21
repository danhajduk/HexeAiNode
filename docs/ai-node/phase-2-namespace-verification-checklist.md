# Hexe AI Node — Phase 2 Namespace Verification Checklist

Status: Active
Last updated: 2026-03-20

## Runtime Namespace Checks

- [x] bootstrap topic constant uses `hexe/bootstrap/core`
- [x] bootstrap payload validation expects `hexe/bootstrap/core`
- [x] trusted status telemetry publishes to `hexe/nodes/{node_id}/status`
- [x] active runtime code no longer publishes or subscribes to `synthia/...`

## Test Coverage Checks

- [x] bootstrap tests expect `hexe/bootstrap/core`
- [x] trusted status telemetry tests expect `hexe/nodes/{node_id}/status`
- [x] execution telemetry and declaration contract tests expect `hexe/nodes/{node_id}/status`
- [x] onboarding/security tests expect `hexe/bootstrap/core`

## Documentation Checks

- [x] bootstrap contract examples use `hexe/bootstrap/core`
- [x] phase documentation examples use `hexe/bootstrap/core`
- [x] integration docs describe `hexe/nodes/{node_id}/status`

## Remaining Non-Phase-2 Legacy References

These are not active runtime MQTT references and remain outside this checklist's completion scope:

- task-queue instructions in `docs/New_tasks.txt`
- migration history and audit docs that describe the old namespace
- non-MQTT legacy names such as `X-Synthia-*`, `synthia-*` service IDs, and `SynthiaCore` repository/path references

## Blocked Verification

- [ ] live end-to-end integration with a real Core instance

Status: Not verifiable from current repository state because this workspace does not provide a running Hexe Core integration target.
