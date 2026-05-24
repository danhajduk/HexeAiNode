# Client AI V2 Communication Guide

Status: Partially implemented

This guide explains how a client node should communicate with the AI Node using the V2 client AI contract.

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

## Production Execution

Production execution continues to use the existing route:

```text
POST /api/execution/direct
```

The request is task-family based. Do not use separate classify or summarize routes.

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

## Prompt Registration

Prompt registration continues to use the existing route:

```text
POST /api/prompts/services
```

V2-compatible prompts can include `output_contract` and `benchmark` metadata.

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

## Legacy Benchmark Compatibility

The old local LLM benchmark remains available during migration under:

```text
/api/benchmarks/local-llm/...
```

That path is retained for compatibility while client-owned benchmark execution migrates to V2.
