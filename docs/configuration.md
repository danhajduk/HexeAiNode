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
- `SYNTHIA_PROVIDER_CAPABILITY_REFRESH_INTERVAL_SECONDS` default `14400`
- `SYNTHIA_FINALIZE_POLL_INTERVAL_SECONDS` default `2`
- `SYNTHIA_PROVIDER_REGISTRY_PATH` default `data/provider_registry.json`
- `SYNTHIA_PROVIDER_METRICS_PATH` default `data/provider_metrics.json`
- `SYNTHIA_OPENAI_PRICING_CATALOG_PATH` default `data/openai_pricing_catalog.json`
- `SYNTHIA_OPENAI_PRICING_REFRESH_INTERVAL_SECONDS` default `86400`
- `SYNTHIA_OPENAI_PRICING_STALE_TOLERANCE_SECONDS` default `172800`
- `SYNTHIA_OPENAI_PRICING_SOURCE_URLS` optional comma-separated `https://openai.com/...` URLs
- `SYNTHIA_OPENAI_PRICING_FETCH_TIMEOUT_SECONDS` default `20`
- `SYNTHIA_OPENAI_PRICING_FETCH_RETRY_COUNT` default `2`

Provider-specific:

- `OPENAI_API_KEY` required for live OpenAI discovery and use
- `SYNTHIA_OPENAI_BASE_URL` optional OpenAI-compatible override

## Config Files

- `scripts/stack.env`: local service commands for `bootstrap.sh`
- `.run/*.json`: persisted node runtime state
- `.run/provider_credentials.json`: restricted-permission provider credential store
- `data/provider_registry.json`: provider capability snapshot
- `data/provider_metrics.json`: provider metrics snapshot
- `data/openai_pricing_catalog.json`: cached OpenAI pricing snapshot and change history

## Repository Data Snapshots

- `data/provider_registry.json` and `data/provider_metrics.json` are project snapshots and may be committed when they reflect the desired current node/provider state.
- `.run/*.json` remains local runtime state and should not be committed.

## Secrets Handling

- Trust tokens and operational MQTT tokens are stored in trust state and must not be logged or committed.
- OpenAI provider credentials may be supplied through environment or saved locally in `.run/provider_credentials.json`; they must not be logged or committed.
- `.run/`, `.venv/`, `logs/`, and local Core doc symlinks are ignored in git.

## Defaults And Required Values

- Provider selection defaults to OpenAI as a supported cloud provider and starts disabled until configured.
- Task capability selection defaults to the canonical task family list when created locally.
- Valid trust state requires node identity, Core pairing metadata, trust token, and operational MQTT credentials.
