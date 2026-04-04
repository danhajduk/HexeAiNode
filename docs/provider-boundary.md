# Provider Boundary

## Purpose

This document explains the provider boundary in `HexeAiNode`.

It shows what stays node-generic, what is provider-specific, and how provider setup and provider intelligence fit into the node lifecycle without replacing onboarding, trust, readiness, or governance.

## Node-Generic Versus Provider-Specific

## Node-generic responsibilities

These remain owned by the node regardless of provider:

- onboarding and trust activation
- trusted identity persistence
- lifecycle state transitions
- capability setup gating
- capability declaration submission
- governance refresh and readiness logic
- service control
- generic node status and operator visibility

Primary code areas:

- `src/ai_node/runtime/`
- `src/ai_node/lifecycle/`
- `src/ai_node/registration/`
- `src/ai_node/trust/`
- `src/ai_node/identity/`
- `src/ai_node/governance/`
- `src/ai_node/core_api/`

## Provider-specific responsibilities

These belong to the provider boundary:

- provider adapters
- provider model discovery and catalog normalization
- provider capability resolution support
- provider metrics and registry snapshots
- provider-specific execution routing
- provider-specific configuration and credential storage
- provider-specific UI setup and diagnostics surfaces

Primary code areas:

- `src/ai_node/providers/`
- `src/ai_node/providers/adapters/`
- `src/ai_node/runtime/provider_resolver.py`
- `src/ai_node/config/provider_credentials_config.py`
- `src/ai_node/config/provider_selection_config.py`
- `src/ai_node/config/provider_enabled_models_config.py`

## Current Provider Model

The current implementation is provider-aware but node-first.

The node is not defined as an OpenAI node. Instead:

- the node remains a generic Hexe AI node
- OpenAI is the current implemented provider family
- provider enablement, credentials, model selection, and pricing feed capability declaration readiness
- provider behavior is layered under node-generic trust, readiness, and governance rules

## Provider Modules

## Provider package

Provider-facing backend modules currently include:

- `src/ai_node/providers/base.py`
- `src/ai_node/providers/models.py`
- `src/ai_node/providers/provider_registry.py`
- `src/ai_node/providers/runtime_manager.py`
- `src/ai_node/providers/execution_router.py`
- `src/ai_node/providers/task_execution.py`
- `src/ai_node/providers/capability_resolution.py`
- `src/ai_node/providers/config_loader.py`
- `src/ai_node/providers/metrics.py`

## OpenAI-specific and catalog modules

Current OpenAI-specific provider modules include:

- `src/ai_node/providers/openai_catalog.py`
- `src/ai_node/providers/openai_model_catalog.py`
- `src/ai_node/providers/model_capability_catalog.py`
- `src/ai_node/providers/model_feature_catalog.py`
- `src/ai_node/providers/model_feature_schema.py`
- `src/ai_node/providers/adapters/openai_adapter.py`

## Non-production or local adapter scaffolds

- `src/ai_node/providers/adapters/local_adapter.py`
- `src/ai_node/providers/adapters/mock_adapter.py`

## Runtime And Config Boundary Around Providers

Provider-specific runtime support is not isolated only under `providers/`. It also includes node-level orchestration and readiness helpers around provider state:

- `src/ai_node/runtime/provider_resolver.py`
- `src/ai_node/runtime/capability_resolver.py`
- `src/ai_node/runtime/capability_declaration_runner.py`
- `src/ai_node/runtime/task_execution_service.py`
- `src/ai_node/runtime/node_control_api.py`

Provider-facing config and persisted state boundaries include:

- `src/ai_node/config/provider_credentials_config.py`
- `src/ai_node/config/provider_selection_config.py`
- `src/ai_node/config/provider_enabled_models_config.py`
- `src/ai_node/persistence/provider_capability_report_store.py`
- `src/ai_node/persistence/client_usage_store.py`

## Provider Setup In The Node Lifecycle

Provider setup happens after trust activation.

It does not replace:

- onboarding
- trust
- trusted identity
- node lifecycle

In the current runtime model:

- onboarding and trust establish a trusted node
- trusted startup resumes through `trusted -> capability_setup_pending`
- provider readiness is one of the inputs that determines whether capability declaration is allowed
- governance and operational readiness remain node-level outcomes, not provider-local outcomes

## Provider Readiness And Capability Declaration

Provider state affects declaration readiness through node-level gating.

Current provider-related gating concepts include:

- provider selection validity
- enabled provider state
- enabled model state
- model classification availability
- pricing availability

These are consumed by node-level setup and declaration logic rather than treated as a separate provider-owned lifecycle.

## Provider-Specific APIs

Current provider-specific route families are exposed through the node control API and include OpenAI-oriented routes such as:

- provider configuration
- provider credential save and read
- provider model catalog inspection
- enabled model selection
- provider pricing diagnostics and refresh
- provider capability refresh

Representative provider-specific route groups include:

- `/api/providers/config`
- `/api/providers/openai/credentials`
- `/api/providers/openai/models/catalog`
- `/api/providers/openai/models/capabilities`
- `/api/providers/openai/models/features`
- `/api/providers/openai/models/enabled`
- `/api/providers/openai/models/latest`
- `/api/providers/openai/capability-resolution`
- `/api/providers/openai/pricing/diagnostics`
- `/api/providers/openai/pricing/refresh`
- `/api/capabilities/providers/refresh`

These routes are provider-specific or provider-adjacent.

They do not replace the generic node route families for:

- node status
- onboarding
- governance status
- service control
- capability declaration

## Frontend Provider Boundary

Provider behavior in the frontend is currently mixed into the main node app shell, but still conceptually sits under the provider setup area rather than replacing the full node setup experience.

Current relevant UI areas include:

- `frontend/src/features/setup/`
- `frontend/src/features/operational/`
- `frontend/src/features/diagnostics/`
- `frontend/src/App.jsx`

The standard-alignment target is to keep provider setup as one feature area inside the node UI, not as the definition of the whole UI.

## Alignment Notes

Aligned already:

- provider-specific backend modules exist
- provider config has dedicated modules
- provider state is distinct from trust state
- provider readiness feeds node-level gating rather than replacing node lifecycle

Needs follow-up:

- cleaner repo-local provider-boundary documentation for operators and reviewers
- clearer API map separating generic node routes from provider-specific routes
- further frontend modularity so provider UI logic moves farther out of `App.jsx`
