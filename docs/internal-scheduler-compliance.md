# Internal Scheduler Compliance

Last Updated: 2026-04-05 US/Pacific

This note records how the node-local recurring work now aligns with the Hexe standard in [background-tasks-and-internal-scheduler-standard.md](/home/dan/Projects/Hexe/docs/standards/Node/background-tasks-and-internal-scheduler-standard.md).

## Covered Tasks

- `provider_capability_refresh`
- `heartbeat`
- `telemetry`
- `operational_mqtt_health`

## Compliance Summary

- explicit ownership:
  - recurring work is owned by the runtime scheduler in [internal_scheduler.py](/home/dan/Projects/HexeAiNode/src/ai_node/runtime/internal_scheduler.py)
  - the scheduler is started and stopped by [node_control_api.py](/home/dan/Projects/HexeAiNode/src/ai_node/runtime/node_control_api.py)
- explicit schedule model:
  - each task is registered with interval metadata and operator-readable schedule names and details
  - heartbeat uses `heartbeat_5_seconds`
  - telemetry uses `telemetry_60_seconds`
  - operational MQTT health uses a dynamic schedule:
    - `every_10_seconds` in trusted, degraded, capability-activation, and active-recovery states
    - `every_10_seconds` for a 5 minute warm-up window after backend startup
    - `every_10_seconds` for a 5 minute warm-up window after recovery back to `operational`
    - `every_5_minutes` in stable operational state
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
- the current scheduler uses interval-backed tasks with operator-visible named schedules, including `4_times_a_day` for provider capability refresh
- the shared schedule catalog now includes `interval_seconds` for tasks that require an explicit integer-second cadence
- the current implementation follows the mandatory node baseline for heartbeat, telemetry, and operational MQTT health
- readiness-critical versus non-blocking behavior remains encoded per task registration and runtime handling
