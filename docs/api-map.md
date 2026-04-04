# AI Node API Map

This document groups the node-local FastAPI surface by the Hexe node API standard route families.

Verified against:

- [node_control_api.py](/home/dan/Projects/HexeAiNode/src/ai_node/runtime/node_control_api.py)
- [node-control-api-contract.md](/home/dan/Projects/HexeAiNode/docs/ai-node/node-control-api-contract.md)

## Canonical API Policy For This Repo

Canonical route policy in this repository:

- operator and frontend routes are rooted under `/api/...`
- provider-specific routes are rooted under `/api/providers/{provider_id}/...`
- service-control routes are rooted under `/api/services/...`
- execution routes are rooted under `/api/execution/...`

Compatibility or convenience surfaces in this repository:

- `GET /` is a convenience index route, not the canonical application API surface
- `/debug/...` routes are compatibility and admin-convenience mirrors, not the preferred operator route family
- admin-protected routes still use the legacy compatibility header `X-Synthia-Admin-Token`

## Route Families

### Health

Canonical routes:

- `GET /api/health`

Compatibility or convenience:

- `GET /`

Notes:

- `/api/health` is the canonical machine-readable liveness check.
- `/` exists as a service metadata and endpoint listing surface.

### Node Status And Recovery

Canonical routes:

- `GET /api/node/status`
- `POST /api/node/recover`

Notes:

- `/api/node/status` is the repo’s primary lifecycle, trust, onboarding, and readiness status surface.
- `/api/node/recover` is the explicit degraded recovery action.

### Onboarding

Canonical routes:

- `POST /api/onboarding/initiate`
- `POST /api/onboarding/restart`

Notes:

- The repo does not currently expose a separate `/api/onboarding/status` route because onboarding state is surfaced through `/api/node/status`.

### Provider Configuration And Provider Runtime

Canonical routes:

- `GET /api/providers/config`
- `POST /api/providers/config`
- `GET /api/providers/openai/credentials`
- `POST /api/providers/openai/credentials`
- `POST /api/providers/openai/preferences`
- `GET /api/providers/openai/models/latest`
- `GET /api/providers/openai/models/catalog`
- `GET /api/providers/openai/models/capabilities`
- `GET /api/providers/openai/models/features`
- `GET /api/providers/openai/models/enabled`
- `POST /api/providers/openai/models/enabled`
- `GET /api/providers/openai/capability-resolution`
- `GET /api/providers/openai/pricing/diagnostics`
- `POST /api/providers/openai/pricing/refresh`
- `POST /api/providers/openai/models/classification/refresh`
- `POST /api/providers/openai/pricing/manual`

Notes:

- This repo currently has one implemented provider route family: `openai`.
- Provider credentials, catalog inspection, model selection, pricing refresh, and provider capability refresh all remain clearly under the provider namespace.
- `POST /api/providers/openai/models/classification/refresh` is admin-protected and still depends on the legacy compatibility header alias.

### Capability Configuration And Declaration

Canonical routes:

- `GET /api/capabilities/config`
- `POST /api/capabilities/config`
- `POST /api/capabilities/declare`
- `POST /api/capabilities/rebuild`
- `POST /api/capabilities/redeclare`
- `POST /api/capabilities/providers/refresh`
- `GET /api/capabilities/node/resolved`
- `GET /api/capabilities/diagnostics`

Notes:

- This repo keeps resolved node capability visibility under the capabilities route family rather than duplicating it under `/api/node/...`.
- `rebuild`, `redeclare`, `providers/refresh`, and `diagnostics` are admin-oriented capability control surfaces.

### Governance

Canonical routes:

- `GET /api/governance/status`
- `POST /api/governance/refresh`

Notes:

- Governance visibility and manual refresh are separated cleanly from node status and capability declaration.

### Budgets And Usage

Canonical routes:

- `GET /api/budgets/state`
- `POST /api/budgets/declare`
- `POST /api/budgets/refresh`
- `GET /api/usage/clients`

Compatibility or convenience:

- `GET /debug/budgets`

Notes:

- `/api/budgets/...` is the preferred operational route family.
- `/api/usage/clients` is part of the operator-facing usage surface and feeds the frontend client usage views.
- `/debug/budgets` mirrors the budget-state payload for debug convenience.

### Prompt Services

Canonical routes:

- `GET /api/prompts/services`
- `POST /api/prompts/services`
- `GET /api/prompts/services/{prompt_id}`
- `PUT /api/prompts/services/{prompt_id}`
- `POST /api/prompts/services/{prompt_id}/lifecycle`
- `POST /api/prompts/services/{prompt_id}/probation`

Compatibility or convenience:

- `GET /debug/prompts`

Notes:

- Prompt service registration, update, lifecycle, and probation stay under one dedicated route family.
- `/debug/prompts` is a convenience mirror of prompt state, not the canonical route family.

### Execution

Canonical routes:

- `POST /api/execution/authorize`
- `POST /api/execution/direct`

Compatibility or convenience:

- `GET /debug/execution`

Notes:

- Authorization and direct execution are explicitly separated from setup and provider configuration routes.
- Execution observability currently appears under the debug convenience family.

### Services And Runtime Control

Canonical routes:

- `GET /api/services/status`
- `POST /api/services/restart`

Notes:

- This repo follows the Hexe node standard by keeping runtime service inspection and restart operations under a dedicated service-control family.

### Debug And Admin Convenience Surfaces

Compatibility or convenience routes:

- `GET /debug/providers`
- `GET /debug/providers/models`
- `GET /debug/providers/metrics`
- `GET /debug/prompts`
- `GET /debug/budgets`
- `GET /debug/execution`

Notes:

- These routes are useful for diagnostics and operator debugging, but they are not the canonical standard route families for new frontend or API integrations.
- New integrations should prefer the corresponding `/api/...` families whenever an equivalent canonical surface exists.

## Admin Header Compatibility Note

The admin-protected routes in this repo still use:

- `X-Synthia-Admin-Token`

This is a compatibility-sensitive protocol identifier and should be treated as a documented legacy exception during the Hexe migration rather than a silent naming inconsistency.
