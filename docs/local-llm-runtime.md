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

## Experimental Vision Runtime

The node also includes a sibling llama.cpp vision runtime for local image analysis experiments. It uses a separate
container, socket, cache, and health wrapper so the default text LLM can remain unchanged while vision support is tested.

Default vision target:

- model: `ggml-org/Qwen2.5-VL-3B-Instruct-GGUF:Q4_K_M`
- alias: `qwen2.5-vl-3b-instruct-q4_k_m`
- socket: `/run/hexe/ai-node/llamacpp-vision.sock`
- health socket: `/run/hexe/ai-node/llamacpp-vision-health.sock`
- container: `hexe-ai-node-llamacpp-vision`

```bash
scripts/llamacpp-vision-control.sh build
scripts/llamacpp-vision-control.sh create
scripts/llamacpp-vision-control.sh start
scripts/llamacpp-vision-control.sh ready
scripts/llamacpp-vision-control.sh status
scripts/llamacpp-vision-control.sh logs
scripts/llamacpp-vision-control.sh unload-model
scripts/llamacpp-vision-control.sh stop
```

Do not run the vision runtime concurrently with image generation on the 12 GB GPU unless an operator has verified
available VRAM. The first-pass vision runtime keeps `--parallel 1` and an 8192 context by default.

The vision runtime is resident by default. `HEXE_VISION_LLM_ALWAYS_ON_ENABLED=true` lets the node periodically start
the vision container and wait for the default model when no local work is in flight. Set
`HEXE_VISION_LLM_ALWAYS_ON_ENABLED=false` for maintenance windows or when GPU image generation should keep the VRAM.
The check interval is controlled by `HEXE_VISION_LLM_RESIDENCY_CHECK_INTERVAL_SECONDS` and defaults to 60 seconds.
Service status includes `services.vision_llm.residency`, which distinguishes `container_stopped`, `model_loading`,
`container_running_model_unloaded`, and `model_loaded`.

`scripts/llamacpp-vision-control.sh unload-model` is the stable unload entry point. The pinned llama.cpp server loads
the model as part of the server process and does not expose a process-resident model unload operation, so this command
currently uses a `container_stop_fallback` that frees VRAM by stopping the vision container and health wrapper. The
node reports `unload_model_supported: false` and `unload_model_mode: container_stop_fallback` until a true model unload
primitive is available.

## Experimental Image Generation Runtimes

The node includes one ComfyUI container with two ComfyUI server processes for local image generation experiments. The
container is intentionally separate from the text and vision llama.cpp runtimes because diffusion models place different
pressure on VRAM and model storage.

GPU ComfyUI target:

- image: `hexe-ai-node-comfyui:local`
- container: `hexe-ai-node-comfyui`
- API socket: `/run/hexe/ai-node/comfyui-gpu.sock`
- health socket: `/run/hexe/ai-node/comfyui-gpu-health.sock`
- runtime base: CUDA 12.1 / PyTorch cu121 for compatibility with the NVIDIA 535 driver
- models: `runtime/models/comfyui-gpu`
- input: `runtime/input/comfyui-gpu`
- output: `runtime/output/comfyui-gpu`
- checkpoint target: `RealVisXL_V5.0_fp16.safetensors`
- LoRA target: `sdxl_lightning_4step_lora.safetensors`

CPU ComfyUI target:

- image: `hexe-ai-node-comfyui:local`
- container: `hexe-ai-node-comfyui`
- API socket: `/run/hexe/ai-node/comfyui-cpu.sock`
- health socket: `/run/hexe/ai-node/comfyui-cpu-health.sock`
- runtime mode: `--cpu`
- models: `runtime/models/comfyui-cpu`
- input: `runtime/input/comfyui-cpu`
- output: `runtime/output/comfyui-cpu`
- checkpoint target: `DreamShaper8_LCM.safetensors`

```bash
scripts/comfyui-control.sh gpu prepare
scripts/comfyui-control.sh gpu gate
scripts/comfyui-control.sh gpu build
scripts/comfyui-control.sh gpu ready
scripts/comfyui-control.sh gpu status
scripts/comfyui-control.sh gpu logs
scripts/comfyui-control.sh gpu stop

scripts/comfyui-control.sh cpu prepare
scripts/comfyui-control.sh cpu ready
scripts/comfyui-control.sh cpu status
scripts/comfyui-control.sh cpu logs
scripts/comfyui-control.sh cpu stop

scripts/comfyui-control.sh all status
```

For compatibility, `scripts/comfyui-control.sh ready` still defaults to the GPU readiness check, but the managed
container starts both runtime processes together. Both processes start with `--disable-auto-launch` and without a
startup checkpoint argument; checkpoints and LoRAs should be loaded by the request workflow unless a future explicit
keep-warm policy is enabled. During directory preparation, the control script creates per-runtime model folders and
symlinks the expected checkpoint/LoRA from the legacy `runtime/models/comfyui` folder when the file is already present.
ComfyUI no longer publishes host HTTP ports by default. The container keeps HTTP bound internally for ComfyUI itself,
then exposes API and health access through Unix sockets under `/run/hexe/ai-node`. The health sockets serve `/health`;
the API sockets forward regular ComfyUI HTTP API calls such as `/system_stats`, `/prompt`, and `/history`.

The node service can expose a temporary manual Web UI bridge when requested through service control:

```bash
GET /api/services/comfyui-webui/preflight
POST /api/services/start {"target":"comfyui_webui"}
POST /api/services/stop {"target":"comfyui_webui"}
```

The bridge defaults to `http://localhost:18188` and forwards local TCP traffic to the configured ComfyUI Unix socket.
`GET /api/services/status` reports the `comfyui_webui` service with its runtime, URL, socket path, and pid file. This
does not publish the ComfyUI container port; LAN-wide exposure requires changing `HEXE_COMFYUI_WEBUI_HOST` explicitly.
The node writes `.run/comfyui-webui-session.json` while a manual session is starting, active, closing, or restoring;
the vision residency scheduler treats that marker as `blocked_by_manual_comfyui_webui` and will not reload vision during
the manual GPU takeover. Stopping `comfyui_webui` closes the bridge, stops ComfyUI, waits for the runtime sockets to
disappear, and only then clears the manual session marker.

Before the manual bridge starts, the node checks the local execution queue for active or queued vision work
(`task.vision_analysis`, image description, object detection, and document OCR). If any local vision work is present,
manual ComfyUI takeover is rejected with `vision_work_pending` and the preflight payload lists the blocking jobs. The
preflight also reports queued cloud-reroute candidates, but already-enqueued jobs are not rewritten automatically because
the current queue runner cannot safely rebind an executable local runner into a cloud runner after admission.

While the manual session is active, the node polls ComfyUI `/queue` through the Unix socket. Non-empty
`queue_running` or `queue_pending` resets the idle timer. Once the queue is empty for
`HEXE_COMFYUI_WEBUI_IDLE_TIMEOUT_SECONDS` seconds, default `300`, the `comfyui_webui_idle_close` scheduler job closes the
manual Web UI session. `GET /api/services/status` includes `comfyui_webui.session.idle_seconds`,
`idle_timeout_seconds`, and `auto_close_at_epoch` for UI countdowns. Idle auto-close shuts down the Web UI bridge,
stops ComfyUI, waits for the ComfyUI sockets to disappear, clears the manual session marker, and then calls the normal
vision residency path to reload the vision runtime when enabled.

Example socket probes:

```bash
curl --unix-socket /run/hexe/ai-node/comfyui-gpu-health.sock http://comfyui/health
curl --unix-socket /run/hexe/ai-node/comfyui-cpu.sock http://comfyui/system_stats
```

GPU ComfyUI startup is gated on vision VRAM release by default. Before `scripts/comfyui-control.sh gpu start` or
`ready` recreates the GPU container, the control script checks the vision socket/container, calls
`scripts/llamacpp-vision-control.sh unload-model` when vision is resident, and waits until the vision sockets/container
are gone. Gate latency is written to `.run/comfyui-gpu-vision-gate.json` as `vision_unload_seconds`; the later reload is
tracked separately by the vision residency scheduler, so the artifact keeps `vision_reload_pending: true` after an
unload. Set `COMFYUI_GPU_VISION_GATE_ENABLED=false` only for manual maintenance.

Vision has higher residency priority than GPU ComfyUI when ComfyUI is idle or only has a non-critical workload. The
vision residency scheduler reloads the vision model when no local work is in flight and only defers to GPU ComfyUI
when a critical GPU image-generation job is queued or running.

CPU ComfyUI is reserved for low-priority background image work. The direct execution queue exposes a `cpu_comfyui` lane
with concurrency `HEXE_COMFYUI_CPU_QUEUE_CONCURRENCY` defaulting to 1. Only `task.image_generation` or
`task.generation.image` requests with `priority: "background"` or `priority: "low"` are eligible for that lane; normal
and high-priority image work stays off the CPU ComfyUI queue. Queue diagnostics include `queues.cpu_comfyui` with
queued depth, active job, and oldest queued age.

GPU presets live in `config/comfyui-gpu-presets.json` and are exposed through:

```text
GET /api/comfyui/gpu/presets
GET /api/comfyui/gpu/presets/{preset_id}
```

The preset catalog is based on the RealVisXL checkpoint plus `sdxl_lightning_4step_lora.safetensors`. Each preset
declares seed behavior, steps, CFG, sampler, scheduler, resolution, batch size, and denoise settings. Presets are
general GPU ComfyUI generation configs; prompt text is supplied by the request workflow.

Local task-to-runtime assignments are exposed through:

```text
GET /api/local-runtimes/assignments
GET /api/local-runtimes/assignments/{task_family}?priority=normal
```

Text tasks map to the always-on local llama.cpp text runtime and default to `qwen3-8b-q4_k_m`. Vision tasks map to
the resident vision llama.cpp runtime and default to `qwen2.5-vl-3b-instruct-q4_k_m`. Interactive image generation
maps to GPU ComfyUI with RealVisXL plus SDXL-Lightning presets; low-priority and background image generation maps to
CPU ComfyUI with DreamShaper. Direct execution route previews include `local_runtime_assignment` so operators can
confirm the selected runtime, model/checkpoint, queue, and policy before queuing work.

On the RTX 3060 12 GB node, ComfyUI should be treated as exclusive GPU work for real generation. With both llama.cpp
runtimes loaded, only about 2.5 GB VRAM remains, which is not enough for typical SDXL, FLUX, or Stable Diffusion 3.5
workflows. Stop `hexe-ai-node-llamacpp-vision` before lightweight generation, and stop both llama.cpp containers before
testing heavier workflows.

Measured with both llama.cpp runtimes loaded, an idle ComfyUI service adds about 102 MiB VRAM and reports healthy, but
that is only the UI/runtime process before a diffusion checkpoint is loaded.

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

The local text LLM is always-on by default. `HEXE_LOCAL_LLM_ALWAYS_ON_ENABLED=true` makes the node periodically check
the llama.cpp sockets and start the configured default model when the runtime is not ready. Set
`HEXE_LOCAL_LLM_ALWAYS_ON_ENABLED=false` for maintenance windows where the text LLM should remain offline. The check
interval is controlled by `HEXE_LOCAL_LLM_ALWAYS_ON_CHECK_INTERVAL_SECONDS` and defaults to 60 seconds. Service status
includes `services.local_llm.always_on`, which reports whether the policy is enabled, whether the default model is
loaded, whether a start is due, and why no action was taken.

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
