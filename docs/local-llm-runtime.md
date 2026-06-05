# Local LLM Runtime

Hexe can run a local llama.cpp server beside the node and prefer Unix sockets for local traffic.
The default container image is pinned to `ghcr.io/ggml-org/llama.cpp:server-cuda-b7869` for compatibility with this host's NVIDIA 535 / CUDA 12.4 driver stack; the plain `server` tag is CPU-only on this host.

## Default Model Set

The default runtime target is `Qwen/Qwen3-8B-GGUF:Q4_K_M` with alias `qwen3-8b-q4_k_m`.
This is intended as the default local LLM for the RTX 3060 12 GB node because it leaves more VRAM headroom than the
14B comparator.

Configured local model download targets live in `config/local-llm-models.json`:

- `qwen3-14b-q4_k_m`: Qwen 14B higher-capacity comparator.
- `qwen3-8b-q4_k_m`: Qwen 8B faster same-family comparator.
- `gemma-3-12b-it-q4_k_m`: Gemma 12B instruction comparator.
- `mistral-nemo-instruct-2407-q4_k_m`: Mistral Nemo comparator.
- `llama-3.1-8b-instruct-q4_k_m`: Llama 3.1 8B instruction baseline.

## Runtime Commands

```bash
scripts/llamacpp-control.sh build
scripts/llamacpp-control.sh start
scripts/llamacpp-control.sh ready
scripts/llamacpp-control.sh status
scripts/llamacpp-control.sh logs
scripts/llamacpp-control.sh stop
```

Validate the currently loaded model:

```bash
curl --unix-socket /run/hexe/ai-node/llamacpp.sock http://llamacpp/v1/models
```

Validate local default-model resolution through the AI Node by omitting `requested_model` while requesting the local
provider:

```bash
curl -s http://127.0.0.1:9002/api/execution/direct \
  -H 'Content-Type: application/json' \
  -d '{
    "task_id": "local-default-smoke",
    "task_family": "task.chat",
    "requested_by": "operator",
    "requested_provider": "local",
    "inputs": {"prompt": "Reply with the word ready."},
    "trace_id": "local-default-smoke"
  }'
```

The response should report `provider_used: "local"` and `model_used: "qwen3-8b-q4_k_m"` unless an explicit prompt or
request model override is in effect.

The llama.cpp socket defaults to `/run/hexe/ai-node/llamacpp.sock`.
The health wrapper socket defaults to `/run/hexe/ai-node/llamacpp-health.sock`.
Downloaded model cache defaults to `runtime/cache/llamacpp` so Hugging Face downloads survive container recreation.
The node service status resolves the llama.cpp container from `LLAMACPP_CONTAINER_NAME` (default `hexe-ai-node-llamacpp`) and reports its host PID, CPU percent, and memory percent under `services.local_llm`; supervisor registration and heartbeat payloads include the same service metadata.

When an explicit local model override switches llama.cpp away from the default model, the node tracks the non-default
model's idle time. `HEXE_LOCAL_LLM_DEFAULT_REVERT_IDLE_SECONDS` controls how long a non-default model may sit idle
before the node returns to `qwen3-8b-q4_k_m`; the default is 900 seconds, and `0` disables automatic reversion.
`HEXE_LOCAL_LLM_DEFAULT_REVERT_CHECK_INTERVAL_SECONDS` controls the background check interval and defaults to 60
seconds. Reversion waits while local model switching or direct execution is in flight, and the local execution queue can
pass queued model requirements into the same reversion gate.

## Local Capability Mapping

Local llama.cpp models participate in the same node capability graph used for OpenAI model task resolution. The local
mapping is deterministic and conservative:

- enabled: chat, classification, summarization, reasoning, information extraction, structured extraction, translation,
  sentiment analysis, task planning, workflow reasoning, and streaming response
- enabled for code-named local models such as `coder`, `code`, `codestral`, or `deepseek-coder`: code generation,
  review, debugging, and explanation
- not enabled by the local mapping: tool calling, environment control, vision, OCR, image generation/editing/variation,
  audio, realtime voice, embeddings/search/indexing, moderation, and policy checks

Inspect the local mapping with:

```text
GET /api/providers/local/capability-resolution
```

Rebuild the node-wide resolved task surface with:

```text
POST /api/capabilities/rebuild
```

The node-wide payload at `GET /api/capabilities/node/resolved` includes a `provider_capabilities.local` section so local
and OpenAI task contributions can be compared directly.

## Model Download And Load Tests

```bash
scripts/download-local-llm-models.py --dry-run
scripts/download-local-llm-models.py
scripts/local-llm-gpu-load-test.py --model qwen3-8b-q4_k_m --concurrency 1 --iterations 3
```

The downloader will not download an entire Hugging Face repository unless `--allow-full-repo` is supplied.

## Provider Comparison

Use `POST /api/execution/compare` to run the same prompt through explicit provider/model pairs and compare latency, text, usage, and estimated cost.

Example provider list:

```json
[
  {"provider": "openai", "model": "gpt-5-mini"},
  {"provider": "local", "model": "qwen3-8b-q4_k_m"}
]
```

For `POST /api/benchmarks/execution/v2`, local targets are loaded one at a time before execution. If a target names a configured local model without a provider, the node treats it as `provider: local`. The node restarts llama.cpp when the requested local model is not already active, waits for readiness, then starts the timed inference request. Per-target `latency_ms` measures only the `/v1/chat/completions` execution after the model is ready; model load/swap duration is reported separately as `runtime_metrics.load_seconds`.

The benchmark execution endpoint is synchronous, so the client HTTP timeout must cover total wall time for every requested target: model swaps plus inference. Use at least 300 seconds for a five-model local benchmark, and 420 seconds for five models across five test inputs or a cold runtime. Concurrent local benchmark requests do not start competing model restarts; if another request is already loading a local benchmark model, the overlapping target returns `status: failed` with `error.code: local_llm_busy` and `error.retryable: true`.
