# Phase 3 — Prompt Contracts and Execution Governance

Status: Partially implemented

## Goal
Introduce governed prompt execution.

Each prompt becomes a governed contract between the caller, Core, and AI Node.

## Prompt Metadata

- prompt_id
- prompt_name
- owner service
- task_family
- expected frequency
- privacy class
- cost sensitivity
- version

## Prompt Lifecycle

probation → active → restricted → suspended → expired

## Governance Controls

Core controls:

- prompt approval
- budget limits
- allowed models
- prompt suspension

Node enforces:

- prompt budgets
- probation limits
- usage telemetry

## Current Baseline

The current repository already implements a limited Phase 3 baseline:

- prompt/service registration persistence
- probation transitions
- deny-by-default execution authorization for registered prompts
- provider runtime execution with fallback and metrics

The end-to-end task execution layer is not yet developed.

## Canonical Task Request Envelope

Status: Implemented

The Phase 3 request-envelope baseline is now defined by `TaskExecutionRequest` in `src/ai_node/execution/task_models.py`.

Fields:

- `task_id: string`
- `prompt_id: string | null`
- `task_family: string`
- `requested_by: string`
- `requested_provider: string | null`
- `requested_model: string | null`
- `inputs: object`
- `constraints: object`
- `priority: background | low | normal | high`
- `timeout_s: integer`
- `trace_id: string`
- `lease_id: string | null`

Current validation rules:

- required string fields must be non-empty after trimming
- optional `prompt_id`, `requested_provider`, and `requested_model` are accepted when present
- `task_family` must pass the existing task-family identifier validation rules
- `inputs` and `constraints` must be objects
- `timeout_s` must be greater than `0` and no more than `3600`
- extra fields are rejected

This envelope is now used by the local direct execution API at `POST /api/execution/direct` and by the scheduler lease execution loop.

## Canonical Task Result Envelope

Status: Implemented

The Phase 3 result-envelope baseline is now defined by `TaskExecutionResult` and `TaskExecutionMetrics` in `src/ai_node/execution/task_models.py`.

Fields:

- `task_id: string`
- `status: accepted | completed | failed | rejected | degraded | unsupported`
- `output: object | null`
- `metrics: object`
- `error_code: string | null`
- `error_message: string | null`
- `provider_used: string | null`
- `model_used: string | null`
- `completed_at: datetime | null`

Current validation rules:

- `task_id` must be non-empty after trimming
- `metrics` values must be non-negative
- `failed`, `rejected`, and `unsupported` results require `error_code`
- `completed` and `degraded` results require `output`
- terminal statuses require `completed_at`
- `accepted` results must not include `completed_at`
- extra fields are rejected

This envelope currently defines the canonical local result shape for upcoming direct-execution and lease-execution services. It is not yet emitted by a dedicated task execution service.

## Phase 3 Task Family Vocabulary v1

Status: Implemented

The Phase 3 execution vocabulary now reuses the existing extended canonical task-family set from `src/ai_node/capabilities/task_families.py`.

The node does not introduce a second reduced execution-only family list. Execution validation uses the same current canonical family values already used for capability selection and declaration.

## Execution Task Family Validation

Status: Implemented

`validate_execution_task_family()` now validates an incoming execution family against:

- the existing canonical task-family vocabulary
- locally declared task families
- the accepted capability profile when one is available

The validator keeps the current extended task-family values as-is. It does not translate them into a second semantic alias vocabulary.

Current failure reasons:

- `unsupported_task_family`
- `task_family_not_declared`
- `task_family_not_accepted`

## Provider Selection Policy

Status: Implemented

The baseline provider-selection policy is now defined in `src/ai_node/execution/provider_selection_policy.py`.

Current policy inputs:

- enabled providers
- default provider
- requested provider
- requested model
- provider health snapshot
- usable models by provider
- provider retry configuration
- requested timeout
- optional governance constraints

Current policy behavior:

- prefer `requested_provider` first when it is enabled, governance-allowed, and not unavailable
- then try the configured default provider
- then try remaining enabled providers in stable order
- skip providers whose current health is `unavailable`
- restrict model choices to usable models when a provider-specific usable model list exists
- further restrict model choices by governance-approved model lists when present
- narrow to the requested model when one is explicitly requested
- cap execution timeout using `routing_policy_constraints.max_timeout_s` when provided
- cap retry count using `routing_policy_constraints.max_retry_count` when provided

Current fallback rule:

- fallback is allowed only when more than one eligible provider remains after health and governance filtering

Current governance fields consumed when present:

- `approved_providers`
- `approved_models`
- `routing_policy_constraints.max_timeout_s`
- `routing_policy_constraints.max_retry_count`

This policy module is a reusable planning layer for the next resolver task. It does not yet execute providers directly.

## Provider Resolver

Status: Implemented

`ProviderResolver` is now implemented in `src/ai_node/runtime/provider_resolver.py`.

Current responsibilities:

- read provider-selection context from the current runtime manager
- apply the shared provider-selection policy
- choose the primary provider
- choose a concrete model for that provider
- expose fallback provider order
- return rejection reasons when no eligible provider or model can be selected

Current model selection order:

- first allowed model from the policy allowlist
- otherwise the configured provider default model when it remains eligible
- otherwise the first available model currently known for that provider

Current runtime inputs come from `ProviderRuntimeManager.provider_selection_context_payload()`:

- enabled providers
- default provider
- default model by provider
- provider retry counts
- provider health
- available models by provider
- usable models by provider

This resolver is not yet wired into a task execution service. It is the concrete provider/model selection layer that later execution tasks will call.

## Execution Lifecycle States

Status: Implemented

The canonical execution lifecycle state list is now defined in `src/ai_node/execution/lifecycle.py`:

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

The repository now also includes `ExecutionLifecycleTracker`, which provides the baseline internal state-tracking layer for Phase 3 execution work.

Current tracker behavior:

- non-terminal states remain in the active-task map
- terminal states move the task into bounded recent history
- each record tracks `task_id`, `state`, `updated_at`, optional `lease_id`, `provider_id`, `model_id`, and free-form `details`

This tracker is not yet exposed through node control APIs. It is the internal lifecycle primitive for the upcoming task execution service and observability tasks.

## Task Execution Service

Status: Implemented

`TaskExecutionService` is now implemented in `src/ai_node/runtime/task_execution_service.py`.

Current service flow:

- track `receiving_task` and `validating_task`
- validate the requested task family against the current canonical execution-family rules
- authorize `prompt_id` through the existing execution gateway when a prompt ID is supplied
- degrade early when the existing governance status is already stale
- validate and normalize task-family inputs before provider execution
- resolve provider and model through `ProviderResolver`
- track `queued_local` and `executing`
- invoke the current provider runtime through a normalized `UnifiedExecutionRequest`
- return the canonical `TaskExecutionResult`
- write terminal lifecycle state into the internal lifecycle tracker

Current outputs:

- `completed` on successful provider execution
- `degraded` when governance is stale or when provider/model execution can only terminate in a degraded state after fallback evaluation
- `unsupported` when the requested task family is outside the current canonical family set
- `rejected` for authorization failures and non-degraded policy/validation failures
- `failed` for runtime execution failures

Input validation is now defined in `src/ai_node/execution/input_validation.py` and keeps the broader existing task families while making their inputs explicit:

- text-style families accept normalized prompt-like fields or validated `messages[]`
- email families normalize `subject` plus `body/content` into prompt text
- event summarization normalizes `event` objects into deterministic JSON prompt text
- image classification accepts image-only payloads and supplies a default instruction when needed
- `temperature` and `max_tokens` are validated before provider execution

Failure taxonomy is now defined in `src/ai_node/execution/failure_codes.py`. It groups the existing detailed runtime reasons into broader canonical Phase 3 categories without replacing the more specific current error codes.

Degraded-mode behavior now extends the existing runtime rather than introducing a second execution model:

- requested provider/model resolution still prefers the requested target first
- if the requested provider cannot satisfy the request, later eligible providers can still be selected
- if provider/model availability is exhausted, the service returns a degraded terminal result instead of collapsing directly to a hard failure
- scheduler lease execution treats degraded results as completed lease work with degraded task status preserved in the payload

Execution telemetry is now emitted over the existing trusted operational telemetry publisher rather than a separate transport. `src/ai_node/runtime/execution_telemetry.py` wraps the same trusted status MQTT path used elsewhere in the runtime and emits execution-scoped events including:

- `task_received`
- `provider_selected`
- `provider_fallback`
- `task_started`
- `task_progress`
- `task_completed`
- `task_rejected`
- `task_failed`
- `execution_timeout`

This keeps execution telemetry aligned with the existing node-owned telemetry boundary: operational MQTT only, never bootstrap transport.

Execution metrics now also reuse the broader runtime provider metrics already collected by `src/ai_node/providers/metrics.py`. `TaskExecutionResult.metrics` still includes per-run fields like `execution_duration_ms`, `provider_latency_ms`, `retries`, `fallback_used`, token usage, and estimated cost, but now also surfaces the current provider/model snapshot context:

- `provider_avg_latency_ms`
- `provider_p95_latency_ms`
- `provider_success_rate`
- `provider_total_requests`
- `provider_failed_requests`

This keeps Phase 3 metrics aligned with the runtime’s existing provider/model counters rather than introducing a separate execution-metrics store.

Observability hooks now reuse those same existing surfaces. `src/ai_node/runtime/node_control_api.py` exposes `GET /debug/execution`, which combines:

- active task state from `ExecutionLifecycleTracker.active_payload()`
- recent task history from `ExecutionLifecycleTracker.history_payload()`
- aggregated failure reasons from existing provider/model failure classes
- provider usage from the current provider metrics totals
- model usage from the current provider metrics model snapshots

This keeps execution observability aligned with the broader runtime debug surfaces instead of creating a separate Phase 3 observability store.

Contract coverage is now consolidated in `tests/test_execution_contracts.py`. That suite exercises the broader current execution contract across:

- valid task execution
- unsupported task rejection
- provider fallback behavior
- governance enforcement
- lease lifecycle completion
- lease expiration handling
- trusted execution telemetry emission

Current scope boundary:

- the service currently dispatches through `TaskRouter`
- the default router path still executes through the provider runtime manager
- it now uses task-family-specific baseline handlers for classification and summarization
- it is now exposed through `POST /api/execution/direct`

## Task Router

Status: Implemented

`TaskRouter` is now implemented in `src/ai_node/runtime/task_router.py`.

Current responsibilities:

- resolve an exact-match handler for a task family when one is registered
- fall back to a default handler when the family is still considered routable
- reject execution with `task_family_not_routable` when no explicit or default route is available

Current routing model:

- uses the existing extended canonical task-family identifiers directly
- does not introduce a second family vocabulary
- supports a default provider-execution handler, which the current task execution service uses as its baseline route

The router is now the dispatch seam between the task execution service and upcoming baseline task-family handlers.

## Handler Pipeline

Status: Implemented

The shared Phase 3 handler pipeline is now defined in `src/ai_node/execution/pipeline.py` as:

1. `normalize_input`
2. `validate_task`
3. `validate_inputs`
4. `resolve_provider_model`
5. `execute_handler`
6. `normalize_output`
7. `emit_telemetry`
8. `return_result`

Current implementation note:

- the current task execution service already performs parts of this sequence
- the upcoming baseline handlers will attach to this pipeline contract explicitly instead of inventing per-handler flow
- telemetry emission remains a placeholder stage until the dedicated execution telemetry tasks are implemented

## Baseline Task Handlers

Status: Implemented

Baseline handlers now live in `src/ai_node/runtime/task_handlers.py`.

Current handler coverage uses the broader existing family declarations already present in the repository:

- classification:
  - `task.classification`
  - `task.classification.text`
  - `task.classification.email`
  - `task.classification.image`
- summarization:
  - `task.summarization`
  - `task.summarization.text`
  - `task.summarization.email`
  - `task.summarization.event`

Current baseline behavior:

- normalize prompt-like inputs from existing request fields such as `prompt`, `text`, `content`, and `body`
- preserve `messages` when provided
- normalize event summarization payloads into a deterministic JSON prompt
- reject requests with no usable prompt or messages as `invalid_input`
- execute through the current provider runtime manager using the resolved provider and model

The task execution service now registers these handlers into the router by default while still keeping the broader default provider-execution path available for other already-declared families.

## Provider Abstraction Layer

Status: Implemented

The provider abstraction layer now lives in `src/ai_node/providers/task_execution.py`.

Current abstraction contract:

- `execute_classification()`
- `execute_summarization()`

Current implementations:

- `RuntimeManagerProviderTaskExecutor`
  - delegates to the existing `ProviderRuntimeManager.execute()` path
- `OpenAIProviderTaskExecutor`
  - delegates directly to an OpenAI provider adapter
- `OllamaProviderTaskExecutor`
  - explicit placeholder that currently raises `ollama_task_executor_not_implemented`

Current integration:

- baseline classification and summarization handlers now depend on this abstraction layer instead of calling the runtime manager directly
- the runtime-backed executor keeps provider selection and execution behavior aligned with the existing broader node runtime
- the abstraction layer creates a stable seam for future provider-specific execution work without replacing the current provider runtime stack

## Governance Enforcement In Execution

Status: Implemented

Execution-time governance enforcement is now defined in `src/ai_node/execution/governance.py` and applied by `TaskExecutionService`.

Current enforcement points:

- before provider resolution:
  - task-family allowlist from `generic_node_class_rules.allow_task_families`
  - timeout cap from `routing_policy_constraints.max_timeout_s`
  - input-size cap from `routing_policy_constraints.max_input_bytes`
- after provider resolution:
  - provider allowlist from `approved_providers`
  - model allowlist from `approved_models`

Current compatibility behavior:

- broader governance entries like `summarization` are treated as matching existing declared families such as `task.summarization.text`
- exact `task.*` governance entries are matched exactly

Current result behavior:

- governance violations currently return `rejected`
- violation codes include:
  - `governance_violation_task_family`
  - `governance_violation_timeout`
  - `governance_violation_input_size`
  - `governance_violation_provider`
  - `governance_violation_model`

## Scheduler Lease Integration

Status: Implemented

Scheduler lease integration now uses the canonical Core lease routes through `src/ai_node/core_api/scheduler_lease_client.py` and `src/ai_node/runtime/scheduler_lease_integration.py`.

Current integration behavior:

- request leases through `POST /api/system/scheduler/leases/request`
- heartbeat through `POST /api/system/scheduler/leases/{lease_id}/heartbeat`
- report progress through `POST /api/system/scheduler/leases/{lease_id}/report`
- complete through `POST /api/system/scheduler/leases/{lease_id}/complete`

Current node mapping rule:

- `worker_id` is mapped directly to the persisted `node_id`
- scheduler capability filters use the node’s declared task-family capabilities
- lease IDs can be bound onto the existing `TaskExecutionRequest` model through `SchedulerLeaseIntegration.bind_lease_to_task_request(...)`

Current scope boundary:

- this task adds the canonical integration layer only
- it does not yet implement the polling/heartbeat execution loop for lease-backed task execution

## Lease Execution Mode

Status: Implemented

Lease-backed execution now has a baseline runner in `src/ai_node/runtime/lease_execution_mode.py`.

Current `run_once()` flow:

1. request one lease through the scheduler lease integration layer
2. extract a task request from the leased job payload
3. bind `lease_id` onto the existing `TaskExecutionRequest`
4. start a background heartbeat loop
5. report initial execution progress
6. execute the task through `TaskExecutionService`
7. complete the lease as `completed` or `failed`

Current lease-loss behavior:

- heartbeat rejection is treated as lease loss
- lease-backed execution returns `lease_lost` when heartbeat fails during execution
- invalid lease payloads complete the lease as failed with `invalid_lease_job_payload`

Current scope boundary:

- this is a conservative single-lease execution path
- it does not yet implement a continuous worker poll loop
- revoke handling is currently represented through lease-loss semantics rather than a separate push channel

See:

- `docs/nodes/node-phase3-task-execution-architecture.md`
- `docs/ai-node/node-control-api-contract.md`
