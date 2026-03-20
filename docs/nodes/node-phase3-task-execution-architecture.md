# Node Phase 3 Task Execution Architecture

Status: Partially implemented

## Scope

This document defines the Phase 3 execution architecture for the AI Node based on:

- code currently present in this repository
- the existing Core scheduler lease contract
- the existing node prompt-registration and execution-authorization scaffolding

This document does not claim end-to-end task execution is already implemented. It describes the verified baseline, the current subsystem boundaries, and the missing execution-layer work tracked in Tasks 268-290.

## Source Of Truth

Core contracts:

- `docs/Core-Documents/nodes/scheduled-work-execution-contract.md`
- `docs/Core-Documents/nodes/node-capability-activation-architecture.md`
- `docs/Core-Documents/nodes/node-phase2-lifecycle-contract.md`

Local implementation:

- `src/ai_node/runtime/node_control_api.py`
- `src/ai_node/execution/gateway.py`
- `src/ai_node/providers/runtime_manager.py`
- `src/ai_node/providers/execution_router.py`
- `src/ai_node/providers/provider_registry.py`
- `src/ai_node/providers/metrics.py`
- `src/ai_node/providers/models.py`
- `src/ai_node/prompts/registration.py`

## Architecture Status

Implemented:

- prompt/service registration persistence and probation control
- deny-by-default execution authorization gate
- provider registry and provider-health snapshotting
- provider execution router with fallback and retry behavior
- provider metrics persistence and debug inspection
- unified provider request/response models used by the runtime manager

Partially implemented:

- provider selection and fallback during provider invocation
- provider intelligence and model availability filtering feeding later execution decisions
- local execution through `ProviderRuntimeManager.execute()`

Not developed:

- canonical task request/result envelopes
- task router and task execution service
- task-family-specific handlers
- scheduler lease client for node-driven execution
- direct execution API using a normalized Phase 3 task contract
- execution lifecycle state machine
- execution telemetry event stream beyond provider metrics/logging

## Subsystem Boundaries

Core responsibilities:

- scheduler queueing, lease issuance, heartbeat acceptance, progress reports, completion, and revoke behavior
- node governance and capability acceptance
- trust and lifecycle authority through the Phase 1 and Phase 2 contracts

Node responsibilities:

- maintain trusted runtime state
- enforce local prompt registration and probation before execution
- maintain provider registry, health, models, and metrics
- choose an eligible provider/model from locally enabled and usable providers
- execute provider calls once a task has passed validation and governance checks

Provider adapter responsibilities:

- translate a unified execution request into provider-specific API calls
- normalize provider output into the shared response model
- expose model listing and health checks

## Current Execution Baseline

### 1. Governance pre-check

Implemented.

`ExecutionGateway.authorize()` is the current execution gate. It enforces:

- prompt ID must be present
- task family must be present
- prompt must be registered locally
- registered prompt task family must match the requested family
- prompt status must not be `probation`

Current output is the small authorization result envelope:

- `allowed`
- `reason`
- `prompt_id`
- `task_family`

This is exposed through `POST /api/execution/authorize` in `node_control_api.py`.

### 2. Provider runtime

Implemented.

`ProviderRuntimeManager` already owns:

- provider configuration loading
- adapter construction
- provider health checks
- model discovery
- filtered provider intelligence generation
- execution delegation through `ProviderExecutionRouter`

Current direct execution path is now exposed through the local node control API:

- caller submits `TaskExecutionRequest` to `POST /api/execution/direct`
- `NodeControlState` builds the shared `TaskExecutionService`
- the execution service enforces prompt authorization, governance, capability-family validation, provider/model resolution, and handler dispatch
- provider-backed execution still terminates at `ProviderRuntimeManager.execute()`, which forwards to `ProviderExecutionRouter`
- degraded execution remains part of that same shared path, including fallback-provider evaluation and stale-governance handling
- execution telemetry events are published through the existing trusted operational status publisher with execution event payloads, not a separate telemetry transport

### 3. Observability baseline

Implemented.

Provider runtime already persists:

- per-provider success totals
- per-model request counts
- failure classes
- rolling latency samples
- token and estimated-cost counters

Current inspection surfaces:

- `GET /debug/providers`
- `GET /debug/providers/models`
- `GET /debug/providers/metrics`

### 4. Scheduler compatibility baseline

Documented in Core, not developed in this repository for AI Node execution.

The canonical node execution lease lifecycle remains the existing scheduler contract:

- `POST /api/system/scheduler/leases/request`
- `POST /api/system/scheduler/leases/{lease_id}/heartbeat`
- `POST /api/system/scheduler/leases/{lease_id}/report`
- `POST /api/system/scheduler/leases/{lease_id}/complete`
- `POST /api/system/scheduler/leases/{lease_id}/revoke`

Per Core documentation, future node-specialized execution must stay compatible with this lease protocol unless a later major contract revision replaces it.

## Phase 3 Execution Flow

The intended Phase 3 execution flow, constrained to the verified architecture boundaries above, is:

1. Receive a canonical task request through either direct execution or scheduler lease execution.
2. Validate request envelope shape and task-family-specific inputs.
3. Enforce prompt registration and local governance checks.
4. Enforce capability and provider/model eligibility against accepted node capabilities and usable model state.
5. Resolve provider and model using local provider runtime state.
6. Execute through a task-family handler that delegates to the provider abstraction layer.
7. Normalize the result into a canonical task result envelope.
8. Emit execution telemetry and persist execution metrics.
9. If lease-backed, report progress and final completion through the scheduler lease contract.

Status:

- Steps 1, 2, 4, 6, 7, 8, and 9 are not developed as a single end-to-end service.
- Step 3 exists in baseline form through `ExecutionGateway`.
- Step 5 exists in baseline form through `ProviderExecutionRouter`.

## Task Routing Model

Current status: Partially implemented.

What exists today:

- canonical task-family strings are already persisted and declared through capability selection
- prompt registration binds a `prompt_id` to a single `task_family`
- unified provider execution requests already carry `task_family`

What is missing:

- a dedicated task router that dispatches by task family
- a dedicated execution-service layer that consumes the existing extended canonical task-family vocabulary
- a handler registry that separates classification, summarization, and future families

Required architecture rule for upcoming implementation:

- routing decisions must use the existing canonical task-family identifiers already used by capability selection and declaration
- routing must not encode provider names into task-family names or introduce a second conflicting family vocabulary
- provider choice must remain a later resolution step, after task-family validation

## Provider Selection Strategy

Current status: Partially implemented.

Verified current behavior in `ProviderExecutionRouter`:

- start with `requested_provider` if present
- append configured default provider
- append configured fallback provider
- append any remaining registered providers
- skip providers whose health is neither `available` nor `degraded`
- retry a provider according to configured retry count
- record failures and continue to fallback candidates
- return the first successful normalized provider response

Current limitations:

- no dedicated model-selection policy object
- no explicit governance-aware provider/model allowlist enforcement in the execution path
- no task-family-specific provider preferences
- no explicit timeout policy beyond adapter-local behavior

Phase 3 implementation rule:

- provider and model resolution must consume enabled providers, usable models, and governance constraints without bypassing the existing provider health and fallback logic.

## Execution Lifecycle

Current status: Not developed.

The repository does not yet expose a formal task execution lifecycle state machine.

For Phase 3 implementation, the lifecycle tracked by the task execution service should distinguish:

- `idle`
- `receiving_task`
- `validating_task`
- `queued_local`
- `executing`
- `reporting_progress`
- `completed`
- `failed`
- `degraded`
- `rejected`

This state model is not yet implemented in code and should not be treated as active behavior until the runtime surfaces it.

## Scheduler Integration

Current status: Not developed for node execution, but Core contract is implemented and canonical.

Implementation boundary:

- the node should act as an execution client using the existing scheduler `worker_id` field
- node identity should map the execution client identity to the persisted node identity already managed by the onboarding/runtime layers
- lease execution must reuse the same task execution service as direct execution mode
- lease expiration and revoke events must terminate local execution safely and prevent stale completion reporting

## Governance Enforcement Points

Governance must be enforced at four layers.

### A. Prompt/service registration gate

Implemented baseline.

Use `ExecutionGateway` to reject:

- missing prompt ID
- missing task family
- unknown prompt
- task-family mismatch
- prompt in probation

### B. Capability gate

Partially implemented baseline, full execution-path integration not developed.

The node already persists selected task families and resolved capabilities during Phase 2 capability setup. Phase 3 execution must reject tasks that are not part of the accepted capability profile or locally declared task-family set.

### C. Provider/model gate

Partially implemented baseline.

The node already computes usable OpenAI models and filters unavailable or blocked models out of the Core-facing available-model declaration. Phase 3 execution must reuse that same usable-model boundary so execution cannot silently target blocked models.

### D. Lease/governance freshness gate

Not developed in execution path.

Lease-backed or direct execution should degrade or reject when the node no longer has valid trust/governance state for execution.

## Recommended Implementation Order

To stay aligned with the current codebase and Core contracts, the remaining Phase 3 work should proceed in this order:

1. Define canonical request/result envelopes and execution vocabulary.
2. Implement task-family validation and provider resolution as narrow runtime services.
3. Add a task router and baseline handlers that reuse `ProviderRuntimeManager.execute()`.
4. Add direct execution mode on top of the shared execution service.
5. Add scheduler lease execution mode using the Core lease contract.
6. Add execution telemetry, lifecycle tracking, and observability hooks.
7. Add contract tests that cover direct and lease-backed paths.

## See Also

- `docs/ai-node/phase-3.md`
- `docs/ai-node/node-control-api-contract.md`
- `docs/runtime.md`
