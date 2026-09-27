# Integration

This document summarizes how this node uses platform contracts without redefining them.

## Core APIs Used By The Node

- onboarding and trust flow through the onboarding runtime
- capability declaration via `POST /api/system/nodes/capabilities/declaration`
- provider intelligence submission via `POST /api/system/nodes/providers/capabilities/report`
- governance sync via `GET /api/system/nodes/governance/current?node_id=...`
- provider-side service-token validation via `POST /api/system/nodes/services/introspect`
- budget reconciliation via `POST /api/system/nodes/budgets/usage-summary`

Provider execution routes require a Core-issued bearer token. The node fails closed unless Core introspection confirms the caller subject, provider audience, and `service.execute:<task_family>` scope.

## MQTT Usage

- bootstrap discovery uses anonymous MQTT through the bootstrap runner
- trusted operational status uses `hexe/nodes/{node_id}/status`
- trusted telemetry uses operational MQTT credentials from local trust state
- node-originated domain events publish directly to `hexe/events/{domain}/{event_name}` using QoS 1 and `retain=false`

### Direct Shared Domain Events

`DomainEventPublisher` validates the canonical node-originated envelope before publishing. The path after `hexe/events/` must equal the dotted `event_type` with dots replaced by slashes. For example, `delivery.window.upserted` publishes to `hexe/events/delivery/window/upserted`.

The publisher sets `source.node_id` from trusted local state, uses `event_id` for deduplication, and rejects payloads larger than 65,536 UTF-8 JSON bytes. It also rejects legacy Core-promotion fields and fields carrying secrets, credentials, tokens, attachments, raw message bodies, prompts, or other private raw content. Callers must publish only small, structured, non-private domain metadata in `subject` and `data`.

This contract does not alter bootstrap, command, notification, telemetry, state, or `hexe/nodes/{node_id}/status` topics. This repository currently has no shared-domain-event consumer and therefore has no promotion envelope to unwrap.

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
