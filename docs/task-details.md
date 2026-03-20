# Task Details

## Task 131-148
Original task source: `docs/New_tasks.txt`

Summary of preserved scope:
- Audit the current node docs and classify what should stay local versus what should point to Synthia Core.
- Create a clean top-level docs structure for node-specific documentation.
- Define ownership boundaries between this repository and Synthia Core.
- Support an optional local `docs/core` symlink to canonical Core docs through a helper script and gitignore rules.
- Add a canonical Core reference map using GitHub links to `danhajduk/SynthiaCore`.
- Create concise, code-verified node docs for overview, architecture, setup, configuration, integration, runtime, and operations.
- Update the root `README.md` to point to the new docs entry points.
- Validate internal links and keep the docs usable even when the local Core symlink does not exist.

Task mapping:
- Task 131: Audit the existing node documentation
- Task 132: Create the target documentation structure
- Task 133: Define docs ownership boundaries
- Task 134: Add local Core docs symlink support
- Task 135: Create canonical Core reference mapping
- Task 136: Create `docs/index.md`
- Task 137: Create `docs/overview.md`
- Task 138: Create `docs/architecture.md`
- Task 139: Create `docs/setup.md`
- Task 140: Create `docs/configuration.md`
- Task 141: Create `docs/integration.md`
- Task 142: Create `docs/runtime.md`
- Task 143: Create `docs/operations.md`
- Task 144: Refactor or remove Core-owned duplicated docs
- Task 145: Update root `README.md`
- Task 146: Validate all documentation links
- Task 147: Add a minimal archive folder only if needed
- Task 148: Final documentation consistency pass

## Task 153-176
Original task source: `docs/New_tasks.txt`

Summary of preserved scope:
- Build an OpenAI pricing catalog subsystem that fetches official OpenAI pricing pages, parses pricing data, normalizes model identifiers, validates and caches the results, and merges pricing into the local provider model catalog.
- Keep the scraping and parsing layer isolated from runtime inference logic and future-proof it for additional official sources without adding third-party pricing providers.
- Add configurable official pricing sources, refresh cadence, stale-cache protection, manual refresh controls, pricing diff detection, diagnostics visibility, and structured observability.
- Integrate canonical pricing into existing cost estimation so unknown or stale pricing disables projections rather than guessing.
- Add unit tests for normalization, parsing, validation, fallback behavior, and documentation describing architecture, source policy, and limitations.

Task mapping:
- Task 153: Create OpenAI pricing catalog module
- Task 154: Define canonical pricing data model
- Task 155: Add pricing source configuration
- Task 156: Implement raw HTML fetcher
- Task 157: Implement pricing page parser
- Task 158: Add model name normalization layer
- Task 159: Add snapshot/base model resolver
- Task 160: Create pricing validation layer
- Task 161: Add local pricing cache storage
- Task 162: Add stale-cache protection
- Task 163: Implement merged model catalog builder
- Task 164: Add unknown-model detection
- Task 165: Add pricing refresh service
- Task 166: Add refresh interval configuration
- Task 167: Add CLI/admin task for manual refresh
- Task 168: Add diff detection for pricing changes
- Task 169: Add unit tests for normalization
- Task 170: Add unit tests for parser extraction
- Task 171: Add unit tests for validation and fallback behavior
- Task 172: Add observability/logging
- Task 173: Expose pricing catalog to the budget engine
- Task 174: Add admin diagnostics endpoint/view
- Task 175: Add documentation
- Task 176: Add future-proof parser abstraction

## Task 257
Original task source: `docs/New_tasks.txt`

Resolution:
- Canonical Core docs now explicitly cover the previously missing compatibility and startup-continuation details.
- The remaining local mismatch report can be treated as resolved historical context.

Evidence:
- `docs/Core-Documents/nodes/node-phase2-lifecycle-contract.md`
  - `operational_ready` is now documented as the canonical readiness signal
  - compatibility behavior for `lifecycle_state=trusted` with `operational_ready=true` is explicitly documented
- `docs/Core-Documents/nodes/node-capability-activation-architecture.md`
  - trusted startup fast-path continuation is now explicitly documented
  - node-local setup payload boundary is explicitly documented

## Task 265
Original task source: `docs/New_tasks.txt`

Resolution:
- Canonical Core docs now define the implemented provider-intelligence metrics contract for routing inputs.
- The contract confirms that the current standards path is `pricing` and `latency_metrics` maps on `available_models[]`, which matches the node's current Core-facing payload.

Evidence:
- `docs/Core-Documents/core/api/node-provider-intelligence-contract.md`
  - defines the canonical contract for `POST /api/system/nodes/providers/capabilities/report`
  - defines the admin inspection contract for `GET /api/system/nodes/providers/routing-metadata`
  - documents that Core currently persists `pricing` and `latency_metrics`
  - documents that `success_rate`, request/failure counts, usage totals, and cost totals are not yet separate normative routing fields
- `src/ai_node/core_api/capability_client.py`
  - sends `pricing` and `latency_metrics` in the compatibility payload Core consumes
- `tests/test_capability_client.py`
  - verifies provider-intelligence payload construction and latency metric propagation

## Task 267-290
Original task source: `docs/New_tasks.txt`

Original task details:
- Phase objective: implement the execution layer for AI Nodes.
- This phase enables nodes to accept and execute tasks, route work based on declared capabilities, select providers/models, integrate with scheduler leases, emit execution telemetry, and enforce governance during execution.
- Phase 3 bridges:
  - Phase 2 (capabilities + governance + readiness)
  - Scheduler lease system (existing)
  - Real task execution (missing layer)

Task mapping:
- Task 267: Create `docs/nodes/node-phase3-task-execution-architecture.md`
  - Must define execution flow, task routing model, provider selection strategy, execution lifecycle, scheduler integration, governance enforcement points.
- Task 268: Define canonical task request envelope
  - Fields: `task_id`, `task_family`, `requested_by`, `inputs`, `constraints`, `priority`, `timeout_s`, `trace_id`, optional `lease_id`
  - Add validation rules.
- Task 269: Define canonical task result envelope
  - Fields: `task_id`, `status`, `output`, `metrics`, `error_code`, `error_message`, `provider_used`, `model_used`, `completed_at`
  - Status vocabulary requested: `accepted|completed|failed|rejected|degraded|unsupported`.
- Task 270: Define Task Family Vocabulary v1
  - Canonical list requested:
    - `task.classification`
    - `task.summarization`
    - `task.extraction`
    - `task.translation`
    - `task.intent_resolution`
    - `task.chat_response`
  - Rule: semantic only, no provider or implementation names.
- Task 271: Implement task family validation
  - Validate incoming `task_family` against `declared_task_families` and accepted capability profile
  - Reject unsupported families.
- Task 272: Define provider selection policy
  - Document and implement provider selection, model selection, fallback providers, timeout handling, retry rules
  - Inputs: `enabled_providers`, `available_models`, governance constraints.
- Task 273: Implement `src/ai_node/runtime/provider_resolver.py`
  - Responsibilities: map `task_family -> provider`, select model, apply fallback logic, enforce governance limits.
- Task 274: Define execution lifecycle states
  - States requested: `idle`, `receiving_task`, `validating_task`, `queued_local`, `executing`, `reporting_progress`, `completed`, `failed`, `degraded`, `rejected`
  - Expose via internal state tracking.
- Task 275: Implement `src/ai_node/runtime/task_execution_service.py`
  - Responsibilities: accept task request, validate task, route to handler, invoke provider, produce result envelope, emit telemetry.
- Task 276: Implement `src/ai_node/runtime/task_router.py`
  - Responsibilities: dispatch based on `task_family`, map to handler functions, enforce capability constraints.
- Task 277: Define handler pipeline
  - Standard pipeline requested:
    1. normalize input
    2. validate task
    3. validate inputs
    4. resolve provider/model
    5. execute handler
    6. normalize output
    7. emit telemetry
    8. return result
- Task 278: Implement baseline task handlers
  - Implement `task.classification` and `task.summarization`
  - Each handler accepts normalized input, calls provider abstraction, returns normalized output.
- Task 279: Implement provider abstraction layer
  - Create/extend `src/ai_node/providers/`
  - Interface requested: `execute_classification()`, `execute_summarization()`
  - Implement adapters for `OpenAI` and `Ollama` (placeholder acceptable if needed).
- Task 280: Define governance enforcement in execution
  - Enforce allowed task families, allowed providers, allowed models, max timeout, max input size
  - Reject or degrade if violated.
- Task 281: Implement scheduler lease integration
  - Use existing routes: request lease, heartbeat, report progress, complete
  - Implement worker_id mapping to node_id, capability-based lease filtering, lease_id binding to task execution.
- Task 282: Implement lease execution mode
  - Flow:
    1. request lease
    2. receive job
    3. execute task
    4. heartbeat during execution
    5. report progress (optional)
    6. complete with result
  - Handle lease expiration and revoke events.
- Task 283: Implement direct execution mode
  - Expose internal execution path for direct API calls and synchronous execution
  - Must reuse same execution service.
- Task 284: Define input validation rules
  - Per `task_family` define required inputs, optional inputs, default values, normalization rules
  - Reject invalid input early.
- Task 285: Define failure code taxonomy
  - Codes requested:
    - `unsupported_task_family`
    - `provider_unavailable`
    - `model_unavailable`
    - `governance_violation`
    - `invalid_input`
    - `execution_timeout`
    - `lease_expired`
    - `internal_execution_error`
- Task 286: Implement degraded mode behavior
  - Handle provider unavailable, model unavailable, governance stale, partial execution failure
  - Behavior: fallback provider or degraded result or rejection.
- Task 287: Extend telemetry for task execution
  - Emit events:
    - `task_received`
    - `task_rejected`
    - `task_started`
    - `task_progress`
    - `task_completed`
    - `task_failed`
    - `provider_selected`
    - `provider_fallback`
    - `execution_timeout`
  - Use existing telemetry endpoint.
- Task 288: Implement execution metrics
  - Track execution duration, provider latency, success/failure rate, retries, fallback usage
  - Attach to `result.metrics`.
- Task 289: Implement observability hooks
  - Expose active tasks, recent task history, failure reasons, provider usage, model usage.
- Task 290: Implement contract tests
  - Test valid task execution, unsupported task rejection, provider fallback, governance enforcement, lease lifecycle, lease expiration handling, telemetry emission.

Completion criteria preserved from source:
- nodes can execute tasks end-to-end
- scheduler-driven execution works
- provider routing is functional
- governance is enforced during execution
- telemetry reflects execution behavior
- baseline task families are operational
