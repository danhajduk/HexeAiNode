# Local LLM Runtime

Hexe can run a local llama.cpp server beside the node and prefer Unix sockets for local traffic.
The default container image is pinned to `ghcr.io/ggml-org/llama.cpp:server-cuda-b7869` for compatibility with this host's NVIDIA 535 / CUDA 12.4 driver stack; the plain `server` tag is CPU-only on this host.

## Default Model Set

The default runtime target is `Qwen/Qwen3-8B-GGUF:Q4_K_M` with alias `qwen3-8b-q4_k_m`.
This is intended for reasoning and classification on hosts with roughly 9.5-10 GB VRAM.

Configured benchmark candidates live in `config/local-llm-models.json`:

- `qwen3-8b-q4_k_m`: Qwen 8B baseline.
- `qwen3-14b-q4_k_m`: Qwen 14B higher-capacity comparator.
- `gemma-3-12b-it-q4_k_m`: Gemma 12B instruction comparator.
- `mistral-nemo-instruct-2407-q4_k_m`: Mistral Nemo comparator.

## Runtime Commands

```bash
scripts/llamacpp-control.sh build
scripts/llamacpp-control.sh start
scripts/llamacpp-control.sh ready
scripts/llamacpp-control.sh status
scripts/llamacpp-control.sh logs
scripts/llamacpp-control.sh stop
```

The llama.cpp socket defaults to `/run/hexe/ai-node/llamacpp.sock`.
The health wrapper socket defaults to `/run/hexe/ai-node/llamacpp-health.sock`.
Downloaded model cache defaults to `runtime/cache/llamacpp` so Hugging Face downloads survive container recreation.
The node service status resolves the llama.cpp container from `LLAMACPP_CONTAINER_NAME` (default `hexe-ai-node-llamacpp`) and reports its host PID, CPU percent, and memory percent under `services.local_llm`; supervisor registration and heartbeat payloads include the same service metadata.

## Model Download And Benchmarks

```bash
scripts/download-local-llm-models.py --dry-run
scripts/download-local-llm-models.py
scripts/benchmark-local-llm.py --model qwen3-8b-q4_k_m
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

## OpenAI Replay Benchmarks

When benchmark capture is enabled, OpenAI executions for `prompt.email.classifier` are stored for replay across the local model rotation. Other prompt IDs are ignored by capture and by pending replay claims. The automatic rotation runs every 60 seconds, resets failed classifier replay rows back to pending once at the start of each run, skips swaps when no configured model has pending classifier prompts, and reports `idle`, `running`, or `swapping` based on active benchmark work. Operators can also re-run all local LLMs, which requeues non-running local replay rows for every configured benchmark model while preserving the OpenAI baseline records.

The manual model-change action stops following the current model's pending queue before switching. It loads the next configured model without classifying prompts as part of the click; if the currently loaded model already has an active prompt, the switch is skipped until that prompt finishes.

The benchmark view defaults to showing prompts where at least one completed local model label differs from the reference label. Operators can override the correct label from the detail view; that correction becomes the scoring reference for OpenAI and all local model match summaries. The per-label summary is displayed as a local-model matrix with match rate, matched/classified record count, and average confidence score per label. Structured output parsing accepts plain JSON and markdown-fenced JSON, including `reasoning`, `rationale`, `reason`, or `explanation` fields.
