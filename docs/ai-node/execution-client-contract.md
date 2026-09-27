# AI Node Execution Client Contract

Status: Partially implemented

This is the canonical contract for clients that resolve Hexe AI Node through Core. Code is authoritative where behavior is marked not developed.

## Identity and service discovery

`requested_by` is the caller principal, normally the Core node ID carried by the service-token subject. Execution-request `service_id` is the caller's logical service principal used for prompt access and budget selection; it defaults to `requested_by`. It is not the selected Core catalog service, prompt owner, executor, billing principal, or customer. `customer_id`, when present, selects the customer/budget context.

Prompt records separately use `service_id` and `owner_service` for the prompt-owning service. AI Node currently validates identity fields only as bounded non-empty strings. Token-to-identity validation is not developed.

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

The shared schema is `GET /api/schemas/client-ai/v2/image-generation-inputs.v1.schema.json`. It intentionally permits additional properties for template/provider controls. The weather schema requires `image_type=scenery`, `condition`, and `day_night`, and uses Draft 2020-12 `unevaluatedProperties: false` to reject unknown properties after shared properties are evaluated.

Canonical controls are `output_format=png`, `quality=low|medium|high`, `width`, `height`, `steps`, `cfg`, `denoise`, and `seed`. Local quality maps to 4, 6, or 8 steps when `steps` is absent. Dimensions are normalized to multiples of 8 within 256–4096. `size`, `target_width`, and `target_height` are compatibility inputs; no separate resize stage exists.

## Prompt versions and input schemas

Prompt versions are immutable and coexist. Creation adds the first version. `PUT /api/prompts/services/{prompt_id}` appends a version when `definition` or `version` is supplied; it never replaces an existing version. Reuse fails with `duplicate_prompt_version`. `GET /api/prompts/services/{prompt_id}` exposes `current_version` and all versions.

Queued requests pinned with `prompt_version` continue using it. Unpinned work resolves the current version at execution time, so reproducible clients must pin. A metadata-only update changes prompt-level metadata and does not mutate an existing version.

Each immutable version may associate its input schema in metadata:

```json
{
  "input_schema_id": "https://hexe.local/schemas/client-ai/v2/weather-scenery-inputs.v1.schema.json",
  "input_schema_url": "/api/schemas/client-ai/v2/weather-scenery-inputs.v1.schema.json"
}
```

Persistence and discovery are implemented. Automatic server-side validation against the referenced schema is not developed; callers and prompt owners currently validate inputs.

## Direct, queued, and accepted responses

`POST /api/execution/direct` is deterministic by `response_mode`: `sync` waits for a terminal execution result; `async_if_queued` creates a job and returns an `execution-job.v2` queued acknowledgement. It does not switch modes based on capacity.

`accepted` is not terminal and is excluded from published `execution-response.v2`. Async clients continue by polling the acknowledgement's `status_url`. The internal Python result model still accepts `accepted` for legacy callers, but it is outside the V2 terminal contract.

Queued clients poll no faster than `check_after_seconds`. Terminal statuses are `completed`, `failed`, `cancelled`, and `expired_wait_budget`; completed jobs put the execution envelope in `result`.

## Timeout ownership

The effective provider budget is `min(request.timeout_s, prompt.constraints.max_timeout_s)` when both exist, so the prompt ceiling wins over a larger request value. Queue wait is separate: its boundary is the earliest of `queue.deadline_at` and enqueue time plus `queue.max_wait_seconds`. Exhaustion before dispatch yields terminal `expired_wait_budget` and consumes no provider execution budget.

The caller owns its HTTP timeout. For sync calls it should exceed the effective provider budget; for polling it should be short and repeatable. A client timeout does not cancel server work. Job `expires_at` is record-TTL metadata, not an execution deadline or guaranteed deletion time.

## Canonical images and artifact lifetime

Clients consume `output.images[]`. Every completed image artifact guarantees a non-empty `url`, positive `width`, `height`, and `size_bytes`, plus an image MIME type. `relative_path` is informational and may be null. A relative URL is resolved against Core's `provider_api_base_url`; clients must use `url` instead of constructing filesystem paths.

Local artifact routes currently have no route authentication, URL signature, or URL-specific expiration. Files live under configured runtime output storage and survive API restarts. Ordinary generated images are retained for 30 days by default. Weather scenery is bounded more tightly to seven days and the newest 100 files by default. These limits are configurable, so clients needing durable ownership should download promptly. Retry a failed artifact retrieval as GET only; do not automatically regenerate unless duplicates are acceptable.

A completed asynchronous job containing images includes `artifact_ack` with the acknowledgement URL, method, and job-scoped request body. After every image has been downloaded and durably stored, the client posts that body to `POST /api/execution/artifacts/ack`. This means all job artifacts were retrieved and are no longer needed. The operation is idempotent, records `artifact_acknowledgement` on the job, and immediately deletes node-local artifact files; non-local artifact URLs are acknowledged but retained by their owning provider. Clients must not acknowledge after only a partial download.

Legacy `output.image` and `output.text` on visual results are compatibility fields and may be deprecated. Inline image bytes are not canonical.

## Authentication

Core resolution and authorization require Core contracts and credentials. AI Node HTTP route token verification is not developed for prompt lookup/create/update, direct execution, route preview, job polling/cancellation, or artifact retrieval. The live OpenAPI therefore declares no security scheme. Deployments must keep these routes behind a trusted network boundary.

## Identifier, retry, and restart semantics

`task_id` and `trace_id` are non-empty UTF-8 strings up to 128 characters. UUIDs or caller-namespaced IDs are recommended. `task_id` identifies caller work; `trace_id` correlates telemetry and may equal `task_id`. Uniqueness is caller-scoped for the caller's retention window; AI Node supplies no separate retention guarantee and does not reject collisions.

Neither ID is an idempotency key. Repeated submission creates new work. On an ambiguous POST result, use a received `job_id`; otherwise retry only if duplicates are acceptable. Polling may resume after client timeout/network loss. Persisted terminal records remain pollable after API restart while present, but in-memory queued/running work may be lost. `expired_wait_budget` requires a new request.

## Cancellation and expiration

Cancellation schemas are `execution-job-cancel.v2.request.schema.json` and `execution-job-cancel.v2.response.schema.json`. `DELETE /api/execution/jobs/{job_id}` cancels queued work. Success returns HTTP 200 with terminal `cancelled`. If dispatch wins the race or the job is terminal, HTTP 409 returns `cancellable=false` and `cancel_rejected_reason`; running provider work is not stopped.

`expired_wait_budget` means dispatch did not start before the queue boundary and no provider work continues for that job. `expires_at` only describes configured record TTL; automatic deletion at that time is not developed and it never cancels work.

## Core publication

AI Node publishes a Core capability manifest containing supported task families, supported/enabled provider classes, and per-task `capability_endpoints` with direct execution method, path, and absolute URL. Core derives `provider_api_base_url` from the registered node API base. Direct execution is `/api/execution/direct`, polling is `/api/execution/jobs/{job_id}`, and local artifacts use `/api/manual-image-generation/outputs/`.

The current Core declaration does not have separate polling/artifact-base fields or concrete-executor IDs. Clients derive those paths from this contract; terminal `provider_used` and `resolution_metadata.concrete_executor` are authoritative for the executor. Dedicated Core fields require a coordinated Core contract change and are not implemented here.

## APIs

- `GET /api/schemas/client-ai/v2`
- `GET /api/schemas/client-ai/v2/execution-request.v2.schema.json`
- `GET /api/schemas/client-ai/v2/image-generation-inputs.v1.schema.json`
- `GET /api/schemas/client-ai/v2/weather-scenery-inputs.v1.schema.json`
- `GET /api/schemas/client-ai/v2/execution-response.v2.schema.json`
- `GET /api/schemas/client-ai/v2/execution-job.v2.schema.json`
- `GET /api/schemas/client-ai/v2/execution-job-cancel.v2.request.schema.json`
- `GET /api/schemas/client-ai/v2/execution-job-cancel.v2.response.schema.json`
- `POST /api/execution/route-preview`
- `POST /api/execution/direct`
- `GET /api/execution/jobs/{job_id}`
- `DELETE /api/execution/jobs/{job_id}`
- `POST /api/execution/artifacts/ack`
- `GET /api/prompts/services/{prompt_id}`
- `POST /api/prompts/services`
- `PUT /api/prompts/services/{prompt_id}`
- `GET /api/manual-image-generation/outputs/{relative_path}`
