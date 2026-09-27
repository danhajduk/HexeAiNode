# AI Node Execution Client Contract

Status: Implemented for Core-authorized execution

This is the canonical contract for clients that resolve Hexe AI Node through Core. Code is authoritative where behavior is marked not developed.

## Identity and service discovery

`requested_by` and execution-request `service_id` identify the caller principal carried by the Core service-token subject. `service_id` defaults to `requested_by`; both must match the verified JWT `sub`. They are not the selected Core catalog service, prompt owner, executor, billing principal, or customer. `customer_id`, when present, selects the customer/budget context.

Prompt records separately use `service_id` and `owner_service` for the prompt-owning service. Production execution routes require the Core-issued service token as an `Authorization: Bearer <token>` header. AI Node introspects the token through Core, requires `service.execute:<task_family>`, binds `requested_by` and `service_id` to JWT `sub`, binds the provider node and provider to JWT `aud`, and fails closed when validation is inactive or unavailable.

The expected execution audience is `node-service:<provider-node-id>:<provider>`. When `requested_provider` is omitted, the verified audience supplies it; when it is present, it must match the verified audience.

Clients use Core resolution's `provider_api_base_url` plus the advertised execution path. Hard-coded example hostnames must not override Core resolution.

## Provider identity and mapping

Provider identity has two levels: Core/provider classes such as `local` and `openai`, and concrete executors such as `visual_runtime`, `vision_runtime`, and `openai`.

| Core/request concept | AI Node field | Meaning |
| --- | --- | --- |
| requested candidate | `requested_provider` | Optional caller preference inside Core authorization and prompt policy. |
| authorized/resolved class | `resolution_metadata.provider_class`, `resolution_metadata.selected_provider` | `local` or the authorized cloud provider ID. |
| actual runtime | `provider_used`, `resolution_metadata.concrete_executor` | Executor that performed the work. |
| locality | `resolution_metadata.execution_location` | `local` or `cloud`. |

For completed `local_only` work, the response schema normatively requires:

```json
{
  "provider_class": "local",
  "execution_location": "local",
  "cloud_used": false,
  "routing_policy_mode": "local_only"
}
```

Local image execution additionally returns `provider_used=visual_runtime`. `resolution_metadata` may be null only when a request ends before provider resolution.

## Routing-policy precedence

Core authorization is the outer boundary. The selected prompt version's `constraints.routing_policy.mode` is the prompt-owned boundary. Request `constraints.routing_policy.mode` may narrow but cannot broaden it. Queue policy may further restrict the result and provider availability is evaluated last; neither may add a provider excluded earlier.

The effective provider set is the intersection of Core, prompt, request, and queue policy. AI Node enforces the prompt/request merge before provider selection. An empty intersection fails with `prompt_routing_policy_conflict`; it never silently falls back. “Prompt boundary” refers to that selected prompt-version policy, not to a V3 prompt version.

## Image inputs and weather strictness

The shared schema is `GET /api/schemas/client-node/v2/image-generation-inputs.v1.schema.json`. It intentionally permits additional properties for template/provider controls. The weather schema requires `image_type=scenery`, `condition`, and `day_night`, and uses Draft 2020-12 `unevaluatedProperties: false` to reject unknown properties after shared properties are evaluated.

Canonical controls are `output_format=png`, `quality=low|medium|high`, `width`, `height`, `steps`, `cfg`, `denoise`, and `seed`. Local quality maps to 4, 6, or 8 steps when `steps` is absent. Dimensions are normalized to multiples of 8 within 256–4096. `size`, `target_width`, and `target_height` are compatibility inputs; no separate resize stage exists.

## Prompt versions and input schemas

Prompt versions are immutable and coexist. Creation adds the first version. `PUT /api/prompts/services/{prompt_id}` appends a version when `definition` or `version` is supplied; it never replaces an existing version. Reuse fails with `duplicate_prompt_version`. `GET /api/prompts/services/{prompt_id}` exposes `current_version` and all versions.

The canonical stored grammar is `vMAJOR.MINOR` with an optional `.PATCH`; each numeric component is decimal without leading zeroes, except the value `0`. The accepted `vMAJOR` shorthand is normalized before persistence and lookup, so `v10` becomes `v10.0`. Registration rejects all other forms. Execution additionally recognizes the historical exact-match form `YYYY-MM-DD.vMAJOR` so already-persisted versions remain addressable; this compatibility form cannot be used to register a new version. State loading migrates major-only stored versions in memory and rejects collisions such as stored `v10` plus `v10.0`.

Queued requests pinned with `prompt_version` continue using it. Unpinned work resolves the current version at execution time, so reproducible clients must pin. A metadata-only update changes prompt-level metadata and does not mutate an existing version.

Each immutable version may associate its input schema in metadata:

```json
{
  "input_schema_id": "https://hexe.local/schemas/client-node/v2/weather-scenery-inputs.v1.schema.json",
  "input_schema_url": "/api/schemas/client-node/v2/weather-scenery-inputs.v1.schema.json"
}
```

The node resolves only schemas published from its local Client Node V2 catalog. When either reference is present, it validates `inputs` against the selected immutable prompt version before template expansion, routing, queue insertion, or provider execution. If both references are present they must identify the same schema. External URLs, traversal paths, missing schemas, invalid schemas, and mismatched references fail closed.

Invalid direct-execution or route-preview inputs return HTTP 422 with `detail.error_code=prompt_input_validation_failed` and field-level `detail.diagnostics`. Each diagnostic contains a JSON-pointer-like `path`, the failed schema `keyword`, and a message. Schema-resolution failures use stable `prompt_input_schema_*` error codes. The authorization preview returns the same error code as its denial `reason` and includes diagnostics. Validation applies equally to synchronous and queued requests, so invalid work is never enqueued or sent to a provider.

## Direct, queued, and accepted responses

`POST /api/execution/direct` is deterministic by `response_mode`: `sync` waits for a terminal execution result; `async_if_queued` creates a job and returns an `execution-job.v2` queued acknowledgement. It does not switch modes based on capacity.

`accepted` is not terminal and is excluded from published `execution-response.v2`. Async clients continue by polling the acknowledgement's `status_url`. The internal Python result model still accepts `accepted` for legacy callers, but it is outside the V2 terminal contract.

Queued clients poll no faster than `check_after_seconds`. Terminal statuses are `completed`, `failed`, `cancelled`, and `expired_wait_budget`; completed jobs put the execution envelope in `result`.

## Timeout ownership

The effective provider budget is `min(request.timeout_s, prompt.constraints.max_timeout_s)` when both exist, so the prompt ceiling wins over a larger request value. Queue wait is separate: its boundary is the earliest of `queue.deadline_at` and enqueue time plus `queue.max_wait_seconds`. Exhaustion before dispatch yields terminal `expired_wait_budget` and consumes no provider execution budget.

The caller owns its HTTP timeout. For sync calls it should exceed the effective provider budget; for polling it should be short and repeatable. A client timeout does not cancel server work. Job `expires_at` is the automatic deletion time for terminal status records, not an execution deadline; terminal transitions reset it from the completion time.

## Canonical images and artifact lifetime

Clients consume `output.images[]`. Every completed image artifact guarantees a non-empty `url`, positive `width`, `height`, and `size_bytes`, plus an image MIME type. `relative_path` is informational and may be null. A relative URL is resolved against Core's `provider_api_base_url`; clients must use `url` instead of constructing filesystem paths.

Local artifact retrieval requires a Core service token with `ai.artifacts.read`; URLs are not signed and have no URL-specific expiration. Files live under configured runtime output storage and survive API restarts. Ordinary generated images are retained for 30 days by default. Weather scenery is bounded more tightly to seven days and the newest 100 files by default. These limits are configurable, so clients needing durable ownership should download promptly. Retry a failed artifact retrieval as GET only; do not automatically regenerate unless duplicates are acceptable.

A completed asynchronous job containing images includes `artifact_ack` with the acknowledgement URL, method, and job-scoped request body. After every image has been downloaded and durably stored, the client posts that body to `POST /api/execution/artifacts/ack`. This means all job artifacts were retrieved and are no longer needed. The operation is idempotent, records `artifact_acknowledgement` on the job, and immediately deletes node-local artifact files; non-local artifact URLs are acknowledged but retained by their owning provider. Clients must not acknowledge after only a partial download.

Image-generation inputs may include `artifact_lifetime`. Use `short_lived` for node-local artifacts that may be deleted after one hour, or `long_term` to use the node's general generated-image retention period. If omitted, the existing output-class retention policy remains in effect. Completed local image artifacts echo `artifact_lifetime`, `created_at`, and `expires_at` when an explicit lifetime was requested. Artifact acknowledgement can still delete either class earlier.

Legacy `output.image` and `output.text` on visual results are compatibility fields and may be deprecated. Inline image bytes are not canonical.

## Authentication

Client routes accept `Authorization: Bearer <Core-issued-token>`. AI Node validates the token through Core and fails closed on invalid, revoked, expired, insufficiently scoped, or unverifiable tokens. The live OpenAPI declares `CoreServiceBearer` and publishes required scopes per operation.

Execution and route-preview operations require `service.execute:<task_family>`. Prompt reads require `ai.prompts.read`; writes require `ai.prompts.write`; lifecycle and review operations require their corresponding `ai.prompts.lifecycle` or `ai.prompts.review` scope. Job polling and cancellation require `ai.jobs.read` and `ai.jobs.cancel`. Artifact retrieval and acknowledgement require `ai.artifacts.read` and `ai.artifacts.ack`. Prompt catalog/detail responses are filtered by the verified caller and prompt access policy, and prompt mutations require ownership. Job operations are restricted to the verified job owner.

The Core-proxied WebUI uses the separate `X-Hexe-Management-Authorization` operator contract; it does not reuse client service tokens.

## Identifier, retry, and restart semantics

`task_id`, `trace_id`, and optional `idempotency_key` are non-empty UTF-8 strings up to 128 characters. UUIDs or caller-namespaced IDs are recommended. `task_id` identifies caller work; `trace_id` correlates telemetry and may equal `task_id`. Neither is silently treated as an idempotency key.

When `idempotency_key` is supplied, the node scopes it to the verified `requested_by` caller and hashes the normalized complete request. An exact retry returns the original synchronous result or queued acknowledgement without creating work. Concurrent exact submissions join the first submission. Reuse by the same caller with a different request returns HTTP 409 `idempotency_key_conflict`; a different caller may reuse the same key safely.

Completed mappings persist across backend restarts for `HEXE_EXECUTION_IDEMPOTENCY_RETENTION_SECONDS`, which defaults to 24 hours and has a 60-second minimum. After expiration the key may create new work. Failed submissions are not retained and may be retried. Polling may resume after client timeout/network loss. Persisted terminal records remain pollable after API restart while present.

Persisted jobs that were still `queued` restart with the same request, caller, routing decision, queue intent, priority, and job ID. Their status payload includes `recovery.status=queued_for_resume`. A job persisted as `running` is never automatically replayed because provider dispatch may already have occurred; it becomes terminal `failed` with `execution_queue_restart_while_running` and `recovery.status=not_replayed`. This fail-closed boundary prevents accidental duplicate provider work. `expired_wait_budget` requires a new request.

## Cancellation and expiration

Cancellation schemas are `execution-job-cancel.v2.request.schema.json` and `execution-job-cancel.v2.response.schema.json`. `DELETE /api/execution/jobs/{job_id}` cancels queued work and cooperatively cancels running provider-managed work when `running_cancellation_supported` is true. Success returns HTTP 200 with terminal `cancelled` and releases the queue slot. HTTP 409 returns `cancellable=false` and a stable `cancel_rejected_reason`: `running_cancellation_unsupported`, `running_cancellation_unavailable`, or `job_already_<terminal-status>`. Local vision and visual-runtime work cannot currently be interrupted after dispatch.

`expired_wait_budget` means dispatch did not start before the queue boundary and no provider work continues for that job. Terminal jobs are automatically removed after `expires_at`; subsequent status, cancellation, or artifact-acknowledgement requests return HTTP 404 with `{"detail":"job_not_found"}`. `not_found` is not an execution-job status. Job-record expiration does not delete image files or their independent retention metadata. Cancelling a running job clears any partial result and artifact acknowledgement; image artifacts already created before cancellation remain governed by their image-retention metadata.

## Core publication

AI Node publishes a Core capability manifest containing supported task families, supported/enabled provider classes, and per-task `capability_endpoints`. The direct-execution entry retains `transport`, `method`, `path`, and absolute `url`, which Core uses to publish the authoritative `provider_api_base_url` and `execution_endpoint_url` during service resolution.

Each capability endpoint also publishes relative, base-URL-independent metadata for direct request/response schemas, job polling, cancellation, artifact retrieval, artifact acknowledgement, and Client Node V2 schema discovery. The `concrete_executors` list identifies the enabled execution implementations for that task family, including `local`, `visual_runtime`, `vision_runtime`, and enabled cloud provider IDs as applicable. Core preserves this metadata in the resolved candidate's `capability_endpoint`; clients resolve every relative path against `provider_api_base_url` and do not construct paths or use the declaration-time absolute URL as a separate authority. Terminal `provider_used` and `resolution_metadata.concrete_executor` remain authoritative for the executor that actually ran a request.

## APIs

- `GET /api/schemas/client-node/v2`
- `GET /api/schemas/client-node/v2/execution-request.v2.schema.json`
- `GET /api/schemas/client-node/v2/image-generation-inputs.v1.schema.json`
- `GET /api/schemas/client-node/v2/weather-scenery-inputs.v1.schema.json`
- `GET /api/schemas/client-node/v2/execution-response.v2.schema.json`
- `GET /api/schemas/client-node/v2/execution-job.v2.schema.json`
- `GET /api/schemas/client-node/v2/execution-job-not-found.v1.response.schema.json`
- `GET /api/schemas/client-node/v2/execution-job-cancel.v2.request.schema.json`
- `GET /api/schemas/client-node/v2/execution-job-cancel.v2.response.schema.json`
- `POST /api/execution/route-preview`
- `POST /api/execution/direct`
- `GET /api/execution/jobs/{job_id}`
- `DELETE /api/execution/jobs/{job_id}`
- `POST /api/execution/artifacts/ack`
- `GET /api/prompts/services/{prompt_id}`
- `POST /api/prompts/services`
- `PUT /api/prompts/services/{prompt_id}`
- `GET /api/manual-image-generation/outputs/{relative_path}`
