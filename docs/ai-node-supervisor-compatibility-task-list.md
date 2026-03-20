# AI Node Supervisor Compatibility Task List

Status: Implemented task analysis based on design source and current repository state
Last updated: 2026-03-16

## Source Of Truth

Primary design source:

- `../Synthia/docs/Upgrades/synthia-core-supervisor-node-design.md`

Key source sections used in this task list:

- Section 2, High Level Architecture
- Section 4, Supervisor
- Section 5, Supervisor API
- Section 6, Node Model
- Section 7, Node Startup Flow
- Section 8, Installation Flow
- Section 9, Host Telemetry

## Current Repository Gap Summary

The current AI-node implementation is still built around direct Core pairing and bootstrap-driven Core discovery rather than a Supervisor-mediated host model.

Repository evidence:

- [docs/ai-node-architecture.md](./ai-node-architecture.md) states the AI Node is "not a Supervisor-managed local standalone addon".
- [src/ai_node/runtime/onboarding_runtime.py](../src/ai_node/runtime/onboarding_runtime.py) performs registration directly against Core after bootstrap discovery.
- [src/ai_node/main.py](../src/ai_node/main.py) starts the node around bootstrap MQTT, trust state, capability declaration, and local control API, but has no Supervisor detection or Supervisor registration path.
- [src/ai_node/lifecycle/node_lifecycle.py](../src/ai_node/lifecycle/node_lifecycle.py) has no Supervisor-aware lifecycle states.

Because the new design makes the required topology `Core -> Supervisor -> Nodes`, Supervisor compatibility is not a small integration. It is a first-order architecture change.

## Detailed Task List

## 1. Re-baseline node architecture around `Core -> Supervisor -> Nodes`

Source:

- Design section 2 says the ecosystem now consists of `Core -> Supervisor -> Nodes`.
- Design section 6 says anything outside Core becomes a Node and communicates via Core API, MQTT, and Supervisor API.

Tasks:

- Replace the current repository architecture language that describes the AI Node as directly paired to Core without Supervisor involvement.
- Define the AI Node's new local authority boundary:
  - Supervisor owns host resources and local lifecycle control.
  - AI Node owns capability execution, capability declaration, local provider/runtime state, and node-local health.
  - Core remains governance and orchestration authority.
- Create an explicit compatibility target for this repository:
  - "AI Node requires a local Supervisor on every supported host"
  - "AI Node may not assume direct host ownership for process lifecycle decisions"
  - "AI Node may not bypass Supervisor for normal startup"
- Identify which existing local responsibilities stay in the node and which move behind the Supervisor contract.
- Produce a transition matrix for current subsystems:
  - bootstrap discovery
  - onboarding
  - trust activation
  - telemetry
  - service management
  - provider runtime refresh
  - node control API

Deliverables:

- Updated node architecture document
- Internal subsystem ownership table
- Supervisor compatibility checklist tracked in docs

## 2. Add a Supervisor client and connection model

Source:

- Design section 5 defines the Supervisor API transports:
  - preferred `unix:///run/synthia/supervisor.sock`
  - fallback `http://127.0.0.1:8765/api`
- Design section 5 says the Supervisor API must never bind to external interfaces by default.

Tasks:

- Add a dedicated Supervisor client module in the backend.
- Support transport resolution in this order:
  - Unix socket first
  - loopback HTTP fallback second
- Add configuration for Supervisor endpoint discovery with safe defaults that match the design.
- Ensure all Supervisor traffic is constrained to local-only transports.
- Add API wrapper methods for the expected Supervisor endpoints:
  - `/api/health`
  - `/api/host/info`
  - `/api/resources`
  - `/api/runtimes`
  - `/api/runtimes/register`
  - `/api/runtimes/start`
  - `/api/runtimes/stop`
  - `/api/runtimes/restart`
  - `/api/runtimes/heartbeat`
- Define request and response schema models for those calls in this repo, even if the Supervisor implementation lands elsewhere.
- Add connection-state diagnostics so the node can report:
  - supervisor detected
  - transport in use
  - registration status
  - last heartbeat result
  - last local API error

Known contract detail provided for `/api/health`:

- Purpose: quick supervisor liveness/readiness check
- Response envelope:
  - `ok`
  - `data`
  - `error`
  - `generated_at`
- `data` fields currently specified:
  - `status`
  - `service`
  - `version`
  - `host_id`
  - `started_at`
  - `uptime_seconds`
  - `ready`
- `status` values currently specified:
  - `ok`
  - `degraded`
  - `error`
- `ready` indicates whether Supervisor is ready to accept runtime operations

Implementation tasks for this endpoint:

- Add a typed health-response model matching the provided envelope and `data` payload.
- Use `/api/health` as the first probe during Supervisor detection before attempting runtime registration.
- Treat `ok=true` and `data.ready=true` as the minimum success condition for normal runtime operations.
- Decide explicit node behavior for partial health cases:
  - `ok=true` with `status=degraded`
  - `ok=true` with `ready=false`
  - `ok=false` with structured `error`
- Persist last-known Supervisor health snapshot for diagnostics only, not as authority for continued operation.
- Surface these health fields in the node status/debug output:
  - `service`
  - `version`
  - `host_id`
  - `status`
  - `ready`
  - `generated_at`
- Add retry/backoff rules for health probing that are separate from runtime heartbeat logic.
- Add tests covering:
  - healthy ready Supervisor
  - reachable but not ready Supervisor
  - degraded Supervisor
  - invalid envelope or missing required fields
  - clock-skew or stale `generated_at` handling if freshness rules are added

Known contract detail provided for `/api/host/info`:

- Purpose: return static-ish host identity and environment metadata
- Response envelope:
  - `ok`
  - `data`
  - `error`
  - `generated_at`
- `data` fields currently specified:
  - `host_id`
  - `hostname`
  - `machine_id`
  - `platform`
  - `hardware`
  - `network`
  - `supervision_mode`
- `platform` fields currently specified:
  - `os`
  - `os_version`
  - `kernel`
  - `architecture`
- `hardware` fields currently specified:
  - `vendor`
  - `model`
  - `cpu_model`
  - `cpu_physical_cores`
  - `cpu_logical_cores`
  - `memory_total_mb`
- `network` fields currently specified:
  - `primary_interface`
  - `reported_ipv4`
  - `reported_ipv6`
  - `mac_addresses`
- `machine_id` is optional but useful for host fingerprinting
- `reported_ipv4` and `reported_ipv6` are metadata only and must never be treated as identity
- `supervision_mode` values currently specified:
  - `direct`
  - `supervised`

Implementation tasks for this endpoint:

- Add a typed host-info response model with optional `machine_id`.
- Use `host_id` as the primary Supervisor host identifier in node diagnostics and local state.
- Treat `machine_id` as auxiliary fingerprint metadata only, not as node identity.
- Surface `supervision_mode` in node status so the runtime can distinguish a production supervised path from any development compatibility path.
- Record platform and hardware facts as informational metadata unless an explicit local policy depends on them.
- Ensure `reported_ipv4`, `reported_ipv6`, and `mac_addresses` are not reused as trust identity fields, pairing keys, or external bind targets.
- Decide whether host fingerprint changes should trigger a warning, re-registration, or no action.
- Add tests for:
  - complete payloads
  - missing optional `machine_id`
  - empty network arrays
  - invalid `supervision_mode`
  - host metadata changes across restarts

Known contract detail provided for `/api/resources`:

- Purpose: return current host resource state and pressure
- Response envelope:
  - `ok`
  - `data`
  - `error`
  - `generated_at`
- `data` sections currently specified:
  - `cpu`
  - `memory`
  - `disk`
  - `gpu`
  - `pressure`
- `cpu` fields currently specified:
  - `usage_percent`
  - `load_avg_1m`
  - `load_avg_5m`
  - `load_avg_15m`
- `memory` fields currently specified:
  - `total_mb`
  - `used_mb`
  - `available_mb`
  - `usage_percent`
- `disk` is a list of per-mount snapshots with:
  - `mountpoint`
  - `total_mb`
  - `used_mb`
  - `available_mb`
  - `usage_percent`
- `gpu` is a list and can be empty when no GPU exists
- `pressure` fields currently specified:
  - `state`
  - `reasons`
- `pressure.state` values currently specified:
  - `normal`
  - `warning`
  - `degraded`
  - `critical`

Implementation tasks for this endpoint:

- Add typed resource models for CPU, memory, disk, GPU, and pressure.
- Make resource polling optional and separate from the Supervisor health probe.
- Define how node behavior changes by `pressure.state`:
  - `normal`: no throttling
  - `warning`: reduce non-essential background work
  - `degraded`: block heavy optional work and mark constrained status
  - `critical`: enter protective mode for expensive local operations
- Decide which existing AI-node subsystems should react first:
  - provider refresh
  - pricing refresh
  - local execution routing
  - future local model runtimes
- Add GPU-aware logic paths without assuming GPU presence.
- Expose the current pressure state and top reasons in the local status API.
- Add tests for:
  - CPU and memory-only hosts
  - multiple disk mountpoints
  - empty GPU list
  - malformed resource numbers
  - pressure transitions over time

Known contract detail provided for `/api/runtimes`:

- Purpose: list registered runtimes known to the Supervisor
- Response envelope:
  - `ok`
  - `data`
  - `error`
  - `generated_at`
- `data` fields currently specified:
  - `items`
  - `count`
- Per-runtime fields currently specified:
  - `runtime_id`
  - `node_id`
  - `node_type`
  - `display_name`
  - `runtime_kind`
  - `state`
  - `health`
  - `registered_at`
  - `last_heartbeat_at`
- `runtime_kind` values currently specified:
  - `systemd`
  - `docker`
  - `process`
  - `external`
- `state` values currently specified:
  - `registered`
  - `starting`
  - `running`
  - `stopping`
  - `stopped`
  - `failed`
  - `unknown`
- `health` values currently specified:
  - `healthy`
  - `degraded`
  - `unhealthy`
  - `unknown`

Implementation tasks for this endpoint:

- Add typed runtime-list response models.
- Use `/api/runtimes` as a read-after-write verification path after runtime registration.
- Define how the AI Node identifies its own record:
  - preferred by `runtime_id`
  - validated against `node_id`
  - validated against `node_type=ai-node`
- Add logic to detect duplicate or conflicting AI-node runtime registrations on the same host.
- Decide how much peer-runtime visibility the AI Node should expose locally:
  - full list for diagnostics
  - summarized sibling-runtime view
  - no peer detail beyond self-state
- Add handling for Supervisor-reported divergence cases:
  - node believes it is running but Supervisor state is `failed`
  - node heartbeat succeeds but `health=degraded`
  - multiple runtime records match this node identity
- Add tests for:
  - self-runtime present and healthy
  - self-runtime missing after registration attempt
  - duplicate runtime entries
  - mixed `systemd` and `docker` sibling runtimes
  - unknown runtime states and health values

Deliverables:

- `supervisor/` or equivalent client package
- typed Supervisor API models
- local-only transport configuration
- tests for Unix socket and loopback HTTP behavior

## 3. Change startup sequencing to detect and register with Supervisor first

Source:

- Design section 7 defines startup order:
  1. Node starts
  2. Node detects host supervisor
  3. Node registers with supervisor
  4. Node begins onboarding with Core
- Design section 8 requires checking for Supervisor during installation and startup readiness.

Tasks:

- Insert Supervisor detection ahead of Core bootstrap/onboarding.
- Make `GET /api/health` the initial Supervisor probe during startup.
- Fetch `GET /api/host/info` immediately after health succeeds so the node knows which host and supervision mode it is attaching to.
- Add a startup gate that blocks normal onboarding until Supervisor registration succeeds.
- Define the runtime registration payload the AI Node sends to Supervisor:
  - node identity
  - node type (`ai-node`)
  - software version
  - supported capabilities summary
  - local control endpoint metadata if needed
  - heartbeat cadence
- Persist minimal Supervisor registration metadata locally.
- Add retry logic for Supervisor detection and registration that is separate from Core onboarding retries.
- Distinguish hard failures from soft failures:
  - missing Supervisor
  - Supervisor reachable but `ready=false`
  - Supervisor reachable but `status=degraded`
  - Supervisor reachable but host metadata invalid or unsupported
  - unreachable Supervisor
  - rejected registration
  - stale or lost Supervisor session
- Ensure bootstrap/Core onboarding does not begin until Supervisor registration reaches a valid ready state.

Deliverables:

- new startup coordinator
- Supervisor-first registration flow
- local persisted Supervisor session/registration state

## 4. Redesign lifecycle states to include Supervisor mediation

Source:

- Design section 4 says Supervisor controls node lifecycle.
- Design section 7 says Supervisor is the local coordination point for startup.

Tasks:

- Replace the current lifecycle model with one that explicitly tracks Supervisor state.
- Add new lifecycle states or equivalent status flags for:
  - `supervisor_detecting`
  - `supervisor_unavailable`
  - `supervisor_registering`
  - `supervisor_registered`
  - `supervisor_heartbeat_degraded`
  - `core_onboarding_pending_after_supervisor`
- Update transition rules so direct `bootstrap -> core_discovered -> registration_pending` is no longer the default first path.
- Rework degraded-state handling to identify whether the fault domain is:
  - Supervisor connectivity
  - Core onboarding
  - capability declaration
  - governance sync
  - provider runtime
- Update status payloads returned by the local control API to expose Supervisor-aware lifecycle context.

Deliverables:

- updated lifecycle enum and transition table
- migration for node status API payloads
- tests for valid Supervisor-aware transitions

## 5. Refactor onboarding to become Supervisor-aware rather than Core-direct by default

Source:

- Design section 6 says nodes communicate with Core via Core API, MQTT, and Supervisor API.
- Design section 7 says the Supervisor is the local coordination point before Core onboarding begins.

Tasks:

- Decouple "Core discovered" from "ready to register with Core".
- Decide whether bootstrap discovery remains node-owned or becomes Supervisor-assisted on the host.
  - If bootstrap remains node-owned, make it explicitly post-Supervisor-registration.
  - If bootstrap becomes Supervisor-assisted, remove direct bootstrap assumptions from the node and consume Supervisor-provided Core connection details.
- Update the onboarding runtime so it can attach Supervisor registration/session context to local status and diagnostics.
- Ensure the node can recover correctly if the Supervisor session is lost during pending approval, trust activation, or operational runtime.
- Add clear behavior for "Supervisor available, Core unavailable" versus "Core available, Supervisor unavailable".
- Revisit whether the node should expose a local approval URL directly or whether Supervisor/local tooling should mediate user-visible onboarding guidance.

Deliverables:

- updated onboarding runtime contract
- explicit sequencing between Supervisor registration and Core onboarding
- failure-mode matrix for Supervisor/Core combinations

## 6. Add heartbeat and liveness reporting to Supervisor

Source:

- Design section 5 includes `/api/runtimes/heartbeat`.
- Design section 5 says local runtimes publish heartbeats and status to Supervisor.
- Design section 9 includes node health as part of host telemetry.

Tasks:

- Define a Supervisor heartbeat publisher in the node backend.
- Publish runtime liveness at a fixed interval with:
  - lifecycle state
  - process identity
  - version
  - trust state summary
  - capability declaration summary
  - provider runtime health summary
  - local control API health
- Include degraded and recovery transitions in heartbeat payloads.
- Add a lease/expiry model so the node knows when its Supervisor registration is stale and must be renewed.
- Ensure heartbeat failures degrade node state in a controlled way without corrupting trust state.
- Add metrics/logging for heartbeat latency, consecutive failures, and re-registration attempts.

Deliverables:

- Supervisor heartbeat publisher
- liveness payload schema
- tests for heartbeat retries and expiry handling

## 7. Accept Supervisor lifecycle control instead of assuming self-managed services

Source:

- Design section 4 assigns lifecycle control to Supervisor.
- Design section 5 includes runtime start, stop, and restart endpoints.

Tasks:

- Audit the current `service_manager` and local systemd integration to determine what remains node-owned versus Supervisor-owned.
- Remove assumptions that node restart policy is only handled through local systemd/user tooling.
- Decide how the local node control API should behave when lifecycle operations are now owned by Supervisor.
- Add safe handling for Supervisor-issued stop/restart expectations:
  - graceful shutdown hooks
  - persistence flush before exit
  - startup reason tracking after restart
- Prevent conflicting control planes where both the node API and Supervisor try to own restart semantics independently.
- Add compatibility behavior for development mode where a full Supervisor may not be present.

Deliverables:

- service-management responsibility matrix
- Supervisor-compatible shutdown/startup hooks
- updated local admin tooling expectations

## 8. Introduce host and runtime resource awareness

Source:

- Design section 4 assigns resource monitoring and local resource policy enforcement to Supervisor.
- Design section 5 includes `/api/host/info` and `/api/resources`.

Tasks:

- Add read paths from AI Node to consume host resource snapshots from Supervisor.
- Use `/api/host/info` and `/api/resources` as the canonical Supervisor reads for host identity and current resource state.
- Decide which node behaviors should react to host resource limits:
  - provider refresh jobs
  - expensive local model operations
  - concurrent execution limits
  - background telemetry or pricing refresh cadence
- Add a node-local policy adapter that can honor Supervisor-provided resource ceilings without inventing global governance policy.
- Expose resource-awareness diagnostics in the local node status API.
- Expose selected host metadata in diagnostics:
  - `host_id`
  - `hostname`
  - `supervision_mode`
  - current `pressure.state`
- Add support for "resource constrained" operational states distinct from generic degraded failures.

Deliverables:

- resource snapshot integration
- node-local resource policy adapter
- surfaced resource state in local diagnostics

## 9. Separate node telemetry from host telemetry

Source:

- Design section 4 says Supervisor provides host telemetry.
- Design section 9 says Supervisors emit CPU, memory, disk, network, and node health telemetry to Core.

Tasks:

- Stop treating the AI Node as the place that owns host-level telemetry.
- Keep node-owned telemetry limited to node runtime health, capability status, provider status, and node-local execution signals.
- Define which telemetry remains published directly to Core versus which should be routed or aggregated by Supervisor.
- Use `/api/runtimes` as the local source of truth for Supervisor-observed runtime inventory when comparing node self-view versus host view.
- If node health must be represented in Supervisor host telemetry, add a compact node-health summary payload suitable for Supervisor aggregation.
- Update MQTT/API telemetry docs so host metrics and node metrics are not mixed semantically.
- Review existing operational telemetry publishers for any host-level assumptions and remove them.

Deliverables:

- telemetry boundary definition
- node-health summary contract for Supervisor
- updated telemetry implementation notes and tests

## 10. Extend persisted state to include Supervisor relationship data

Source:

- Design section 7 requires Supervisor registration before Core onboarding.
- Design section 8 requires installation-time and runtime Supervisor dependency handling.

Tasks:

- Add a persistent state file or extend existing state to store:
  - detected Supervisor transport
  - Supervisor `host_id`
  - Supervisor `supervision_mode`
  - Supervisor instance identity if exposed
  - runtime registration ID
  - last successful registration timestamp
  - heartbeat lease metadata
  - last known host metadata snapshot if needed for diagnostics
  - last known resource pressure snapshot for diagnostics
- Keep trust state separate from Supervisor session state so losing local host registration does not silently corrupt Core trust.
- Define recovery behavior on startup when:
  - trust state exists but Supervisor session does not
  - Supervisor session exists but trust state does not
  - both exist but reference conflicting node identity
- Add migration logic for existing `.run/` state from the current Core-direct model.
- Decide whether cached host metadata snapshots are durable diagnostics only or should be invalidated when host fingerprint data changes.

Deliverables:

- Supervisor state store
- state migration tests
- startup reconciliation rules

## 11. Update installation and bootstrap UX to require Supervisor presence

Source:

- Design section 8 says the node must check for a local Supervisor during installation.
- Design section 8 says if Supervisor is missing, the installer should prompt, install, and start it.

Tasks:

- Update setup scripts and docs so Supervisor presence is a first-class prerequisite.
- Add an installation-time detection step for the Supervisor socket or loopback endpoint.
- Add a guided fallback flow when Supervisor is missing:
  - explain why it is required
  - identify the expected install package or install step
  - verify the Supervisor is running before continuing
- Rework `scripts/bootstrap.sh`, `scripts/run-from-env.sh`, and related startup helpers so they do not represent AI Node as independently deployable without Supervisor.
- Decide whether AI Node still owns two services directly (`backend` and `frontend`) or whether the Supervisor should manage only the backend runtime while the frontend remains separate.
- Ensure developer-mode shortcuts are clearly labeled as non-production compatibility paths.

Deliverables:

- updated installation scripts
- updated setup documentation
- explicit Supervisor prerequisite checks

## 12. Revisit the local node control API contract

Source:

- Design section 4 says Supervisor provides a host API and controls node lifecycle.
- Design section 5 defines a host-local control API owned by Supervisor.

Tasks:

- Audit the current local FastAPI control surface for overlap with future Supervisor authority.
- Split endpoints into:
  - node-private runtime/control endpoints that should remain local to the AI Node
  - information that should instead be exposed or proxied through Supervisor
- Add Supervisor status visibility to the node status API.
- Decide whether the existing node control API should bind only to loopback by default in all modes.
- Remove or de-emphasize any API operations that imply the node independently owns host/runtime supervision.
- Define a clear contract for how local operator tools should discover whether to talk to Supervisor or directly to the node.

Deliverables:

- revised node control API boundary
- updated API contract docs
- tests for exposure defaults and status payload changes

## 13. Add security constraints for Supervisor-local trust

Source:

- Design section 5 requires local-only Supervisor transports by default.
- Design section 4 makes Supervisor the local resource authority.

Tasks:

- Treat Supervisor connectivity as a privileged local trust boundary.
- Ensure the node only connects to:
  - the expected Unix socket path
  - or loopback HTTP fallback
- Reject non-local Supervisor endpoints unless explicitly enabled for development/testing.
- Review what node secrets may ever be sent to Supervisor and minimize that set.
- Ensure trust tokens and operational MQTT credentials are not exposed in heartbeats or runtime registration calls unless the final contract explicitly requires them.
- Add redaction for Supervisor diagnostics and logs.
- Add tests that confirm the node refuses external Supervisor addresses by default.

Deliverables:

- Supervisor transport security policy
- log redaction coverage
- security tests for endpoint restrictions

## 14. Keep capability declaration and provider runtime compatible with the new layering

Source:

- Design section 3 keeps Core responsible for governance, policy, and capability registry.
- Design section 6 says nodes provide capabilities and declare them to Core.

Tasks:

- Preserve the current provider-capability and capability-declaration flows as node-owned behavior where possible.
- Ensure Supervisor registration does not become a hidden second capability registry.
- Add minimal capability summary data to Supervisor registration only if needed for host-local management.
- Keep authoritative capability declaration targeted at Core.
- Verify that any future Supervisor-managed lifecycle actions cannot bypass Core trust or capability acceptance state.
- Document which runtime facts are:
  - node-local operational facts
  - Supervisor host-management facts
  - Core governance facts

Deliverables:

- capability-boundary note
- updated integration documentation
- regression tests confirming Core remains capability authority

## 15. Update repository documentation to remove drift

Source:

- Design sections 2 through 9 establish the new model.

Tasks:

- Update [docs/ai-node-architecture.md](./ai-node-architecture.md) to remove the statement that the AI Node is "not a Supervisor-managed local standalone addon".
- Update [docs/overview.md](./overview.md), [docs/runtime.md](./runtime.md), and [docs/integration.md](./integration.md) to describe Supervisor as a required local coordination layer.
- Add a dedicated node-to-supervisor integration document.
- Update setup and operations docs to explain:
  - Supervisor dependency
  - startup order
  - transport defaults
  - local troubleshooting flow
- Mark any still-unimplemented Supervisor behavior as not yet developed rather than documenting it as complete.

Deliverables:

- architecture doc rewrite
- updated runtime/setup/operations docs
- dedicated Supervisor integration doc

## 16. Build a comprehensive migration and test plan

Source:

- The design changes startup order, lifecycle ownership, installation flow, and telemetry boundaries.

Tasks:

- Add unit tests for:
  - Supervisor discovery
  - Unix socket transport
  - loopback HTTP fallback
  - runtime registration
  - heartbeat publishing
  - session expiry and re-registration
  - lifecycle transitions
  - state migration from current `.run/` files
- Add integration tests covering:
  - fresh install with Supervisor present
  - fresh install with Supervisor missing
  - trusted restart with lost Supervisor session
  - Supervisor restart while node is operational
  - Core available but Supervisor unavailable
  - Supervisor available but Core unavailable
- Add regression tests to ensure existing node-owned features still work after Supervisor mediation:
  - capability declaration
  - governance sync
  - provider refresh
  - operational MQTT readiness
  - local status API
- Define phased rollout checkpoints:
  - internal architecture refactor complete
  - Supervisor client complete
  - startup sequence complete
  - telemetry/resource integration complete
  - docs and scripts updated

Deliverables:

- test matrix
- migration checklist
- phased rollout plan

## Suggested Implementation Order

1. Architecture and lifecycle re-baselining
2. Supervisor client and transport support
3. Supervisor-first startup sequencing
4. Supervisor registration and heartbeat
5. Persisted state migration
6. Local API boundary cleanup
7. Installation/script changes
8. Telemetry/resource integration
9. Documentation updates
10. Full regression and migration testing

## Highest-Risk Areas

- Startup sequencing changes in [src/ai_node/main.py](../src/ai_node/main.py)
- Direct Core registration assumptions in [src/ai_node/runtime/onboarding_runtime.py](../src/ai_node/runtime/onboarding_runtime.py)
- Current lifecycle model in [src/ai_node/lifecycle/node_lifecycle.py](../src/ai_node/lifecycle/node_lifecycle.py)
- Service ownership overlap between node-local tooling and future Supervisor control
- State migration from the current Core-direct trust/onboarding model
