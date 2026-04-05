# AI Node Prompt Lifecycle And Access Policy

Status: Proposed policy for implementation
Last updated: 2026-04-04

## Purpose

This document defines the recommended prompt lifecycle, freshness expectations, and access policy for the AI Node prompt subsystem.

Current implementation status:

- Implemented:
  - node-local prompt registration
  - immutable prompt versions
  - prompt lifecycle state persistence
  - prompt usage tracking
  - prompt execution gating by lifecycle state
  - prompt update API through `PUT /api/prompts/services/{prompt_id}`
- Not implemented:
  - `review_due` lifecycle state
  - automatic freshness transitions based on inactivity or drift
  - access control that limits prompt execution to the creating client

This policy is intended to become the source of truth for future implementation.

## Current Verified Behavior

The current node stores prompt records with:

- prompt identity and ownership metadata
- lifecycle state
- version history
- usage counters and timestamps
- local execution constraints

Current executable-state behavior:

- `active` is executable
- `probation` is denied with `prompt_in_probation`
- `restricted`, `suspended`, `retired`, and `expired` are denied with `prompt_state_invalid`

Current sharing behavior:

- prompts are effectively node-global
- the execution gateway does not enforce creator-client ownership
- any caller that can reference a prompt ID and pass normal execution checks can use the prompt

## Policy Goals

- make prompt freshness explicit and reviewable
- keep immutable prompt versions
- make prompt updates the normal path instead of retire-and-recreate workflows
- separate prompt ownership from prompt execution visibility
- allow safe shared prompts while preserving restricted prompts
- make stale prompts visible before they become unsafe

## Recommended Lifecycle

The recommended lifecycle is:

1. `draft`
   Not executable. Prompt exists for editing and review.
2. `probation`
   Not executable for normal production traffic. Used for validation, quarantine, or temporary hold.
3. `active`
   Executable for normal allowed callers.
4. `review_due`
   Still executable, but requires operator or owner review because the prompt is stale or affected by drift.
5. `restricted`
   Executable only under narrowed policy conditions.
6. `suspended`
   Not executable until manually restored.
7. `retired`
   Not executable and replaced operationally, but retained for history and audit.
8. `archived`
   Optional long-term historical state hidden from normal operational flows.

## Lifecycle Meaning

`draft`

- creation and editing state
- not visible for general execution
- may be promoted to `probation` or `active`

`probation`

- used when a prompt is new, under investigation, or explicitly paused for validation
- default deny for execution

`active`

- normal production state
- canonical executable state

`review_due`

- stale or drift-affected state
- should remain executable for a limited review window
- must be surfaced clearly in UI and API summaries

`restricted`

- prompt is still allowed, but only for specific services, clients, providers, models, or other policy conditions

`suspended`

- hard stop state for safety, policy, or operational reasons

`retired`

- no longer used for new execution
- preserved for audit, usage history, and version lineage

`archived`

- optional state for older prompt records that should not appear in normal operational lists

## Freshness Policy

Prompts should not remain `active` forever without review.

Recommended default rules:

- move `active` prompts to `review_due` when they have not been used for 30 days
- move `active` prompts to `review_due` when provider/model assumptions materially drift
- move `active` prompts to `review_due` when prompt policy or execution constraints change in a way that may affect correctness
- move `review_due` prompts to `suspended` after 90 days without review

What counts as a refresh or review:

- a prompt owner updates metadata or definition through the update API
- an operator explicitly re-approves the prompt for continued use
- the prompt is validated against new provider/model behavior and marked current

Freshness should be based on:

- `usage.last_used_at`
- `updated_at`
- last explicit review timestamp
- relevant provider/model policy drift timestamps when available

## Version Policy

Prompt versions should remain immutable.

Rules:

- creating a new definition produces a new version
- the newest approved version becomes `current_version`
- older versions may remain executable only if explicitly allowed
- version pinning should remain supported
- retirement applies to the prompt record lifecycle, not to version mutability

The canonical update path is:

- `PUT /api/prompts/services/{prompt_id}`

That route already exists and should be the primary way to evolve prompts rather than retiring and re-registering them.

## Ownership And Access Policy

The current node behavior is effectively node-global prompt use. The recommended policy is more explicit.

Default ownership model:

- every prompt has an owning service
- prompt creation should also record an owning client or owning principal when available

Default access model:

- prompts should be `owner-scoped` by default, not globally executable by every client
- shared execution should require explicit policy

Recommended visibility/execution scopes:

- `private`
  - only the owning client or principal may execute or modify
- `service`
  - callers within the owning service boundary may execute
- `shared`
  - allowed callers may execute based on explicit allowlists or policy
- `public`
  - any node caller allowed by the node may execute

The existing `privacy_class` field is not sufficient by itself to enforce access boundaries. Access scope should become its own explicit contract field.

## Access Rules

Recommended execution checks:

- caller must be allowed by prompt access scope
- prompt lifecycle state must be executable
- task family must match
- requested version must exist
- requested provider/model must satisfy prompt-local constraints

Recommended modification rules:

- only prompt owners or node operators may update prompt metadata or definitions
- only node operators may force `restricted`, `suspended`, `retired`, or `archived`
- owners may request `review_due -> active` after review, subject to policy

## Migration Policy For Current Prompts

Because the current repo has no prompt freshness model yet, existing prompts should not be assumed current.

Recommended migration rule:

- once `review_due` is implemented, all existing prompt records should be migrated to `review_due`

Reason:

- current prompts predate the freshness policy
- they do not have verified review timestamps
- treating them as review-due is the safest baseline without destroying usage history

Migration should:

- preserve existing versions
- preserve usage counters and timestamps
- append a lifecycle-history entry with reason `policy_migration_review_due`
- avoid changing `prompt_id`

## API Policy Requirements

The API should support:

- prompt create
- prompt read
- prompt update
- prompt lifecycle transition
- prompt access policy update
- prompt freshness review / revalidation
- prompt list filtering by lifecycle state and access scope

Minimum required additions beyond the current baseline:

- support `review_due`
- add explicit review metadata
- add explicit access scope and allowed-caller policy
- add bulk transition support for migration of existing prompts to `review_due`

## UI Policy Requirements

The UI should:

- show lifecycle state clearly
- highlight `review_due` prompts
- allow operators to review and reactivate prompts
- guide users toward update-in-place instead of retire-and-recreate
- show whether a prompt is private, service-scoped, shared, or public

## Recommended Next Step

Implement the lifecycle and access policy in the repo in this order:

1. add `review_due` to the prompt model and execution contract
2. add review metadata and access-scope fields
3. preserve `PUT /api/prompts/services/{prompt_id}` as the canonical update path
4. add migration tooling to mark all current prompts as `review_due`
5. add automatic freshness evaluation later as a scheduled or on-demand policy pass
