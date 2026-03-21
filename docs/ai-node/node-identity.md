# Hexe AI Node — Unique Node Identity

Status: Active
Implementation status: Implemented (Tasks 059-067)
Last updated: 2026-03-11

## Purpose

Define the canonical local node identity model used by AI Node across onboarding, trust persistence, and restart behavior.

## Canonical Identity

- Field: `node_id`
- Format: UUIDv4 string (lowercase canonical text form)
- Scope: generated and owned by the AI Node runtime
- Lifetime: stable for the full lifetime of the local node installation

## Generation Rules

1. If no valid persisted identity exists, generate `node_id` as UUIDv4.
2. Persist identity immediately to local identity storage.
3. Reuse the same value for all subsequent starts, onboarding attempts, and trusted operation.

## Immutability Rules

- `node_id` is immutable once created.
- Restarting onboarding must not rotate `node_id`.
- Network failures, approval retries, or registration retries must not rotate `node_id`.
- `node_id` changes only on explicit identity reset operation.

## Lifecycle Constraints

- `unconfigured`: node may be untrusted, but `node_id` must still be present once generated.
- `bootstrap_*` and `registration_*`: registration/finalize operations must correlate to same `node_id`.
- `trusted` and later: persisted trust-state `node_id` must equal local identity `node_id`.
- Mismatch between trust-state `node_id` and identity store is a hard validation failure.

## Storage Contract

- Canonical file: `.run/node_identity.json`
- Required keys:
  - `node_id`
  - `created_at`
- Optional keys:
  - `id_format` (`uuidv4` or `legacy`)
  - `schema_version` (recommended for migration safety)

## Migration and Backfill

- If trust-state exists and node identity file is missing, AI Node backfills identity from `trust_state.node_id`.
- Backfilled identities are persisted with `id_format = legacy`.
- Once persisted, identity remains immutable and is used for all future registration attempts.

## API/UX Expectations

- Control API status surface should expose:
  - `node_id`
  - identity validity state
- Setup and pending-approval UI should display `node_id` for support/debug workflows.

## Security Notes

- `node_id` is not a secret.
- `node_id` must never be used as an authentication credential.
- Trust/auth relies on issued trust tokens, not node identity alone.

## See Also

- [Phase 1 Overview](./phase1-overview.md)
- [Registration Flow](./registration-flow.md)
- [Trust State](./trust-state.md)
- [Security Boundaries](./security-boundaries.md)
