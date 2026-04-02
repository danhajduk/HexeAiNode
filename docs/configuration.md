# Configuration

Only configuration verified from this repository is documented here.

## Environment Variables

Backend runtime:

- `SYNTHIA_API_HOST` default `127.0.0.1`
- `SYNTHIA_API_PORT` default `9002`
- `SYNTHIA_BOOTSTRAP_CONFIG_PATH` default `.run/bootstrap_config.json`
- `SYNTHIA_BACKEND_LOG_PATH` default `logs/backend.log`
- `SYNTHIA_BOOTSTRAP_CONNECT_TIMEOUT_SECONDS` default `30`
- `SYNTHIA_NODE_SOFTWARE_VERSION` default `0.1.0`
- `SYNTHIA_NODE_PROTOCOL_VERSION` default `1.0`
- `SYNTHIA_NODE_HOSTNAME` default local hostname
- `SYNTHIA_NODE_UI_ENDPOINT` optional absolute node UI URL sent during onboarding; when unset the node derives `http://<detected-ip>:<ui-port>/`
- `SYNTHIA_NODE_UI_PORT` default `8081`
- `SYNTHIA_NODE_API_BASE_URL` optional absolute node API base URL sent during onboarding; when unset the node derives `http://<detected-ip>:<api-port>`
- `SYNTHIA_TRUST_STATE_PATH` default `.run/trust_state.json`
- `SYNTHIA_NODE_IDENTITY_PATH` default `.run/node_identity.json`
- `SYNTHIA_PROVIDER_SELECTION_CONFIG_PATH` default `.run/provider_selection_config.json`
- `SYNTHIA_PROVIDER_CREDENTIALS_PATH` default `.run/provider_credentials.json`
- `SYNTHIA_TASK_CAPABILITY_SELECTION_CONFIG_PATH` default `.run/task_capability_selection_config.json`
- `SYNTHIA_CAPABILITY_STATE_PATH` default `.run/capability_state.json`
- `SYNTHIA_GOVERNANCE_STATE_PATH` default `.run/governance_state.json`
- `SYNTHIA_PHASE2_STATE_PATH` default `.run/phase2_state.json`
- `SYNTHIA_PROVIDER_CAPABILITY_REPORT_PATH` default `.run/provider_capability_report.json`
- `SYNTHIA_PROMPT_SERVICE_STATE_PATH` default `.run/prompt_service_state.json`
- `SYNTHIA_BUDGET_STATE_PATH` default `.run/budget_state.json`
- `SYNTHIA_PROVIDER_CAPABILITY_REFRESH_INTERVAL_SECONDS` default `14400`
- `SYNTHIA_FINALIZE_POLL_INTERVAL_SECONDS` default `2`
- `SYNTHIA_PROVIDER_REGISTRY_PATH` default `data/provider_registry.json`
- `SYNTHIA_PROVIDER_METRICS_PATH` default `data/provider_metrics.json`
- `SYNTHIA_OPENAI_PRICING_CATALOG_PATH` default `providers/openai/provider_model_pricing.json`
- `SYNTHIA_OPENAI_PRICING_REFRESH_INTERVAL_SECONDS` default `86400`
- `SYNTHIA_OPENAI_PRICING_STALE_TOLERANCE_SECONDS` default `172800`
- `SYNTHIA_OPENAI_PRICING_SOURCE_URLS` optional comma-separated OpenAI pricing URLs, including `https://developers.openai.com/...`
- `SYNTHIA_OPENAI_PRICING_FETCH_TIMEOUT_SECONDS` default `20`
- `SYNTHIA_OPENAI_PRICING_FETCH_RETRY_COUNT` default `2`
- `SYNTHIA_OPENAI_PRICING_DEBUG_RESPONSE_PATH` default `data/response.json`; set empty to disable raw AI extraction debug output
- `SYNTHIA_OPENAI_PRICING_PROMPT_SENT_PATH` default `data/promtp_sent.txt`; set empty to disable prompt debug output
- `SYNTHIA_OPENAI_PRICING_MARKDOWN_URL` default `https://developers.openai.com/api/docs/pricing.md`
- `SYNTHIA_OPENAI_API_PRICING_FETCH_ENABLED` default `false`; set `true` to enable OpenAI API pricing extraction calls

Provider-specific:

- `OPENAI_API_KEY` required for live OpenAI discovery and use
- `SYNTHIA_OPENAI_BASE_URL` optional OpenAI-compatible override

## Config Files

- `scripts/stack.env`: local service commands for `bootstrap.sh`
- `.run/*.json`: persisted node runtime state
- `.run/provider_selection_config.json`: provider enablement and optional per-provider budget ceiling state, including `max_cost_cents` plus `period`
- `.run/provider_credentials.json`: restricted-permission provider credential store
- `.run/budget_state.json`: cached budget policy, grant usage, reservations, and recent denial state
- `data/provider_registry.json`: provider capability snapshot
- `data/provider_metrics.json`: provider metrics snapshot
- `providers/openai/provider_model_classifications.json`: canonical deterministic OpenAI model capability classifications
- `providers/openai/provider_model_pricing.json`: canonical OpenAI pricing catalog after extraction + validation
- `providers/openai/provider_model_pricing_overrides.json`: optional manual pricing overrides merged after extraction
- `providers/openai/pricing_page_text_cache.json`: cached extracted pricing page text used for diagnostics
- `providers/openai/pricing_page_text_normalized_cache.json`: normalized pricing source text cache
- `providers/openai/pricing_page_sections_cache.json`: sectioned pricing source + family diagnostics cache
- `data/response.json`: raw + parsed AI pricing extraction response debug artifact (when debug path is enabled)
- `data/promtp_sent.txt`: debug copy of prompts sent to OpenAI extraction calls (when enabled)

## Repository Data Snapshots

- `data/provider_registry.json` and `data/provider_metrics.json` are project snapshots and may be committed when they reflect the desired current node/provider state.
- `.run/*.json` remains local runtime state and should not be committed.

## Secrets Handling

- Trust tokens and operational MQTT tokens are stored in trust state and must not be logged or committed.
- OpenAI provider credentials may be supplied through environment or saved locally in `.run/provider_credentials.json`; they must not be logged or committed.
- `.run/`, `.venv/`, `logs/`, and local Core doc symlinks are ignored in git.

## Defaults And Required Values

- Provider selection defaults to OpenAI as a supported cloud provider and starts disabled until configured.
- Provider selection may also persist optional per-provider budget ceilings in `providers.budget_limits.<provider_id>`.
- Each provider budget entry may include:
  - `max_cost_cents`
  - `period` with `monthly` or `weekly`; weekly windows run Monday through Sunday in the node's local timezone.
- Task capability selection defaults to the canonical task family list when created locally.
- Legacy `task.classification.text` values are canonicalized to `task.classification` when provider/task execution config is loaded or saved.
- Valid trust state requires node identity, Core pairing metadata, trust token, and operational MQTT credentials.
