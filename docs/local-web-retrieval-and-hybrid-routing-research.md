# Local Web Retrieval And Hybrid Routing Research

## Scope

This note evaluates two additions to the Hexe AI Node:

1. governed internet retrieval for the local llama.cpp text model;
2. deciding whether a request should run locally or require cloud support.

It is a design recommendation, not an implemented runtime contract.

## Current Baseline

- `task.chat` maps to the `text_llm` lane and the local `qwen3-8b-q4_k_m` model.
- Provider selection already filters by enabled provider, runtime health, governance-approved provider/model, required model
  features, budget, timeout, retry count, and routing mode.
- Existing routing modes are `local_only`, `local_preferred`, `cloud_only`, and `cloud_fallback`.
- The local adapter reports `supports_tools=false` and sends ordinary chat-completion requests. It has no search or URL
  retrieval loop.
- `task.tool_usage` existing in the general taxonomy does not by itself provide or authorize a tool.

## Recommended Web Retrieval Design

Add retrieval as a node-owned, governed tool. Do not give the model arbitrary network access and do not depend on
llama.cpp Web UI built-in tools.

Recommended flow:

1. A request or a freshness detector marks the task as requiring external information.
2. Policy checks whether web retrieval is allowed for the requester, prompt, data classification, and domain set.
3. A `web_search` service accepts a bounded query, locale, freshness window, safe-search level, and result limit.
4. The service queries a configured backend:
   - preferred self-hosted option: SearXNG JSON API;
   - managed option: Brave Search API or another explicitly configured provider.
5. The node normalizes results to title, canonical URL, snippet, source, and retrieval timestamp.
6. Optional page fetching runs in a separate hardened fetcher with DNS/IP validation, redirect limits, content-type and
   size limits, timeouts, an allow/deny list, and protection against loopback, private, link-local, and metadata targets.
7. Retrieved text is treated as untrusted evidence, stripped of active content, bounded by token budget, and labeled so
   prompt instructions in pages cannot override system or governance rules.
8. The local model receives the evidence and must return source-linked citations. The execution result records queries,
   source URLs, timestamps, truncation, and retrieval failures.

The node should own the tool loop even if llama.cpp function calling is enabled. The node can validate a structured
`web_search` call, execute it, append a `tool` result, and request the final answer. This preserves authorization,
auditing, budgets, retries, and provider independence.

### Why not llama.cpp built-in tools

llama.cpp supports OpenAI-style function calling when an appropriate Jinja chat template is enabled. Its server README
also states that the `/tools` API used by its Web UI is internal, subject to change, and should not be used by downstream
applications. Hexe should use the stable chat-completion tool-call shape and implement tool execution at the node
boundary instead.

### Search backend choice

| Option | Advantages | Costs and risks | Recommended use |
|---|---|---|---|
| Self-hosted SearXNG | Local policy control, JSON API, multiple upstream engines, no per-query vendor key in Hexe | Another service to operate; upstream engines can rate-limit or block it | Default for privacy-oriented installations |
| Brave Search API | Managed independent index, structured results, freshness, simple API | External query disclosure, credential and usage cost | Optional managed backend |
| Direct page fetch only | No search dependency when the caller supplies URLs | Cannot discover sources; SSRF and hostile-content controls are essential | Separate `fetch_url` tool, disabled by default |

SearXNG JSON output must be explicitly enabled in its `settings.yml`; public instances often disable it. A Hexe-owned
deployment is preferable to relying on an arbitrary public instance.

## Recommended Local-Versus-Cloud Decision

Use a staged decision rather than asking either model to make an unverified judgment about itself.

### Stage 1: deterministic eligibility

Reject a candidate before inference when any hard requirement fails:

- provider/model unavailable or model not resident within the request wait budget;
- task family or required feature not declared for the model;
- input/context/output size exceeds model limits;
- required modality, structured output, tool, or retrieval backend is unsupported;
- governance, privacy, data-residency, provider allowlist, or budget policy forbids it;
- request explicitly selects `local_only` or `cloud_only`.

Extend the request requirements used by provider selection with explicit signals such as:

- `required_features` including `web_search`, `tool_calling`, `structured_output`, and modality features;
- `freshness_required` and optional maximum source age;
- `quality_tier` or minimum evaluated quality threshold;
- `latency_budget_ms`, `max_cost_cents`, and `cloud_allowed`;
- context/input/output size estimates and sensitivity classification.

### Stage 2: preflight difficulty estimate

For eligible local tasks, calculate a conservative score from observable inputs:

- task-family benchmark performance for the exact local model;
- similarity to previously verified successful and failed requests;
- prompt and context length relative to the model limit;
- requested reasoning, coding, schema, citation, and tool complexity;
- freshness and retrieval requirements;
- current queue, model-load estimate, latency deadline, and resource pressure.

Start with auditable rules and calibrated thresholds. Do not train a learned router until enough representative Hexe
traffic has paired local/cloud results or human/automatic quality labels.

### Stage 3: local-first verification and escalation

When policy permits and the preflight score is safe:

1. execute locally;
2. run task-specific verification rather than trusting self-reported confidence;
3. return the local result if verification passes;
4. otherwise escalate once to an eligible cloud model when cloud use is allowed and budget remains.

Useful verifiers include schema validation, citation/source entailment checks, deterministic classification confidence,
code tests, required-field checks, grounded-answer coverage, and task-specific judge scores. Raw token probability or a
model saying it is confident should be only one calibrated signal, never the sole gate.

The result metadata should expose `route_decision`, `decision_stage`, `decision_reasons`, `local_attempted`,
`verification_result`, `escalated`, selected provider/model, latency, and cost. This lets operators tune thresholds and
build training data without hiding routing behavior.

### Stage 4: learned router after measurement

RouteLLM shows that a router trained on preference data can choose between weaker and stronger models to balance cost
and quality. FrugalGPT demonstrates a model cascade that attempts cheaper models and escalates based on learned quality
signals. These support a later learned Hexe router, but neither removes the need for deterministic governance,
capability, privacy, and budget gates.

Train and validate on Hexe's actual task distribution. Optimize a constrained objective such as cloud-call rate or cost
subject to a minimum acceptance quality, and retain a conservative fallback for out-of-distribution and high-risk tasks.

## Proposed Delivery Sequence

1. Add a provider-neutral retrieval contract and disabled-by-default search configuration.
2. Implement a SearXNG adapter, normalized evidence model, SSRF-safe optional fetcher, citations, audit telemetry, and
   focused tests.
3. Enable llama.cpp tool-call parsing for the selected model/template and implement a bounded node-owned tool loop.
4. Add deterministic request-requirement and local/cloud decision metadata to the existing provider policy.
5. Add task-specific local-result verification and one-step cloud escalation.
6. Collect paired outcomes and operator feedback; only then evaluate a learned router against the rules baseline.

## Open Product Decisions

- Whether Hexe will operate SearXNG locally or use a managed search API by default.
- Which requesters and data classifications may disclose queries externally.
- Whether URL page fetching is required in the first release or snippets are sufficient.
- Quality targets and cloud-cost ceilings per task family.
- Whether escalation requires explicit user approval for sensitive or unexpectedly billable requests.

## Primary Sources

- llama.cpp server documentation: <https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md>
- SearXNG Search API: <https://docs.searxng.org/dev/search_api.html>
- SearXNG search settings: <https://docs.searxng.org/admin/settings/settings_search.html>
- Brave Search API: <https://api-dashboard.search.brave.com/api-reference/web/search/get>
- RouteLLM paper: <https://arxiv.org/abs/2406.18665>
- RouteLLM reference implementation: <https://github.com/lm-sys/RouteLLM>
- FrugalGPT paper: <https://arxiv.org/abs/2305.05176>
- Selective-LAMA confidence-aware evaluation: <https://aclanthology.org/2023.findings-eacl.150/>
