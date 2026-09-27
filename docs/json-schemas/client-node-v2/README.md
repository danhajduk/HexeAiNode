# Client Node V2 Schemas

Status: Implemented

This folder defines the V2+ external-client contracts for AI Node discovery, prompts, image templates, execution, models, runtimes, queues, services, and errors.

The primary external-client discovery endpoint is `GET /api/schemas/client-node/v2`. It returns links to the full OpenAPI document, client-facing execution APIs, live prompt/template/service catalogs, every published JSON schema, and the Markdown guides below. Resolve every relative `api_path` against the `provider_api_base_url` published by Core.

Every operation advertised by the discovery catalog publishes a response schema. Every advertised mutation also publishes a request schema. `/openapi.json` remains the complete generated API reference.

Cross-node execution semantics, compatibility rules, authentication requirements, and known idempotency gaps are defined in
[the AI Node execution client contract](../../ai-node/execution-client-contract.md).

## Contract Direction

V2+ keeps the AI Node as an execution proxy:

- prompt-owning client nodes own labels, expected outputs, benchmark cases, scoring, and prompt tuning
- the AI Node executes prompt requests against requested provider/model targets
- the AI Node returns raw outputs, parsed outputs, usage, cost, latency, runtime metrics, and errors
- the AI Node does not judge benchmark correctness

## Schemas

- [prompt-register.v2.request.schema.json](./prompt-register.v2.request.schema.json): prompt registration with canonical prompt-version normalization and benchmark metadata
- [execution-request.v2.schema.json](./execution-request.v2.schema.json): normal task-family execution request
- [execution-response.v2.schema.json](./execution-response.v2.schema.json): canonical terminal execution result
- [execution-job.v2.schema.json](./execution-job.v2.schema.json): queued acknowledgement and job status
- [execution-artifact-ack.v1.request.schema.json](./execution-artifact-ack.v1.request.schema.json): completed-job artifact acknowledgement
- [execution-artifact-ack.v1.response.schema.json](./execution-artifact-ack.v1.response.schema.json): persisted acknowledgement and cleanup result
- [execution-job-cancel.v2.request.schema.json](./execution-job-cancel.v2.request.schema.json): optional queued-job cancellation body
- [execution-job-cancel.v2.response.schema.json](./execution-job-cancel.v2.response.schema.json): successful and race-rejected cancellation results
- [image-generation-inputs.v1.schema.json](./image-generation-inputs.v1.schema.json): shared image-generation input controls
- [weather-scenery-inputs.v1.schema.json](./weather-scenery-inputs.v1.schema.json): strict Interaction weather-scenery prompt inputs
- [benchmark-execution-request.v2.schema.json](./benchmark-execution-request.v2.schema.json): multi-target execution-only benchmark request
- [benchmark-execution-response.v2.schema.json](./benchmark-execution-response.v2.schema.json): unified response containing target outputs and metadata
- [schema-catalog.v2.response.schema.json](./schema-catalog.v2.response.schema.json): implemented schema discovery response for client developers
- `execution-authorize`, `execution-compare`, `route-preview`, and `execution-queues`: dedicated execution API contracts
- `prompt-*`: prompt catalog, detail, mutation, update, lifecycle, probation, and review contracts
- `image-template-*`: image-template catalog, detail, mutation, registration, update, lifecycle, and review contracts
- `models-by-task`, `runtime-assignments`, and `service-status`: read-only discovery contracts
- [error-response.v2.schema.json](./error-response.v2.schema.json): shared FastAPI error envelope
- [communication.md](./communication.md): V2 client communication guide for developers

## Schema Discovery

Current implemented behavior:

- schemas are available from this repository under `docs/json-schemas/`
- `GET /api/schemas/client-node/v2` returns the schema catalog
- `GET /api/schemas/client-node/v2/{schema_name}` returns an individual schema document
- `GET /api/schemas/client-node/v2/communication.md` returns the V2 communication guide as Markdown
- `GET /api/schemas/client-node/v2/execution-client-contract.md` returns the canonical cross-node execution contract
- `GET /api/schemas/client-node/v2/README.md` returns this remotely discoverable schema index
