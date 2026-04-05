# JSON Schemas

This folder contains repo-local JSON schemas owned by the Hexe AI Node repository.

These schemas document contracts implemented and enforced in this repo. They do not replace Core-owned shared platform schemas.

## Coverage

This folder now covers:

- existing client-facing AI request and prompt schemas in `docs/json-schemas/client-ai/`
- node-control API request models defined in `src/ai_node/runtime/node_control_api.py`
- task execution request/result models defined in `src/ai_node/execution/task_models.py`
- provider-enabled-model snapshot models defined in `src/ai_node/config/provider_enabled_models_config.py`
- local config and persisted-state JSON contracts validated by repo code

## Repo-Owned Schemas

- [node-control-api.request-models.schema.json](/home/dan/Projects/HexeAiNode/docs/json-schemas/node-control-api.request-models.schema.json)
- [task-execution.models.schema.json](/home/dan/Projects/HexeAiNode/docs/json-schemas/task-execution.models.schema.json)
- [provider-enabled-models.schema.json](/home/dan/Projects/HexeAiNode/docs/json-schemas/provider-enabled-models.schema.json)
- [provider-selection-config.schema.json](/home/dan/Projects/HexeAiNode/docs/json-schemas/provider-selection-config.schema.json)
- [provider-credentials.schema.json](/home/dan/Projects/HexeAiNode/docs/json-schemas/provider-credentials.schema.json)
- [task-capability-selection-config.schema.json](/home/dan/Projects/HexeAiNode/docs/json-schemas/task-capability-selection-config.schema.json)
- [capability-state.schema.json](/home/dan/Projects/HexeAiNode/docs/json-schemas/capability-state.schema.json)
- [governance-state.schema.json](/home/dan/Projects/HexeAiNode/docs/json-schemas/governance-state.schema.json)
- [phase2-state.schema.json](/home/dan/Projects/HexeAiNode/docs/json-schemas/phase2-state.schema.json)
- [budget-state.schema.json](/home/dan/Projects/HexeAiNode/docs/json-schemas/budget-state.schema.json)
- [provider-capability-report.schema.json](/home/dan/Projects/HexeAiNode/docs/json-schemas/provider-capability-report.schema.json)
- [prompt-service-state.schema.json](/home/dan/Projects/HexeAiNode/docs/json-schemas/prompt-service-state.schema.json)

## Existing Client AI Schemas

- [client-ai/README.md](/home/dan/Projects/HexeAiNode/docs/json-schemas/client-ai/README.md)

## Notes

- The catalog schemas use `$defs` for the individual model definitions.
- These files are derived from the implemented repo contracts as they exist now.
- Core-owned shared schemas remain documented through [core-references.md](/home/dan/Projects/HexeAiNode/docs/core-references.md) and should not be duplicated here unless this repo owns the exact local contract.
