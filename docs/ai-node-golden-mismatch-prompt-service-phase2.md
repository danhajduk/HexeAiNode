# AI Node Golden Mismatch Report - Prompt Service Registration and Execution Gate Scaffolding

Status: Open
Generated: 2026-03-12
Scope:
- Local node code: `src/ai_node/runtime/node_control_api.py`, `src/ai_node/persistence/prompt_service_state_store.py`, `src/ai_node/execution/gateway.py`
- Local API contract: `docs/ai-node/node-control-api-contract.md`
- Golden docs source: `/home/dan/Projects/Synthia/docs`

## Summary

- Total findings: 2
- Highest-risk drift: node-side execution authorization deny-by-default scaffolding is implemented locally but has no golden Phase 2 source-of-truth contract coverage yet.

## Finding 1: Prompt/service registration and probation contract missing in golden docs

Type:
- Missing documentation

What local code/docs show:
- Node control API now exposes local prompt registration and probation endpoints:
  - `GET /api/prompts/services`
  - `POST /api/prompts/services`
  - `POST /api/prompts/services/{prompt_id}/probation`
- Persisted local state exists for prompt services and probation metadata.

What golden docs currently show:
- Phase 2 lifecycle/capability/governance contracts do not define these node-local prompt registration/probation APIs or state shape.

Why this matters:
- Prompt lifecycle behavior can drift between node implementation and canonical documentation.

## Finding 2: Execution authorization deny-by-default scaffold missing in golden docs

Type:
- Missing documentation

What local code/docs show:
- Node control API exposes `POST /api/execution/authorize`.
- Execution gateway denies unregistered prompts by default and blocks prompts in probation.

What golden docs currently show:
- No explicit prompt execution authorization contract for this node-local scaffold path.

Why this matters:
- Consumers may assume no guard or inconsistent behavior before Core-side integration is finalized.

## Recommended Golden Doc Updates

- Add a Phase 2.x extension section in golden docs describing node-local prompt registration/probation scaffolding and provisional execution authorization gate behavior.
- Explicitly mark this layer as local pre-Core-integration scaffold to avoid overstating end-state architecture.
