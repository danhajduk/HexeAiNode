# Synthia AI Node (Python)

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
- `SYNTHIA_OPENAI_PRICING_CATALOG_PATH` (default: `data/openai_pricing_catalog.json`)
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

These `data/` snapshots are intended to stay in the repository for this project and are not omitted from commits unless you explicitly want them excluded.

OpenAI credential + latest-model endpoints:

```bash
curl http://127.0.0.1:9002/api/providers/openai/credentials
curl -X POST http://127.0.0.1:9002/api/providers/openai/credentials \
  -H 'Content-Type: application/json' \
  -d '{"api_token":"sk-proj-...","service_token":"sk-service-...","project_name":"ops"}'
curl -X POST http://127.0.0.1:9002/api/providers/openai/preferences \
  -H 'Content-Type: application/json' \
  -d '{"default_model_id":"gpt-5.4-pro","selected_model_ids":["gpt-5.4-pro","gpt-5.4-mini"]}'
curl http://127.0.0.1:9002/api/providers/openai/models/latest?limit=9
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
```

UI behavior:

- `Setup AI Provider` opens a dedicated OpenAI provider page instead of using the dashboard popup.
- The provider setup form now requires an OpenAI API token, service token, and project name.
- Tokens are validated before submit and are masked after save.
- Saving the OpenAI provider setup triggers backend model discovery immediately, so a saved token fetches models right away.
- The provider page shows the full filtered catalog in 240px mini-cards aligned left, grouped by family, with newest models first.
- Each model card includes capability badges, speed tier, cost tier, and recommended tasks from the saved capability catalog.
- Models can be enabled or disabled for node capability resolution separately from the selected-model pricing flow.
- OpenAI model selections on the provider page save automatically when you select or unselect a model.
- Selecting a model with unavailable pricing opens a per-model pricing popup so you can enter that model's price immediately or skip it.
- `Review Selected Model Prices` walks through the currently selected models one by one so you can set different prices per model.
- Manual pricing can be saved for the primary selected model or applied across all selected models from the provider page.
- The OpenAI pricing refresh endpoint is manual-only for now and just reloads the local pricing snapshot without scraping remote pricing pages.
- Filtered OpenAI provider models are also persisted locally in `data/provider_models.json`.
- After filtered models are refreshed, the node automatically picks the smallest available OpenAI LLM for capability classification and stores the batch result in `data/provider_model_capabilities.json`.
- Enabled provider models are persisted in `data/provider_enabled_models.json`, and only enabled models contribute to the resolved node capability summary.
- In Capability Summary, selected models are marked with a green check.

Task capability selection endpoints:

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

This repository keeps node-specific documentation. Platform-wide contracts and shared architecture are owned by Synthia Core.

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
