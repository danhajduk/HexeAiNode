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
    select_runtime
    compose pull
    ;;
  create)
    prepare_runtime_dirs
    select_runtime
    compose up --no-start
    ;;
  start)
    prepare_runtime_dirs
    rm -f "$LLAMACPP_VISION_SOCKET_PATH" "$LLAMACPP_VISION_HEALTH_SOCKET"
    select_runtime
    compose up -d --force-recreate
    start_health_wrapper
    ;;
  stop)
    compose down
    pkill -f "scripts/llamacpp-health.py.*${LLAMACPP_VISION_HEALTH_SOCKET}" >/dev/null 2>&1 || true
    rm -f "$LLAMACPP_VISION_SOCKET_PATH" "$LLAMACPP_VISION_HEALTH_SOCKET"
    ;;
  unload-model)
    # llama.cpp server does not currently expose a model-residency unload operation for this runtime.
    # Stop the container as the VRAM-freeing fallback while preserving one stable operator/API command.
    "$0" stop
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
    wait_ready
    ;;
  *)
    echo "Usage: $0 {build|create|start|stop|restart|status|logs|ready|unload-model}" >&2
    exit 2
    ;;
esac
