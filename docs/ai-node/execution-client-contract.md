# AI Node Execution Client Contract

Status: Partially implemented

This is the canonical local contract for nodes that resolve Hexe AI Node through Core and call its execution API. Code remains authoritative where a behavior is marked not developed.

## Identity and service discovery

`requested_by` is the trusted caller principal, normally the Core node ID from the service-token subject. A stable logical client ID remains accepted for deployments that do not yet enforce service tokens.

Execution-request `service_id` is the caller's logical service principal used for prompt access and budget selection. It is not the selected Core catalog service and it is not the prompt record's identity. If omitted, budget enforcement falls back to `requested_by`. For Interaction weather calls the correct value is `hexe-interaction`; `hexe-interaction.weather-backgrounds` is appropriate only if Core and prompt access policy recognize it as a separate caller service.

Prompt records separately contain `service_id` and `owner_service`; those fields identify the prompt-owning service.

Callers must use Core resolution's `provider_api_base_url` plus the advertised execution path. Hostnames such as `http://hexe-ai:9002` are illustrative and must not override Core resolution.

## Provider identity

Provider identity has two levels:

- `local` and cloud provider IDs are routing/provider classes used by Core resolution, Core authorization, and request `requested_provider`.
- `provider_used` is the concrete executor that completed the work, such as `visual_runtime`, `vision_runtime`, or `openai`.

For local image execution, clients prove that cloud was not used by requiring all of:

- request effective routing policy is `local_only`
- terminal `resolution_metadata.provider_class` is `local`
- terminal `resolution_metadata.execution_location` is `local`
- terminal `resolution_metadata.cloud_used` is `false`
- terminal `provider_used` is `visual_runtime`

Core candidates and authorization therefore use `provider=local`; they must not use `visual_runtime` as the Core provider ID.

## Routing-policy precedence

Core governance is the outer boundary. Prompt policy is the prompt-owned boundary. A request may narrow that boundary but cannot broaden it. The AI Node merges these constraints and rejects a conflict; the provider runtime receives only the resulting route. For a local-only prompt, a request cannot enable cloud fallback.

## Image inputs

The canonical schema is `GET /api/schemas/client-ai/v2/image-generation-inputs.v1.schema.json`.

`image_type` is optional in the global image-input contract. Prompt-specific schemas may require it. The weather contract at `GET /api/schemas/client-ai/v2/weather-scenery-inputs.v1.schema.json` requires `image_type=scenery`, `condition`, and `day_night`. The value is semantic input owned by the caller. `image_type=scenery` selects the generic local scenery template only when neither an explicit request template nor a governed prompt template binding exists.

Canonical controls are:

- `output_format`: `png` for the local visual runtime
- `quality`: portable `low|medium|high` hint; local execution maps it to 4, 6, or 8 steps when `steps` is absent
- `width` and `height`: requested generation dimensions, normalized to the nearest multiple of 8 in the range 256–4096
- `steps`, `cfg`, `denoise`, and `seed`: optional advanced generation controls

Compatibility controls:

- `size=WIDTHxHEIGHT` supplies generation dimensions only when `width` or `height` is absent
- `target_width` and `target_height` fall back to generation dimensions
- no distinct post-generation resize stage is implemented, so target dimensions do not describe a second output size

Prompt-specific schemas may set `additionalProperties: false`; the global image schema remains extensible because templates and cloud providers have additional controls.

## Prompt versions and schema association

Prompt versions are immutable entries. Updating a prompt with a new version appends it and makes it current. Existing versions coexist and remain selectable when version pinning is allowed. Reusing a version returns `duplicate_prompt_version`. `GET /api/prompts/services/{prompt_id}` exposes `current_version` and all stored versions. Callers that require stable queued behavior must send `prompt_version`; an unpinned queued request may resolve the then-current prompt when it starts.

Prompt-version metadata associates an input contract without binding the prompt to a node-owned template:

```json
{
  "input_schema_id": "https://hexe.local/schemas/client-ai-v2/weather-scenery-inputs.v1.schema.json",
  "input_schema_url": "/api/schemas/client-ai/v2/weather-scenery-inputs.v1.schema.json"
}
```

Schema-reference persistence is implemented through version metadata. Automatic JSON Schema validation of prompt inputs is not developed; callers and prompt owners must currently validate against the referenced schema.

## Direct and queued execution

`POST /api/execution/direct` is deterministic by `response_mode`:

- `sync`: holds the connection until terminal execution or an execution timeout/error
- `async_if_queued`: always creates a queue job and immediately returns a queued acknowledgement

It does not dynamically switch modes based on capacity.

Queued flow:

1. Submit with `response_mode=async_if_queued`.
2. Read `job_id`, `status_url`, `check_after_seconds`, queue information, and `expires_at`.
3. Poll `GET /api/execution/jobs/{job_id}` no faster than `check_after_seconds`.
4. Terminal job statuses are `completed`, `failed`, `cancelled`, and `expired_wait_budget`.
5. On `completed`, consume the terminal execution envelope from `result`.
6. On failure or cancellation, consume `error.code` and `error.message`.
7. Cancel queued work with `DELETE /api/execution/jobs/{job_id}` and optional `{"reason":"..."}`. Running jobs currently return HTTP 409 and are not cancellable.

`expires_at` currently records the configured queue-job TTL. Automatic terminal-record deletion at that timestamp is not developed, so clients must not treat it as a guaranteed deletion instant.

Task-ID idempotent replay is not developed. Repeating `POST /api/execution/direct` creates another execution or queue job even when `task_id` is reused. Clients must avoid automatic POST retries unless they can establish that the first request was not accepted.

## Timeout ownership

`timeout_s` is the caller's provider/execution budget. Prompt `constraints.max_timeout_s` is a ceiling, so the effective execution timeout is the smaller positive value. Queue waiting is separate and is controlled by `queue.max_wait_seconds` and `queue.deadline_at`. The HTTP client deadline is caller-owned and should exceed the effective timeout for synchronous calls. For queued calls, the client polling deadline is caller-owned and independent of provider execution timeout.

The queue job TTL controls status-record metadata; it is not a provider timeout. Core service-token expiry controls authorization validity and is also separate.

## Canonical results and images

Terminal results use `GET /api/schemas/client-ai/v2/execution-response.v2.schema.json`. Queued responses and job status use `GET /api/schemas/client-ai/v2/execution-job.v2.schema.json`.

The canonical image representation is:

```json
{
  "output": {
    "images": [
      {
        "url": "/api/manual-image-generation/outputs/hexe/scenery/example.png",
        "relative_path": "hexe/scenery/example.png",
        "mime_type": "image/png",
        "width": 1344,
        "height": 768,
        "size_bytes": 123456
      }
    ]
  }
}
```

Clients must consume `output.images[]`. `image_base64`, `b64_json`, nested provider `images[].b64_json`, and JSON embedded in `output.text` are not canonical. Existing `output.image` and `output.text` values on local visual results are compatibility fields and may be deprecated after clients migrate. Image bytes are retrieved with the artifact `url`; the execution response does not inline image bytes.

## Authentication status

Core resolution and authorization require the Core contracts and Core-issued credentials. On the current AI Node implementation, prompt lookup/update, direct execution, queue status/cancellation, and generated-image retrieval do not enforce the Core-issued service token at the HTTP route layer. They rely on the deployment network boundary and prompt-access fields.

Per-route service-token verification is **Not developed**. Clients must not assume that presenting the Core token is currently verified by AI Node, and operators must not expose these routes to an untrusted network. A future authentication implementation must apply the same accepted token to execution, its job status/cancellation, and artifact retrieval while keeping administrative tokens separate.

## Identifiers

`task_id` identifies the caller's logical execution. `trace_id` correlates that execution with logs and upstream work; it may equal `task_id` but does not have to. Both are non-empty strings and should be globally unique for the caller's retention window. Neither field is currently an idempotency key. `job_id` is generated by AI Node for each queued submission.

## APIs

- `GET /api/schemas/client-ai/v2`
- `GET /api/schemas/client-ai/v2/execution-request.v2.schema.json`
- `GET /api/schemas/client-ai/v2/image-generation-inputs.v1.schema.json`
- `GET /api/schemas/client-ai/v2/weather-scenery-inputs.v1.schema.json`
- `GET /api/schemas/client-ai/v2/execution-response.v2.schema.json`
- `GET /api/schemas/client-ai/v2/execution-job.v2.schema.json`
- `POST /api/execution/route-preview`
- `POST /api/execution/direct`
- `GET /api/execution/jobs/{job_id}`
- `DELETE /api/execution/jobs/{job_id}`
- `GET /api/prompts/services/{prompt_id}`
- `POST /api/prompts/services`
- `PUT /api/prompts/services/{prompt_id}`
- `GET /api/manual-image-generation/outputs/{relative_path}`
