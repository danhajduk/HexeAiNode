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

## Task 324-349
Original task source: `docs/New_tasks.txt`

Normalization note:
- Original task wording used `per-user` budget grants.
- Core now defines the canonical budget contract in `docs/Core-Documents/nodes/node-budget-management-contract.md` using budget policy plus grant scopes of `node`, `customer`, and `provider`.
- This task range is aligned to that Core-owned contract so node work follows the issued policy/grant model instead of inventing a separate per-user-only contract.

Summary of preserved scope:
- Implement node-local execution-time budget enforcement against cached Core-issued budget policy and grants.
- Persist grants, usage, reservations, reset windows, and outage-tolerant refresh state locally.
- Require the execution request to carry the caller/customer identity and related fields needed to select the applicable grant.
- Enforce grant ceilings before dispatch, finalize actual spend after execution, and release reservations on rejected, failed, timed-out, or cancelled work.
- Expose diagnostics, admin/debug views, telemetry, and end-to-end tests for local budget enforcement without putting Core on the hot path.
- Update Phase 3 documentation and node-control API docs to reflect the Core-owned budget-policy contract boundary.

Task mapping:
- Task 324: Define the local budget-enforcement contract for Core-issued budget policy and cached grants
- Task 325: Verify the canonical Core budget-policy and grant schema
- Task 326: Persist budget-policy snapshots and cached grants locally
- Task 327: Persist grant usage, reservation totals, and reset-window metadata locally
- Task 328: Define the local budget period model for daily, weekly, and monthly reset windows
- Task 329: Add budget-policy refresh and cache-loading flow
- Task 330: Define canonical request fields for caller/customer identity, service identity, provider targeting, and cost constraints
- Task 331: Extend task execution request validation for customer-scoped budget enforcement
- Task 332: Define the local money-budget reservation model
- Task 333: Add pre-execution reservation checks against applicable node/customer/provider grants
- Task 334: Add post-execution budget finalization flow
- Task 335: Add reservation release behavior for rejected, failed-before-dispatch, timed-out, and cancelled executions
- Task 336: Add degraded-mode budget behavior when estimated cost exists but final cost is unavailable
- Task 337: Reject execution when no applicable active cached grant exists or the active period budget is exhausted
- Task 338: Add denial and failure taxonomy for budget enforcement outcomes
- Task 339: Add concurrency-safe reservation handling
- Task 340: Extend provider selection and execution planning to honor request-side max-cost constraints together with cached customer/provider ceilings
- Task 341: Expose budget-policy state and grant balances through diagnostics and observability
- Task 342: Add telemetry for budget-policy refresh, reservation, denial, finalization, and reset events
- Task 343: Add local admin/debug APIs for cached grants, usage, reservations, and denials
- Task 344: Add automated budget reset / rollover handling
- Task 345: Add tests for reservation math and settlement behavior
- Task 346: Add tests for concurrency and double-spend prevention
- Task 347: Add tests for missing, stale, exhausted, or inconsistent grants
- Task 348: Add end-to-end local budget-enforcement tests without Core on the hot path
- Task 349: Update Phase 3 and node-control API documentation for the Core-issued budget-policy model
- nodes can execute tasks end-to-end
- scheduler-driven execution works
- provider routing is functional
- governance is enforced during execution
- telemetry reflects execution behavior
- baseline task families are operational

## Task 367-371
Original task source: user request on 2026-03-20

Preserved scope:
- Move provider budget configuration out of the generic setup surface and into provider-specific setup pages/routes using the shape `/setup/provider/<provider-name>`.
- Support schedule selection for provider budgets instead of amount-only configuration.
- The supported local provider budget schedule options requested are:
  - `monthly`
  - `weekly`
- Weekly budget periods must be defined as local-time calendar weeks running `Monday` through `Sunday`.
- Persistence and API contract updates must carry both the provider budget amount and its schedule type.
- Update the UI and docs so the provider setup flow makes the per-provider budget location and weekly/monthly behavior clear.

Task mapping:
- Task 367: Move provider budget setup into provider-specific setup routes
- Task 368: Add monthly/weekly provider budget scheduling model
- Task 369: Define weekly budget periods as local-time `Monday` through `Sunday`
- Task 370: Persist amount plus schedule type through config and API contracts
- Task 371: Update setup UI and documentation for provider budget scheduling

## Task 372-374
Original task source: user request on 2026-03-20

Preserved scope:
- Align the AI Node task-family vocabulary with the Core canonical naming for classification work.
- The explicit requested mapping is:
  - `task.classification.text` -> `task.classification`
- Update all relevant local surfaces so the canonical family is used consistently in:
  - task validation
  - execution
  - provider routing
  - prompt registration / authorization
  - setup and capability selection flows
  - API payloads
  - docs and tests
- If local persisted state or compatibility surfaces still contain the old value, add a migration or compatibility path so existing nodes do not break during the rename.

Task mapping:
- Task 372: Align local task-family vocabulary with Core canonical classification naming
- Task 373: Update execution, routing, prompt, and setup flows to emit/use `task.classification`
- Task 374: Add migration/compatibility handling for old `task.classification.text` state and remove doc/test drift

## Task 375-378
Original task source: user request on 2026-03-20

Preserved scope:
- Prompts are explicitly node-owned and must not be governed by Core.
- Remove or correct any local documentation, contracts, code assumptions, or queue items that imply Core approves, owns, distributes, or governs prompts for the AI Node.
- Core’s role for this area is limited to budget/spend authority declarations.
- The requested Core declaration model is:
  - “this node may spend up to X for these services/providers/models”
- Budget handling should therefore be expressed in terms of spend authority scoped by:
  - service
  - provider
  - model
- This work must not reintroduce Core-managed prompt governance through budget enforcement or API contracts.
- Diagnostics and docs should make the boundary obvious:
  - prompts are local to the node
  - spend authority comes from Core

Task mapping:
- Task 375: Remove any remaining Core-governs-prompts assumptions
- Task 376: Define the corrected local/Core budget contract around Core-issued spend authority
- Task 377: Implement service/provider/model scoped spend-allowance handling without Core prompt governance
- Task 378: Update diagnostics, API contracts, and docs for the corrected boundary

## Task 379-381
Original task source: user request on 2026-03-20

Preserved scope:
- Check whether the node currently tracks changes in available task families after selecting or deselecting provider models.
- If the enabled-model change alters the resolved task families exposed by the node, the node should automatically re-declare capabilities with Core.
- If the enabled-model change does not alter the resolved task families, avoid unnecessary redeclaration.
- Update the enabled-model API response, tests, and docs so operators can tell whether redeclaration was triggered or skipped.

Task mapping:
- Task 379: Detect resolved task-family changes after enabled-model updates
- Task 380: Trigger capability redeclaration only when enabled-model changes alter the task surface
- Task 381: Update API/tests/docs to report redeclaration outcome for enabled-model changes
