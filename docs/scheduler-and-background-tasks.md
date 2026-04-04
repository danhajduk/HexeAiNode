# Scheduler And Background Tasks

## Purpose

This document explains recurring work, scheduler-adjacent behavior, and long-lived runtime tasks in `HexeAiNode`.

It maps the current implementation to the Hexe node scheduler/background-task standard without redefining the Core-owned scheduler contract.

## Background Work Model In This Repo

This node currently combines:

- node-local recurring work
- long-lived runtime monitors
- provider-refresh behavior
- Core lease compatibility behavior for scheduled execution

The repo does not expose one single `scheduler/` package. Instead, scheduler-adjacent behavior is spread across runtime, telemetry, and execution modules.

## Ownership Boundaries

## Runtime owners

Primary runtime ownership currently sits under:

- `src/ai_node/main.py`
- `src/ai_node/runtime/`
- `src/ai_node/telemetry/`
- `src/ai_node/execution/`

Key modules include:

- `src/ai_node/runtime/node_control_api.py`
- `src/ai_node/runtime/service_manager.py`
- `src/ai_node/runtime/bootstrap_timeout.py`
- `src/ai_node/runtime/bootstrap_mqtt_runner.py`
- `src/ai_node/runtime/operational_mqtt_readiness.py`
- `src/ai_node/runtime/capability_declaration_runner.py`
- `src/ai_node/runtime/task_execution_service.py`
- `src/ai_node/runtime/scheduler_lease_integration.py`
- `src/ai_node/runtime/execution_telemetry.py`

## Background And Long-Lived Behaviors

Current recurring or long-lived runtime behaviors include:

- bootstrap connection monitoring
- trusted status telemetry publishing
- operational MQTT readiness tracking
- provider capability refresh behavior
- provider metrics and usage aggregation support
- capability declaration coordination
- scheduler lease integration for execution flows

## Node-Local Recurring Work

Current node-local recurring or long-lived work includes:

- bootstrap timeout monitoring
- operational status and telemetry publishing
- provider capability refresh timing
- readiness and trusted runtime continuation checks

These are node-local runtime concerns.

## Core-Scheduled Or Lease-Based Work

The repo also participates in Core-scheduled execution compatibility through:

- `src/ai_node/runtime/scheduler_lease_integration.py`
- `src/ai_node/core_api/scheduler_lease_client.py`
- execution and task service modules under `src/ai_node/execution/`

This is not a separate local scheduler authority. It is compatibility with the Core-owned lease lifecycle.

## Provider-Specific Refresh Behavior

Provider-related recurring work currently includes:

- provider capability refresh
- provider metrics tracking
- provider model availability and feature resolution support

This work influences node readiness and capability declaration, but still remains subordinate to node-level lifecycle and governance rules.

## Readiness Interaction

Recurring and long-lived runtime work affects readiness in different ways.

Examples:

- bootstrap timeout behavior can prevent successful onboarding progression
- provider readiness and refresh behavior can block capability declaration readiness
- operational MQTT readiness contributes runtime health context
- capability/governance failures can move the node into degraded behavior

Not every recurring task is itself the lifecycle state owner. Instead, these tasks feed node-level readiness and degraded-state decisions.

## Persisted State And Visibility

The repo persists several state categories relevant to recurring work and runtime visibility, including:

- `.run/provider_capability_report.json`
- `.run/capability_state.json`
- `.run/governance_state.json`
- `.run/phase2_state.json`
- `.run/prompt_service_state.json`
- `.run/budget_state.json`
- `data/provider_registry.json`
- `data/provider_metrics.json`

These files support runtime continuity, operator visibility, and diagnostics rather than acting as one generic scheduler database.

## Operator-Visible Surfaces

Current operator-visible surfaces for runtime and recurring behavior include:

- `GET /api/node/status`
- `GET /api/governance/status`
- `GET /api/services/status`
- capability and provider diagnostics surfaces
- provider refresh and capability refresh actions in the UI
- diagnostics and operational UI sections under `frontend/src/features/`

The current repo still needs a cleaner, dedicated API/documentation map for these behaviors, but the visibility surfaces already exist.

## Degraded And Failure Behavior

The repo currently treats some failures as degraded-state relevant, including:

- capability submission failures
- governance sync failures
- telemetry or trusted runtime failures
- readiness-related provider issues

This means the runtime already behaves in a scheduler/background-task-aware way, even if the repo docs have not yet presented that behavior under one dedicated scheduler narrative.

## Alignment Notes

Aligned already:

- recurring work has identifiable runtime owners
- scheduler lease compatibility exists as a separate concern from generic local startup
- runtime state and telemetry surfaces exist
- readiness and degraded behavior already consume recurring/runtime signals

Needs follow-up:

- clearer grouped documentation of recurring work ownership
- API map showing scheduler/background-task visibility surfaces
- explicit operator guidance for which recurring/runtime failures are blocking versus warning-only
