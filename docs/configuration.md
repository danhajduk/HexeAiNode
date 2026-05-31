# Configuration

Only configuration verified from this repository is documented here.

## Environment Variables

Backend runtime:

- `HEXE_API_HOST` default `127.0.0.1`
- `HEXE_API_PORT` default `9002`
- `HEXE_BOOTSTRAP_CONFIG_PATH` default `.run/bootstrap_config.json`
- `HEXE_BACKEND_LOG_PATH` default `logs/backend.log`
- `HEXE_BOOTSTRAP_CONNECT_TIMEOUT_SECONDS` default `30`
- `HEXE_NODE_SOFTWARE_VERSION` default `0.1.0`
- `HEXE_NODE_PROTOCOL_VERSION` default `1.0`
- `HEXE_NODE_HOSTNAME` default local hostname
- `HEXE_NODE_UI_ENDPOINT` optional absolute node UI URL sent during onboarding; when unset the node derives `http://<detected-ip>:<ui-port>/`
- `HEXE_NODE_UI_PORT` default `8081`
- `HEXE_NODE_API_BASE_URL` optional absolute node API base URL sent during onboarding; when unset the node derives `http://<detected-ip>:<api-port>`
- `HEXE_TRUST_STATE_PATH` default `.run/trust_state.json`
- `HEXE_NODE_IDENTITY_PATH` default `.run/node_identity.json`
- `HEXE_PROVIDER_SELECTION_CONFIG_PATH` default `.run/provider_selection_config.json`
- `HEXE_PROVIDER_CREDENTIALS_PATH` default `.run/provider_credentials.json`
- `HEXE_TASK_CAPABILITY_SELECTION_CONFIG_PATH` default `.run/task_capability_selection_config.json`
- `HEXE_CAPABILITY_STATE_PATH` default `.run/capability_state.json`
- `HEXE_GOVERNANCE_STATE_PATH` default `.run/governance_state.json`
- `HEXE_PHASE2_STATE_PATH` default `.run/phase2_state.json`
- `HEXE_PROVIDER_CAPABILITY_REPORT_PATH` default `.run/provider_capability_report.json`
- `HEXE_PROMPT_SERVICE_STATE_PATH` default `.run/prompt_service_state.json`
- `HEXE_BUDGET_STATE_PATH` default `.run/budget_state.json`
- `HEXE_PROVIDER_CAPABILITY_REFRESH_INTERVAL_SECONDS` default `14400`
- `HEXE_FINALIZE_POLL_INTERVAL_SECONDS` default `2`
- `HEXE_PROVIDER_REGISTRY_PATH` default `data/provider_registry.json`
- `HEXE_PROVIDER_METRICS_PATH` default `data/provider_metrics.json`
- `HEXE_PROVIDER_LOCAL_DEFAULT_MODEL_ID` default `qwen3-14b-q4_k_m`
- `HEXE_PROVIDER_LOCAL_TRANSPORT` default `socket`
- `HEXE_PROVIDER_LOCAL_SOCKET` default `/run/hexe/ai-node/llamacpp.sock`
- `HEXE_PROVIDER_LOCAL_BASE_URL` default `http://127.0.0.1:8011/v1`
- `HEXE_OPENAI_PRICING_CATALOG_PATH` default `providers/openai/provider_model_pricing.json`
- `HEXE_OPENAI_PRICING_MANUAL_CONFIG_PATH` default `config/openai-pricing.yaml`
- `HEXE_DEBUG_AOPENAI` optional boolean; when true, writes full OpenAI request/response debug payloads
- `HEXE_DEBUG_AOPENAI_LOG_PATH` default `logs/openai_debug.jsonl`
- `HEXE_OPENAI_PRICING_REFRESH_INTERVAL_SECONDS` default `86400`
- `HEXE_OPENAI_PRICING_STALE_TOLERANCE_SECONDS` default `172800`
- `HEXE_OPENAI_PRICING_SOURCE_URLS` optional comma-separated OpenAI pricing URLs, including `https://developers.openai.com/...`
- `HEXE_OPENAI_PRICING_FETCH_TIMEOUT_SECONDS` default `20`
- `HEXE_OPENAI_PRICING_FETCH_RETRY_COUNT` default `2`
- `HEXE_OPENAI_PRICING_DEBUG_RESPONSE_PATH` default `data/response.json`; set empty to disable raw AI extraction debug output
- `HEXE_OPENAI_PRICING_PROMPT_SENT_PATH` default `data/promtp_sent.txt`; set empty to disable prompt debug output
- `HEXE_OPENAI_PRICING_MARKDOWN_URL` default `https://developers.openai.com/api/docs/pricing.md`
- `HEXE_OPENAI_API_PRICING_FETCH_ENABLED` default `false`; set `true` to enable OpenAI API pricing extraction calls
- `HEXE_DIRECT_EXECUTION_ADMISSION_ENABLED` default `true`; enables local busy rejection before direct task execution
- `HEXE_DIRECT_EXECUTION_MAX_IN_FLIGHT` default `2`; hard ceiling for concurrent expensive execution work across direct, benchmark, and compare routes
- `HEXE_DIRECT_EXECUTION_DYNAMIC_IN_FLIGHT_ENABLED` default `false`; when true, computes a lower effective concurrency limit from current host memory, swap, and load pressure
- `HEXE_DIRECT_EXECUTION_MIN_EFFECTIVE_IN_FLIGHT` default `1`; minimum effective concurrency when dynamic in-flight capacity is enabled and the node is hot but not critical
- `HEXE_DIRECT_EXECUTION_MIN_MEMORY_AVAILABLE_MB` default `512`; rejects direct execution when host available memory drops below this floor
- `HEXE_DIRECT_EXECUTION_WARM_MEMORY_AVAILABLE_MB` default `8192`; dynamic capacity enters warm tier at or below this available-memory value
- `HEXE_DIRECT_EXECUTION_HOT_MEMORY_AVAILABLE_MB` default `2048`; dynamic capacity enters hot tier at or below this available-memory value
- `HEXE_DIRECT_EXECUTION_MAX_SWAP_USED_RATIO` default `0.95`; rejects direct execution when swap usage is at or above this ratio
- `HEXE_DIRECT_EXECUTION_WARM_SWAP_USED_RATIO` default `0.5`; dynamic capacity enters warm tier at or above this swap ratio
- `HEXE_DIRECT_EXECUTION_HOT_SWAP_USED_RATIO` default `0.8`; dynamic capacity enters hot tier at or above this swap ratio
- `HEXE_DIRECT_EXECUTION_MAX_LOAD_PER_CPU` default `2.0`; rejects direct execution when 1-minute load divided by CPU count is at or above this value
- `HEXE_DIRECT_EXECUTION_WARM_LOAD_PER_CPU` default `0.8`; dynamic capacity enters warm tier at or above this load-per-CPU value
- `HEXE_DIRECT_EXECUTION_HOT_LOAD_PER_CPU` default `1.5`; dynamic capacity enters hot tier at or above this load-per-CPU value
- `HEXE_DIRECT_EXECUTION_RETRY_AFTER_SECONDS` default `30`; retry hint returned with direct execution busy responses

Provider-specific:

- `OPENAI_API_KEY` required for live OpenAI discovery and use
- `HEXE_OPENAI_BASE_URL` optional OpenAI-compatible override

## Config Files

- `scripts/stack.env`: local service commands for `bootstrap.sh`
- `.run/*.json`: persisted node runtime state
- `.run/provider_selection_config.json`: provider enablement and optional per-provider budget ceiling state, including `max_cost_cents` plus `period`
- `.run/provider_credentials.json`: restricted-permission provider credential store
- `.run/provider_credentials.json` may include `debug_aopenai` and `debug_aopenai_log_path` under `providers.openai`
- `.run/budget_state.json`: cached budget policy, grant usage, reservations, and recent denial state
- `data/provider_registry.json`: provider capability snapshot
- `data/provider_metrics.json`: provider metrics snapshot
- `providers/openai/provider_model_classifications.json`: canonical deterministic OpenAI model capability classifications
- `providers/openai/provider_model_pricing.json`: canonical OpenAI pricing catalog after extraction + validation
- `providers/openai/provider_model_pricing_overrides.json`: optional manual pricing overrides merged after extraction
- `config/openai-pricing.yaml`: manual per-model OpenAI pricing file; `Input`, `Cached input`, and `Output` override fetched/catalog prices
- `logs/openai_debug.jsonl`: optional OpenAI full request/response debug log when `debug_aopenai` is enabled
- `providers/openai/pricing_page_text_cache.json`: cached extracted pricing page text used for diagnostics
- `providers/openai/pricing_page_text_normalized_cache.json`: normalized pricing source text cache
- `providers/openai/pricing_page_sections_cache.json`: sectioned pricing source + family diagnostics cache
- `data/response.json`: raw + parsed AI pricing extraction response debug artifact (when debug path is enabled)
- `data/promtp_sent.txt`: debug copy of prompts sent to OpenAI extraction calls (when enabled)

## Repository Runtime Artifacts

- `.run/` remains local runtime state and should not be committed.
- `logs/` remains local runtime logging and should not be committed.
- `data/` is also treated as local runtime output in this repository and is gitignored by default.
- runtime path ownership is documented in [runtime-path-ownership.md](/home/dan/hexe/HexeAiNode/docs/runtime-path-ownership.md).

## Secrets Handling

- Trust tokens and operational MQTT tokens are stored in trust state and must not be logged or committed.
- OpenAI provider credentials may be supplied through environment or saved locally in `.run/provider_credentials.json`; they must not be logged or committed.
- `.run/`, `.venv/`, `logs/`, and local Core doc symlinks are ignored in git.
- detailed verified handling for trust tokens, provider credentials, redaction, and debug artifacts is documented in [security-and-sensitive-state.md](/home/dan/hexe/HexeAiNode/docs/security-and-sensitive-state.md).

## Defaults And Required Values

- Provider selection defaults to OpenAI as a supported cloud provider and local LLM as a supported local provider; both start disabled until configured.
- Existing provider selection files are normalized on load so stale configs gain the built-in `local` supported provider before local enablement is saved.
- Provider selection may also persist optional per-provider budget ceilings in `providers.budget_limits.<provider_id>`.
- Each provider budget entry may include:
  - `max_cost_cents`
  - `period` with `monthly` or `weekly`; weekly windows run Monday through Sunday in the node's local timezone.
- Task capability selection defaults to the canonical task family list when created locally.
- Legacy `task.classification.text` values are canonicalized to `task.classification` when provider/task execution config is loaded or saved.
- Valid trust state requires node identity, Core pairing metadata, trust token, and operational MQTT credentials.
