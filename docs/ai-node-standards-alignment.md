# Hexe AI Node Standards Alignment

## Purpose

This document explains how `HexeAiNode` maps to the Hexe Node Standard defined under:

- `/home/dan/Projects/Hexe/docs/standards/Node/`

This file is repo-specific. It does not redefine the shared node standard. It shows how this repository implements it.

## Summary

`HexeAiNode` is already structurally close to the Hexe node standard.

It is especially strong on:

- modular backend boundaries
- typed configuration and state stores
- capability, governance, and readiness implementation depth
- provider boundary implementation
- script baseline
- test coverage depth

Current gaps are mostly in:

- explicit standards mapping documentation
- repo-local provider-boundary documentation
- repo-local scheduler/background-task documentation
- runtime-path ownership documentation

## Standards Map

## Core Node Model

Standard:

- [core-node-model.md](/home/dan/Projects/Hexe/docs/standards/Node/core-node-model.md)

Current repo alignment:

- lifecycle model implemented through:
  - `src/ai_node/lifecycle/`
  - `src/ai_node/runtime/onboarding_runtime.py`
  - `src/ai_node/runtime/node_control_api.py`
  - `src/ai_node/trust/`
- repo docs covering current runtime behavior:
  - [architecture.md](/home/dan/Projects/HexeAiNode/docs/architecture.md)
  - [runtime.md](/home/dan/Projects/HexeAiNode/docs/runtime.md)

Assessment:

- aligned on lifecycle and trust concepts
- needs a clearer repo-local mapping document for review

## Backend Standard

Standard:

- [backend-standard.md](/home/dan/Projects/Hexe/docs/standards/Node/backend-standard.md)

Current repo alignment:

- modular backend package:
  - `src/ai_node/main.py`
  - `src/ai_node/runtime/`
  - `src/ai_node/core_api/`
  - `src/ai_node/capabilities/`
  - `src/ai_node/governance/`
  - `src/ai_node/persistence/`
  - `src/ai_node/providers/`
  - `src/ai_node/security/`
  - `src/ai_node/trust/`

Assessment:

- strongly aligned
- needs clearer repo-local docs linking modules to the standard domains

## API Standard

Standard:

- [api-standard.md](/home/dan/Projects/Hexe/docs/standards/Node/api-standard.md)

Current repo alignment:

- health, node status, capability, governance, provider, and service-control routes exist through:
  - `src/ai_node/runtime/node_control_api.py`

Assessment:

- functionally aligned
- now covered by [api-map.md](/home/dan/Projects/HexeAiNode/docs/api-map.md)

## Frontend Standard

Standard:

- [frontend-standard.md](/home/dan/Projects/Hexe/docs/standards/Node/frontend-standard.md)

Current repo alignment:

- modular feature structure already present:
  - `frontend/src/features/setup/`
  - `frontend/src/features/operational/`
  - `frontend/src/features/diagnostics/`
  - `frontend/src/features/node-ui/`
  - `frontend/src/components/`
  - `frontend/src/theme/`
- shared API wrapper exists:
  - `frontend/src/api.js`

Assessment:

- now aligned more clearly after the extraction documented in [frontend-modularity-audit.md](/home/dan/Projects/HexeAiNode/docs/frontend-modularity-audit.md)

## Onboarding, Trust, And Readiness Standard

Standard:

- [onboarding-trust-and-readiness-standard.md](/home/dan/Projects/Hexe/docs/standards/Node/onboarding-trust-and-readiness-standard.md)

Current repo alignment:

- onboarding and trust flow implemented through:
  - `src/ai_node/runtime/onboarding_runtime.py`
  - `src/ai_node/registration/`
  - `src/ai_node/trust/`
  - `src/ai_node/identity/`
- repo docs:
  - [runtime.md](/home/dan/Projects/HexeAiNode/docs/runtime.md)
  - [integration.md](/home/dan/Projects/HexeAiNode/docs/integration.md)

Assessment:

- strongly aligned in code
- needs a clearer repo-local explanation of post-trust blocked states and readiness mapping

## Scripts And Operations Standard

Standard:

- [scripts-and-operations-standard.md](/home/dan/Projects/Hexe/docs/standards/Node/scripts-and-operations-standard.md)

Current repo alignment:

- script baseline exists:
  - `scripts/bootstrap.sh`
  - `scripts/run-from-env.sh`
  - `scripts/stack-control.sh`
  - `scripts/restart-stack.sh`
  - `scripts/stack.env.example`
  - `scripts/systemd/`

Assessment:

- aligned on script baseline and now documented with a clear repo-local status path in [operations.md](/home/dan/Projects/HexeAiNode/docs/operations.md)

## Background Tasks And Internal Scheduler Standard

Standard:

- [background-tasks-and-internal-scheduler-standard.md](/home/dan/Projects/Hexe/docs/standards/Node/background-tasks-and-internal-scheduler-standard.md)

Current repo alignment:

- recurring and long-lived runtime work exists through:
  - provider refresh behavior
  - status telemetry publishing
  - scheduler lease integration
  - startup timeout and connectivity monitoring

Primary code areas:

- `src/ai_node/runtime/`
- `src/ai_node/telemetry/`
- `src/ai_node/execution/`

Assessment:

- partially aligned in implementation
- needs explicit repo-local documentation of ownership and readiness impact

## Persistence, Configuration, And Security Standard

Standard:

- [persistence-configuration-and-security-standard.md](/home/dan/Projects/Hexe/docs/standards/Node/persistence-configuration-and-security-standard.md)

Current repo alignment:

- typed config modules:
  - `src/ai_node/config/`
- modular state stores:
  - `src/ai_node/persistence/`
  - `src/ai_node/trust/`
  - `src/ai_node/identity/`
- security helpers:
  - `src/ai_node/security/`

Assessment:

- structurally aligned
- now covered by [runtime-path-ownership.md](/home/dan/Projects/HexeAiNode/docs/runtime-path-ownership.md)

## Security And Sensitive-State Standard

Current repo alignment:

- redaction helpers:
  - `src/ai_node/security/redaction.py`
- bootstrap boundary enforcement:
  - `src/ai_node/security/boundaries.py`
- provider credential masking and file permissions:
  - `src/ai_node/config/provider_credentials_config.py`
- trust-state redacted logging:
  - `src/ai_node/trust/trust_store.py`
- onboarding diagnostics redaction:
  - `src/ai_node/diagnostics/onboarding_logger.py`

Assessment:

- now covered by [security-and-sensitive-state.md](/home/dan/Projects/HexeAiNode/docs/security-and-sensitive-state.md)

## Provider Boundary Standard

Standard:

- [provider-boundary-standard.md](/home/dan/Projects/Hexe/docs/standards/Node/provider-boundary-standard.md)

Current repo alignment:

- provider-specific modules already exist under:
  - `src/ai_node/providers/`
  - `src/ai_node/runtime/provider_*`
  - `src/ai_node/config/provider_*`

Assessment:

- strongly aligned in code
- not yet well documented as a first-class repo boundary

## Testing And Documentation Requirements

Standard:

- [testing-and-documentation-requirements.md](/home/dan/Projects/Hexe/docs/standards/Node/testing-and-documentation-requirements.md)

Current repo alignment:

- extensive backend test coverage under:
  - `tests/`
- repo docs already include:
  - overview
  - architecture
  - setup
  - configuration
  - runtime
  - operations
  - integration

Assessment:

- strongly aligned on testing depth
- needs a repo-local compliance appendix and clearer standards mapping

## Current Alignment Snapshot

- Aligned already:
  - backend structure
  - onboarding and trust implementation
  - scripts baseline
  - testing depth
  - provider boundary in code
- Partially aligned:
  - frontend modularity
  - scheduler/background-task visibility
  - API grouping documentation
  - runtime path ownership docs
  - security-boundary documentation
- Not yet explicit:
  - formal repo-local compliance appendix

## Related Repo Docs

- [index.md](/home/dan/Projects/HexeAiNode/docs/index.md)
- [architecture.md](/home/dan/Projects/HexeAiNode/docs/architecture.md)
- [runtime.md](/home/dan/Projects/HexeAiNode/docs/runtime.md)
- [operations.md](/home/dan/Projects/HexeAiNode/docs/operations.md)
- [core-references.md](/home/dan/Projects/HexeAiNode/docs/core-references.md)
