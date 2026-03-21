# Integration

This document summarizes how this node uses platform contracts without redefining them.

## Core APIs Used By The Node

- onboarding and trust flow through the onboarding runtime
- capability declaration via `POST /api/system/nodes/capabilities/declaration`
- provider intelligence submission via `POST /api/system/nodes/providers/capabilities/report`
- governance sync via `GET /api/system/nodes/governance/current?node_id=...`

## MQTT Usage

- bootstrap discovery uses anonymous MQTT through the bootstrap runner
- trusted operational status uses `hexe/nodes/{node_id}/status`
- trusted telemetry uses operational MQTT credentials from local trust state

## Capabilities Declared

The node declares task-family, provider, node-feature, and environment-hint data built from local runtime state. The exact platform contract lives in Core; this repo implements the local manifest build and submission flow.

## Governance And Configuration Expectations

- Core provides trusted governance after capability acceptance.
- The node persists governance metadata locally and evaluates freshness before steady-state operation.
- Local configuration selects providers and task families before declaration.

## Telemetry And Health Returned

- trusted status publish result is tracked by the telemetry publisher
- provider intelligence and metrics are exposed through debug/control APIs
- service health is surfaced through user-level systemd queries

## Canonical Platform Contracts

- [Core References](./core-references.md)
