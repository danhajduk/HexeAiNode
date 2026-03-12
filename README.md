# Synthia AI Node (Python)

## Environment setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Current run mode

The project currently provides Phase 1 onboarding modules and tests.
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
- `SYNTHIA_TASK_CAPABILITY_SELECTION_CONFIG_PATH` (default: `.run/task_capability_selection_config.json`)
- `SYNTHIA_PROMPT_SERVICE_STATE_PATH` (default: `.run/prompt_service_state.json`)
- `OPENAI_API_KEY` (required for live OpenAI model discovery)
- `SYNTHIA_OPENAI_BASE_URL` (optional OpenAI-compatible endpoint override)

Control API refresh endpoint:

```bash
curl -X POST http://127.0.0.1:9002/api/capabilities/providers/refresh \
  -H 'Content-Type: application/json' \
  -d '{"force_refresh": true}'
```

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
