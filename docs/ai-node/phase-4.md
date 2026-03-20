# Phase 4 — Provider Intelligence and Model Routing

Status: Active
Implementation status: Partially implemented
Last updated: 2026-03-19

## Goal
Enable Core to make intelligent AI routing decisions.

## Node-Side Implemented Behavior

The current node implementation reports provider intelligence with:

- available models
- pricing
- latency
- success rates
- context limits

For OpenAI specifically:

- selected models are tracked separately from usable models
- selected models missing classification or pricing remain visible locally
- only usable models are published to Core as `available_models`
- manual pricing overrides are persisted and re-applied during later refreshes

This matches the Core taxonomy rule that `provider_models` derive from normalized `provider_intelligence[].available_models[]` in `docs/Core-Documents/nodes/capability-taxonomy.md`.

## Example Node-Side Provider Data

provider: openai

models:
- gpt-4o
- gpt-4o-mini

metrics:
- avg_latency
- p95_latency
- success_rate

## Current Boundary

Implemented in this repository:

- provider/model discovery and local registry persistence
- model usability filtering before declaration/routing publication
- pricing merge and manual override preservation
- provider intelligence submission to Core
- local UI visibility for selected, usable, and blocked models

Still Core-side / outside this repository:

- approved model list enforcement
- model policy governance
- routing decision engine behavior
- final operator-facing routing metadata surfaces

## Contract Notes

Core documentation currently provides these Phase 4-adjacent references:

- `docs/Core-Documents/core/api/api-reference.md`
- `docs/Core-Documents/nodes/capability-taxonomy.md`

These docs establish the ingestion endpoint and taxonomy usage, but they do not yet provide a full normative provider-intelligence schema contract in the same way Phase 1 and Phase 2 do. Local documentation in this repository therefore describes only behavior verified in node code and avoids claiming stronger Core-side guarantees than the current Core docs provide.

## Core Responsibilities

- maintain approved model list
- track provider cost and latency
- route workloads based on policy
