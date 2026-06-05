#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${COMFYUI_ENV_FILE:-$ROOT_DIR/scripts/stack.env}"
COMPOSE_FILE="$ROOT_DIR/compose.comfyui.yaml"
DOCKER_BIN="${DOCKER_BIN:-docker}"
COMFYUI_READY_TIMEOUT_S_OVERRIDE="${COMFYUI_READY_TIMEOUT_S:-}"

if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  . "$ENV_FILE"
fi

export COMFYUI_CONTAINER_NAME="${COMFYUI_CONTAINER_NAME:-hexe-ai-node-comfyui}"
export COMFYUI_IMAGE="${COMFYUI_IMAGE:-hexe-ai-node-comfyui:local}"
export COMFYUI_REF="${COMFYUI_REF:-master}"
export COMFYUI_HOST="${COMFYUI_HOST:-127.0.0.1}"
export COMFYUI_PORT="${COMFYUI_PORT:-8188}"
export COMFYUI_MODEL_DIR="${COMFYUI_MODEL_DIR:-$ROOT_DIR/runtime/models/comfyui}"
export COMFYUI_INPUT_DIR="${COMFYUI_INPUT_DIR:-$ROOT_DIR/runtime/input/comfyui}"
export COMFYUI_OUTPUT_DIR="${COMFYUI_OUTPUT_DIR:-$ROOT_DIR/runtime/output/comfyui}"
export COMFYUI_USER_DIR="${COMFYUI_USER_DIR:-$ROOT_DIR/runtime/user/comfyui}"
export COMFYUI_CACHE_DIR="${COMFYUI_CACHE_DIR:-$ROOT_DIR/runtime/cache/comfyui}"
export COMFYUI_READY_TIMEOUT_S="${COMFYUI_READY_TIMEOUT_S_OVERRIDE:-${COMFYUI_READY_TIMEOUT_S:-240}}"
COMFYUI_CUDA_MODE="${COMFYUI_CUDA_MODE:-auto}"
COMFYUI_CUDA_SMOKE_IMAGE="${COMFYUI_CUDA_SMOKE_IMAGE:-nvidia/cuda:12.4.1-base-ubuntu22.04}"
COMFYUI_CUDA_CHECK_TIMEOUT_S="${COMFYUI_CUDA_CHECK_TIMEOUT_S:-45}"

compose() {
  if "$DOCKER_BIN" compose version >/dev/null 2>&1; then
    "$DOCKER_BIN" compose -f "$COMPOSE_FILE" "$@"
    return
  fi
  if command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_PROJECT_NAME=hexe-ai-node-comfyui docker-compose -f "$COMPOSE_FILE" "$@"
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
  if truthy "${COMFYUI_FORCE_CPU:-}"; then
    printf 'cpu'
    return
  fi
  if truthy "${COMFYUI_FORCE_CUDA:-}"; then
    printf 'cuda'
    return
  fi
  case "${COMFYUI_CUDA_MODE,,}" in
    auto|cpu|cuda|skip) printf '%s' "${COMFYUI_CUDA_MODE,,}" ;;
    *)
      echo "Invalid COMFYUI_CUDA_MODE=$COMFYUI_CUDA_MODE. Expected auto, cpu, cuda, or skip." >&2
      return 2
      ;;
  esac
}

cuda_smoke_check() {
  timeout "${COMFYUI_CUDA_CHECK_TIMEOUT_S}s" "$DOCKER_BIN" run --rm --gpus all "$COMFYUI_CUDA_SMOKE_IMAGE" nvidia-smi >/dev/null
}

prepare_runtime_dirs() {
  mkdir -p "$COMFYUI_MODEL_DIR"
  mkdir -p "$COMFYUI_INPUT_DIR"
  mkdir -p "$COMFYUI_OUTPUT_DIR"
  mkdir -p "$COMFYUI_USER_DIR"
  mkdir -p "$COMFYUI_CACHE_DIR"
}

select_runtime() {
  local mode
  mode="$(cuda_mode)"
  case "$mode" in
    cpu|skip)
      echo "ComfyUI CUDA detection: using configured CPU/skip mode"
      ;;
    cuda)
      cuda_smoke_check
      ;;
    auto)
      if cuda_smoke_check; then
        echo "ComfyUI CUDA detection: Docker GPU passthrough available"
      else
        echo "ComfyUI CUDA detection: Docker GPU passthrough unavailable; continuing with image defaults" >&2
      fi
      ;;
  esac
}

health_probe() {
  curl -fsS "http://${COMFYUI_HOST}:${COMFYUI_PORT}/system_stats"
}

wait_ready() {
  local deadline
  deadline=$((SECONDS + ${COMFYUI_READY_TIMEOUT_S:-240}))
  while (( SECONDS < deadline )); do
    if health_probe >/dev/null 2>&1; then
      health_probe
      return 0
    fi
    sleep "${COMFYUI_READY_INTERVAL_S:-2}"
  done
  echo "ComfyUI runtime did not become ready before timeout" >&2
  return 1
}

case "${1:-}" in
  build)
    prepare_runtime_dirs
    select_runtime
    compose build
    ;;
  create)
    prepare_runtime_dirs
    select_runtime
    compose up --no-start
    ;;
  start)
    prepare_runtime_dirs
    select_runtime
    compose up -d --force-recreate
    ;;
  stop)
    compose down
    ;;
  restart)
    "$0" stop
    "$0" start
    ;;
  status)
    compose ps
    health_probe || true
    ;;
  logs)
    compose logs --tail "${COMFYUI_LOG_TAIL:-100}" comfyui
    ;;
  ready)
    "$0" start
    wait_ready
    ;;
  *)
    echo "Usage: $0 {build|create|start|stop|restart|status|logs|ready}" >&2
    exit 2
    ;;
esac
