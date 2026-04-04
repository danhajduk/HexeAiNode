# Hexe AI Node (Python)

Compatibility-sensitive identifiers such as `X-Synthia-*` headers and `synthia-*` service IDs still use legacy naming during this migration phase.

## Environment setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Current run mode

The project currently provides implemented onboarding, trust/capability/governance activation,
and provider-intelligence runtime control paths (including local provider visibility debug APIs).
Backend entrypoint is available as `python -m ai_node.main`.

## Backend run

```bash
source .venv/bin/activate
PYTHONPATH=src python -m ai_node.main
```

Backend control APIs are served via FastAPI (default: `0.0.0.0:9002` when using stack env service command).

Backend file logs are written by code logger to:

```text
logs/backend.log
```

Node control API contract:

- `docs/ai-node/node-control-api-contract.md`

Bootstrap connection timeout:
- Default: 30 seconds in `bootstrap_connecting`
- Behavior: transitions back to `unconfigured` if timeout expires
- Override with env var: `SYNTHIA_BOOTSTRAP_CONNECT_TIMEOUT_SECONDS`

Smoke-check mode:

```bash
PYTHONPATH=src python -m ai_node.main --once
```

## Provider intelligence

Provider capability intelligence is cached locally and refreshed on-demand/periodically with a default 4-hour interval.

Config knobs:
- `SYNTHIA_PROVIDER_CAPABILITY_REPORT_PATH` (default: `.run/provider_capability_report.json`)
- `SYNTHIA_PROVIDER_CAPABILITY_REFRESH_INTERVAL_SECONDS` (default: `14400`)
- `SYNTHIA_PROVIDER_CREDENTIALS_PATH` (default: `.run/provider_credentials.json`)
- `SYNTHIA_TASK_CAPABILITY_SELECTION_CONFIG_PATH` (default: `.run/task_capability_selection_config.json`)
- `SYNTHIA_PROMPT_SERVICE_STATE_PATH` (default: `.run/prompt_service_state.json`)
- `SYNTHIA_OPENAI_PRICING_CATALOG_PATH` (default: `providers/openai/provider_model_pricing.json`)
- `SYNTHIA_OPENAI_PRICING_MANUAL_CONFIG_PATH` (default: `config/openai-pricing.yaml`)
- `SYNTHIA_DEBUG_AOPENAI` (optional; `true` enables full OpenAI request/response debug capture)
- `SYNTHIA_DEBUG_AOPENAI_LOG_PATH` (default: `logs/openai_debug.jsonl`)
- `SYNTHIA_OPENAI_PRICING_REFRESH_INTERVAL_SECONDS` (default: `86400`)
- `SYNTHIA_OPENAI_PRICING_STALE_TOLERANCE_SECONDS` (default: `172800`)
- `SYNTHIA_OPENAI_PRICING_SOURCE_URLS` (optional comma-separated OpenAI pricing URLs; defaults include `https://developers.openai.com/api/docs/pricing`)
- `OPENAI_API_KEY` (required for live OpenAI model discovery)
- `SYNTHIA_OPENAI_BASE_URL` (optional OpenAI-compatible endpoint override)

Control API refresh endpoint:

```bash
curl -X POST http://127.0.0.1:9002/api/capabilities/providers/refresh \
  -H 'Content-Type: application/json' \
  -d '{"force_refresh": true}'
```

Provider debug endpoints:

```bash
curl http://127.0.0.1:9002/debug/providers
curl http://127.0.0.1:9002/debug/providers/models
curl http://127.0.0.1:9002/debug/providers/metrics
```

Tracked runtime snapshots:

- `data/provider_registry.json`: current discovered provider/model registry snapshot
- `data/provider_metrics.json`: current provider metrics snapshot

These `data/` snapshots are local runtime artifacts in the current repo model and are gitignored by default. Treat them as regenerated local output rather than committed source-of-truth files.

OpenAI credential + latest-model endpoints:

```bash
curl http://127.0.0.1:9002/api/providers/openai/credentials
curl -X POST http://127.0.0.1:9002/api/providers/openai/credentials \
  -H 'Content-Type: application/json' \
  -d '{"api_token":"sk-proj-...","service_token":"sk-service-...","project_name":"ops"}'
curl -X POST http://127.0.0.1:9002/api/providers/openai/preferences \
  -H 'Content-Type: application/json' \
  -d '{"default_model_id":"gpt-5.4-pro","selected_model_ids":["gpt-5.4-pro","gpt-5.4-mini"]}'
curl http://127.0.0.1:9002/api/providers/openai/models/latest?limit=13
curl http://127.0.0.1:9002/api/providers/openai/models/catalog
curl http://127.0.0.1:9002/api/providers/openai/models/capabilities
curl http://127.0.0.1:9002/api/providers/openai/models/enabled
curl -X POST http://127.0.0.1:9002/api/providers/openai/models/enabled \
  -H 'Content-Type: application/json' \
  -d '{"model_ids":["gpt-5-mini","gpt-4.1"]}'
curl http://127.0.0.1:9002/api/providers/openai/capability-resolution
curl http://127.0.0.1:9002/api/providers/openai/pricing/diagnostics
curl -X POST http://127.0.0.1:9002/api/providers/openai/pricing/refresh \
  -H 'Content-Type: application/json' \
  -d '{"force_refresh":true}'
curl -X POST http://127.0.0.1:9002/api/providers/openai/pricing/manual \
  -H 'Content-Type: application/json' \
  -d '{"model_id":"gpt-5.4-pro","input_price_per_1m":3.0,"output_price_per_1m":15.0}'
curl -X POST http://127.0.0.1:9002/api/capabilities/declare
```

Manual price file:

- Edit [config/openai-pricing.yaml](/home/dan/Projects/HexeAiNode/config/openai-pricing.yaml)
- YAML values in that file take precedence over fetched pricing and JSON pricing snapshots
- Fields are per model: `Input`, `Cached input`, `Output`

OpenAI full debug capture:

- Set `debug_aopenai: true` under the OpenAI entry in `.run/provider_credentials.json`, or set `SYNTHIA_DEBUG_AOPENAI=true`
- Optional log path: `debug_aopenai_log_path` or `SYNTHIA_DEBUG_AOPENAI_LOG_PATH`
- Full OpenAI request/response payloads are written to a separate JSONL file, defaulting to `logs/openai_debug.jsonl`

UI behavior:

- `Setup AI Provider` opens a dedicated OpenAI provider page instead of using the dashboard popup.
- The provider setup form now requires an OpenAI API token, service token, and project name.
- Tokens are validated before submit and are masked after save.
- Saving the OpenAI provider setup triggers backend model discovery immediately, so a saved token fetches models right away.
- The provider page shows the filtered representative UI catalog returned by `/api/providers/openai/models/catalog` in grouped mini-cards, with newest models first inside each family.
- Each model card includes family/classification data from the saved capability catalog, feature-derived badges, speed/cost/coding tiers, and pricing details that match the model family.
- Models can be enabled or disabled for node capability resolution separately from the selected-model pricing flow.
- OpenAI model selections on the provider page save automatically when you select or unselect a model.
- Selecting a model with unavailable pricing opens a per-model pricing popup so you can enter that model's price immediately or skip it.
- `Review Selected Model Prices` walks through the currently selected models one by one so you can set different prices per model.
- Manual pricing can be saved for the primary selected model or applied across all selected models from the provider page.
- For token-priced models, cards show input/output `/1M token` prices; for other families they show normalized pricing units such as `per image`, `per minute`, or `per 1M characters`.
- The OpenAI pricing refresh endpoint is disabled by default. When `SYNTHIA_OPENAI_API_PRICING_FETCH_ENABLED=true`, it fetches official pricing page text, runs strict extraction for filtered catalog models, validates the output, and preserves last-known-good data on extraction failures.
- Raw AI pricing extraction responses are saved to `data/response.json` for debugging by default; set `SYNTHIA_OPENAI_PRICING_DEBUG_RESPONSE_PATH=` (empty) to disable or set a custom path.
- Filtered OpenAI provider models are also persisted locally in `data/provider_models.json`.
- After filtered models are refreshed, capability classification is resolved locally with deterministic rules and stored in `providers/openai/provider_model_classifications.json`.
- Capability classification no longer depends on calling an OpenAI classifier model at runtime.
- Enabled provider models are persisted in `data/provider_enabled_models.json`, and only enabled models contribute to the resolved node capability summary.
- Capability declaration is manual; provider/model refresh actions and enabled-model updates return `declaration.status = pending_manual` until you call `POST /api/capabilities/declare`.
- Declaration is gated until enabled models are classified and have pricing coverage.
- The runtime provider-intelligence report now exports only the filtered OpenAI catalog to Core, not the full raw `/v1/models` list.
- In Capability Summary, selected models are marked with a green check.

Task capability selection endpoints:

Capability declarations also accept runtime-resolved granular coding families such as `task.code_generation`, `task.code_review`, `task.code_debugging`, and `task.code_explanation`.

```bash
curl http://127.0.0.1:9002/api/capabilities/config
curl -X POST http://127.0.0.1:9002/api/capabilities/config \
  -H 'Content-Type: application/json' \
  -d '{"selected_task_families":["task.classification.text","task.summarization.text"]}'

curl -X POST http://127.0.0.1:9002/api/prompts/services \
  -H 'Content-Type: application/json' \
  -d '{"prompt_id":"prompt.alpha","service_id":"svc-alpha","task_family":"task.classification.text","metadata":{"owner":"ops"}}'

curl -X POST http://127.0.0.1:9002/api/execution/authorize \
  -H 'Content-Type: application/json' \
  -d '{"prompt_id":"prompt.alpha","task_family":"task.classification.text"}'
```

## Frontend run

```bash
cd frontend
npm install
npm run dev -- --host 0.0.0.0 --port 8081
```

## Validation

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v
```

## Documentation

This repository keeps node-specific documentation. Platform-wide contracts and shared architecture are owned by Hexe Core.

- `docs/index.md` for the primary docs entry point
- `docs/overview.md` for node scope and ownership boundaries
- `docs/setup.md` for install and startup steps
- `docs/core-references.md` for canonical Core documentation links

## Service bootstrap (run on boot)

1. Copy and configure service commands:

```bash
cp scripts/stack.env.example scripts/stack.env
```

Edit `scripts/stack.env` and set:
- `BACKEND_CMD`
- `FRONTEND_CMD`

2. Install boot service:

```bash
./scripts/bootstrap.sh
```

This installs two rendered systemd units from templates:
- `scripts/systemd/synthia-ai-node-backend.service.in`
- `scripts/systemd/synthia-ai-node-frontend.service.in`

Optional for automatic start at boot even without active login session:

```bash
sudo loginctl enable-linger "$USER"
```

3. Manual control:

```bash
./scripts/stack-control.sh status
./scripts/stack-control.sh restart
./scripts/stack-control.sh stop
./scripts/stack-control.sh start
./scripts/restart-stack.sh
```
