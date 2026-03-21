# Hexe AI Node — Phase 3 Internal Cleanup

Status: Active
Implementation status: In progress
Last updated: 2026-03-20

## Purpose

This document defines the Phase 3 internal cleanup pass after the completed display rebrand and MQTT namespace migration work.

Phase 3 focuses on remaining legacy `Synthia` identifiers that are still present in code, scripts, tests, and documentation, while preserving any identifiers that remain contract-sensitive or externally owned.

## Cleanup Categories

### Rename In This Repository

These are candidates for local cleanup when the change is safe and high value:

- user-facing script output and examples
- non-contract comments and internal helper names
- non-contract tests and fixture labels
- active documentation that still describes the current system with legacy naming

### Preserve For Compatibility

These must remain unchanged until a coordinated Core or protocol migration changes the contract:

- HTTP headers such as `X-Synthia-Node-Id` and `X-Synthia-Admin-Token`
- service IDs and unit names such as `synthia-ai-node-backend.service`
- API root service identifier `synthia-ai-node-control-api`
- bootstrap payload examples that still use `Synthia Core` as the Core display name until Core-owned example payloads are revised

### Preserve As External References

These remain legacy because they point to external or canonical locations outside this repository:

- `SynthiaCore` repository links
- `/home/dan/Projects/Synthia` local path references
- golden mismatch artifacts that explicitly reference historical Core documentation

### Archive As Historical

These should be clearly marked historical rather than rewritten as if they describe the current live system:

- prior-phase audit artifacts
- golden mismatch notes
- archived docs that exist to preserve implementation history

## Current Verified Legacy Areas

The current repository audit identifies legacy naming in the following active areas:

- runtime/API compatibility headers
- service manager and systemd unit identifiers
- bootstrap payload examples that still show `Synthia Core`
- script examples and developer convenience paths

## Phase 3 Rules

- prefer renaming local-only identifiers when risk is low
- do not break external contracts to remove a name cosmetically
- keep payload schemas unchanged
- update tests with each safe rename
- mark unavoidable legacy references clearly in docs

## Exit Criteria

Phase 3 is complete when:

- remaining `Synthia` references in active code are either safely renamed or explicitly documented as compatibility/external exceptions
- active docs use Hexe naming unless they intentionally describe a historical artifact
- tests and script examples align with the final local naming choices
- a final cleanup report records what remains and why
