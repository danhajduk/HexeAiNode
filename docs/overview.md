# Hexe AI Node Overview

Hexe AI Node is the node-local runtime that onboards with Hexe Core, persists trust state, declares AI capabilities, syncs governance, exposes a local control API, and manages provider execution/runtime metadata.

## What This Repository Owns

- Python backend entrypoint and runtime flow in `src/ai_node/`
- local FastAPI control APIs
- local persistence under `.run/` and `data/`
- provider runtime visibility and execution routing
- local frontend dashboard in `frontend/`
- local service/bootstrap scripts in `scripts/`

## What The Node Provides

- bootstrap-to-trust onboarding
- trusted capability declaration and governance sync
- operational MQTT status telemetry
- provider capability discovery and metrics
- prompt/service registration scaffolding
- execution authorization gate scaffolding

## What It Depends On From Core

- bootstrap advertisement and onboarding contracts
- trust activation payloads
- capability declaration endpoints
- governance payloads
- shared MQTT topic and notification standards

## What It Does Not Own

- platform-wide lifecycle definitions
- shared trust and governance contracts
- canonical MQTT standards
- platform architecture and terminology

## Relationship to Hexe Core

This node depends on Hexe Core for platform contracts and trusted control-plane behavior. Use [core-references.md](./core-references.md) for the canonical Core docs, and treat the docs in this repo as node-specific implementation guidance only.
