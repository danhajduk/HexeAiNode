# Client AI V2 Communication Guide

Status: Partially implemented.

This guide explains how a client node should communicate with the AI Node using the V2 client AI contract.

Important implementation note: the schema catalog includes proposed V2+ schemas as well as implemented contracts.
`execution-request.v2.schema.json` tracks the implemented direct execution request model for fields used by
`POST /api/execution/direct`.

## Implemented Route Summary

Implemented client-facing routes in this repository:

| Route | Status | Purpose |
| --- | --- | --- |
| `POST /api/execution/authorize` | Implemented | Lightweight prompt authorization and access check. |
| `GET /api/execution/admission` | Implemented | Read the AI Node's direct execution admission state and `max_in_flight` limit. |
| `POST /api/execution/route-preview` | Implemented | Dry-run provider/model and queue routing for a direct execution request. |
| `POST /api/execution/direct` | Implemented | Production task execution through provider/model routing. |
| `GET /api/execution/jobs/{job_id}` | Implemented | Poll an async queued execution job. |
| `DELETE /api/execution/jobs/{job_id}` | Implemented | Cancel a queued execution job before it starts running. |
| `GET /api/execution/queues` | Implemented | Read local/cloud execution queue diagnostics. |
| `GET /api/providers/local/capability-resolution` | Implemented | Inspect deterministic local model feature and task mapping. |
| `GET /api/providers/models/by-task/{task_family}` | Implemented | Discover enabled local/cloud providers and models mapped to a task family. |
| `POST /api/benchmarks/execution/v2` | Implemented | Execution-only multi-target benchmark run. The client owns scoring. |
| `GET /api/schemas/client-ai/v2` | Implemented | Schema catalog discovery. |
| `GET /api/schemas/client-ai/v2/{schema_name}` | Implemented | Fetch one schema document. |
| `GET /api/schemas/client-ai/v2/communication.md` | Implemented | Fetch this communication guide. |

Admission guard status:

- `POST /api/execution/direct`: Implemented.
- `POST /api/benchmarks/execution/v2`: Implemented.
- `POST /api/execution/compare`: Implemented.
- Dynamic `effective_max_in_flight`: Implemented when enabled by node configuration.

## Boundary

The AI Node is an execution proxy.

Client nodes own:

- prompt intent
- expected labels or outputs
- benchmark cases
- scoring and correctness judgment
- prompt tuning decisions

The AI Node owns:

- provider and model execution
- prompt authorization
- routing and explicit target execution
- usage, latency, cost, and error metadata
- raw and parsed model outputs

The AI Node does not judge benchmark correctness and does not pick a winner.

## Prompt Contract Versions

The AI Node accepts legacy and V2+ prompt registrations. Prefer V3 for new prompt contracts because it is the first
contract version that can declare routing intent directly in the prompt policy.

Status: V3 routing policy is implemented for prompt registration and direct execution routing. V3 importance policy is
implemented for prompt registration and direct execution priority mapping. V3 capability requirements are implemented
for provider/model selection. Local/cloud execution queues and async queued-job responses are implemented for direct
execution.

| Version | Use | Routing behavior |
| --- | --- | --- |
| V1 | Legacy prompt records and older clients. | No prompt-level routing policy; requests use legacy provider selection. |
| V2 | Benchmark-capable prompt contracts with output and evaluation metadata. | No prompt-level routing policy; requests may still narrow routing with provider/governance fields. |
| V3 | Preferred contract for new clients. | Adds `constraints.routing_policy.mode` as the prompt-level routing boundary, privacy-aware local/cloud constraints, `constraints.importance.level` as prompt-owned urgency, and `constraints.capability_requirements.required_features` as prompt-owned model requirements. |

V3 prompt routing modes:

- `local_only`: execute only on the local provider. Do not fall back to cloud.
- `local_preferred`: prefer local execution, but cloud may be eligible if local cannot serve the request.
- `cloud_only`: execute only on a cloud provider.
- `cloud_fallback`: prefer cloud execution, but local may be eligible if cloud cannot serve the request.

The prompt routing policy and the API request both participate in routing, but they do not have equal authority. The
prompt policy is the maximum allowed boundary for the prompt. The API request may narrow or prefer a route for a single
call by sending `constraints.routing_policy.mode`, and node governance may restrict it further. A request must not
weaken prompt privacy or broaden the prompt's routing boundary.

Examples:

- Prompt `local_only` plus API `cloud_only`: reject as incompatible.
- Prompt `local_preferred` plus API `local_only`: allowed because the request is stricter.
- Prompt V1 or V2 without routing policy: use legacy provider selection unless the request narrows it.
- Governance that disables OpenAI: cloud routes are unavailable even when the prompt or request allows cloud.

V3 prompt privacy routing:

- `privacy_class = "restricted"` or `"sensitive"` is treated as a local-only routing boundary even when
  `constraints.routing_policy.mode` is omitted.
- Sensitive/restricted prompts cannot be broadened by request-side `cloud_only`, `cloud_fallback`, or an explicit cloud
  `requested_provider`.
- `privacy_class = "public"` or `"internal"` keeps the normal prompt/request routing behavior.

V3 prompt importance levels:

- `background`: low urgency and batchable work.
- `normal`: default behavior. V1, V2, and V3 prompts without an explicit importance policy normalize to this level.
- `high`: user-visible or time-sensitive work.
- `critical`: rare user-blocking or operations-sensitive work. In the current direct execution API this maps to `high`
  execution priority because `TaskExecutionRequest.priority` supports `background`, `low`, `normal`, and `high`.

Importance does not weaken routing or privacy. A `critical` prompt with `routing_policy.mode = local_only` still remains
local-only. When a prompt is used, the prompt owner's importance policy determines the effective execution priority;
caller `priority` cannot inflate or reduce that prompt-owned importance.

V3 prompt capability requirements:

- `constraints.capability_requirements.required_features` lists model feature flags that every selected model must
  support, for example `reasoning`, `structured_output`, `tool_calling`, `vision_input`, or `code_generation`.
- Capability requirements narrow provider/model selection. They do not broaden routing or override privacy.
- An explicit `requested_model` cannot bypass prompt-owned required features. If the requested model does not satisfy
  the requirements, the resolver may select another eligible model or return a model-unavailable result.
- Successful and non-success execution results that reached provider resolution include the effective requirements in
  `resolution_metadata.capability_requirements`.

## Production Execution

Production execution continues to use the existing route:

```text
POST /api/execution/direct
```

The request is task-family based. Do not use separate classify or summarize routes. The implemented request model is
`TaskExecutionRequest`, which accepts these top-level fields:

- `task_id`
- `prompt_id`
- `prompt_version`
- `task_family`
- `requested_by`
- `service_id`
- `customer_id`
- `requested_provider`
- `requested_model`
- `inputs`
- `constraints`
- `priority`
- `response_mode`
- `job_name`
- `timeout_s`
- `trace_id`
- `lease_id`

`TaskExecutionRequest` rejects unknown top-level fields. In particular, do not send top-level `output_contract` to
`/api/execution/direct`; that field belongs to prompt registration metadata and explicit benchmark requests.

Example:

```json
{
  "task_id": "task-123",
  "prompt_id": "mail.classifier",
  "prompt_version": "v2.0",
  "task_family": "task.classification",
  "requested_by": "mail-node",
  "service_id": "mail-node",
  "trace_id": "trace-123",
  "inputs": {
    "subject": "Package update",
    "body": "Your package has shipped."
  }
}
```

The AI Node returns the normal execution result.

### Route Preview

Use `POST /api/execution/route-preview` with the same `TaskExecutionRequest` payload to dry-run routing before deciding
whether to execute or queue a job. The preview does not acquire direct execution admission, does not enqueue a job, and
does not call a model provider.

Example response:

```json
{
  "status": "preview",
  "dry_run": true,
  "would_execute": true,
  "would_queue": true,
  "task_id": "task-queued-123",
  "response_mode": "async_if_queued",
  "queue": "local",
  "importance": "normal",
  "routing_decision": {
    "original_routing_mode": "local_preferred",
    "execution_routing_mode": "local_preferred",
    "selected_queue": "local",
    "original_queue": "local",
    "spillover": false,
    "reason": "routing_policy_local_preferred"
  },
  "effective_request": {
    "requested_provider": null,
    "requested_model": null,
    "constraints": {
      "routing_policy": {
        "mode": "local_preferred"
      }
    },
    "timeout_s": 60
  },
  "authorization": {
    "allowed": true,
    "reason": "authorized",
    "prompt_id": "mail.classifier",
    "prompt_version": "v3.0",
    "privacy_class": "internal"
  },
  "provider_resolution": {
    "allowed": true,
    "selected_provider": "local",
    "selected_model": "qwen3-8b-q4_k_m",
    "provider_order": ["local", "openai"],
    "fallback_provider_ids": ["openai"],
    "model_allowlist_by_provider": {
      "local": ["qwen3-8b-q4_k_m"]
    },
    "timeout_s": 60,
    "retry_count": 0,
    "rejection_reason": null
  }
}
```

If prompt authorization fails, the preview returns `would_execute = false`, `would_queue = false`, and the
authorization rejection reason without performing provider resolution.

### Async Queued Execution

Set `response_mode` to `async_if_queued` when the client wants the AI Node to accept the request into an internal queue
instead of blocking the HTTP call until model execution finishes.

```json
{
  "task_id": "task-queued-123",
  "job_name": "mail classification 123",
  "prompt_id": "mail.classifier",
  "prompt_version": "v3.0",
  "task_family": "task.classification",
  "requested_by": "mail-node",
  "service_id": "mail-node",
  "trace_id": "trace-queued-123",
  "response_mode": "async_if_queued",
  "inputs": {
    "subject": "Package update",
    "body": "Your package has shipped."
  }
}
```

Queued responses use HTTP `200` and this shape:

```json
{
  "status": "queued",
  "job_id": "job-0123456789abcdef",
  "job_name": "mail classification 123",
  "message": "job queued - check in 5 secs",
  "check_after_seconds": 5,
  "status_url": "/api/execution/jobs/job-0123456789abcdef",
  "queue": "local",
  "queue_position": 1,
  "eta": {
    "estimated_start_seconds": 5,
    "estimated_start_at": "2026-06-04T17:30:05-07:00",
    "source": "queue_position",
    "confidence": "rough"
  },
  "importance": "normal",
  "routing_decision": {
    "original_routing_mode": "local_preferred",
    "execution_routing_mode": "local_preferred",
    "selected_queue": "local",
    "original_queue": "local",
    "spillover": false,
    "reason": "routing_policy_local_preferred"
  },
  "expires_at": "2026-06-04T17:30:00-07:00"
}
```

If the client already has too many queued or running async jobs, the node returns HTTP `200` with a queue rejection
payload instead of creating a job:

```json
{
  "status": "rejected",
  "error_code": "queue_client_limit_exceeded",
  "error_message": "queue_client_limit_exceeded",
  "client_id": "mail-node",
  "queue": "local",
  "pending_count": 20,
  "max_pending_per_client": 20,
  "check_after_seconds": 5
}
```

The fairness cap is keyed by `requested_by` and counts queued plus running async jobs across local and cloud queues.
Clients should poll existing jobs or retry after `check_after_seconds`. The node default is
`HEXE_EXECUTION_QUEUE_MAX_PENDING_PER_CLIENT = 20`; `0` disables this cap.

Poll the job status with:

```text
GET /api/execution/jobs/{job_id}
```

The job status payload includes `status` as `queued`, `running`, `completed`, `failed`, or `not_found`. Completed jobs
place the normal `TaskExecutionResult` under `result`; failed jobs return a short `error` object. Both the initial
queued response and the polled job status include `routing_decision` and `eta`. The `eta` object is a rough start-time
estimate based on current queue position, active jobs, queue concurrency, and `check_after_seconds`; clients should poll
using `check_after_seconds` rather than treating the estimate as a guarantee.

Queued job status is persisted to `HEXE_EXECUTION_QUEUE_STATE_PATH`, or by default to `execution_queue_jobs.json` next
to the node config. Completed, failed, and cancelled job records can still be polled after API restart while they remain
in the queue state file. Jobs that were `queued` or `running` when the API stopped are recovered as `failed` with
`error.code = "execution_queue_recovery_required"` because the in-memory execution runner cannot be safely resumed from
disk. Clients should resubmit the request if it is still needed.

Cancel a queued job before it starts with:

```text
DELETE /api/execution/jobs/{job_id}
```

Optional body:

```json
{
  "reason": "client_cancelled"
}
```

Cancellation returns the job payload with `status = "cancelled"` and `error.code = "cancelled"`. Running or already
terminal jobs cannot be cancelled; the API returns HTTP `409` with `cancel_rejected_reason`. Missing jobs return HTTP
`404`.

Queue diagnostics include a `persistence` object showing whether status persistence is configured, the state-file path,
and `recovered_unfinished_count` for unfinished jobs recovered during startup.
Diagnostics also include `fairness.max_pending_per_client` and per-queue `per_client_pending` counts.

Queue selection:

- Local queue: explicit `requested_provider = "local"`, request `constraints.routing_policy.mode = "local_only"`, or
  a V3 prompt policy that is `local_only` or `local_preferred`.
- Cloud queue: explicit cloud provider, request `cloud_only`, or a V3 prompt policy that is `cloud_only` or
  `cloud_fallback`.
- Capability-aware queue selection: when no hard route is declared, or when a flexible route such as
  `local_preferred`/`cloud_fallback` can only be served by one side, the node uses provider task capability maps to
  choose the local or cloud queue and narrows execution routing to match that choice.
- Spillover: `local_preferred` high-importance or critical queued requests may enter the cloud queue when the local
  queue is already backed up, an eligible cloud model is available, and the request passes configured cloud budget and
  max-cost guardrails. This does not apply to `local_only` or explicit `requested_provider = "local"` requests.
- If neither side declares a route, the queued request defaults to the cloud queue and normal provider resolution still
  runs at execution time.

Importance selection:

- V3 prompt `constraints.importance.level` controls queue priority when a prompt is present.
- Without prompt-owned importance, `TaskExecutionRequest.priority` controls queue priority.
- V1 and V2 prompts, and V3 prompts without explicit importance, are treated as `normal`.

Local queue capacity is configured as `LLAMACPP_PARALLEL + 1` by default. This intentionally keeps only a small number
of local jobs in or near llama.cpp while the AI Node queue decides which job enters next by importance and FIFO order
within the same importance. Requests that need a local model swap remain queued until they can enter local execution;
the existing local runtime switch path handles the swap, then the idle reversion policy returns to
`qwen3-8b-q4_k_m` when the alternate model is idle long enough.

Local model state is exposed through `GET /api/node/status` under `services.local_llm.model_states`:

```json
{
  "configured": true,
  "runtime_ready": true,
  "active_model_ids": ["qwen3-8b-q4_k_m"],
  "default_model_id": "qwen3-8b-q4_k_m",
  "models": [
    {
      "model_id": "qwen3-8b-q4_k_m",
      "default": true,
      "health_state": "available",
      "warmth_state": "loaded",
      "loaded": true,
      "swap_required": false,
      "repo": "Qwen/Qwen3-8B-GGUF",
      "quantization": "Q4_K_M",
      "ctx_size": 4096
    }
  ]
}
```

`warmth_state` values:

- `loaded`: the model is currently active in the local llama.cpp runtime.
- `warm`: the default model is expected to be ready because the local runtime sockets are healthy, but no active model
  id was reported.
- `cold`: the model is configured but not currently active or warmed by a healthy local runtime.
- `swap_required`: another local model is active, so this model requires a local runtime switch before execution.

Use `GET /api/execution/queues` for operational diagnostics:

```json
{
  "configured": true,
  "queues": {
    "local": {
      "queued_count": 1,
      "active_count": 1,
      "concurrency": 2,
      "oldest_queued_at": "2026-06-04T17:00:00-07:00",
      "per_importance": {
        "high": 1
      }
    },
    "cloud": {
      "queued_count": 0,
      "active_count": 0,
      "concurrency": 4,
      "oldest_queued_at": null,
      "per_importance": {}
    }
  },
  "job_count": 2,
  "generated_at": "2026-06-04T17:00:05-07:00"
}
```

### Direct Execution Response

Successful direct execution returns a `TaskExecutionResult` shape:

```json
{
  "task_id": "task-123",
  "status": "completed",
  "output": {
    "text": "..."
  },
  "metrics": {
    "execution_duration_ms": 1242.5,
    "provider_latency_ms": 1198.4,
    "provider_avg_latency_ms": 1150.0,
    "provider_p95_latency_ms": 1800.0,
    "provider_success_rate": 0.98,
    "provider_total_requests": 100,
    "provider_failed_requests": 2,
    "retries": 0,
    "fallback_used": false,
    "prompt_tokens": 120,
    "cached_input_tokens": 0,
    "completion_tokens": 40,
    "total_tokens": 160,
    "estimated_cost": 0.00012
  },
  "error_code": null,
  "error_message": null,
  "provider_used": "openai",
  "model_used": "gpt-5-mini",
  "resolution_metadata": {
    "selected_provider": "openai",
    "selected_model": "gpt-5-mini",
    "provider_selection_reason": "requested_provider",
    "model_selection_reason": "requested_model",
    "requested_provider": "openai",
    "requested_model": "gpt-5-mini",
    "effective_requested_provider": "openai",
    "effective_requested_model": "gpt-5-mini",
    "routing_policy_mode": null,
    "provider_order": ["openai"],
    "fallback_provider_ids": [],
    "model_allowlist_by_provider": {
      "openai": ["gpt-5-mini"]
    },
    "timeout_s": 60,
    "retry_count": 0,
    "rejection_reason": null
  },
  "completed_at": "2026-05-28T00:00:00-07:00"
}
```

Non-success task results still use HTTP `200` when the request reached the execution service and the task itself was
rejected, unsupported, degraded, or failed under the execution contract. In those cases `status`, `error_code`, and
`error_message` describe the task outcome. When provider resolution ran, `resolution_metadata` is included on both
successful and non-success task results so clients can inspect why a provider/model was chosen or why resolution failed.
When a V3 prompt contributes `constraints.capability_requirements.required_features`, the same metadata includes
`capability_requirements` with the effective feature list and source.
For non-success results after resolution, `resolution_metadata.error_policy` describes whether the failure class is
retryable and whether fallback to another provider/model is allowed.

Execution retry/fallback policy:

| Failure category | Retryable | Fallback allowed | Client action |
| --- | --- | --- | --- |
| `provider_unavailable` | yes | yes | Retry later or use another allowed provider. |
| `model_unavailable` | no | yes | Choose another allowed model/provider. |
| `execution_timeout` | yes | yes | Retry with a smaller request or another provider. |
| `lease_expired` | yes | no | Renew the lease, then retry. |
| `governance_violation`, `budget_violation`, `invalid_input`, `unsupported_task_family` | no | no | Fix request, policy, budget, or declared capability. |
| `internal_execution_error` | no | no | Inspect node/provider logs before retrying. |

HTTP errors mean the request did not execute normally. Examples:

- `400`: invalid request shape, unknown top-level field, invalid task family, missing required value, or direct execution not configured.
- `422`: FastAPI/Pydantic request validation failure before the route handler runs.
- `503`: AI Node admission guard rejected the request before provider execution started.

### Structured Output In Direct Execution

If the prompt requires structured output, send the JSON Schema inside `inputs` as either `json_schema` or
`structured_output_schema`. The authorization layer checks those input fields when the prompt has
`constraints.structured_output_required`.

Example:

```json
{
  "task_id": "task-123",
  "prompt_id": "mail.classifier",
  "prompt_version": "v2.0",
  "task_family": "task.classification",
  "requested_by": "mail-node",
  "service_id": "mail-node",
  "trace_id": "trace-123",
  "inputs": {
    "normalized_text": "subject: Package update\nbody: Your package has shipped.",
    "json_schema": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "label": {
          "type": "string"
        },
        "confidence": {
          "type": "number"
        },
        "rationale": {
          "type": "string"
        }
      },
      "required": ["label", "confidence", "rationale"]
    }
  }
}
```

### Provider And Model Selection

Client nodes ask for a task family such as `task.classification` or `task.summarization`. The AI Node chooses an
eligible provider and model from its configured providers, prompt preferences, governance rules, and model capability
data.

Use `requested_provider` only when the client needs to prefer a provider. Use `requested_model` only as an explicit
override. If the requested provider is not enabled or does not have an eligible model, the resolver may use another
eligible provider unless governance constraints prohibit fallback.

For V3 prompts, local-only execution should be declared on the prompt contract. Sensitive or restricted prompts also
become local-only through `privacy_class`:

```json
{
  "prompt_id": "mail.classifier",
  "service_id": "mail-node",
  "task_family": "task.classification",
  "version": "v3.0",
  "privacy_class": "sensitive",
  "constraints": {
    "routing_policy": {
      "mode": "local_only"
    }
  },
  "definition": {
    "prompt_template": "Classify: {{normalized_text}}"
  }
}
```

V3 prompts can also require model features. This is prompt-owned selection policy, not a hint:

```json
{
  "prompt_id": "mail.reasoned.classifier",
  "service_id": "mail-node",
  "task_family": "task.classification",
  "version": "v3.0",
  "constraints": {
    "routing_policy": {
      "mode": "local_preferred"
    },
    "capability_requirements": {
      "required_features": ["reasoning", "structured_output"]
    }
  },
  "definition": {
    "prompt_template": "Classify with rationale: {{normalized_text}}"
  }
}
```

A single execution request can narrow routing with `constraints.routing_policy.mode`:

```json
{
  "task_id": "task-local-123",
  "prompt_id": "mail.classifier",
  "prompt_version": "v3.0",
  "task_family": "task.classification",
  "requested_by": "mail-node",
  "service_id": "mail-node",
  "trace_id": "trace-local-123",
  "inputs": {
    "normalized_text": "subject: Package update\nbody: Your package has shipped."
  },
  "constraints": {
    "routing_policy": {
      "mode": "local_only"
    }
  }
}
```

For V1/V2 clients that do not have prompt-level routing policy, local-only behavior can still be requested with both
`requested_provider` and the request governance provider allowlist:

```json
{
  "task_id": "task-local-123",
  "prompt_id": "mail.classifier",
  "prompt_version": "v2.0",
  "task_family": "task.classification",
  "requested_by": "mail-node",
  "service_id": "mail-node",
  "requested_provider": "local",
  "trace_id": "trace-local-123",
  "inputs": {
    "normalized_text": "subject: Package update\nbody: Your package has shipped.",
    "json_schema": {
      "type": "object"
    }
  },
  "constraints": {
    "governance": {
      "approved_providers": ["local"]
    }
  },
  "priority": "background"
}
```

Local-only execution requires the AI Node provider configuration to include an enabled local provider. If local is not
enabled, the request should fail as provider unavailable or not governance-approved instead of falling back to OpenAI.

Local llama.cpp models contribute to node task capability resolution through deterministic feature mapping. Inspect
that provider-specific mapping with `GET /api/providers/local/capability-resolution`; inspect the merged local + cloud
task surface with `GET /api/capabilities/node/resolved`.

To discover enabled providers and models for one task family:

```text
GET /api/providers/models/by-task/task.classification
```

The response includes `providers[]` with `provider_id`, `queue`, `resolved_tasks`, and `models[]` entries containing
`model_id`, `default`, and `usable`.

Use this discovery route before registering or updating V3 capability requirements when a client needs to check which
local or cloud side can serve a task family. Feature-level V3 requirements are enforced during execution from model
feature maps; clients can inspect local capability resolution and OpenAI model feature endpoints when they need to
preflight specific `required_features`.

## Execution Admission And Backpressure

Before sending a batch of direct execution requests, a client node should inspect:

```text
GET /api/execution/admission
```

This route is safe to call while the node is busy. It does not consume execution capacity.

Example response:

```json
{
  "configured": true,
  "enabled": true,
  "would_accept_now": true,
  "current_rejection_reason": null,
  "in_flight": 0,
  "accepted_count": 2,
  "rejected_count": 6,
  "last_rejection": {
    "accepted": false,
    "route": "direct",
    "reason": "max_in_flight_exceeded",
    "retry_after_seconds": 30,
    "in_flight": 2,
    "effective_max_in_flight": 2,
    "capacity_tier": "static",
    "resources": {
      "memory_available_mb": 13145,
      "swap_used_ratio": 0.24,
      "load_per_cpu": 0.035
    },
    "timestamp": "2026-05-28T00:27:36-07:00"
  },
  "route_counts": {
    "direct": {
      "in_flight": 0,
      "accepted_count": 2,
      "rejected_count": 6
    }
  },
  "thresholds": {
    "enabled": true,
    "max_in_flight": 2,
    "configured_max_in_flight": 2,
    "effective_max_in_flight": 2,
    "dynamic_in_flight_enabled": false,
    "min_effective_in_flight": 1,
    "capacity_tier": "static",
    "min_memory_available_mb": 512,
    "warm_memory_available_mb": 8192,
    "hot_memory_available_mb": 2048,
    "max_swap_used_ratio": 0.95,
    "warm_swap_used_ratio": 0.5,
    "hot_swap_used_ratio": 0.8,
    "max_load_per_cpu": 2.0,
    "warm_load_per_cpu": 0.8,
    "hot_load_per_cpu": 1.5,
    "retry_after_seconds": 30
  },
  "resources": {
    "memory_total_mb": 15872,
    "memory_available_mb": 13145,
    "swap_total_mb": 9168,
    "swap_free_mb": 6968,
    "swap_used_ratio": 0.24,
    "load_1m": 0.56,
    "load_5m": 0.67,
    "load_15m": 0.69,
    "cpu_count": 16,
    "load_per_cpu": 0.035
  }
}
```

Important fields:

- `thresholds.max_in_flight`: configured hard ceiling for concurrent expensive executions.
- `thresholds.configured_max_in_flight`: same configured ceiling, named explicitly for clients that also read effective capacity.
- `thresholds.effective_max_in_flight`: current live concurrency limit after dynamic capacity adjustment.
- `thresholds.dynamic_in_flight_enabled`: whether the node is currently adjusting effective capacity from resource pressure.
- `thresholds.capacity_tier`: `static`, `healthy`, `warm`, or `hot`.
- `in_flight`: number of expensive executions currently running across guarded routes.
- `route_counts`: accepted, rejected, and in-flight counters by guarded route.
- `would_accept_now`: whether another guarded execution would be accepted at the moment this status was sampled.
- `current_rejection_reason`: why the next direct execution would be rejected, if any.
- `accepted_count`: count of accepted direct executions since backend startup.
- `rejected_count`: count of guarded executions rejected by admission guard since backend startup.
- `last_rejection`: last admission rejection, including reason, retry hint, resource snapshot, and timestamp.
- `thresholds.retry_after_seconds`: retry hint clients should honor after `503`.
- `resources.memory_available_mb`: host memory available for new work.
- `resources.swap_used_ratio`: current swap pressure ratio.
- `resources.load_per_cpu`: 1-minute load divided by CPU count.

Current execution admission reasons:

| Reason | Meaning | Client behavior |
| --- | --- | --- |
| `max_in_flight_exceeded` | The node already has `thresholds.max_in_flight` direct executions running. | Stop sending more work to this node until at least `retry_after_seconds` has passed. |
| `memory_available_below_floor` | Available host memory is below `thresholds.min_memory_available_mb`. | Stop the batch and retry later; consider routing to another AI Node if available. |
| `swap_pressure_high` | Swap usage is at or above `thresholds.max_swap_used_ratio`. | Stop the batch and retry later; do not immediately replay the whole batch. |
| `load_average_high` | Host load per CPU is at or above `thresholds.max_load_per_cpu`. | Pause and retry later with a smaller batch. |

When the node is busy, guarded execution returns HTTP `503`:

```http
HTTP/1.1 503 Service Unavailable
Retry-After: 30
```

Body:

```json
{
  "detail": {
    "accepted": false,
    "status": "busy",
    "reason": "max_in_flight_exceeded",
    "retry_after_seconds": 30,
    "in_flight": 2,
    "route": "direct",
    "effective_max_in_flight": 2,
    "capacity_tier": "static",
    "resources": {
      "memory_available_mb": 13145,
      "swap_used_ratio": 0.24,
      "load_per_cpu": 0.035
    }
  }
}
```

The rejected request did not enter provider execution. The AI Node should not have spent OpenAI budget, local model
tokens, comparison fan-out, or benchmark work for that rejected request.

### Client Batch Behavior

Client nodes should treat `thresholds.effective_max_in_flight` as the current per-node concurrency ceiling for guarded
execution. If that field is absent for compatibility with an older node, use `thresholds.max_in_flight`.

Recommended direct execution batching:

1. Call `GET /api/execution/admission`.
2. If `would_accept_now` is `false`, wait `thresholds.retry_after_seconds` or the `last_rejection.retry_after_seconds`.
3. Compute remaining capacity as `max(thresholds.effective_max_in_flight - in_flight, 0)`.
4. Send at most that many concurrent guarded execution requests to this AI Node.
5. On the first `503`, stop launching more requests from the same batch.
6. Honor the `Retry-After` header before retrying rejected items.
7. Retry rejected work as a smaller batch, not as the original full batch.

Example client-side capacity calculation:

```text
max_in_flight = admission.thresholds.effective_max_in_flight
in_flight = admission.in_flight
send_now = max(max_in_flight - in_flight, 0)
```

If `effective_max_in_flight = 2` and `in_flight = 0`, send at most 2 concurrent calls. If a client sends 8 simultaneous calls,
the expected current behavior is 2 accepted and 6 rejected with HTTP `503`.

Do not retry all rejected requests immediately. Immediate replay can create the same overload pattern again.

### Admission Scope

Current implemented admission enforcement covers these expensive routes:

```text
POST /api/execution/direct
POST /api/benchmarks/execution/v2
POST /api/execution/compare
```

Admission status is available through:

```text
GET /api/execution/admission
```

Lightweight routes such as `POST /api/execution/authorize`, `GET /api/execution/admission`, health, status, schema
discovery, and debug/status routes do not consume execution admission capacity.

Dynamic capacity is optional. When enabled by the operator, the node keeps `thresholds.configured_max_in_flight` as the
hard ceiling and lowers `thresholds.effective_max_in_flight` under resource pressure:

| Capacity tier | Effective capacity |
| --- | --- |
| `healthy` | configured ceiling |
| `warm` | half of configured ceiling, not below `min_effective_in_flight` |
| `hot` | `min_effective_in_flight` |
| `static` | configured ceiling because dynamic capacity is disabled |

## Prompt Registration

Prompt registration continues to use the existing route:

```text
POST /api/prompts/services
```

V2-compatible prompts can include `output_contract` and `benchmark` metadata.
This metadata describes the prompt contract, but it is not a valid top-level field for `/api/execution/direct`.

Example:

```json
{
  "prompt_id": "mail.classifier",
  "service_id": "mail-node",
  "task_family": "task.classification",
  "version": "v2.0",
  "definition": {
    "system_prompt": "Return JSON only.",
    "prompt_template": "Classify this email: {{body}}",
    "template_variables": ["body"]
  },
  "output_contract": {
    "format": "json",
    "parse_json_output": true
  },
  "benchmark": {
    "enabled": true,
    "mode": "execution_only",
    "owner_evaluates_results": true
  }
}
```

## Execution-Only Benchmarking

Benchmark execution uses:

```text
POST /api/benchmarks/execution/v2
```

The client sends the prompt, input, task family, and explicit provider/model targets. Cloud targets are optional.
Unlike `/api/execution/direct`, this benchmark route accepts `output_contract`. When an `output_contract.json_schema`
is present, the AI Node passes that schema into the per-target direct execution inputs.

Example:

```json
{
  "benchmark_id": "bench-123",
  "prompt_id": "mail.classifier",
  "prompt_version": "v2.0",
  "task_family": "task.classification",
  "requested_by": "mail-node",
  "service_id": "mail-node",
  "trace_id": "trace-bench-123",
  "inputs": {
    "body": "Your package has shipped."
  },
  "output_contract": {
    "format": "json",
    "parse_json_output": true,
    "json_schema": {
      "type": "object"
    }
  },
  "targets": [
    {
      "provider": "local",
      "model": "mistral-nemo-instruct-2407-q4_k_m"
    },
    {
      "provider": "openai",
      "model": "gpt-5-mini",
      "role": "baseline"
    }
  ]
}
```

The AI Node returns one response with per-target outputs and metadata. It does not return scores, winners, or correctness judgments.

Benchmark clients should still be conservative with concurrency. Current code enforces shared execution admission at
the benchmark route boundary, and each accepted benchmark request consumes one shared execution slot even if it runs
multiple provider/model targets internally.

When `output_contract.json_schema` is present, the AI Node sends the schema to each provider target as the required
structured response format. Local LLM targets, including llama.cpp-compatible models such as
`llama-3.1-8b-instruct-q4_k_m`, must return the result object directly:

```json
{
  "label": "action_required",
  "confidence": 0.95,
  "rationale": "short reason"
}
```

Do not treat the schema as a tool/function definition for the model to call. A response such as
`{"name":"classify_email","parameters":{"email":"..."}}` is an input echo, not a classifier result, and clients should
not count it as parseable output. If a model still emits a function-style wrapper, the wrapper arguments are only
accepted when they contain the fields required by the output schema, for example `label`, `confidence`, and `rationale`.

## Schema Discovery

Fetch the V2 schema catalog:

```text
GET /api/schemas/client-ai/v2
```

Fetch one schema:

```text
GET /api/schemas/client-ai/v2/{schema_name}
```

Fetch this guide:

```text
GET /api/schemas/client-ai/v2/communication.md
```

Schema caveat: `execution-request.v2.schema.json` documents a proposed V2+ direct execution shape. Until the direct
execution route is migrated to that schema, client nodes should follow the implemented `/api/execution/direct`
contract described above.

## Legacy Benchmark Compatibility

The old node-owned local LLM benchmark API and dashboard view have been removed.
Client nodes should use the V2 execution-only benchmark request when they need multi-target benchmark evidence.
