# Client AI V2 Schemas

Status: Implemented

This folder defines the V2+ client-facing AI contracts for benchmark-capable prompts and execution-only benchmark requests.

These schemas track the migration covered by Tasks 916-925. Schema discovery, V2 prompt metadata passthrough, and execution-only benchmark requests are implemented. Broader client migration and prompt-tuning consumers remain pending.

Cross-node execution semantics, compatibility rules, and known authentication and idempotency gaps are defined in
[the AI Node execution client contract](../../ai-node/execution-client-contract.md).

## Contract Direction

V2+ keeps the AI Node as an execution proxy:

- prompt-owning client nodes own labels, expected outputs, benchmark cases, scoring, and prompt tuning
- the AI Node executes prompt requests against requested provider/model targets
- the AI Node returns raw outputs, parsed outputs, usage, cost, latency, runtime metrics, and errors
- the AI Node does not judge benchmark correctness

## Schemas

- [prompt-register.v2.request.schema.json](./prompt-register.v2.request.schema.json): prompt registration with benchmark-capable V2 metadata
- [execution-request.v2.schema.json](./execution-request.v2.schema.json): normal task-family execution request
- [execution-response.v2.schema.json](./execution-response.v2.schema.json): canonical terminal execution result
- [execution-job.v2.schema.json](./execution-job.v2.schema.json): queued acknowledgement and job status
- [execution-job-cancel.v2.request.schema.json](./execution-job-cancel.v2.request.schema.json): optional queued-job cancellation body
- [execution-job-cancel.v2.response.schema.json](./execution-job-cancel.v2.response.schema.json): successful and race-rejected cancellation results
- [image-generation-inputs.v1.schema.json](./image-generation-inputs.v1.schema.json): shared image-generation input controls
- [weather-scenery-inputs.v1.schema.json](./weather-scenery-inputs.v1.schema.json): strict Interaction weather-scenery prompt inputs
- [benchmark-execution-request.v2.schema.json](./benchmark-execution-request.v2.schema.json): multi-target execution-only benchmark request
- [benchmark-execution-response.v2.schema.json](./benchmark-execution-response.v2.schema.json): unified response containing target outputs and metadata
- [schema-catalog.v2.response.schema.json](./schema-catalog.v2.response.schema.json): implemented schema discovery response for client developers
- [communication.md](./communication.md): V2 client communication guide for developers

## Schema Discovery

Current implemented behavior:

- schemas are available from this repository under `docs/json-schemas/`
- `GET /api/schemas/client-ai/v2` returns the schema catalog
- `GET /api/schemas/client-ai/v2/{schema_name}` returns an individual schema document
- `GET /api/schemas/client-ai/v2/communication.md` returns the V2 communication guide as Markdown
- `GET /api/schemas/client-ai/v2/execution-client-contract.md` returns the canonical cross-node execution contract
- `GET /api/schemas/client-ai/v2/README.md` returns this remotely discoverable schema index
