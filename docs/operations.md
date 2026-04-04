# Operations

This repo follows the Hexe node scripts and operations baseline through:

- [scripts/bootstrap.sh](/home/dan/Projects/HexeAiNode/scripts/bootstrap.sh)
- [scripts/run-from-env.sh](/home/dan/Projects/HexeAiNode/scripts/run-from-env.sh)
- [scripts/stack-control.sh](/home/dan/Projects/HexeAiNode/scripts/stack-control.sh)
- [scripts/restart-stack.sh](/home/dan/Projects/HexeAiNode/scripts/restart-stack.sh)
- [scripts/stack.env.example](/home/dan/Projects/HexeAiNode/scripts/stack.env.example)
- [scripts/systemd/](/home/dan/Projects/HexeAiNode/scripts/systemd)

## Canonical Local Operations Paths

- configure commands in `scripts/stack.env`
- install or refresh user services with `scripts/bootstrap.sh`
- start, stop, restart, and inspect the local stack with `scripts/stack-control.sh`
- use `scripts/restart-stack.sh` when the preferred path is user-systemd restart with fallback installation logic

## Standard Status Path

The canonical local status command for this repository is:

```bash
scripts/stack-control.sh status
```

This is the preferred repo-local status path because it:

- uses the same env-backed stack model as local start and stop
- checks the backend and frontend PID ownership under `.run/`
- does not require user-systemd to be installed first

When user services are installed, the service-level inspection path is:

```bash
systemctl --user status synthia-ai-node-backend.service
systemctl --user status synthia-ai-node-frontend.service
```

## Environment-Driven Startup

- `scripts/stack.env` is the local command source for backend and frontend startup
- `scripts/run-from-env.sh backend` runs the configured backend command
- `scripts/run-from-env.sh frontend` runs the configured frontend command
- backend and frontend commands remain externally configurable without editing the service templates directly

## Bootstrap And Service Installation

- `scripts/bootstrap.sh` renders user service templates from `scripts/systemd/*.service.in`
- the rendered unit files are installed into `${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user`
- the bootstrap flow requires `scripts/stack.env` and fails clearly when it is missing
- bootstrap reloads user systemd, enables both services, and restarts them immediately

Current user service template names:

- `synthia-ai-node-backend.service.in`
- `synthia-ai-node-frontend.service.in`

Current installed user service names:

- `synthia-ai-node-backend.service`
- `synthia-ai-node-frontend.service`

These names remain legacy compatibility-era identifiers and should be treated as documented operational exceptions unless a later coordinated migration changes them.

## Logs

- backend log file default: `logs/backend.log`
- frontend log file default under stack control: `logs/frontend.log`
- onboarding structured log path: `logs/onboarding.json`
- optional OpenAI debug log path: `logs/openai_debug.jsonl`
- runtime logs include onboarding, trust persistence, capability activation, telemetry, provider refresh, and service-control events

## Health Checks

- `scripts/stack-control.sh status`
- `curl http://127.0.0.1:9002/api/health`
- `curl http://127.0.0.1:9002/api/node/status`
- `curl http://127.0.0.1:9002/api/governance/status`
- `curl http://127.0.0.1:9002/debug/providers`
- `curl http://127.0.0.1:9002/debug/providers/models`
- `curl http://127.0.0.1:9002/debug/providers/metrics`

## Common Failure Modes

- invalid or missing trust state prevents trusted resume
- bootstrap broker unavailable or wrong host prevents onboarding
- Core API errors block capability declaration or governance sync
- missing operational MQTT credentials blocks trusted status publication
- missing `OPENAI_API_KEY` limits live OpenAI provider discovery
- user systemd bus access issues make service status appear `unknown`

## Recovery Steps

1. Run `scripts/stack-control.sh status` to confirm backend and frontend ownership state.
2. Check `logs/backend.log` for the most recent lifecycle or telemetry error.
3. Inspect `GET /api/node/status` for lifecycle state, blocking reasons, and trusted runtime context.
4. Verify `.run/trust_state.json` and `.run/node_identity.json` are present and internally consistent.
5. Re-run provider or governance refresh through the control API if the node is trusted but stale.
6. Restart backend or full node services with `scripts/stack-control.sh restart` or `scripts/restart-stack.sh` when process state is stuck.

## First Things To Inspect During Incident Response

- `scripts/stack-control.sh status`
- current lifecycle state
- trust-state validity
- Core API reachability
- operational MQTT reachability
- provider refresh/debug endpoints
- service manager status for backend and frontend
