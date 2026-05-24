# Client AI V2 Schemas

Status: Partially implemented

This folder defines the V2+ client-facing AI contracts for benchmark-capable prompts and execution-only benchmark requests.

These schemas track the migration covered by Tasks 916-925. Schema discovery, V2 prompt metadata passthrough, and execution-only benchmark requests are implemented. Broader client migration and prompt-tuning consumers remain pending.

## Contract Direction

V2+ keeps the AI Node as an execution proxy:

- prompt-owning client nodes own labels, expected outputs, benchmark cases, scoring, and prompt tuning
- the AI Node executes prompt requests against requested provider/model targets
- the AI Node returns raw outputs, parsed outputs, usage, cost, latency, runtime metrics, and errors
- the AI Node does not judge benchmark correctness

## Schemas

- [prompt-register.v2.request.schema.json](./prompt-register.v2.request.schema.json): prompt registration with benchmark-capable V2 metadata
- [execution-request.v2.schema.json](./execution-request.v2.schema.json): normal task-family execution request
- [benchmark-execution-request.v2.schema.json](./benchmark-execution-request.v2.schema.json): multi-target execution-only benchmark request
- [benchmark-execution-response.v2.schema.json](./benchmark-execution-response.v2.schema.json): unified response containing target outputs and metadata
- [schema-catalog.v2.response.schema.json](./schema-catalog.v2.response.schema.json): proposed schema discovery response for client developers
- [communication.md](./communication.md): V2 client communication guide for developers

## Schema Discovery

Current implemented behavior:

- schemas are available from this repository under `docs/json-schemas/`
- `GET /api/schemas/client-ai/v2` returns the schema catalog
- `GET /api/schemas/client-ai/v2/{schema_name}` returns an individual schema document
- `GET /api/schemas/client-ai/v2/communication.md` returns the V2 communication guide as Markdown
