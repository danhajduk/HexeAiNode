# Synthia AI Node - Phase 2 Implementation Plan and Module Map

Status: Active
Implementation status: Planned (Tasks 058+)
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
