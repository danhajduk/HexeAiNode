# AI Node Budget Enforcement Contract

Status: Implemented baseline

## Purpose

Defines the node-local runtime contract for enforcing Core-issued spend authority and cached grants during task execution.

This document aligns to the Core-owned contract in:

- `docs/Core-Documents/nodes/node-budget-management-contract.md`

## Core Comparison

Current implementation alignment:

- Core remains the policy authority.
- The node consumes `budget_policy` from the governance bundle and can refresh from `GET /api/system/nodes/budgets/policy/current`.
- The node caches grants locally and enforces them on the execution hot path.
- Core declarations scope spend by service and may further constrain a grant by `metadata.provider_id` and `metadata.model_id`.
- Grant scopes follow the Core contract:
  - `node`
  - `customer`
  - `provider`
- Usage is accumulated locally per grant period and queued into local pending usage-summary state for later reporting.

Current local-only additions:

- reservation tracking keyed by task ID
- recent budget-denial history for diagnostics
- optional node-local provider budget windows (`weekly` or `monthly`) layered on top of Core spend authority
- local admin/debug inspection payloads

No Core-doc follow-up ticket is currently required for the baseline node hot-path payload. The Core document now defines the effective `budget_policy` and grant shape the node needs.

## Request Contract

Execution requests now support the following fields relevant to budget enforcement:

- `requested_by`
- `service_id`
- `customer_id`
- `requested_provider`
- `constraints.max_cost_cents`
- `constraints.max_cost_usd`
- `constraints.budget.max_cost_cents`

Normalization rules:

- `service_id` defaults to `requested_by` when omitted
- `customer_id` is optional, but customer-scoped grants only apply when it is present
- request-side max-cost constraints are normalized into cents for reservation and provider filtering

## Local State

Persisted budget state lives in:

- `.run/budget_state.json`

Current state contains:

- cached `budget_policy`
- per-grant usage totals
- per-provider budget-window usage totals
- active reservations
- recent denials
- queued usage summaries

## Execution Flow

The implemented local execution flow is:

1. load or refresh cached budget policy
2. resolve provider and model
3. identify applicable active grants for the request
   grants are filtered by service, scope, and optional provider/model metadata
4. reserve cost before provider dispatch
5. reject execution when no applicable grant exists or remaining Core or local provider budget is insufficient
6. finalize usage after successful execution using execution metrics
7. release reservations on failed dispatch or rejected execution

## Current Limitations

- usage summaries are queued locally but not yet flushed to the Core usage-summary route automatically
- pre-dispatch reservation estimates use request-side cost ceilings first and fall back to a lightweight local pricing estimate when possible
- provider-budget exhaustion decisions reconcile against accumulated exact provider spend so sub-cent model calls do not consume a full cent each at enforcement time
- budget reset is driven by grant period changes observed in fresh policy/grant snapshots
