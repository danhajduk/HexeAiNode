# AI Node Prompt Management Contract

Status: Implemented baseline
Last updated: 2026-03-20

## Scope Boundary

This document defines the node-local prompt-management surface now implemented by the AI Node.

Node-owned responsibilities:

- persist local prompt definitions and version history
- enforce prompt lifecycle state before execution
- enforce prompt task-family compatibility
- enforce prompt version validity
- apply prompt-local provider/model preferences and execution constraints
- track local prompt usage, failures, and denials
- expose local CRUD, lifecycle, and debug APIs

Core responsibilities that remain adjacent but separate:

- declare spend authority for node services/providers/models through budget policy and grants
- stay out of node-local prompt ownership, versioning, lifecycle, and enforcement

## Persisted Prompt Model

Each prompt definition stores:

- `prompt_id`
- `prompt_name`
- `service_id`
- `owner_service`
- `task_family`
- `status`
  Current lifecycle state: `probation | active | restricted | suspended | retired | expired`
- `privacy_class`
  `public | internal | restricted | sensitive`
- `execution_policy`
  - `allow_direct_execution`
  - `allow_version_pinning`
- `provider_preferences`
  - `preferred_providers[]`
  - `preferred_models[]`
  - `default_provider`
  - `default_model`
- `constraints`
  - `max_timeout_s`
  - `structured_output_required`
  - `allowed_model_overrides[]`
- `metadata`
- `current_version`
- `versions[]`
  - `version`
  - `definition.system_prompt`
  - `definition.prompt_template`
  - `definition.template_variables[]`
  - `definition.default_inputs`
- `lifecycle_history[]`
- `usage`
  - `execution_count`
  - `success_count`
  - `failure_count`
  - `denial_count`
  - `last_used_at`
  - `last_denial_reason`
  - `last_failure_reason`
  - `last_execution_status`

## Versioning Rules

- prompt creation starts at `v1` unless an explicit version is supplied
- prompt updates that include a new definition create a new immutable version
- the newest saved version becomes `current_version`
- execution may pin a specific `prompt_version`
- execution is denied with `invalid_prompt_version` when the requested version does not exist

## Authorization Rules

Before execution begins, the node denies when:

- `prompt_id` is not registered
- `task_family` does not match the prompt contract
- prompt lifecycle state is not executable
- requested prompt version is missing
- requested provider is outside prompt-local provider preferences
- requested model override is not allowed
- structured output is required but no schema is supplied

Current denial reasons include:

- `prompt_not_registered`
- `prompt_in_probation`
- `prompt_state_invalid`
- `prompt_task_family_mismatch`
- `invalid_prompt_version`
- `prompt_provider_not_allowed`
- `prompt_model_override_not_allowed`
- `prompt_structured_output_required`

## Execution Merging

When prompt authorization succeeds, the execution service:

- applies prompt `default_provider` / `default_model` when the request does not specify them
- caps request timeout using prompt `max_timeout_s`
- injects the prompt version `system_prompt` when the request does not provide one
- records prompt denials and execution outcomes into local usage state

## Local API Surface

- `GET /api/prompts/services`
- `POST /api/prompts/services`
- `GET /api/prompts/services/{prompt_id}`
- `PUT /api/prompts/services/{prompt_id}`
- `POST /api/prompts/services/{prompt_id}/lifecycle`
- `POST /api/prompts/services/{prompt_id}/probation`
- `POST /api/execution/authorize`
- `GET /debug/prompts`
