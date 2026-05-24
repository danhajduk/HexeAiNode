# Benchmark Execution Migration

Status: Partially implemented
Last updated: 2026-05-24

## Purpose

This document records the migration from node-local benchmark judging to an execution-only benchmark model.

Implemented today:

- client AI V2 schema discovery through `GET /api/schemas/client-ai/v2`
- V2 prompt registration/update metadata passthrough for `output_contract` and `benchmark`
- execution-only V2 benchmark requests through `POST /api/benchmarks/execution/v2`

Removed legacy behavior:

- local LLM shadow benchmarking for captured OpenAI calls
- local benchmark replay against configured llama.cpp rotation models
- local benchmark comparison API and dashboard view

Not developed:

- migration tooling for prompt-tuning workflows outside this node
- dedicated UI for external V2 benchmark execution

## Boundary

The AI Node is execution infrastructure. It should act as a governed proxy to AI providers and local runtimes.

The AI Node owns:

- provider access
- provider/model routing when requested by policy
- model execution
- budget, timeout, and governance enforcement
- latency, token, cost, and runtime metadata collection
- raw and parsed provider responses

The prompt-owning client node owns:

- prompt intent
- expected output semantics
- labels and label definitions
- benchmark cases
- scoring rules
- model selection decisions
- prompt tuning decisions

The AI Node must not decide benchmark correctness for external benchmark requests. It should return evidence, not judgment.

## Removed Local Benchmark Compatibility

The local LLM shadow benchmark path has been removed. The AI Node no longer captures OpenAI production calls as benchmark records, replays them locally, exposes node-owned match rates, or stores manual label corrections.

## New Execution-Only Benchmark Model

The V2 benchmark API executes one prompt request against one or more explicit targets and returns one response containing all target results.

The response should include, per target:

- provider id
- model id
- status
- raw output text
- parsed structured output when parseable
- token usage when available
- latency
- cost when available
- provider error details when failed
- local runtime metrics when available, such as VRAM and GPU utilization

The response should not include:

- winner selection
- correctness judgment
- label match scoring
- prompt tuning recommendation

Those decisions belong to the prompt-owning client node.

## Prompt Contract Versus API Request

Benchmark capability should be declared in the prompt contract, but concrete benchmark execution should be requested through the API.

Prompt contract ownership:

- prompt id
- prompt version
- task family
- prompt template and system prompt
- output schema expectations
- benchmark capability metadata for prompt versions `v2.0+`
- prompt-owner policy describing whether the prompt may be used in benchmark workflows

API request ownership:

- execution mode, such as normal execution or benchmark execution
- target provider/model list
- cloud baseline inclusion or omission
- input values for this execution
- timeout and budget constraints

This split keeps benchmark enablement with the prompt owner while keeping runtime target selection explicit per execution.

## Prompt Version Line

Prompt versions `v2.0+` should be the benchmark-capable prompt line.

The current implementation stores V2 prompt `output_contract` and `benchmark` payloads in prompt metadata and version metadata. The remaining migration work is broader adoption by prompt-owning client nodes.

- `v1` prompts remain compatible with existing execution behavior.
- `v2.0+` prompts may include benchmark metadata and stricter output schema declarations.
- Old prompts should continue to run until owners migrate them.
- Migration should avoid requiring every client node to update at once.

## Task Families And API Shape

The canonical execution surface should remain task-family based.

Use one benchmark execution API with a `task_family` field:

- `task.classification`
- `task.summarization`
- `task.information_extraction`
- other declared task families

Do not create separate canonical routes such as:

- `/classify`
- `/summarize`
- `/summary`

Separate per-task routes would duplicate validation, governance, routing, and provider execution behavior. Convenience wrappers can be reconsidered later, but the canonical contract should stay generic and task-family driven.

## Cloud Optionality

Benchmark execution should not require cloud execution.

Supported request shapes should include:

- local-only benchmark execution
- cloud-only benchmark execution
- cloud plus local execution
- multiple local and cloud candidate targets

The client decides whether a cloud baseline is needed for the benchmark case.

## Migration Tasks

Tracked task range: Task 916 through Task 925.

The legacy local LLM benchmark path is no longer preserved. Client-owned benchmark execution is available through the V2 execution-only API.
