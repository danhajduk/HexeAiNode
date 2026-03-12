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
- degraded recovery trigger
- service status/restart controls
- prompt/service registration and probation controls
- execution authorization gate scaffolding

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

## Onboarding

### Initiate onboarding

- `POST /api/onboarding/initiate`
- Request:
  - `mqtt_host: string`
  - `node_name: string`
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
- Success: provider intelligence refresh payload.
- Error:
  - `400` when runner is unavailable.

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
