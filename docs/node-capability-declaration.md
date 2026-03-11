# AI Node Capability Declaration (Phase 2.2)

Status: Draft architecture target
Implementation status: Not developed
Last updated: 2026-03-11

## Purpose

This document defines the Phase 2.2 capability declaration model for AI Node.
Phase 2.2 occurs only after trust activation (Phase 2.1).

Core does not know a node's actual capability profile until the node submits a formal declaration manifest.

## Scope Boundary

Capability declaration is:

- not prompt registration
- not prompt governance
- not direct AI execution

Capability declaration is the structured statement of what the node supports and what the operator enables.

## Supported Vs Enabled Model

The declaration model separates two concepts:

- `supported`: what this node can technically support
- `enabled`: what the operator has chosen to enable on this node

Rules:

- Supported does not imply approved policy use.
- Enabled does not imply unlimited use.
- Core stores both supported and enabled views.

## Operator-Driven Provider/Service Selection

Provider/service activation is user-driven during 2.2 setup.

### UX Intent

- Ask: "What should be enabled on this node?"
- Do not assume all supported providers are enabled.
- Require explicit operator choice for enabled providers/services.

### Initial Provider Set

- OpenAI: only real provider option in this phase
- Future provider placeholders remain available in manifest shape

### Secret Handling

- Provider credentials should remain local to the node whenever possible.
- Core should receive capability and enablement metadata, not unnecessary provider secrets.

## Capability Manifest Structure

Capability declaration is submitted as a formal manifest with stable groups.

### Group 1: Functional AI Task Families

Initial declaration targets:

- `text_classification`
- `email_classification`
- `image_classification`
- `image_generation`

These are declaration targets and not guarantees that all are immediately active in implementation.

### Group 2: Provider Support

- Supported providers list (technical capability)
- Enabled providers list (operator selection)
- Initial implemented path: OpenAI
- Placeholders for future providers/local services

### Group 3: Node Features

Node-level features declared independently of task families.

Examples:

- `policy_enforcement`
- `telemetry_support`
- `prompt_registration_support`
- `prompt_governance_support`
- `operational_mqtt_support`
- `local_runtime_controller_support` (future)

Feature model guidance:

- Keep extensible but explicit.
- Separate execution-facing and management-facing features.

### Group 4: Environment/Resource Hints

Lightweight environment hints for future policy/routing context.

Examples:

- `hostname`
- `os_platform`
- `memory_class`
- `gpu_present` (boolean)

Boundary:

- This is not full telemetry.
- This is not a full hardware inventory.
- This does not promise resource-based scheduling in current phases.

## Submission And Core Acceptance Flow

Capability declaration is API-based and deterministic.

1. Node submits capability manifest to Core API.
2. Core validates manifest format/required structure.
3. Core stores accepted capability record.
4. Core acknowledges accepted profile to node.

Acceptance semantics:

- Core validates structure and record integrity.
- Capability acceptance does not automatically enable functionality by policy.
- Later policy decisions remain a separate governance step.

## Governance Boundary

- Core stores declared capabilities; Core does not invent undeclared node capabilities.
- Node declares capabilities; node does not self-authorize global governance policy.
