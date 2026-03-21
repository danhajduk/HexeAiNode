# Hexe AI Node Documentation

## Start Here

- [Root README](../README.md): quickstart commands and repo entry point.
- [Overview](./overview.md): what this node does and what it depends on.
- [Architecture](./architecture.md): node-internal components and runtime boundaries.
- [Setup](./setup.md): install, configure, and start the node locally.

## Node Documentation

- [Overview](./overview.md): scope, role, and ownership boundaries.
- [Architecture](./architecture.md): backend, runtime, persistence, and UI component map.
- [Configuration](./configuration.md): environment variables, state files, and secret handling.
- [Runtime](./runtime.md): lifecycle, retries, telemetry, and degraded behavior.
- [Integration](./integration.md): how this node talks to Core and MQTT.

## Integration With Hexe Core

- [Core References](./core-references.md): canonical platform documents and `docs/Core-Documents` symlink hints.
- [Documentation Policy](./README.md): what stays in this repo versus what belongs in Core.

Internal identifiers such as MQTT topics, task families, service IDs, and header names may still use legacy `Synthia` naming during migration.

## Operations

- [Operations](./operations.md): logs, health checks, recovery steps, and incident notes.

## Core References

- [Core Reference Map](./core-references.md): one bridge page for canonical Core documentation.
