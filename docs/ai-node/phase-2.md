# Phase 2 — Capability Declaration and Baseline Governance

Status: Active
Implementation status: Implemented (core scope) + Partially implemented (Phase 2 extension scaffolding)
Last updated: 2026-03-19

## Goal
Allow nodes to declare their AI capabilities and receive governance policies.

## Node Responsibilities

- Ask operator which providers/services are enabled
- Build capability manifest
- Submit capability declaration to Core

## Example Capability Data

Task Families:
- task.classification
- task.classification.email
- task.classification.image
- task.summarization.text
- task.summarization.email
- task.generation.text
- task.generation.image

Providers:
- openai

Environment hints:
- host
- memory class
- GPU availability

## Core Responsibilities

- Validate node capability declaration
- Store capability profile
- Issue baseline governance bundle

## Lifecycle

Core implemented lifecycle path:

`trusted -> capability_setup_pending -> capability_declaration_in_progress -> capability_declaration_accepted -> operational`

Additional implemented runtime behavior:

- trusted startup can fast-path to operational when accepted capability + fresh governance already exist
- trusted startup refreshes governance before settling in `capability_setup_pending` when accepted capability exists but the saved governance bundle is stale
- temporary failures in capability declaration or governance sync can move node to `degraded`
- operational MQTT readiness and trusted telemetry publish status are retained as runtime health signals after acceptance rather than post-acceptance lifecycle gates
- deterministic recovery path (`POST /api/node/recover`) returns to:
  - `operational` when accepted capability + fresh governance are present
  - `capability_setup_pending` otherwise

## Phase Boundary Note

Per `docs/Core-Documents/nodes/node-capability-activation-architecture.md`, Phase 2 covers capability declaration, governance issuance/refresh, operational status, and lifecycle/governance telemetry only.

## Prompt / Execution Scaffold (Out Of Phase 2 Core Scope)

Node-local scaffolding now exists for next-phase prompt controls:

- prompt/service registration persistence
- probation transitions
- execution authorization endpoint with deny-by-default behavior for unregistered prompts

This scaffold is implemented locally and documented in the node-control API contract, but it aligns with the node's later prompt-execution phase rather than the Core Phase 2 baseline. It should not be used as the criterion for calling Phase 2 complete.

## See Also

- [Phase 2 Implementation Plan](./phase2-implementation-plan.md)
- [Phase 2 Validation Checklist](./phase2-validation-checklist.md)
- [Phase 2 Review and Handoff](./phase2-review-handoff.md)
- [Node Control API Contract](./node-control-api-contract.md)
