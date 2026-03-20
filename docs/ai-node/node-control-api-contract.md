# AI Node Control API Contract

Status: Implemented
Last updated: 2026-03-12

## Purpose

Defines the node-local FastAPI control surface exposed by `src/ai_node/runtime/node_control_api.py`.

This is the canonical source-of-truth contract for:

- onboarding initiation/restart
- provider and task-capability configuration
- capability declaration trigger
- governance/provider refresh operations
- periodic provider intelligence refresh job lifecycle
- degraded recovery trigger
- service status/restart controls
- prompt/service registration and probation controls
- execution authorization gate scaffolding
- provider runtime visibility debug endpoints

## API Root

- `GET /`
- Returns service metadata and stable endpoint list.

## Health

- `GET /api/health`
- Response:
  - `{"status":"ok"}`

## Node Status

- `GET /api/node/status`
- Response includes:
  - lifecycle status (`status`)
  - onboarding context (`pending_approval_url`, session identifiers)
  - node identity (`node_id`, `identity_state`)
  - startup/trusted context (`startup_mode`, `trusted_runtime_context`)
  - capability setup contract (`capability_setup`)
  - capability runtime state (`capability_declaration`)
  - service status (`services`)
- Behavior:
  - when Core trust-status explicitly reports `support_state=removed`, the node clears its trusted linkage and falls back to `unconfigured` for re-onboarding

## Onboarding

### Initiate onboarding

- `POST /api/onboarding/initiate`
- Request:
  - `mqtt_host: string`
  - `node_name: string`
    Human-friendly node label sent to Core. Spaces are allowed; only a non-empty value is required.
- Success: updated node status payload.
- Error:
  - `400` for invalid lifecycle/input.

### Restart onboarding

- `POST /api/onboarding/restart`
- Success: node reset to `unconfigured` and updated status payload.

## Provider Configuration

### Read provider selection

- `GET /api/providers/config`
- Response:
  - `configured: boolean`
  - `config: object | null`

### Update provider selection

- `POST /api/providers/config`
- Request:
  - `openai_enabled: boolean`
- Success: updated provider config payload.
- Error:
  - `400` when provider store is unavailable.

### Read OpenAI credential summary

- `GET /api/providers/openai/credentials`
- Response:
  - `provider: "openai"`
  - `configured: boolean`
  - `credentials`
    - redacted token hints only
    - `has_api_token`
    - `has_service_token`
    - `project_name`
    - `updated_at`

### Save OpenAI credentials

- `POST /api/providers/openai/credentials`
- Request:
  - `api_token: string`
  - `service_token: string`
  - `project_name: string`
- Success: redacted OpenAI credential summary payload.
- Error:
  - `400` when provider credential validation/store fails.

### Save OpenAI preferred model

- `POST /api/providers/openai/preferences`
- Request:
  - `default_model_id?: string | null`
  - `selected_model_ids?: string[] | null`
- Success: redacted OpenAI credential summary payload with:
  - `credentials.default_model_id`
  - `credentials.selected_model_ids`
- Behavior:
  - `selected_model_ids` stores the full preferred model list
  - `default_model_id` is treated as the primary model and defaults to the first selected model
- Error:
  - `400` when provider credential preference persistence fails.

### Read latest OpenAI models

- `GET /api/providers/openai/models/latest?limit=<n>`
- Query:
  - `limit: integer` optional; API default is `3`
- Response:
  - `provider_id: "openai"`
  - `models[]`
    - `model_id`
    - `display_name`
    - `created`
    - `status`
    - `pricing.input_per_1m_tokens`
    - `pricing.output_per_1m_tokens`
    - `pricing.pricing_basis`
    - `pricing.normalized_price`
    - `pricing.normalized_unit`

### Read filtered OpenAI provider model catalog

- `GET /api/providers/openai/models/catalog`
- Response:
  - `provider_id: "openai"`
  - `models[]`
    - `model_id`
    - `family`
    - `discovered_at`
    - `enabled`
  - `ui_models[]`
    - representative subset of `models[]` used by `/#/providers/openai`
    - same object shape as `models[]`

For OpenAI, this response only includes regular base-model families used for normal LLM selection. Date-stamped snapshots such as `gpt-5.4-pro-2026-03-05`, legacy snapshots such as `gpt-4-0613`, and specialized variants containing tags like `latest`, `preview`, `realtime`, `audio`, `codex`, or `search` are filtered out in favor of canonical model IDs such as `gpt-5.4-pro`.

### Read OpenAI model capability catalog

- `GET /api/providers/openai/models/capabilities`
- Response:
  - `provider_id: "openai"`
  - `classification_model: string | null`
  - `entries[]`
    - `model_id`
    - `family`
    - `reasoning`
    - `vision`
    - `image_generation`
    - `audio_input`
    - `audio_output`
    - `realtime`
    - `tool_calling`
    - `structured_output`
    - `long_context`
    - `coding_strength`
    - `speed_tier`
    - `cost_tier`
    - `feature_flags` (boolean feature map)

### Read OpenAI model feature catalog

- `GET /api/providers/openai/models/features`
- Response:
  - `schema_version`
  - `generated_at`
  - `entries[]`
    - `model_id`
    - `provider`
    - `classification_model`
    - `classified_at`
    - `features` (boolean feature map)

### Read resolved node task capabilities

- `GET /api/capabilities/node/resolved`
- Response:
  - `schema_version`
  - `capability_graph_version`
  - `enabled_models[]`
  - `feature_union` (boolean feature map)
  - `resolved_tasks[]`
  - `enabled_task_capabilities[]`
    - `feature_flags` (canonical model feature schema booleans)

### Refresh OpenAI model capability catalog (admin)

- `POST /api/providers/openai/models/classification/refresh`
- Header (required when `SYNTHIA_ADMIN_TOKEN` is configured):
  - `X-Synthia-Admin-Token: <token>`
- Success:
  - capability refresh payload
  - `redeclare`: capability redeclaration result triggered with reason `capability_catalog_refresh`
- Error:
  - `403` when admin token is required and missing/invalid
  - `400` when capability refresh runtime is unavailable

### Read enabled OpenAI models

- `GET /api/providers/openai/models/enabled`
- Response:
  - `provider_id: "openai"`
  - `models[]`
    - `model_id`
    - `enabled`
    - `selected_at`

### Save enabled OpenAI models

- `POST /api/providers/openai/models/enabled`
- Request:
  - `model_ids: string[]`
- Success:
  - `provider_id: "openai"`
  - `models[]`
    - `model_id`
    - `enabled`
    - `selected_at`

### Read resolved OpenAI capability summary

- `GET /api/providers/openai/capability-resolution`
- Response:
  - `provider_id: "openai"`
  - `enabled_model_ids: string[]`
  - `classification_model: string | null`
  - `updated_at: string | null`
  - `capabilities`
    - `reasoning`
    - `vision`
    - `image_generation`
    - `audio_input`
    - `audio_output`
    - `realtime`
    - `tool_calling`
    - `structured_output`
    - `long_context`
    - `coding_strength`
    - `speed_tier`
    - `cost_tier`
    - `recommended_for[]`
  - `enabled_models[]`

### Read OpenAI pricing diagnostics

- `GET /api/providers/openai/pricing/diagnostics`
- Response:
  - `provider_id: "openai"`
  - `configured: boolean`
  - `refresh_state: "missing" | "manual" | "unavailable"`
  - `stale: boolean`
  - `entry_count: number`
  - `source_urls: string[]`
  - `source_url_used: string | null`
  - `last_refresh_time: string | null`
  - `unknown_models: string[]`
  - `last_error: string | null`
  - `notes?: string[]`

### Trigger OpenAI pricing refresh

- `POST /api/providers/openai/pricing/refresh`
- Request:
  - `force_refresh: boolean` (default `true`)
- Success:
  - `provider_id: "openai"`
  - `status: "manual_only" | "refreshed" | "unchanged"`
  - `changed: boolean`
  - `snapshot: object | null`
  - `notes?: string[]`
- Behavior:
  - returns `status = "manual_only"` when `SYNTHIA_OPENAI_API_PRICING_FETCH_ENABLED` is unset or `false`
  - when live pricing fetch is enabled, extraction is run only for filtered target model IDs
- Error:
  - `400` when pricing refresh runtime is unavailable.

### Save manual OpenAI pricing

- `POST /api/providers/openai/pricing/manual`
- Request:
  - `model_id: string`
  - `display_name?: string | null`
  - `input_price_per_1m?: number | null`
  - `output_price_per_1m?: number | null`
- Success:
  - `provider_id: "openai"`
  - `status: "manual_saved"`
  - `model_id`
  - `snapshot`
- Behavior:
  - request payload writes token-style manual prices only
  - non-token families are still rendered in the UI from normalized pricing fields persisted in the pricing catalog snapshot
- Error:
  - `400` when manual pricing persistence fails or no prices are provided.

## Task Capability Configuration

### Read task-capability selection

- `GET /api/capabilities/config`
- Response:
  - `configured: boolean`
  - `config: object | null`

### Update task-capability selection

- `POST /api/capabilities/config`
- Request:
  - `selected_task_families: string[]`
- Success: updated task-capability config payload.
- Error:
  - `400` when validation/store fails.

## Capability Declaration

### Trigger declaration

- `POST /api/capabilities/declare`
- Request body: empty JSON object `{}`.
- Success: runner declaration result payload.
- Declaration task set behavior:
  - `declared_task_families` is built from resolved node task capabilities (`runtime/node_capabilities.json`) when available.
  - raw model-level capabilities are not directly declared as task families.
- Provider intelligence metadata behavior:
  - declaration manifest `provider_metadata[]` includes:
    - `provider`
    - `enabled_models`
    - `feature_union`
    - `resolved_tasks`
    - `capability_graph_version`
- Errors:
  - `409` with structured payload when prerequisites are unmet:
    - `detail.error_code = capability_setup_prerequisites_unmet`
    - `detail.blocking_reasons[]`
    - `detail.readiness_flags`
  - `400` for invalid lifecycle/runtime constraints.

## Governance

### Governance status

- `GET /api/governance/status`
- Response:
  - `configured: boolean`
  - `status: object | null` (freshness projection)

### Refresh governance

- `POST /api/governance/refresh`
- Success: governance refresh payload.
- Error:
  - `400` when trust/governance runtime is unavailable.

## Provider Capability Refresh

- `POST /api/capabilities/providers/refresh`
- Request:
  - `force_refresh: boolean` (default `false`)
- Header (required when `SYNTHIA_ADMIN_TOKEN` is configured):
  - `X-Synthia-Admin-Token: <token>`
- Success: provider intelligence refresh payload.
- Error:
  - `403` when admin token is required and missing/invalid
  - `400` when runner is unavailable.

## Capability Diagnostics And Manual Controls (admin)

### Diagnostics payload

- `GET /api/capabilities/diagnostics`
- Header (required when `SYNTHIA_ADMIN_TOKEN` is configured):
  - `X-Synthia-Admin-Token: <token>`
- Response:
  - `discovered_models`
  - `enabled_models`
  - `capability_catalog`
  - `classification_model`
  - `last_declaration_payload`
  - `last_declaration_result`
- Error:
  - `403` when admin token is required and missing/invalid

### Rebuild capabilities

- `POST /api/capabilities/rebuild`
- Header (required when `SYNTHIA_ADMIN_TOKEN` is configured):
  - `X-Synthia-Admin-Token: <token>`
- Success:
  - `status: "rebuilt"`
  - `resolved_capabilities`
  - `task_families`
- Error:
  - `403` when admin token is required and missing/invalid
  - `400` when capability rebuild runtime is unavailable

### Manual redeclaration

- `POST /api/capabilities/redeclare`
- Request:
  - `force_refresh: boolean` (default `false`)
- Header (required when `SYNTHIA_ADMIN_TOKEN` is configured):
  - `X-Synthia-Admin-Token: <token>`
- Success:
  - capability redeclaration result payload
- Error:
  - `403` when admin token is required and missing/invalid
  - `400` when capability redeclaration runtime is unavailable

### Background refresh behavior

- Runtime starts a periodic provider refresh loop during API startup.
- Runtime stops the refresh loop during API shutdown.
- Loop behavior:
  - waits configured interval
  - executes provider capability refresh with `force_refresh=false`
  - logs status/changed/core-submission summary
  - logs warning on loop errors

## Degraded Recovery

- `POST /api/node/recover`
- Success: deterministic recovery payload with `target_state`.
- Error:
  - `400` when node is not degraded or recovery runner unavailable.

## Service Controls

### Service status

- `GET /api/services/status`
- Response:
  - `configured: boolean`
  - `services`:
    - `backend: running | stopped | failed | unknown`
    - `frontend: running | stopped | failed | unknown`
    - `node: running | degraded | unknown`

### Restart service

- `POST /api/services/restart`
- Request:
  - `target: \"backend\" | \"frontend\" | \"node\"`
- Success:
  - `status: \"ok\"`
  - `target`
  - `result: \"restarted\"`
  - `services` (post-restart status projection)
- Error:
  - `400` for unsupported target or unavailable service manager.

## Prompt/Service Registration

### Prompt/service state snapshot

- `GET /api/prompts/services`
- Response:
  - `configured: boolean`
  - `state: object | null`

### Register prompt/service metadata

- `POST /api/prompts/services`
- Request:
  - `prompt_id: string`
  - `service_id: string`
  - `task_family: string` (must be canonical task family)
  - `metadata: object` (optional)
- Success:
  - updated prompt/service state payload
- Error:
  - `400` when validation/store fails

### Prompt probation transition

- `POST /api/prompts/services/{prompt_id}/probation`
- Request:
  - `action: \"start\" | \"clear\"`
  - `reason: string` (optional)
- Success:
  - updated prompt/service state payload
- Error:
  - `400` when prompt is missing/unregistered or action is invalid

## Execution Gateway Contract Scaffolding

### Authorize execution request

- `POST /api/execution/authorize`
- Request:
  - `prompt_id: string`
  - `task_family: string`
- Response:
  - `allowed: boolean`
  - `reason: authorized | prompt_not_registered | prompt_in_probation | task_family_mismatch | ...`
  - `prompt_id`
  - `task_family`

Current enforcement model:

- deny-by-default for unregistered prompt IDs
- deny while prompt is in probation
- deny when requested task family mismatches registered task family
- allow only for registered prompt IDs with matching task family and non-probation status

### Direct execution request

- `POST /api/execution/direct`
- Request:
  - canonical `TaskExecutionRequest` payload
  - includes broader existing fields such as `prompt_id`, `requested_provider`, `requested_model`, `constraints`, `timeout_s`, `trace_id`, and optional `lease_id`
- Response:
  - canonical `TaskExecutionResult` payload
  - terminal result is returned directly for completed, rejected, failed, degraded, or unsupported execution
- Error:
  - `400` when direct execution runtime wiring is not configured
  - `422` when request validation fails before execution starts

Execution behavior:

- reuses the shared `TaskExecutionService`
- enforces prompt authorization when `prompt_id` is present
- validates against the existing broader declared/accepted task families
- resolves provider/model from current local usable provider state
- applies governance before and after provider resolution

## Provider Debug Endpoints

### Provider snapshot

- `GET /debug/providers`
- Response:
  - `configured: boolean`
  - `providers: list`

### Provider model snapshot

- `GET /debug/providers/models`
- Response:
  - `configured: boolean`
  - `providers: list` with `provider_id` and `models[]`

### Provider metrics snapshot

- `GET /debug/providers/metrics`
- Response:
  - `configured: boolean`
  - `providers: object` keyed by provider id with metrics totals/model metrics
