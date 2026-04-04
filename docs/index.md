# Hexe AI Node Documentation

## Start Here

- [Root README](../README.md): quickstart commands and repo entry point.
- [Overview](./overview.md): what this node does and what it depends on.
- [Architecture](./architecture.md): node-internal components and runtime boundaries.
- [Setup](./setup.md): install, configure, and start the node locally.
- [Standards Alignment](./ai-node-standards-alignment.md): how this repo maps to the Hexe node standard.
- [Compliance Summary](./ai-node-standard-compliance-summary.md): quick standards-alignment snapshot for this repo.
- [Compliance Appendix](./ai-node-standards-compliance-appendix.md): formal evidence-backed checklist against the Hexe node standard.

## Node Documentation

- [Overview](./overview.md): scope, role, and ownership boundaries.
- [Architecture](./architecture.md): backend, runtime, persistence, and UI component map.
- [Configuration](./configuration.md): environment variables, state files, and secret handling.
- [Runtime](./runtime.md): lifecycle, retries, telemetry, and degraded behavior.
- [Integration](./integration.md): how this node talks to Core and MQTT.
- [Standards Alignment](./ai-node-standards-alignment.md): repo-specific map to the Hexe node standards.
- [Compliance Summary](./ai-node-standard-compliance-summary.md): aligned, partially aligned, and follow-up status.
- [Compliance Appendix](./ai-node-standards-compliance-appendix.md): formal standard-by-standard evidence map.
- [Frontend Modularity Audit](./frontend-modularity-audit.md): verified `App.jsx` extraction targets and completed cleanup.
- [API Map](./api-map.md): route families grouped by the Hexe node API standard, with canonical versus compatibility notes.
- [Provider Boundary](./provider-boundary.md): what is node-generic versus provider-specific in this repo.
- [Scheduler And Background Tasks](./scheduler-and-background-tasks.md): recurring work, lease compatibility, and runtime ownership.
- [Runtime Path Ownership](./runtime-path-ownership.md): `.run`, `data`, and `logs` ownership plus current allowed-variant decision.
- [Security And Sensitive State](./security-and-sensitive-state.md): verified token, credential, redaction, and debug-artifact handling.

## Integration With Hexe Core

- [Core References](./core-references.md): canonical platform documents and `docs/Core-Documents` symlink hints.
- [Documentation Policy](./README.md): what stays in this repo versus what belongs in Core.

Compatibility-sensitive identifiers such as `X-Synthia-*` headers and `synthia-*` service IDs still use legacy naming during migration.

## Operations

- [Operations](./operations.md): logs, health checks, recovery steps, and incident notes.

## Core References

- [Core Reference Map](./core-references.md): one bridge page for canonical Core documentation.
