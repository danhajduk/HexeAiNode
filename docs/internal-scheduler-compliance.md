# Internal Scheduler Compliance

Last Updated: 2026-04-05 US/Pacific

This note records how the node-local recurring work now aligns with the Hexe standard in [background-tasks-and-internal-scheduler-standard.md](/home/dan/Projects/Hexe/docs/standards/Node/background-tasks-and-internal-scheduler-standard.md).

## Covered Tasks

- `provider_capability_refresh`
- `status_telemetry_heartbeat`
- `operational_mqtt_health`

## Compliance Summary

- explicit ownership:
  - recurring work is owned by the runtime scheduler in [internal_scheduler.py](/home/dan/Projects/HexeAiNode/src/ai_node/runtime/internal_scheduler.py)
  - the scheduler is started and stopped by [node_control_api.py](/home/dan/Projects/HexeAiNode/src/ai_node/runtime/node_control_api.py)
- explicit schedule model:
  - each task is registered with interval metadata and operator-readable schedule details
- persisted task state:
  - scheduler snapshots persist in `.run/internal_scheduler_state.json`
  - persistence is handled by [internal_scheduler_state_store.py](/home/dan/Projects/HexeAiNode/src/ai_node/persistence/internal_scheduler_state_store.py)
- operator visibility:
  - `GET /api/node/status` includes `internal_scheduler`
  - `GET /api/capabilities/diagnostics` includes `internal_scheduler`
  - the diagnostics UI renders the internal scheduler payload
- safe startup and shutdown:
  - startup registration and task start happen in `NodeControlState`
  - shutdown cancellation happens through the control app lifecycle hooks
- failure surfacing:
  - task failures update persisted scheduler state and remain visible in diagnostics
  - MQTT-health failures still feed degraded/recovery behavior separately

## Standard Notes

- this implementation standardizes node-local recurring work; it does not replace Core-owned lease scheduling
- the current scheduler uses interval tasks only
- readiness-critical versus non-blocking behavior remains encoded per task registration and runtime handling
