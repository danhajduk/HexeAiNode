# Setup

## Prerequisites

- Python 3 with `venv`
- Node.js and npm for the frontend
- access to a Hexe Core instance for real onboarding
- optional user systemd support for background services

## Environment Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Frontend Setup

```bash
cd frontend
npm install
```

## Local Development Run

Backend:

```bash
source .venv/bin/activate
PYTHONPATH=src python -m ai_node.main
```

Smoke check:

```bash
PYTHONPATH=src python -m ai_node.main --once
```

Frontend:

```bash
cd frontend
npm run dev -- --host 0.0.0.0 --port 8081
```

## Configuration Prerequisites

- Provide `OPENAI_API_KEY` for live OpenAI provider discovery.
- Use the control API or UI to set bootstrap MQTT host and node name before onboarding.
- Ensure the Core endpoint and MQTT broker are reachable from the node host.

## Optional Service Setup

1. Copy the stack environment file:

```bash
cp scripts/stack.env.example scripts/stack.env
```

2. Edit `scripts/stack.env` and confirm `APP_DIR`, `BACKEND_CMD`, and `FRONTEND_CMD`.
3. Install the user services:

```bash
./scripts/bootstrap.sh
```

4. Optional lingering support:

```bash
sudo loginctl enable-linger "$USER"
```
