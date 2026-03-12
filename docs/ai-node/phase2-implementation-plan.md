# Synthia AI Node - Phase 2 Implementation Plan and Module Map

Status: Active
Implementation status: In progress (Tasks 059-069 implemented)
Last updated: 2026-03-11

## Scope

Phase 2 starts after Phase 1 onboarding is stable and a node can reach trusted state.

This plan covers:

- trusted startup continuation
- initial node activation after trust
- provider/service enablement selection on node
- capability declaration construction/submission
- baseline governance sync and accepted profile persistence
- post-trust readiness transition toward operational

Out of scope in Phase 2:

- prompt registration/governance workflows
- AI execution runtime and provider inference orchestration
- runtime manager/controller lifecycle

## Runtime Sequence

1. Startup loads trust state and node identity.
2. Trusted node enters `trusted -> capability_setup_pending`.
3. Operator/provider enablement config is loaded or collected.
4. Capability manifest is built and validated from local state.
5. Node submits capability declaration to Core over trusted API.
6. Core accepted profile/version is persisted locally.
7. Node transitions to `operational` only after accepted declaration.

## Implemented So Far

- Task 059:
  - startup now performs explicit trusted resume when valid trust-state exists
  - lifecycle transitions to `trusted -> capability_setup_pending`
  - persisted bootstrap config path is skipped in trusted resume mode
  - startup status exposes trusted runtime context for node/core relationship visibility
- Task 060:
  - local provider/service selection config model added with validation
  - OpenAI is always software-supported and can be operator-enabled/disabled
  - configuration persists to file storage with load/save/create behavior
- Task 061:
  - FastAPI provider selection endpoints added for load/update flows
  - UI capability-setup step now lets operator toggle OpenAI enablement
  - provider selection persists in local node configuration storage
- Task 062:
  - capability manifest schema model implemented with explicit grouped structure
  - validation helpers enforce required sections and supported-vs-enabled provider consistency
- Task 063:
  - canonical functional task-family declarations added for initial AI families
  - validation now rejects unknown/non-canonical task-family names
- Task 064:
  - provider capability declaration module added with explicit `supported` and `enabled` sets
  - OpenAI remains supported by default, while enablement stays operator-controlled
- Task 065:
  - node feature declarations moved to explicit name+enabled representation
  - future prompt-governance readiness is carried as a clearly disabled declaration
- Task 066:
  - environment/resource hints module added (hostname, OS/platform, memory class, GPU present)
  - manifest now validates lightweight environment hints as a required declaration group
- Task 067:
  - trusted capability declaration API client added with accepted/rejected/retryable response handling
  - declaration request includes trusted node identity and auth token headers
- Task 068:
  - capability declaration runner added with explicit submission lifecycle transitions
  - node now uses `capability_declaration_in_progress` / `accepted` / `failed_retry_pending`
  - transition to `operational` happens only after accepted declaration
- Task 069:
  - accepted capability declaration response metadata is now persisted in local capability state storage
  - stored metadata includes accepted declaration version, acceptance timestamp, profile id, restrictions/notes, and raw Core payload for debugging
  - runner preloads accepted profile state on startup so later governance/policy layers can consume it after restart

## Phase 2 Module Map (Python)

```text
src/ai_node/
  runtime/
    post_trust_handoff.py          # startup trusted continuation and readiness bootstrap
    capability_declaration_runner.py # orchestrates declaration submit/retry/accept flow
  config/
    provider_selection_config.py   # supported/enabled provider config model + validation
  capabilities/
    manifest_schema.py             # capability manifest model and validation
    task_families.py               # canonical task-family declarations
    providers.py                   # supported/enabled provider declarations
    node_features.py               # node feature declarations
    environment_hints.py           # lightweight host/platform/resource hints
  core_api/
    capability_client.py           # trusted API client for capability declaration
  persistence/
    capability_state_store.py      # accepted capability profile/version persistence
```

## Initial Contracts

- Capability declaration payload remains formal and versioned.
- Manifest keeps distinct groups:
  - functional task families
  - supported providers
  - enabled providers
  - node features
  - environment/resource hints
  - manifest metadata/version
- Provider model preserves `supported != enabled`.

## Alignment References

- [AI Node Architecture](../ai-node-architecture.md)
- [AI Node Capability Declaration](../node-capability-declaration.md)
- [Phase 1 Overview](./phase1-overview.md)
- [Phase 1 Implementation Plan](./phase1-implementation-plan.md)
