# Synthia AI Node Architecture

## Scope

This document covers the architecture implemented in this repository only.

## Major Components

- `src/ai_node/main.py`: process entrypoint, lifecycle bootstrap, store wiring, and FastAPI startup.
- `src/ai_node/runtime/`: onboarding runtime, bootstrap MQTT runner, capability runner, control API, readiness checks, telemetry, and service management.
- `src/ai_node/core_api/`: HTTP clients for capability declaration and governance sync.
- `src/ai_node/providers/`: provider registry, adapters, metrics, execution router, and runtime manager.
- `src/ai_node/persistence/` and `src/ai_node/*_store.py`: local state persistence for trust, identity, capability, governance, provider reports, and prompt services.
- `frontend/`: dashboard UI for setup, status, and service controls.
- `scripts/`: local bootstrap and stack-control helpers.

## Runtime Flow

1. `main.py` loads local trust and identity state.
2. If trust exists, startup resumes through `trusted -> capability_setup_pending`.
3. If trust is missing, the node uses bootstrap MQTT discovery and onboarding runtime flow.
4. The control API exposes status, setup actions, capability submission, governance refresh, provider refresh, debug endpoints, and service restart actions.
5. Capability activation uses Core HTTP APIs, local persistence, operational MQTT readiness, and trusted status telemetry.
6. Provider runtime components manage model discovery, provider health, metrics persistence, and execution routing.

## OpenAI Classification And Pricing

Implemented behavior in this repository:

1. OpenAI model capability classification is deterministic and local.
2. Runtime capability classification does not call an OpenAI classifier model.
3. Canonical deterministic classifications are persisted in `providers/openai/provider_model_classifications.json`.
4. `/api/providers/openai/models/catalog` returns both the full normalized filtered catalog and a representative `ui_models` subset used by the provider setup page.
5. Pricing refresh fetches official OpenAI pricing page content from `https://developers.openai.com/api/docs/pricing` when live API pricing fetch is enabled.
6. Source text is normalized and split into canonical pricing sections.
7. Section-specific family extractors build focused source blocks per model family.
8. Family-scoped prompts are run against filtered target models (not the full model list).
9. Family outputs are validated independently, then merged into a canonical catalog.
10. On family failure, last-known-good family pricing is preserved when available.
11. Manual pricing overrides are merged from `providers/openai/provider_model_pricing_overrides.json`.
12. Canonical pricing is persisted in `providers/openai/provider_model_pricing.json`.

Provider setup flow after OpenAI credential save:

1. fetch `/v1/models`
2. filter supported models
3. derive representative UI model IDs for the provider setup page
4. classify models locally with deterministic rules
5. persist canonical classifications
6. derive feature flags from canonical classifications
7. show filtered representative models in the provider setup UI with family-aware capability and pricing cards
8. allow model enable/disable and selection from filtered catalog
9. save manual pricing locally, or fetch official pricing text and extract by family when live pricing refresh is enabled
10. persist canonical pricing + diagnostics artifacts
11. resolve node tasks from enabled model features
12. manually declare capabilities to Core after readiness checks pass

## Communication With Core

- HTTP: registration/onboarding, capability declaration, governance sync
- MQTT: bootstrap discovery and trusted operational status publication
- Local UI: FastAPI control surface consumed by the frontend dashboard

## Local Persistence And State

- `.run/bootstrap_config.json`
- `.run/trust_state.json`
- `.run/node_identity.json`
- `.run/provider_selection_config.json`
- `.run/task_capability_selection_config.json`
- `.run/capability_state.json`
- `.run/governance_state.json`
- `.run/phase2_state.json`
- `.run/prompt_service_state.json`
- `.run/provider_capability_report.json`
- `data/provider_registry.json`
- `data/provider_metrics.json`

## Provider And Service Integration

- OpenAI adapter support is implemented.
- Local providers are scaffolded through the provider adapter/runtime path.
- User-level systemd controls are exposed through the service manager for backend/frontend/node restarts.

## Failure And Recovery Model

- Invalid persisted state is rejected by validators and logged safely.
- Bootstrap connection has a timeout monitor.
- Capability/governance/readiness/telemetry failures can move the node into `degraded`.
- Recovery is exposed through the node control API and trusted startup resume path.

## Related Core References

Use [core-references.md](./core-references.md) for generic onboarding, lifecycle, governance, and MQTT platform contracts.
