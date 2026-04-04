# Runtime Path Ownership

This document defines the current runtime path ownership model for this repository.

Verified against:

- [main.py](/home/dan/Projects/HexeAiNode/src/ai_node/main.py)
- [stack-control.sh](/home/dan/Projects/HexeAiNode/scripts/stack-control.sh)
- [.gitignore](/home/dan/Projects/HexeAiNode/.gitignore)

## Summary

This repository uses a three-way local runtime path model:

- `.run/` for mutable node control state and local persistent runtime state
- `data/` for local derived provider snapshots, caches, and debug extraction artifacts
- `logs/` for operator-readable log files and debug log streams

This is an allowed Hexe node standard variant for this repo because:

- ownership is explicit
- paths are environment-overridable
- mutable state is kept out of source directories
- runtime artifacts are gitignored

## `.run/` Ownership

`.run/` is the canonical local state directory for backend-controlled node state.

Verified persisted state in code:

- bootstrap config
- trust state
- node identity
- provider selection config
- provider credentials
- task capability selection config
- accepted capability state
- governance state
- combined phase-2 state
- provider capability report cache
- prompt service state
- budget state
- client usage SQLite database

Verified default paths:

- `.run/bootstrap_config.json`
- `.run/trust_state.json`
- `.run/node_identity.json`
- `.run/provider_selection_config.json`
- `.run/provider_credentials.json`
- `.run/task_capability_selection_config.json`
- `.run/capability_state.json`
- `.run/governance_state.json`
- `.run/phase2_state.json`
- `.run/provider_capability_report.json`
- `.run/prompt_service_state.json`
- `.run/budget_state.json`
- `.run/client_usage.db`

Operational meaning:

- `.run/` is restart-persistent local node state
- these files are part of the node’s working runtime identity and control plane
- these files are not safe to commit

## `data/` Ownership

`data/` is used in this repo for local derived runtime artifacts rather than canonical source files.

Verified default data paths in code and runtime:

- `data/provider_registry.json`
- `data/provider_metrics.json`
- `data/provider_enabled_models.json`
- `data/provider_models.json`
- `data/provider_model_capabilities.json`
- `data/openai_pricing_catalog.json`
- `data/response.json`
- `data/promtp_sent.txt`

Operational meaning:

- `data/` holds refresh outputs, provider snapshots, and debug extraction artifacts
- it may be regenerated from runtime actions or provider refresh flows
- it is not the canonical home for trust, onboarding, governance, or identity state
- in this repository it is gitignored and should be treated as local runtime output

## `logs/` Ownership

`logs/` is the operator-facing runtime log area.

Verified log paths in code and scripts:

- `logs/backend.log`
- `logs/frontend.log`
- `logs/onboarding.json`
- `logs/openai_debug.jsonl`

Operational meaning:

- backend and frontend process logs live here when started through stack scripts
- onboarding structured logs live here
- provider debug logs live here when enabled
- logs may contain sensitive operational context and must not be committed

## Script Ownership

The local stack scripts treat `.run/` and `logs/` as runtime directories they are responsible for creating.

Verified in [stack-control.sh](/home/dan/Projects/HexeAiNode/scripts/stack-control.sh):

- `RUN_DIR=\"$ROOT_DIR/.run\"`
- `LOG_DIR=\"$ROOT_DIR/logs\"`
- `mkdir -p \"$RUN_DIR\" \"$LOG_DIR\"`

This means:

- script-managed PID files belong in `.run/`
- script-managed process logs belong in `logs/`

## Standard Alignment Decision

Current decision:

- the existing `.run/`, `data/`, and `logs/` layout remains an allowed repository variant

Reason:

- the Hexe node standard requires explicit ownership and safe separation, not one fixed directory name
- this repo already separates control state, derived data, and logs cleanly
- all major paths are configurable through environment variables or startup arguments

Migration guidance:

- no immediate structural migration is required
- future work should preserve the ownership split even if directory names change later
- new state categories should default to `.run/` unless they are clearly derived snapshots or log streams

## Compliance Notes

- aligned: explicit mutable local state directory
- aligned: explicit local log directory
- aligned: explicit derived-data directory
- aligned: gitignored runtime artifacts
- follow-up: tighten sensitive-state documentation for specific files under `.run/`, `data/`, and `logs/`
