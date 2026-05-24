# Task Details

## Task 902-910
Original task source: ad hoc operator request on 2026-05-18.

Summary of preserved scope:
- Add a supervised local llama.cpp runtime for the AI Node.
- Run llama.cpp in a container with NVIDIA GPU access on hosts that support it.
- Prefer Unix domain sockets over TCP for node-to-llama.cpp traffic.
- Keep TCP loopback as an explicit fallback for development or socket-incompatible deployments.
- Add a Python health wrapper that can be supervised and queried separately from the model server.
- Make the health wrapper check llama.cpp readiness, configured model availability, and useful GPU/container signals where practical.
- Integrate the runtime with the AI Node service metadata so Supervisor can observe and control it similarly to other node-local runtimes.
- Implement the existing `local` provider adapter against llama.cpp's OpenAI-compatible API.
- Provide an operator-facing way to compare local and OpenAI results and latency using the same prompt.
- Default the first local model target to `Qwen/Qwen3-8B-GGUF` with `Q4_K_M` quantization unless implementation validation shows it does not fit or behave well on the RTX 3060 12 GB host.

Task mapping:
- Task 902: Define the llama.cpp local runtime contract
  - Document runtime boundaries, socket paths, model path conventions, transport fallback rules, and default model choice.
  - Proposed socket paths:
    - `/run/hexe/ai-node/llamacpp.sock`
    - `/run/hexe/ai-node/llamacpp-health.sock`
- Task 903: Add a socket-first llama.cpp Docker Compose runtime
  - Add compose assets for `ghcr.io/ggml-org/llama.cpp:server` or a locally built CUDA-capable image if required.
  - Mount model storage read-only.
  - Mount the runtime socket directory.
  - Enable NVIDIA GPU access where Docker supports it.
  - Avoid externally exposed model-server ports by default.
- Task 904: Add llama.cpp runtime lifecycle control script
  - Add start, stop, restart, status, logs, and ready actions.
  - Include CUDA/GPU preflight checks similar to the voice node STT runtime pattern.
  - Support CPU fallback only when explicitly configured or when GPU preflight fails in auto mode.
- Task 905: Add llama.cpp health wrapper service
  - Add a small Python wrapper that serves health over a Unix socket.
  - Check llama.cpp `/health` and `/v1/models` through the llama.cpp socket.
  - Report configured model ID, readiness, degraded reasons, and optional GPU visibility.
- Task 906: Surface llama.cpp runtime state in node service metadata
  - Include the local LLM runtime in service status and Supervisor heartbeat metadata.
  - Report container/process identity, health status, configured transport, socket path, and model ID.
- Task 907: Implement the local provider adapter over llama.cpp
  - Replace the current local-provider placeholder.
  - Use `httpx` Unix-socket transport when `SYNTHIA_PROVIDER_LOCAL_TRANSPORT=socket`.
  - Support loopback HTTP fallback with `SYNTHIA_PROVIDER_LOCAL_BASE_URL`.
  - Implement health check, model listing, model capability lookup, prompt execution, zero-cost estimation, and metrics.
- Task 908: Add local provider configuration and model defaults
  - Add env/config fields for local provider transport, socket path, base URL fallback, default model, timeout, and runtime mode.
  - Ensure provider selection can enable `local` without requiring cloud credentials.
  - Default model recommendation for this host: `Qwen/Qwen3-8B-GGUF:Q4_K_M`.
- Task 909: Add local versus OpenAI comparison execution endpoint
  - Add an admin/operator endpoint that executes the same normalized prompt against explicit providers/models.
  - Return per-provider status, latency, model, output text, usage, estimated cost, and error fields.
  - Do not use comparison mode as normal production routing.
- Task 910: Add tests and documentation for the llama.cpp local runtime
  - Add tests for compose/control script command construction, socket health wrapper behavior, local adapter success/failure behavior, config loading, and comparison endpoint response shape.
  - Document install, model download, runtime paths, GPU validation, socket mode, TCP fallback, and comparison workflow.

## Task 911-915
Original task source: ad hoc operator request on 2026-05-18.

Summary of preserved scope:
- Download a small candidate set of local LLM models for benchmarking on the RTX 3060 12 GB host.
- Keep the initial set small enough to avoid unnecessary disk and VRAM pressure.
- Measure model load success, prompt-processing speed, generation speed, first-token latency where practical, total latency, memory/VRAM pressure, and sustained GPU load.
- Use the benchmark data to choose the default local model instead of relying only on model reputation.
- Preserve benchmark results in a repo-local runtime/output file and surface them in diagnostics or documentation.

Initial candidate model set:
- Primary general model: `Qwen/Qwen3-8B-GGUF:Q4_K_M`
- Lower-latency general fallback: `Qwen/Qwen3-4B-GGUF:Q4_K_M` if available from the official Qwen GGUF repositories; otherwise use an equivalent official small Qwen GGUF.
- Coding-focused comparator: `Qwen/Qwen2.5-Coder-7B-Instruct-GGUF` with `Q4_K_M` or `Q5_K_M`, depending on fit and availability.
- Tiny smoke/load-control model: `ggml-org/gemma-3-1b-it-GGUF` or another official llama.cpp-compatible 1B-class GGUF.

Task mapping:
- Task 911: Define local LLM benchmark model set
  - Document candidate model IDs, quantization targets, expected purpose, estimated disk/VRAM footprint, and selection rationale.
  - Include enough diversity to compare quality/latency, but avoid downloading many near-duplicates.
- Task 912: Add local LLM model download and manifest tooling
  - Add a script to download configured Hugging Face GGUF models into a node-local model cache.
  - Write a manifest containing model source, quantization, local path, file size, checksum if practical, and download timestamp.
  - Allow skipping already-present models.
- Task 913: Add llama.cpp benchmark runner for candidate models
  - Add a script that runs repeatable prompts through llama.cpp or the llama.cpp server.
  - Capture load time, prompt tokens/second, generation tokens/second, total latency, output length, and errors.
  - Keep prompt set small but representative: classification, summarization, short chat, and coding/helpful-instruction prompt.
- Task 914: Add GPU load and stability test workflow for local LLM runtime
  - Add a bounded stress test that runs concurrent or repeated local inference requests.
  - Capture `nvidia-smi` samples for utilization, memory, temperature, power, and any throttling/error signals.
  - Fail safely if GPU temperature, memory pressure, or process errors exceed configured limits.
- Task 915: Store and surface local LLM benchmark results
  - Persist benchmark results under `data/` or `.run/` using a JSON schema-like structure.
  - Surface the latest benchmark summary through diagnostics or docs.
  - Use results to recommend the default local provider model for this host.

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

## Task 416
Original task source: `docs/New_tasks.txt`

Status:
- Completed on 2026-03-20 through live Core verification plus coordinated Core validator fix.

What was verified live:
- runtime MQTT namespace migrated from `synthia/...` to `hexe/...` for the implemented bootstrap and trusted-status paths
- tests and documentation were updated to match the migrated namespace
- local verification completed through targeted unit/integration test coverage
- live verification confirmed that the node subscribes to `hexe/bootstrap/core`, discovers Core, and attempts registration against `/api/system/nodes/onboarding/sessions`
- live verification also confirmed that on startup the node now honors Core trust-status removal and resets itself from the stale trusted state back to `unconfigured`
- after updating the live Core validator, direct Core onboarding accepted UUIDv4 `node_id` values, created an approved registration, and returned a trust activation payload with the same UUID `node_id`
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

Observed live integration result on 2026-03-20:
- Core API health responded at `http://127.0.0.1:9001/api/health`
- Node control API responded at `http://127.0.0.1:9002/api/node/status`
- node startup queried Core trust status for the stale node identity and Core returned `support_state=removed`
- after restarting setup, the node connected to MQTT host `10.0.0.100:1884`, subscribed to `hexe/bootstrap/core`, discovered Core, and transitioned through `bootstrap_connected -> core_discovered -> registration_pending`
- the original blocker was a Core-side `node_id_invalid` rejection for UUIDv4 node identities
- after updating the live Core validator, the real Core API accepted UUIDv4 `node_id` values and completed `start -> approve -> finalize`
- approved registration record and trust activation payload both preserved `node_id = 123e4567-e89b-42d3-a456-426614174000`

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

## Task 382-386
Original task source: user request on 2026-05-19

Preserved scope:
- Build local LLM shadow benchmarking for OpenAI calls.
- Production execution must continue to use and return the OpenAI response.
- Every successful OpenAI call should be stored as a benchmark source record with enough normalized request/response data to replay locally.
- Each record should track local benchmark status independently for every configured rotation model, initially:
  - `qwen3-8b-q4_k_m`
  - `qwen3-14b-q4_k_m`
  - `gemma-3-12b-it-q4_k_m`
  - `mistral-nemo-instruct-2407-q4_k_m`
- The benchmark worker should run prompts against whichever llama.cpp model is currently loaded.
- Every 15 minutes, the worker should switch llama.cpp to the next benchmark rotation model when there is pending work for that model.
- After switching, the worker should wait for readiness, then process all missing and new benchmark prompts for the currently loaded model.
- Local benchmark failures must be recorded without affecting the OpenAI production result.
- Persist comparison fields useful for the UI:
  - timestamp
  - prompt id/version
  - normalized input snippet or redacted request payload
  - OpenAI model/output/label/confidence/tokens/latency/cost
  - per-local-model output/label/confidence/tokens/latency/status/error
  - per-local-model VRAM used/delta and model load time so operators can weigh accuracy against GPU pressure
  - agreement/mismatch status
- Add a UI table for comparing OpenAI vs local model behavior.
- The UI table should include VRAM as a visible model-choice factor, alongside latency, tokens, confidence, and agreement.
- Keep retention bounded, for example by count or age, so replay data does not grow indefinitely.
- Avoid switching the local model while the local LLM is serving real production work; if that state cannot be detected yet, document and implement a conservative guard.

Measured local runtime VRAM baseline on 2026-05-19:
- Method: `nvidia-smi memory.used` delta from stopped llama.cpp baseline with `--n-gpu-layers 99`.
- Baseline GPU memory before llama.cpp model load: 1,844 MiB used of 12,288 MiB.
- `qwen3-8b-q4_k_m`, ctx 4096: 7,300 MiB total used, 5,456 MiB delta, load 11.667 s.
- `qwen3-14b-q4_k_m`, ctx 4096: 11,072 MiB total used, 9,228 MiB delta, load 14.737 s.
- `gemma-3-12b-it-q4_k_m`, ctx 4096: 11,114 MiB total used, 9,270 MiB delta, load 16.798 s.
- `mistral-nemo-instruct-2407-q4_k_m`, ctx 8192: 10,272 MiB total used, 8,428 MiB delta, load 17.193 s.
- Raw measurement artifact: `.run/local_llm_vram_measurements.json`.

Task mapping:
- Task 382: Persist OpenAI shadow benchmark records for local LLM comparison
- Task 383: Add local LLM benchmark worker with per-model pending status
- Task 384: Add scheduled llama.cpp model switching for queued benchmark replay
- Task 385: Expose local LLM benchmark comparison API
- Task 386: Add local LLM benchmark comparison table to the node UI

## Task 916-924
Original task source: user request on 2026-05-24

Preserved scope:
- Rework benchmarking so the AI Node is an execution-only proxy to provider/model power, not the owner of benchmark truth.
- Benchmark ownership must move to the prompt-owning client node because that node knows:
  - what the prompt is intended to do
  - which labels or outputs are expected
  - which mistakes matter
  - how benchmark results should drive prompt tuning
- The AI Node must not judge correctness, choose winners, or score model outputs for external benchmark requests.
- The AI Node should run requested prompts against requested provider/model targets and return one unified response containing:
  - provider id
  - model id
  - status
  - raw output text
  - parsed structured output when possible
  - token usage when available
  - latency
  - cost when available
  - provider/model errors
  - local runtime metrics when available, such as VRAM and GPU utilization
- Cloud baselines must be optional. A client can request:
  - local-only execution
  - cloud-only execution
  - cloud plus local comparison execution
  - multiple local/cloud candidates in one request
- The original local LLM shadow benchmark was removed after the V2 execution-only API became available.
- Prompt versions `v2.0+` should be treated as the new benchmark-capable prompt contract line.
- Benchmark enablement belongs in the prompt contract/metadata owned by the client or prompt registry, while benchmark execution mode and target provider/model list belong in the execution API request.
- Task family should remain a request field such as `task.classification` or `task.summarization`; do not split into separate `/classify`, `/summarize`, or `/summary` API routes unless a future standards decision requires convenience wrappers.
- The canonical API should stay task-family based so new tasks do not require new routes.
- Documentation must clearly distinguish:
  - legacy node-local shadow benchmarking: Removed
  - new client-owned execution-only benchmark API: Implemented
  - prompt tuning consumers: client-owned, not AI Node judgment
- Add V2+ JSON schemas under `docs/json-schemas` for prompt registration, execution, benchmark execution requests/responses, and schema discovery.
- Add a future schema discovery route so client developers and client nodes can request the prompt registration and execution schemas from the AI Node instead of reading repository files directly.
- Until schema discovery routes are implemented, developers must use repository-local schema files directly.

Task mapping:
- Task 916: Document the execution-only benchmark architecture and migration boundary
- Task 917: Add prompt contract support for benchmark-capable prompt versions v2.0 and later
- Task 918: Add an execution-only multi-target benchmark API that returns provider/model outputs without scoring
- Task 919: Support cloud-optional and local-only benchmark execution targets
- Task 920: Preserve the existing local LLM shadow benchmark during migration (superseded by Task 923 removal)
- Task 921: Move benchmark ownership, expected outputs, and scoring to prompt-owning client nodes
- Task 922: Add benchmark execution result schemas and tests for raw and parsed outputs
- Task 923: Remove the legacy node-local benchmark surface after V2 execution-only benchmark support
- Task 924: Add migration docs for prompt tuning workflows that consume benchmark execution results
- Task 925: Add client AI V2 schema discovery endpoints for prompt and execution contracts
