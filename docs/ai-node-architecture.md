# AI Node Architecture

Status: Draft architecture target
Implementation status: Not developed
Last updated: 2026-03-11

## Purpose

This document defines the initial target architecture for the Synthia AI Node.
The AI Node is a remote Synthia service paired to Core, not a Supervisor-managed local standalone addon.

Because this repository currently contains architecture planning tasks only, all runtime behavior described here is target design and not yet implemented.

## Section Status Map

Status: Planned

- Architectural Positioning: Planned
- Authority Separation: Planned
- Node/Core Responsibility Boundaries: Planned
- Major Architectural Layers: Planned
- Bootstrap Flow (Phase 1): Planned
- Bootstrap Message Contract: Planned
- Registration Handshake (Phase 2.0): Planned
- Operator Approval Via Core UI: Planned
- Initial Trust Activation Payload (Phase 2.1): Planned
- Local Persisted Node State: Planned
- Node Lifecycle State Model: Planned
- Post-Bootstrap Operational Channel Separation: Planned
- Initial Baseline Policy Structure: Planned
- Trusted MQTT Operational Identity Model: Planned
- Reconnect And Resync Behavior: Planned
- Baseline Status Telemetry Architecture: Planned
- Security Boundaries: Planned
- Future placeholders and roadmap sections: Planned

## Architectural Positioning

- AI Node runs as a remote service and pairs with a Synthia Core instance.
- Synthia Core retains governance authority.
- AI Node executes node-local responsibilities (bootstrap, registration, local policy enforcement, telemetry).
- Architecture is intentionally future-proofed for additional local providers and a future runtime manager layer.

## Authority Separation

Core authority and Node execution responsibilities are intentionally separated.

- Core authority:
  - trust and approval decisions
  - baseline governance policy issuance
  - operational identity issuance
  - future governance and policy refinement
- Node execution scope:
  - bootstrap listener behavior
  - registration and trust-client behavior
  - capability declaration and local enforcement behavior
  - node status/telemetry publication

## Node/Core Responsibility Boundaries

This section defines strict ownership to keep governance centralized in Core and execution localized to the AI Node.

### Core Responsibilities

- Trust authority and trust lifecycle decisions
- Operator approval and rejection workflow
- Initial baseline policy issuance
- MQTT operational identity/token issuance
- Future governance and policy refinement ownership

### AI Node Responsibilities

- Bootstrap listening and discovery participation
- Self-introduction during registration
- Capability declaration to Core
- Local baseline policy enforcement
- Telemetry and status publication

### Core Must Not

- Assume node capabilities before the node has declared them
- Execute node-local actions on behalf of a node without explicit node participation
- Delegate global governance authority to node-side components

### AI Node Must Not

- Invent or apply global policy independent of Core
- Self-approve trust without operator/Core approval flow
- Treat undeclared capabilities as implicitly authorized

## Major Architectural Layers

### 1) Bootstrap Listener

Node-side component that connects to bootstrap discovery channels and waits for Core bootstrap advertisements.

### 2) Registration/Trust Client

Node-side component that performs API registration with Core and handles trust activation material after approval.

### 3) Capability Manager

Node-side component responsible for representing declared node capabilities and enabled provider/service configuration.

### 4) Baseline Policy Engine

Node-side component that stores and enforces initial baseline policy received from Core.

### 5) Telemetry/Status Agent

Node-side component that reports node lifecycle and operational status for Core visibility.

### 6) Future Execution Gateway (Placeholder)

Reserved layer for future normalized AI execution APIs. Included now to prevent architectural drift as execution capabilities are introduced in later phases.

## Bootstrap Flow (Phase 1)

### Required Operator Input

- `mqtt_host` (bootstrap broker host/address)
- `node_name` (human-readable node identity label)

### Bootstrap Connection Rules

- Host is exactly the operator-provided `mqtt_host`
- Port is fixed at `1884`
- Access mode is anonymous for bootstrap discovery
- Node behavior is subscribe-only during bootstrap

### Bootstrap Topic Usage And Purpose

- Bootstrap topics exist only for Core discovery advertisements
- Core publishes registration-discovery information
- Nodes consume bootstrap advertisements and do not publish on bootstrap topics

### Bootstrap Channel Restrictions

- Bootstrap on `1884` is read-only from the node perspective
- No secrets or credentials in bootstrap traffic
- No telemetry/status traffic on bootstrap topics
- No control/command traffic on bootstrap topics

## Bootstrap Message Contract (Discovery Only)

Core bootstrap advertisements are minimal discovery payloads. They are not trust artifacts, policy packages, or operational credentials.

### Required Bootstrap Fields

- `core_id`
- `core_api_url`
- `registration_path` (or full registration endpoint)
- `protocol_version`
- `registration_open` (boolean)

### Validation Expectations

Node-side bootstrap processing must:

- Ignore malformed payloads (invalid JSON/schema mismatch)
- Ignore incomplete payloads (missing required fields)
- Ignore stale payloads (older than local freshness threshold)
- Ignore payloads with unsupported `protocol_version`
- Treat `registration_open=false` as discovery-only with no registration attempt

## Registration Handshake (Phase 2.0)

After valid bootstrap discovery, registration occurs over Core API only.

### Registration Request Payload

- `node_name`
- `node_type`: `ai-node`
- `node_software_version`
- `protocol_version`
- `hostname` (optional)

### Core Registration State

- Core records a pending registration entry for the discovered node identity request.
- Pending registration does not imply trust activation.
- Core is expected to recognize the `ai-node` class before approval.

## Operator Approval Via Core UI

Node admission requires authenticated operator approval in Core UI.

### Approval Flow

1. Core creates approval session material (token/link/session ID).
2. Operator authenticates in Core UI.
3. Operator reviews pending node request and approves or rejects.
4. Core records the final decision and only approved nodes proceed to trust activation.

### Headless Node Behavior

- Headless node remains in `pending_approval` until Core decision is available.
- Node should present clear local status/instructions indicating approval must be completed in Core UI.
- Rejected nodes must not receive trust tokens or operational credentials.

## Initial Trust Activation Payload (Phase 2.1)

After approval, Core returns trust activation material to the node.

### Trust Activation Response

- `node_id`
- `accepted_node_name`
- `node_type`
- `paired_core_id`
- `node_trust_token`
- `initial_baseline_policy`
- `operational_mqtt_identity` / token
- `operational_mqtt_endpoint` details

### Trust Package Persistence

- Node must persist the trust package as sensitive local state.
- Persisted trust package must survive reboot and upgrade.
- Trust activation establishes node/Core pairing but does not yet represent full capability-aware policy.

## Local Persisted Node State

After trust activation, the node stores the minimum durable state required for deterministic reconnect and local baseline enforcement.

### Required Persisted Fields

- `node_id`
- `node_name`
- `node_type`
- `paired_core_id`
- `core_api_endpoint`
- `trust_token`
- `baseline_policy_version`
- `operational_mqtt_identity` / token
- `bootstrap_mqtt_host`
- `registration_timestamp`

### Persistence Expectations

- State persists across restart and software upgrade.
- Secrets/tokens are treated as sensitive local state.
- Normal reboot does not require full re-onboarding.

## Node Lifecycle State Model

### States

- `unconfigured`
- `bootstrap_connecting`
- `bootstrap_connected`
- `core_discovered`
- `registration_pending`
- `pending_approval`
- `trusted`
- `capability_setup_pending`
- `operational`
- `degraded`

### Transition Notes

- `unconfigured -> bootstrap_connecting`: operator provides bootstrap host/name.
- `bootstrap_connecting -> bootstrap_connected`: anonymous broker connection established.
- `bootstrap_connected -> core_discovered`: valid Core bootstrap advertisement received.
- `core_discovered -> registration_pending`: API registration request sent.
- `registration_pending -> pending_approval`: Core records pending node.
- `pending_approval -> trusted`: operator approves and trust package issued.
- `trusted -> capability_setup_pending`: node begins post-trust capability declaration.
- `capability_setup_pending -> operational`: Core accepts capability profile and baseline operations are active.
- Any active state -> `degraded`: policy stale, connectivity loss, or trust-channel impairment.

## Post-Bootstrap Operational Channel Separation

### Channel Roles

- Bootstrap discovery: anonymous MQTT on port `1884`, subscribe-only node behavior, discovery payloads only.
- Trusted MQTT operations: authenticated/scoped MQTT using Core-issued operational identity/token.
- Control/API operations: deterministic Core API path for registration, approval status, capability submission, and policy interactions.
- Telemetry: trusted channel(s) only, not anonymous bootstrap.

### Why Separation Is Mandatory

- Prevents anonymous discovery transport from becoming a general-purpose control plane.
- Keeps trust material and operational commands off discovery channels.
- Preserves clear audit and governance boundaries between discovery and trusted operations.

## Initial Baseline Policy Structure

Initial baseline policy is the minimum viable governance package delivered at trust activation, before capability-aware policy refinement.

### Baseline Policy Includes

- `policy_version`
- `issued_at` timestamp
- refresh expectations (`refresh_after`, `expires_at`, or equivalent)
- generic `ai-node` class rules
- telemetry expectations
- feature gating defaults

### Intentionally Excluded At This Stage

- Fine-grained capability-shaped policy
- workload-specific execution policy
- provider/runtime scheduling directives

## Trusted MQTT Operational Identity Model

After approval/trust activation, Core provisions operational MQTT credentials scoped for the paired node.

### Provisioned To Node

- MQTT username/identity
- MQTT token/password
- trusted MQTT host/port
- allowed topic namespace/scope

### Separation From Bootstrap MQTT

- Bootstrap MQTT is anonymous, read-only discovery.
- Trusted operational MQTT is authenticated, scoped, and policy-governed.
- Anonymous bootstrap is never reused as general operational messaging.

## Reconnect And Resync Behavior

On reboot/restart/outage, node behavior must be deterministic and safety-first.

### Expected Behavior

- Restore persisted local identity/trust state
- Reconnect to paired Core and trusted MQTT first
- Reuse stored initial baseline policy until refreshed/replaced
- Fall back to bootstrap discovery only when pairing context is unavailable or explicitly invalid

### Degraded/Stale Concepts

- `degraded`: temporary inability to reach trusted control/telemetry channels
- `policy_stale`: baseline policy refresh window exceeded while still operating under last-known constraints

## Baseline Status Telemetry Architecture

Before AI execution workloads exist, telemetry focuses on node operational status.

### Baseline Status Signals

- `bootstrap_connected`
- `pending_approval`
- `trusted`
- `capability_declared`
- `degraded`
- `disconnected`
- `policy_stale`

### Transport Guidance

- Emit status on trusted channels (trusted MQTT and/or API-backed status endpoints).
- Do not send telemetry on anonymous bootstrap transport.

## Security Boundaries: Bootstrap, Trust, Operations

### Security Boundary Rules

- Anonymous bootstrap has strict discovery-only limits.
- Operator approval in Core UI is mandatory before trust activation.
- Token issuance authority remains in Core.
- Node stores issued secrets/tokens as sensitive local state.
- API and MQTT trust boundaries remain explicit and non-interchangeable.

### Must Not (Unsafe Shortcuts)

- No secrets in bootstrap payloads.
- No node publish traffic on bootstrap channel.
- No automatic trust activation without authenticated operator approval.
- No use of bootstrap channel for control, policy, or telemetry.

## Future Execution Gateway Placeholder

Future phases will introduce a normalized execution gateway API for:

- text classification
- email classification
- image classification
- image generation

This placeholder exists now to keep Phase 1/2 architecture aligned with future execution direction without implying that execution workloads are currently implemented.

## Future Local Runtime Manager Placeholder

Future architecture may add a local runtime manager with concepts such as:

- local runtime controller
- desired state
- observed state
- managed local providers

This is intentionally a placeholder and not a full runtime-controller design in current phases.

## Phased Architecture Roadmap

### Phase 001: Bootstrap And Registration

- Node discovers Core over anonymous bootstrap and performs API registration.
- Unlocks deterministic onboarding entrypoint without pre-shared trust.

### Phase 002: Trust Activation And Capability Declaration

- Operator approval, trust package issuance, and capability declaration/acceptance.
- Unlocks trusted operations and capability-aware platform understanding.

### Future: Prompt Governance

- Adds prompt-level governance surfaces and policy controls.

### Future: OpenAI Execution

- Adds initial real execution path for OpenAI-backed task families.

### Future: Multi-Provider Support

- Expands provider model beyond OpenAI with governed enablement.

### Future: Local Runtime Support

- Adds managed local runtime lifecycle and desired/observed reconciliation patterns.

## Out Of Scope For Now

- Full AI workload execution implementation
- Detailed runtime-manager/controller implementation
- Multi-provider execution orchestration
- Fine-grained capability-aware policy synthesis
- Production hardening details (performance tuning, HA topology, advanced observability pipelines)

## Notes For Future Phases

- Keep bootstrap and trust activation concerns isolated from execution concerns.
- Preserve Core-governs / Node-executes boundary as capabilities expand.
- Extend capability and policy layers without collapsing authority boundaries.
- Capability declaration details are specified in `docs/node-capability-declaration.md`.

## See Also

- [Phase 1 Overview](./phase1-overview.md)
- [AI Node Phase 2 Implementation Plan](./ai-node/phase2-implementation-plan.md)
- [AI Node Capability Declaration](./node-capability-declaration.md)
- [Synthia Platform Architecture](../../Synthia/docs/platform-architecture.md)
- [Synthia MQTT Platform](../../Synthia/docs/mqtt-platform.md)
- [Synthia API Reference](../../Synthia/docs/api-reference.md)
