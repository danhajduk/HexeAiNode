# Client <-> AI Communication JSON Schemas

This folder contains JSON Schema files for the main client-facing payloads used by the Hexe AI Node control API.

Current coverage:

- prompt registration request: `POST /api/prompts/services`
- prompt update request: `PUT /api/prompts/services/{prompt_id}`
- prompt lifecycle request: `POST /api/prompts/services/{prompt_id}/lifecycle`
- prompt probation request: `POST /api/prompts/services/{prompt_id}/probation`
- prompt lookup response: `GET /api/prompts/services/{prompt_id}`
- prompt state response: `GET /api/prompts/services`
- execution authorization request: `POST /api/execution/authorize`
- execution authorization response: `POST /api/execution/authorize`
- direct AI execution request: `POST /api/execution/direct`
- direct AI execution response: `POST /api/execution/direct`

Notes:

- The task-family field is left as a validated string instead of a hardcoded enum in these docs because the canonical family list is normalized in code and may expand over time.
- Timestamps use ISO-8601 `date-time`.
- These schemas describe the payload contract shape for integration work. Server-side semantic validation still happens in the Python models and gateway logic.
