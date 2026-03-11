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

Smoke-check mode:

```bash
PYTHONPATH=src python -m ai_node.main --once
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
