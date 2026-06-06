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

export COMFYUI_IMAGE="${COMFYUI_IMAGE:-hexe-ai-node-comfyui:local}"
export COMFYUI_REF="${COMFYUI_REF:-master}"
export COMFYUI_HOST="${COMFYUI_HOST:-127.0.0.1}"
export COMFYUI_READY_TIMEOUT_S="${COMFYUI_READY_TIMEOUT_S_OVERRIDE:-${COMFYUI_READY_TIMEOUT_S:-240}}"

export COMFYUI_GPU_CONTAINER_NAME="${COMFYUI_GPU_CONTAINER_NAME:-hexe-ai-node-comfyui-gpu}"
export COMFYUI_GPU_HOST="${COMFYUI_GPU_HOST:-$COMFYUI_HOST}"
export COMFYUI_GPU_PORT="${COMFYUI_GPU_PORT:-8188}"
export COMFYUI_GPU_MODEL_DIR="${COMFYUI_GPU_MODEL_DIR:-$ROOT_DIR/runtime/models/comfyui-gpu}"
export COMFYUI_GPU_INPUT_DIR="${COMFYUI_GPU_INPUT_DIR:-$ROOT_DIR/runtime/input/comfyui-gpu}"
export COMFYUI_GPU_OUTPUT_DIR="${COMFYUI_GPU_OUTPUT_DIR:-$ROOT_DIR/runtime/output/comfyui-gpu}"
export COMFYUI_GPU_USER_DIR="${COMFYUI_GPU_USER_DIR:-$ROOT_DIR/runtime/user/comfyui-gpu}"
export COMFYUI_GPU_CACHE_DIR="${COMFYUI_GPU_CACHE_DIR:-$ROOT_DIR/runtime/cache/comfyui-gpu}"
export COMFYUI_GPU_CHECKPOINT="${COMFYUI_GPU_CHECKPOINT:-RealVisXL_V5.0_fp16.safetensors}"
export COMFYUI_GPU_LORA="${COMFYUI_GPU_LORA:-sdxl_lightning_4step_lora.safetensors}"
export COMFYUI_GPU_ARGS="${COMFYUI_GPU_ARGS:---listen 0.0.0.0 --port 8188 --disable-auto-launch}"

export COMFYUI_CPU_CONTAINER_NAME="${COMFYUI_CPU_CONTAINER_NAME:-hexe-ai-node-comfyui-cpu}"
export COMFYUI_CPU_HOST="${COMFYUI_CPU_HOST:-$COMFYUI_HOST}"
export COMFYUI_CPU_PORT="${COMFYUI_CPU_PORT:-8189}"
export COMFYUI_CPU_MODEL_DIR="${COMFYUI_CPU_MODEL_DIR:-$ROOT_DIR/runtime/models/comfyui-cpu}"
export COMFYUI_CPU_INPUT_DIR="${COMFYUI_CPU_INPUT_DIR:-$ROOT_DIR/runtime/input/comfyui-cpu}"
export COMFYUI_CPU_OUTPUT_DIR="${COMFYUI_CPU_OUTPUT_DIR:-$ROOT_DIR/runtime/output/comfyui-cpu}"
export COMFYUI_CPU_USER_DIR="${COMFYUI_CPU_USER_DIR:-$ROOT_DIR/runtime/user/comfyui-cpu}"
export COMFYUI_CPU_CACHE_DIR="${COMFYUI_CPU_CACHE_DIR:-$ROOT_DIR/runtime/cache/comfyui-cpu}"
export COMFYUI_CPU_CHECKPOINT="${COMFYUI_CPU_CHECKPOINT:-DreamShaper8_LCM.safetensors}"
export COMFYUI_CPU_ARGS="${COMFYUI_CPU_ARGS:---cpu --listen 0.0.0.0 --port 8188 --disable-auto-launch}"

COMFYUI_LEGACY_MODEL_DIR="${COMFYUI_LEGACY_MODEL_DIR:-$ROOT_DIR/runtime/models/comfyui}"
COMFYUI_CUDA_MODE="${COMFYUI_CUDA_MODE:-auto}"
COMFYUI_CUDA_SMOKE_IMAGE="${COMFYUI_CUDA_SMOKE_IMAGE:-nvidia/cuda:12.4.1-base-ubuntu22.04}"
COMFYUI_CUDA_CHECK_TIMEOUT_S="${COMFYUI_CUDA_CHECK_TIMEOUT_S:-45}"

target="${1:-gpu}"
command="${2:-}"
if [[ -z "$command" ]]; then
  command="$target"
  target="gpu"
fi

case "$target" in
  gpu|cpu|all) ;;
  *)
    echo "Invalid ComfyUI target '$target'. Expected gpu, cpu, or all." >&2
    exit 2
    ;;
esac

service_name() {
  case "$1" in
    gpu) printf 'comfyui-gpu' ;;
    cpu) printf 'comfyui-cpu' ;;
  esac
}

target_host() {
  case "$1" in
    gpu) printf '%s' "$COMFYUI_GPU_HOST" ;;
    cpu) printf '%s' "$COMFYUI_CPU_HOST" ;;
  esac
}

target_port() {
  case "$1" in
    gpu) printf '%s' "$COMFYUI_GPU_PORT" ;;
    cpu) printf '%s' "$COMFYUI_CPU_PORT" ;;
  esac
}

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

link_model_file() {
  local source_dir="$1"
  local target_dir="$2"
  local filename="$3"
  if [[ -z "$filename" ]]; then
    return
  fi
  mkdir -p "$target_dir"
  if [[ -e "$target_dir/$filename" ]]; then
    return
  fi
  if [[ -f "$source_dir/$filename" ]]; then
    ln -s "$source_dir/$filename" "$target_dir/$filename"
  fi
}

prepare_gpu_runtime_dirs() {
  mkdir -p "$COMFYUI_GPU_MODEL_DIR/checkpoints" "$COMFYUI_GPU_MODEL_DIR/loras"
  mkdir -p "$COMFYUI_GPU_INPUT_DIR" "$COMFYUI_GPU_OUTPUT_DIR" "$COMFYUI_GPU_USER_DIR" "$COMFYUI_GPU_CACHE_DIR"
  link_model_file "$COMFYUI_LEGACY_MODEL_DIR/checkpoints" "$COMFYUI_GPU_MODEL_DIR/checkpoints" "$COMFYUI_GPU_CHECKPOINT"
  link_model_file "$COMFYUI_LEGACY_MODEL_DIR/loras" "$COMFYUI_GPU_MODEL_DIR/loras" "$COMFYUI_GPU_LORA"
}

prepare_cpu_runtime_dirs() {
  mkdir -p "$COMFYUI_CPU_MODEL_DIR/checkpoints" "$COMFYUI_CPU_MODEL_DIR/loras"
  mkdir -p "$COMFYUI_CPU_INPUT_DIR" "$COMFYUI_CPU_OUTPUT_DIR" "$COMFYUI_CPU_USER_DIR" "$COMFYUI_CPU_CACHE_DIR"
  link_model_file "$COMFYUI_LEGACY_MODEL_DIR/checkpoints" "$COMFYUI_CPU_MODEL_DIR/checkpoints" "$COMFYUI_CPU_CHECKPOINT"
}

prepare_runtime_dirs() {
  case "$1" in
    gpu) prepare_gpu_runtime_dirs ;;
    cpu) prepare_cpu_runtime_dirs ;;
    all)
      prepare_gpu_runtime_dirs
      prepare_cpu_runtime_dirs
      ;;
  esac
}

select_runtime() {
  local mode
  if [[ "$1" == "cpu" ]]; then
    echo "ComfyUI CPU runtime: GPU passthrough disabled"
    return
  fi
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
  local runtime="$1"
  curl -fsS "http://$(target_host "$runtime"):$(target_port "$runtime")/system_stats"
}

wait_ready() {
  local runtime="$1"
  local deadline
  deadline=$((SECONDS + ${COMFYUI_READY_TIMEOUT_S:-240}))
  while (( SECONDS < deadline )); do
    if health_probe "$runtime" >/dev/null 2>&1; then
      health_probe "$runtime"
      return 0
    fi
    sleep "${COMFYUI_READY_INTERVAL_S:-2}"
  done
  echo "ComfyUI $runtime runtime did not become ready before timeout" >&2
  return 1
}

each_target() {
  if [[ "$target" == "all" ]]; then
    printf 'gpu\ncpu\n'
  else
    printf '%s\n' "$target"
  fi
}

case "$command" in
  prepare)
    prepare_runtime_dirs "$target"
    ;;
  build)
    prepare_runtime_dirs "$target"
    for runtime in $(each_target); do
      select_runtime "$runtime"
    done
    if [[ "$target" == "all" ]]; then
      compose build
    else
      compose build "$(service_name "$target")"
    fi
    ;;
  create)
    prepare_runtime_dirs "$target"
    for runtime in $(each_target); do
      select_runtime "$runtime"
      compose up --no-start "$(service_name "$runtime")"
    done
    ;;
  start)
    prepare_runtime_dirs "$target"
    for runtime in $(each_target); do
      select_runtime "$runtime"
      compose up -d --force-recreate "$(service_name "$runtime")"
    done
    ;;
  stop)
    if [[ "$target" == "all" ]]; then
      compose down
    else
      compose stop "$(service_name "$target")"
      compose rm -f "$(service_name "$target")"
    fi
    ;;
  restart)
    "$0" "$target" stop
    "$0" "$target" start
    ;;
  status)
    if [[ "$target" == "all" ]]; then
      compose ps
      health_probe gpu || true
      health_probe cpu || true
    else
      compose ps "$(service_name "$target")"
      health_probe "$target" || true
    fi
    ;;
  logs)
    if [[ "$target" == "all" ]]; then
      compose logs --tail "${COMFYUI_LOG_TAIL:-100}" comfyui-gpu comfyui-cpu
    else
      compose logs --tail "${COMFYUI_LOG_TAIL:-100}" "$(service_name "$target")"
    fi
    ;;
  ready)
    "$0" "$target" start
    for runtime in $(each_target); do
      wait_ready "$runtime"
    done
    ;;
  *)
    echo "Usage: $0 [gpu|cpu|all] {prepare|build|create|start|stop|restart|status|logs|ready}" >&2
    echo "       $0 {prepare|build|create|start|stop|restart|status|logs|ready}  # defaults to gpu" >&2
    exit 2
    ;;
esac
