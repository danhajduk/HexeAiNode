# Node Standard Creation Tasks

Last Updated: 2026-04-04 US/Pacific

## Goal

Create a canonical Hexe node standard that fits both:

- `HexeAiNode` at `/home/dan/Projects/HexeAiNode`
- `HexeEmail` at `/home/dan/Projects/HexeEmail`

The standard must minimize adaptation work. It should standardize node boundaries, contracts, and operator-facing behavior first, while allowing more than one acceptable internal implementation shape.

This file is the work plan for creating that standard. It is not the standard itself.

## Verified Baseline From The Sweep

### What both repos already share

- FastAPI backend entrypoints exist in both repos:
  - `HexeAiNode`: `src/ai_node/main.py`
  - `HexeEmail`: `src/main.py`
- React + Vite frontends exist in both repos.
- Both repos include `scripts/` with bootstrap and systemd templates.
- Both repos implement onboarding, trust persistence, capability/governance behavior, and node-local runtime state.
- Both repos have meaningful automated tests around onboarding, API behavior, provider/runtime logic, and persistence.

### What differs and must be handled carefully

- `HexeAiNode` is subsystem-oriented and package-deep under `src/ai_node/`.
- `HexeEmail` is flatter and more orchestration-centric, with substantial behavior in `src/service.py`.
- `HexeAiNode` frontend is increasingly feature-split and uses a shared API wrapper in `frontend/src/api.js`.
- `HexeEmail` frontend is more monolithic in `frontend/src/App.jsx`, but backend contracts and state models are already typed and structured in `src/models.py` and `src/config.py`.
- `HexeEmail` has explicit node-local scheduled/background Gmail work.
- `HexeAiNode` has scheduler lease integration, runtime execution services, and a more explicit control/runtime separation.

### Design consequence

The standard should define:

- mandatory capability areas
- mandatory operator-visible contracts
- mandatory top-level repository concerns
- recommended internal decomposition patterns
- allowed implementation variants

The standard should not require:

- identical package depth
- identical file names beyond a small core set
- identical frontend decomposition depth
- identical provider architecture details

## Standard Strategy

Use a layered standard:

1. Mandatory
   Node lifecycle, required backend domains, required API groups, required onboarding behavior, required operator UX outcomes, required operational scripts, required observability, required tests, required docs.
2. Recommended
   Feature-split frontend structure, centralized API client layer, split runtime/service modules, scheduler module isolation, stronger contract docs and JSON schemas.
3. Allowed Variants
   Deep package layout like `HexeAiNode`, compact orchestration layout like `HexeEmail`, as long as the same responsibilities are clearly implemented and documented.

## Primary Deliverables

1. A cross-repo comparison matrix.
2. A canonical node standard document.
3. A compliance/gap appendix for `HexeAiNode`.
4. A compliance/gap appendix for `HexeEmail`.

## Work Plan

## 1. Lock Scope And Decision Rules

### Objective

Define exactly what the node standard is allowed to standardize.

### Tasks

- Define the standard boundary:
  - repository structure
  - runtime boundaries
  - API structure
  - frontend structure expectations
  - scripts and operations
  - onboarding and readiness behavior
  - persistence categories
  - testing and documentation expectations
- Define non-goals:
  - provider-specific business rules
  - provider-specific pipelines
  - model-selection logic
  - domain logic specific to AI or email
  - exact internal file granularity
- Define rule labels to use in the final standard:
  - Mandatory
  - Recommended
  - Optional
  - Node-specific

### Output

- A short scope section at the top of the future standard.

## 2. Build The Cross-Repo Comparison Matrix

### Objective

Turn the repo sweep into a precise decision tool.

### Tasks

- Build a side-by-side matrix for:
  - backend structure
  - frontend structure
  - API groups
  - onboarding lifecycle
  - trust state persistence
  - capability declaration
  - governance sync and readiness
  - service controls
  - background tasks and scheduling
  - scripts and systemd
  - configuration loading
  - test coverage shape
  - documentation shape
- Mark each area as:
  - shared now
  - compatible with light normalization
  - divergent but standardizable
  - intentionally node-specific
- Use the matrix to decide what must be standardized versus merely documented.

### Output

- A comparison table that directly feeds the standard.

## 3. Define The Canonical Backend Standard

### Objective

Standardize backend responsibilities without forcing one repo’s file layout onto the other.

### Tasks

- Define the required backend domains every node must have:
  - entrypoint
  - lifecycle state handling
  - onboarding and registration
  - trust and identity
  - Core communication clients
  - capability configuration and declaration
  - governance and readiness
  - runtime orchestration
  - provider integration boundary
  - persistence and state storage
  - diagnostics and logging
  - security and redaction
- Define the minimum acceptable structural rule:
  - the domains must exist
  - the ownership boundary for each domain must be clear
  - they do not need identical folder names in every repo
- Decide whether the standard requires a single orchestrator service.
  Current likely answer:
  - allow one main service or multiple subsystem services
  - require documented orchestration ownership
- Define a small canonical naming baseline where helpful:
  - `main` for backend entrypoint
  - `providers` for provider-specific code
  - `config` for config loading
  - `models` or typed request/response modules for API contracts
  - `persistence` or store modules for local state
- Define when a compact node must split a large orchestration file:
  - not by line count alone
  - by mixed responsibility boundaries
  - by testability or contract clarity issues
- Define standard rules for:
  - config validation
  - runtime state validation
  - safe logging and secret masking
  - startup/shutdown ownership
  - background task ownership

### Output

- A backend section in the standard with required domains and allowed layout variants.

## 4. Define The Canonical API Standard

### Objective

Standardize API categories and naming so node UIs and Core expectations converge.

### Tasks

- Inventory the shared API groups now visible in both repos:
  - health
  - node status
  - bootstrap/config
  - onboarding actions
  - capability config and declaration
  - governance/readiness
  - service status and restart
  - provider-specific routes
  - runtime execution or preview routes
- Decide the canonical namespace baseline:
  - whether `/api/node/*` is the preferred generic node namespace
  - whether route aliases may remain for compatibility
  - whether `/ui/*` routes remain transitional or acceptable
- Define mandatory contract groups for all nodes:
  - liveness/readiness
  - node status/bootstrap/config
  - onboarding control
  - capability config/declaration
  - governance/readiness
  - provider setup/status where applicable
  - service control where restart control is exposed
- Define provider route rules:
  - provider-specific functionality must stay under a clear provider namespace
  - provider routes must not redefine generic node lifecycle contracts
- Define response and error rules:
  - JSON-only responses
  - typed request/response models
  - normalized error payloads
  - backward-compatible route transitions where needed
- Decide whether the standard requires:
  - OpenAPI discipline only
  - or explicit contract docs / JSON schemas for key node APIs

### Output

- A canonical API structure section plus a compatibility policy.

## 5. Define The Canonical Frontend Standard

### Objective

Standardize operator experience and frontend layering without over-prescribing component structure.

### Tasks

- Define the minimum frontend capabilities every node UI must provide:
  - setup or onboarding flow
  - current node status
  - operational dashboard
  - capability or provider setup visibility
  - degraded/error visibility
  - operator actions for the node’s supported lifecycle
- Define required UX outcomes:
  - the operator can see lifecycle state
  - the operator can see trust/onboarding state
  - the operator can see blockers for readiness
  - the operator can see background-task health where applicable
  - the operator can recover from common non-terminal states
- Define recommended frontend structure:
  - feature/domain grouping
  - shared design tokens
  - reusable status primitives
  - centralized API client or fetch wrapper
  - explicit routes or UI mode boundaries
- Define what should remain flexible:
  - number of components
  - route implementation style
  - whether the app starts from a large `App.jsx` or a routed shell
- Define specific consistency rules for:
  - status badges
  - stage cards
  - backend unavailable states
  - polling/refresh feedback
  - mobile responsiveness

### Output

- A frontend section centered on operator-visible requirements and recommended structure.

## 6. Define The Scripts And Operations Standard

### Objective

Make node repos operationally predictable.

### Tasks

- Compare existing script sets in both repos and identify the common baseline.
- Define the minimum required script set:
  - `bootstrap.sh`
  - `run-from-env.sh`
  - `stack-control.sh`
  - `restart-stack.sh`
  - `stack.env.example`
  - backend systemd template
  - frontend systemd template
- Define recommended but optional scripts:
  - `dev.sh`
  - `start.sh`
  - `status.sh`
  - runtime reset helpers
  - acceptance helpers
- Define standard expectations for:
  - environment-driven frontend/backend commands
  - user-level systemd rendering
  - service naming conventions
  - script logging and failure behavior
  - repo-local operational runbook references

### Output

- A required operations/scripts checklist.

## 7. Define The Background Tasks And Internal Scheduler Standard

### Objective

Create a shared rule set for node-local recurring work that supports both current repos.

### Tasks

- Define the node-local scheduler/background-work boundary:
  - recurring internal work owned by the node
  - distinct from Core admission authority
  - distinct from provider-specific implementation details
- Define when a node is considered to have scheduler behavior:
  - polling loops
  - recurring refresh jobs
  - recurring provider sync
  - lease-driven recurring execution
- Define required behavior for nodes with background work:
  - explicit ownership in code
  - persisted task/scheduler state
  - last success timestamp
  - last failure timestamp
  - current status
  - schedule description visible to operators
  - safe startup and restart behavior
- Define whether a dedicated scheduler module is mandatory.
  Current likely answer:
  - no
  - but the scheduler responsibility must be explicit and isolated enough to document and test
- Define failure rules:
  - background task failure must not silently disappear
  - degraded behavior must be visible when materially relevant
  - repeated failures need surfaced operator state

### Output

- A scheduler/background-tasks section usable by both AI and email nodes.

## 8. Define The Onboarding, Trust, And Readiness Standard

### Objective

Align node lifecycle behavior with the existing Core node docs and current repo reality.

### Tasks

- Extract common onboarding invariants from both repos:
  - operator-configured Core target
  - onboarding session creation
  - approval URL visibility
  - finalize polling or equivalent approval completion
  - trust persistence
  - restart-safe resume
  - trusted runtime transition
- Map current repo behavior to canonical lifecycle stages already documented under Core node docs.
- Define required operator-visible onboarding data:
  - current onboarding state
  - session ID
  - approval URL
  - node ID after trust
  - last relevant error
- Define required recovery actions:
  - restart onboarding/setup
  - continue waiting/polling
  - trusted resume after restart
- Define readiness rules:
  - capability state
  - governance state
  - provider readiness where applicable
  - background task readiness where applicable
  - degraded-state visibility

### Output

- A node lifecycle/onboarding/readiness section aligned with Core docs and current repo behavior.

## 9. Define Persistence, Configuration, And Security Rules

### Objective

Standardize categories of local state without forcing identical storage implementations.

### Tasks

- Define required persistence categories:
  - operator config
  - trust material
  - node identity
  - capability state
  - governance state
  - provider state
  - background-task or scheduler state when applicable
  - diagnostics artifacts where applicable
- Define what may vary:
  - JSON files
  - SQLite
  - provider-specific stores
  - exact path layout
- Define required configuration behavior:
  - validated config loading
  - non-empty required values
  - normalized optional values
  - explicit runtime directories
- Define security expectations:
  - secret masking
  - no unsafe raw secret logging
  - safe error payloads
  - documented credential storage boundaries

### Output

- A persistence/config/security section with mandatory categories and allowed storage variants.

## 10. Define Provider Boundary Rules

### Objective

Keep node-generic and provider-specific code cleanly separated in the standard.

### Tasks

- Define the minimum provider boundary:
  - provider adapters or equivalent
  - provider-specific APIs
  - provider-specific stores
  - provider-specific health/status logic
- Define what must stay node-generic:
  - onboarding
  - trust
  - generic node status
  - generic capability declaration lifecycle
  - service controls
- Define how provider-specific setup can appear in the UI without replacing generic node setup stages.
- Ensure the standard works for:
  - AI-provider nodes
  - email-provider nodes
  - future provider families

### Output

- A provider boundary section preventing future architectural drift.

## 11. Define Testing And Documentation Compliance Requirements

### Objective

Make the standard verifiable and maintainable.

### Tasks

- Define required test categories:
  - onboarding and trust flow
  - backend API contracts
  - capability/governance/readiness behavior
  - provider boundary behavior where applicable
  - background-task behavior where applicable
  - frontend smoke/rendering coverage where UI complexity justifies it
- Define documentation minimums for each node repo:
  - README
  - architecture doc
  - setup/run instructions
  - operations/runbook
  - API or contract reference
  - provider setup docs where applicable
- Define which material belongs in repo docs versus Core docs.
- Define how the standard should cross-reference existing Core node contracts instead of duplicating them.

### Output

- A compliance section for tests and documentation.

## 12. Write The Final Standard And Gap Appendix

### Objective

Produce the actual standard and show that it is practical for both repos.

### Tasks

- Draft the canonical node standard with sections ordered by:
  - scope
  - lifecycle and operator model
  - backend structure
  - API structure
  - frontend structure
  - scripts/operations
  - scheduler/background work
  - persistence/config/security
  - provider boundaries
  - testing/docs
- Mark each rule as:
  - Mandatory
  - Recommended
  - Optional
- Add implementation-shape examples from:
  - `HexeAiNode`
  - `HexeEmail`
- Produce a short adaptation appendix for each repo:
  - already aligned
  - light changes recommended
  - larger changes optional
- Confirm the final standard does not force either repo into a large rewrite.

### Output

- The final node standard.
- The repo adaptation appendix.

## Tightening Checks Before Finalizing The Standard

- Do not define rules that require both repos to match folder depth.
- Do not define rules that require frontend fragmentation for its own sake.
- Do not define provider rules that make Gmail-specific or OpenAI-specific assumptions mandatory for all nodes.
- Do not redefine lifecycle states that already exist in Core node docs without explicit reason.
- Prefer standardizing:
  - responsibilities
  - contracts
  - operator visibility
  - operational predictability
  over standardizing:
  - exact filenames
  - exact number of layers
  - exact UI composition patterns

## Acceptance Criteria For This Task-List Phase

- A repo-local task file exists in `HexeAiNode/docs/`.
- The plan is based on verified code structure from both repositories.
- The plan is explicitly tighter than a general brainstorm and is organized by decision area, objective, tasks, and output.
- The plan covers:
  - backend structure
  - frontend structure and design
  - API structure
  - scripts and operations
  - background tasks and internal scheduler
  - onboarding, trust, and readiness
  - persistence, config, and security
  - provider boundaries
  - testing and documentation
- The plan remains biased toward minimum adaptation across both repositories.
