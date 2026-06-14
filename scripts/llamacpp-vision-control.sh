#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${LLAMACPP_VISION_ENV_FILE:-$ROOT_DIR/scripts/stack.env}"
COMPOSE_FILE="$ROOT_DIR/compose.llamacpp-vision.yaml"
DOCKER_BIN="${DOCKER_BIN:-docker}"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"
LLAMACPP_VISION_MODEL_HF_OVERRIDE="${LLAMACPP_VISION_MODEL_HF:-}"
LLAMACPP_VISION_MODEL_ALIAS_OVERRIDE="${LLAMACPP_VISION_MODEL_ALIAS:-}"
LLAMACPP_VISION_CTX_SIZE_OVERRIDE="${LLAMACPP_VISION_CTX_SIZE:-}"
LLAMACPP_VISION_N_GPU_LAYERS_OVERRIDE="${LLAMACPP_VISION_N_GPU_LAYERS:-}"
LLAMACPP_VISION_PARALLEL_OVERRIDE="${LLAMACPP_VISION_PARALLEL:-}"
LLAMACPP_VISION_READY_TIMEOUT_S_OVERRIDE="${LLAMACPP_VISION_READY_TIMEOUT_S:-}"

if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  . "$ENV_FILE"
fi

export LLAMACPP_VISION_CONTAINER_NAME="${LLAMACPP_VISION_CONTAINER_NAME:-hexe-ai-node-llamacpp-vision}"
export LLAMACPP_VISION_IMAGE="${LLAMACPP_VISION_IMAGE:-ghcr.io/ggml-org/llama.cpp:server-cuda-b7869}"
export LLAMACPP_VISION_MODEL_HF="${LLAMACPP_VISION_MODEL_HF_OVERRIDE:-${LLAMACPP_VISION_MODEL_HF:-ggml-org/Qwen2.5-VL-3B-Instruct-GGUF:Q4_K_M}}"
export LLAMACPP_VISION_MODEL_ALIAS="${LLAMACPP_VISION_MODEL_ALIAS_OVERRIDE:-${LLAMACPP_VISION_MODEL_ALIAS:-qwen2.5-vl-3b-instruct-q4_k_m}}"
export LLAMACPP_VISION_MODEL_DIR="${LLAMACPP_VISION_MODEL_DIR:-$ROOT_DIR/runtime/models/llamacpp-vision}"
export LLAMACPP_VISION_CACHE_DIR="${LLAMACPP_VISION_CACHE_DIR:-$ROOT_DIR/runtime/cache/llamacpp-vision}"
export LLAMACPP_VISION_MODELS_PRESET_HOST_PATH="${LLAMACPP_VISION_MODELS_PRESET_HOST_PATH:-$LLAMACPP_VISION_CACHE_DIR/models.ini}"
export LLAMACPP_VISION_MODELS_PRESET_PATH="${LLAMACPP_VISION_MODELS_PRESET_PATH:-/cache/models.ini}"
export LLAMACPP_VISION_MODELS_MAX="${LLAMACPP_VISION_MODELS_MAX:-1}"
export LLAMACPP_VISION_SOCKET_DIR="${LLAMACPP_VISION_SOCKET_DIR:-/run/hexe/ai-node}"
export LLAMACPP_VISION_SOCKET_PATH="${LLAMACPP_VISION_SOCKET_PATH:-$LLAMACPP_VISION_SOCKET_DIR/llamacpp-vision.sock}"
export LLAMACPP_VISION_HEALTH_SOCKET="${LLAMACPP_VISION_HEALTH_SOCKET:-$LLAMACPP_VISION_SOCKET_DIR/llamacpp-vision-health.sock}"
export LLAMACPP_VISION_CTX_SIZE="${LLAMACPP_VISION_CTX_SIZE_OVERRIDE:-${LLAMACPP_VISION_CTX_SIZE:-8192}}"
export LLAMACPP_VISION_N_GPU_LAYERS="${LLAMACPP_VISION_N_GPU_LAYERS_OVERRIDE:-${LLAMACPP_VISION_N_GPU_LAYERS:-99}}"
export LLAMACPP_VISION_PARALLEL="${LLAMACPP_VISION_PARALLEL_OVERRIDE:-${LLAMACPP_VISION_PARALLEL:-1}}"
export LLAMACPP_VISION_READY_TIMEOUT_S="${LLAMACPP_VISION_READY_TIMEOUT_S_OVERRIDE:-${LLAMACPP_VISION_READY_TIMEOUT_S:-240}}"
export LLAMACPP_VISION_LD_PRELOAD="${LLAMACPP_VISION_LD_PRELOAD:-/usr/lib/x86_64-linux-gnu/nvidia/current/libcuda.so.1}"
export LLAMACPP_VISION_UID="${LLAMACPP_VISION_UID:-$(id -u)}"
export LLAMACPP_VISION_GID="${LLAMACPP_VISION_GID:-$(id -g)}"
LLAMACPP_VISION_CUDA_MODE="${LLAMACPP_VISION_CUDA_MODE:-auto}"
LLAMACPP_VISION_CUDA_SMOKE_IMAGE="${LLAMACPP_VISION_CUDA_SMOKE_IMAGE:-nvidia/cuda:12.4.1-base-ubuntu22.04}"
LLAMACPP_VISION_CUDA_CHECK_TIMEOUT_S="${LLAMACPP_VISION_CUDA_CHECK_TIMEOUT_S:-45}"

compose() {
  if "$DOCKER_BIN" compose version >/dev/null 2>&1; then
    "$DOCKER_BIN" compose -f "$COMPOSE_FILE" "$@"
    return
  fi
  if command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_PROJECT_NAME=hexe-ai-node-llamacpp-vision docker-compose -f "$COMPOSE_FILE" "$@"
    return
  fi
  "$DOCKER_BIN" compose -f "$COMPOSE_FILE" "$@"
}

truthy() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

cuda_mode() {
  if truthy "${LLAMACPP_VISION_FORCE_CPU:-}"; then
    printf 'cpu'
    return
  fi
  if truthy "${LLAMACPP_VISION_FORCE_CUDA:-}"; then
    printf 'cuda'
    return
  fi
  case "${LLAMACPP_VISION_CUDA_MODE,,}" in
    auto|cpu|cuda|skip) printf '%s' "${LLAMACPP_VISION_CUDA_MODE,,}" ;;
    *)
      echo "Invalid LLAMACPP_VISION_CUDA_MODE=$LLAMACPP_VISION_CUDA_MODE. Expected auto, cpu, cuda, or skip." >&2
      return 2
      ;;
  esac
}

cuda_smoke_check() {
  timeout "${LLAMACPP_VISION_CUDA_CHECK_TIMEOUT_S}s" "$DOCKER_BIN" run --rm --gpus all "$LLAMACPP_VISION_CUDA_SMOKE_IMAGE" nvidia-smi >/dev/null
}

prepare_runtime_dirs() {
  mkdir -p "$LLAMACPP_VISION_MODEL_DIR"
  mkdir -p "$LLAMACPP_VISION_CACHE_DIR"
  mkdir -p "$LLAMACPP_VISION_SOCKET_DIR"
  mkdir -p "$ROOT_DIR/.run"
}

write_models_preset() {
  "$PYTHON_BIN" - "$LLAMACPP_VISION_MODELS_PRESET_HOST_PATH" <<'PY'
from __future__ import annotations

import os
import sys
from pathlib import Path

preset_path = Path(sys.argv[1])
preset_path.parent.mkdir(parents=True, exist_ok=True)
alias = os.environ["LLAMACPP_VISION_MODEL_ALIAS"].strip()
hf_repo = os.environ["LLAMACPP_VISION_MODEL_HF"].strip()
ctx_size = os.environ["LLAMACPP_VISION_CTX_SIZE"].strip()
n_gpu_layers = os.environ["LLAMACPP_VISION_N_GPU_LAYERS"].strip()
parallel = os.environ["LLAMACPP_VISION_PARALLEL"].strip()
body = "\n".join(
    [
        f"[{alias}]",
        f"hf-repo = {hf_repo}",
        f"ctx-size = {ctx_size}",
        f"n-gpu-layers = {n_gpu_layers}",
        f"parallel = {parallel}",
        "",
    ]
)
preset_path.write_text(body, encoding="utf-8")
PY
}

select_runtime() {
  local mode
  mode="$(cuda_mode)"
  case "$mode" in
    cpu|skip)
      echo "llama.cpp vision CUDA detection: using configured CPU/skip mode"
      ;;
    cuda)
      cuda_smoke_check
      ;;
    auto)
      if cuda_smoke_check; then
        echo "llama.cpp vision CUDA detection: Docker GPU passthrough available"
      else
        echo "llama.cpp vision CUDA detection: Docker GPU passthrough unavailable; continuing with image defaults" >&2
      fi
      ;;
  esac
}

container_running() {
  [[ "$("$DOCKER_BIN" inspect --format '{{.State.Running}}' "$LLAMACPP_VISION_CONTAINER_NAME" 2>/dev/null || true)" == "true" ]]
}

start_health_wrapper() {
  if [[ "${LLAMACPP_VISION_HEALTH_WRAPPER:-1}" == "0" ]]; then
    return
  fi
  if pgrep -f "scripts/llamacpp-health.py.*${LLAMACPP_VISION_HEALTH_SOCKET}" >/dev/null 2>&1 && [[ -S "$LLAMACPP_VISION_HEALTH_SOCKET" ]]; then
    return
  fi
  pkill -f "scripts/llamacpp-health.py.*${LLAMACPP_VISION_HEALTH_SOCKET}" >/dev/null 2>&1 || true
  if [[ -S "$LLAMACPP_VISION_HEALTH_SOCKET" ]]; then
    rm -f "$LLAMACPP_VISION_HEALTH_SOCKET"
  fi
  setsid nohup "$PYTHON_BIN" "$ROOT_DIR/scripts/llamacpp-health.py" \
    --socket-path "$LLAMACPP_VISION_HEALTH_SOCKET" \
    --llama-socket-path "$LLAMACPP_VISION_SOCKET_PATH" \
    --model-id "$LLAMACPP_VISION_MODEL_ALIAS" \
    >"$ROOT_DIR/.run/llamacpp-vision-health.log" 2>&1 &
}

uds_json_request() {
  local method="$1"
  local path="$2"
  local body="${3:-}"
  "$PYTHON_BIN" - "$LLAMACPP_VISION_SOCKET_PATH" "$method" "$path" "$body" <<'PY'
from __future__ import annotations

import json
import socket
import sys

socket_path, method, path, body = sys.argv[1:5]
payload = body.encode("utf-8")
headers = [
    f"{method} {path} HTTP/1.1",
    "Host: llamacpp",
    "Connection: close",
]
if payload:
    headers.extend(
        [
            "Content-Type: application/json",
            f"Content-Length: {len(payload)}",
        ]
    )
request = ("\r\n".join(headers) + "\r\n\r\n").encode("utf-8") + payload
with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
    client.settimeout(30)
    client.connect(socket_path)
    client.sendall(request)
    chunks: list[bytes] = []
    while True:
        chunk = client.recv(65536)
        if not chunk:
            break
        chunks.append(chunk)
raw = b"".join(chunks)
head, _, response_body = raw.partition(b"\r\n\r\n")
try:
    status = int(head.split(maxsplit=2)[1])
except Exception:
    print(raw.decode("utf-8", errors="replace"), file=sys.stderr)
    raise SystemExit(1)
text = response_body.decode("utf-8", errors="replace")
print(text)
if status < 200 or status >= 300:
    raise SystemExit(1)
try:
    parsed = json.loads(text) if text else {}
except Exception:
    parsed = {}
if isinstance(parsed, dict) and parsed.get("success") is False:
    raise SystemExit(1)
PY
}

wait_router() {
  local deadline
  deadline=$((SECONDS + ${LLAMACPP_VISION_READY_TIMEOUT_S:-240}))
  while (( SECONDS < deadline )); do
    if [[ -S "$LLAMACPP_VISION_SOCKET_PATH" ]] && uds_json_request GET /health >/dev/null 2>&1; then
      return 0
    fi
    sleep "${LLAMACPP_VISION_READY_INTERVAL_S:-2}"
  done
  echo "llama.cpp vision router did not become reachable before timeout" >&2
  return 1
}

load_model() {
  wait_router
  uds_json_request POST /models/load "{\"model\":\"$LLAMACPP_VISION_MODEL_ALIAS\"}" >/dev/null
}

model_status_value() {
  "$PYTHON_BIN" - "$LLAMACPP_VISION_SOCKET_PATH" "$LLAMACPP_VISION_MODEL_ALIAS" <<'PY'
from __future__ import annotations

import json
import socket
import sys

socket_path, model_id = sys.argv[1:3]
request = b"GET /v1/models HTTP/1.1\r\nHost: llamacpp\r\nConnection: close\r\n\r\n"
with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
    client.settimeout(5)
    client.connect(socket_path)
    client.sendall(request)
    chunks: list[bytes] = []
    while True:
        chunk = client.recv(65536)
        if not chunk:
            break
        chunks.append(chunk)
raw = b"".join(chunks)
_head, _sep, body = raw.partition(b"\r\n\r\n")
try:
    payload = json.loads(body.decode("utf-8")) if body else {}
except Exception:
    raise SystemExit(1)
for item in payload.get("data") or []:
    if not isinstance(item, dict) or str(item.get("id") or "").strip() != model_id:
        continue
    status = item.get("status")
    if isinstance(status, dict):
        print(str(status.get("value") or "").strip().lower())
        raise SystemExit(0)
    print("loaded")
    raise SystemExit(0)
raise SystemExit(1)
PY
}

wait_model_unloaded() {
  local deadline status
  deadline=$((SECONDS + ${LLAMACPP_VISION_UNLOAD_TIMEOUT_S:-30}))
  while (( SECONDS < deadline )); do
    status="$(model_status_value 2>/dev/null || true)"
    if [[ "$status" == "unloaded" || -z "$status" ]]; then
      return 0
    fi
    sleep "${LLAMACPP_VISION_READY_INTERVAL_S:-2}"
  done
  echo "llama.cpp vision model did not unload before timeout" >&2
  return 1
}

unload_model() {
  if [[ ! -S "$LLAMACPP_VISION_SOCKET_PATH" ]]; then
    return 0
  fi
  uds_json_request POST /models/unload "{\"model\":\"$LLAMACPP_VISION_MODEL_ALIAS\"}" >/dev/null
  wait_model_unloaded
}

health_probe() {
  "$PYTHON_BIN" - "$LLAMACPP_VISION_HEALTH_SOCKET" <<'PY'
from __future__ import annotations
import json
import socket
import sys

socket_path = sys.argv[1]
request = b"GET /health HTTP/1.1\r\nHost: health\r\nConnection: close\r\n\r\n"
with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
    client.settimeout(5)
    client.connect(socket_path)
    client.sendall(request)
    data = b""
    while True:
        chunk = client.recv(65536)
        if not chunk:
            break
        data += chunk
body = data.decode("utf-8", errors="replace").split("\r\n\r\n", 1)[-1]
print(body)
try:
    payload = json.loads(body)
except Exception:
    raise SystemExit(1)
raise SystemExit(0 if payload.get("ready") is True else 1)
PY
}

wait_ready() {
  local deadline
  deadline=$((SECONDS + ${LLAMACPP_VISION_READY_TIMEOUT_S:-240}))
  while (( SECONDS < deadline )); do
    if [[ -S "$LLAMACPP_VISION_HEALTH_SOCKET" ]] && health_probe >/dev/null 2>&1; then
      health_probe
      return 0
    fi
    sleep "${LLAMACPP_VISION_READY_INTERVAL_S:-2}"
  done
  echo "llama.cpp vision runtime did not become ready before timeout" >&2
  return 1
}

case "${1:-}" in
  build)
    prepare_runtime_dirs
    write_models_preset
    select_runtime
    compose pull
    ;;
  create)
    prepare_runtime_dirs
    write_models_preset
    select_runtime
    compose up --no-start
    ;;
  start)
    prepare_runtime_dirs
    write_models_preset
    if ! container_running; then
      rm -f "$LLAMACPP_VISION_SOCKET_PATH" "$LLAMACPP_VISION_HEALTH_SOCKET"
      select_runtime
      compose up -d --force-recreate
    fi
    start_health_wrapper
    ;;
  stop)
    compose down
    pkill -f "scripts/llamacpp-health.py.*${LLAMACPP_VISION_HEALTH_SOCKET}" >/dev/null 2>&1 || true
    rm -f "$LLAMACPP_VISION_SOCKET_PATH" "$LLAMACPP_VISION_HEALTH_SOCKET"
    ;;
  unload-model)
    unload_model
    ;;
  restart)
    "$0" stop
    "$0" start
    ;;
  status)
    compose ps
    if [[ -S "$LLAMACPP_VISION_HEALTH_SOCKET" ]]; then
      health_probe || true
    fi
    ;;
  logs)
    compose logs --tail "${LLAMACPP_VISION_LOG_TAIL:-100}" llamacpp-vision
    ;;
  ready)
    "$0" start
    load_model
    wait_ready
    ;;
  *)
    echo "Usage: $0 {build|create|start|stop|restart|status|logs|ready|unload-model}" >&2
    exit 2
    ;;
esac
