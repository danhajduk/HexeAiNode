# Hexe AI Node — Phase 2 Namespace Migration

Status: Active
Implementation status: In progress
Last updated: 2026-03-20

## Purpose

This document defines the Phase 2 namespace migration for the AI Node repository.

Phase 2 moves runtime MQTT topic usage from the legacy `synthia/...` namespace to the Hexe `hexe/...` namespace without changing payload structure, capability IDs, task family IDs, or onboarding schema keys.

## Scope

This phase covers:

- bootstrap topic migration
- node status and node-scoped MQTT topic migration
- runtime subscription and publish helper migration
- test fixture and documentation example migration

This phase does not cover:

- payload schema changes
- capability identifier changes
- task family identifier changes
- dual-namespace compatibility logic

## Current Verified Legacy Namespace

The current repository still uses the following legacy MQTT roots in active code:

- bootstrap discovery topic: `synthia/bootstrap/core`
- trusted status telemetry topic: `synthia/nodes/{node_id}/status`

Verified code locations:

- [bootstrap_config.py](/home/dan/Projects/SynthiaAiNode/src/ai_node/config/bootstrap_config.py)
- [bootstrap_parser.py](/home/dan/Projects/SynthiaAiNode/src/ai_node/bootstrap/bootstrap_parser.py)
- [trusted_status_telemetry.py](/home/dan/Projects/SynthiaAiNode/src/ai_node/runtime/trusted_status_telemetry.py)

## Target Namespace

After Phase 2, the runtime topic root must be:

```text
hexe/
```

Verified target conversions for this repository:

- `synthia/bootstrap/core` -> `hexe/bootstrap/core`
- `synthia/nodes/{node_id}/status` -> `hexe/nodes/{node_id}/status`

Additional node topic families introduced elsewhere in the codebase during this phase must also use the `hexe/` root.

## Migration Rules

- migrate all runtime topic literals to `hexe/...`
- do not introduce dual-publish or dual-subscribe behavior
- preserve payload shape and lifecycle behavior
- keep capability IDs and task family IDs unchanged
- update tests and docs in the same phase as runtime changes

## Verification Requirements

Phase 2 is complete only when all of the following are true:

- active runtime code no longer publishes or subscribes to `synthia/...`
- bootstrap onboarding uses `hexe/bootstrap/core`
- trusted status telemetry uses `hexe/nodes/{node_id}/status`
- tests expecting MQTT topics are updated and passing
- documentation examples reflect `hexe/...`

## Known Follow-On Work

The current repository still contains legacy `Synthia` naming outside MQTT topics for reasons such as:

- HTTP header compatibility
- service/unit identifiers
- repository/path references to `SynthiaCore`

Those items belong to later cleanup work and must not be conflated with the MQTT namespace migration itself.
