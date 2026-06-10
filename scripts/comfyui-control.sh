#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${COMFYUI_ENV_FILE:-$ROOT_DIR/scripts/stack.env}"
COMPOSE_FILE="$ROOT_DIR/compose.comfyui.yaml"
DOCKER_BIN="${DOCKER_BIN:-docker}"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"
COMFYUI_READY_TIMEOUT_S_OVERRIDE="${COMFYUI_READY_TIMEOUT_S:-}"

if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  . "$ENV_FILE"
fi

export COMFYUI_IMAGE="${COMFYUI_IMAGE:-hexe-ai-node-comfyui:local}"
export COMFYUI_REF="${COMFYUI_REF:-master}"
export COMFYUI_HOST="${COMFYUI_HOST:-127.0.0.1}"
export COMFYUI_CONTAINER_NAME="${COMFYUI_CONTAINER_NAME:-hexe-ai-node-comfyui}"
export COMFYUI_READY_TIMEOUT_S="${COMFYUI_READY_TIMEOUT_S_OVERRIDE:-${COMFYUI_READY_TIMEOUT_S:-240}}"
export COMFYUI_UID="${COMFYUI_UID:-$(id -u)}"
export COMFYUI_GID="${COMFYUI_GID:-$(id -g)}"
export COMFYUI_SOCKET_DIR="${COMFYUI_SOCKET_DIR:-/run/hexe/ai-node}"

export COMFYUI_GPU_HOST="${COMFYUI_GPU_HOST:-$COMFYUI_HOST}"
export COMFYUI_GPU_PORT="${COMFYUI_GPU_PORT:-8188}"
export COMFYUI_GPU_SOCKET_PATH="${COMFYUI_GPU_SOCKET_PATH:-$COMFYUI_SOCKET_DIR/comfyui-gpu.sock}"
export COMFYUI_GPU_HEALTH_SOCKET="${COMFYUI_GPU_HEALTH_SOCKET:-$COMFYUI_SOCKET_DIR/comfyui-gpu-health.sock}"
export COMFYUI_GPU_MODEL_DIR="${COMFYUI_GPU_MODEL_DIR:-$ROOT_DIR/runtime/models/comfyui-gpu}"
export COMFYUI_GPU_CONTROLNET_DIR="${COMFYUI_GPU_CONTROLNET_DIR:-$COMFYUI_GPU_MODEL_DIR/controlnet}"
export COMFYUI_GPU_INPUT_DIR="${COMFYUI_GPU_INPUT_DIR:-$ROOT_DIR/runtime/input/comfyui-gpu}"
export COMFYUI_GPU_OUTPUT_DIR="${COMFYUI_GPU_OUTPUT_DIR:-$ROOT_DIR/runtime/output/comfyui-gpu}"
export COMFYUI_GPU_USER_DIR="${COMFYUI_GPU_USER_DIR:-$ROOT_DIR/runtime/user/comfyui-gpu}"
export COMFYUI_GPU_CUSTOM_NODES_DIR="${COMFYUI_GPU_CUSTOM_NODES_DIR:-$ROOT_DIR/runtime/custom_nodes/comfyui-gpu}"
export COMFYUI_GPU_CHECKPOINT="${COMFYUI_GPU_CHECKPOINT:-RealVisXL_V5.0_fp16.safetensors}"
export COMFYUI_GPU_LORA="${COMFYUI_GPU_LORA:-sdxl_lightning_4step_lora.safetensors}"
export COMFYUI_GPU_CONTROLNET_OPENPOSE_FILE="${COMFYUI_GPU_CONTROLNET_OPENPOSE_FILE:-controlnet-openpose-sdxl-1.0.safetensors}"
export COMFYUI_GPU_CONTROLNET_OPENPOSE_URL="${COMFYUI_GPU_CONTROLNET_OPENPOSE_URL:-https://huggingface.co/thibaud/controlnet-openpose-sdxl-1.0/resolve/main/OpenPoseXL2.safetensors}"
export COMFYUI_GPU_CONTROLNET_CANNY_FILE="${COMFYUI_GPU_CONTROLNET_CANNY_FILE:-controlnet-canny-sdxl-1.0-fp16.safetensors}"
export COMFYUI_GPU_CONTROLNET_CANNY_URL="${COMFYUI_GPU_CONTROLNET_CANNY_URL:-https://huggingface.co/diffusers/controlnet-canny-sdxl-1.0/resolve/main/diffusion_pytorch_model.fp16.safetensors}"
export COMFYUI_GPU_CONTROLNET_DEPTH_FILE="${COMFYUI_GPU_CONTROLNET_DEPTH_FILE:-controlnet-depth-sdxl-1.0-fp16.safetensors}"
export COMFYUI_GPU_CONTROLNET_DEPTH_URL="${COMFYUI_GPU_CONTROLNET_DEPTH_URL:-https://huggingface.co/diffusers/controlnet-depth-sdxl-1.0/resolve/main/diffusion_pytorch_model.fp16.safetensors}"
export COMFYUI_GPU_PULID_MODEL_FILE="${COMFYUI_GPU_PULID_MODEL_FILE:-ip-adapter_pulid_sdxl_fp16.safetensors}"
export COMFYUI_GPU_PULID_MODEL_URL="${COMFYUI_GPU_PULID_MODEL_URL:-https://huggingface.co/huchenlei/ipadapter_pulid/resolve/main/ip-adapter_pulid_sdxl_fp16.safetensors}"
export COMFYUI_GPU_INSIGHTFACE_MODEL_NAME="${COMFYUI_GPU_INSIGHTFACE_MODEL_NAME:-antelopev2}"
export COMFYUI_GPU_INSIGHTFACE_MODEL_URL="${COMFYUI_GPU_INSIGHTFACE_MODEL_URL:-https://huggingface.co/MonsterMMORPG/tools/resolve/main/antelopev2.zip}"

export COMFYUI_CPU_HOST="${COMFYUI_CPU_HOST:-$COMFYUI_HOST}"
export COMFYUI_CPU_PORT="${COMFYUI_CPU_PORT:-8189}"
export COMFYUI_CPU_SOCKET_PATH="${COMFYUI_CPU_SOCKET_PATH:-$COMFYUI_SOCKET_DIR/comfyui-cpu.sock}"
export COMFYUI_CPU_HEALTH_SOCKET="${COMFYUI_CPU_HEALTH_SOCKET:-$COMFYUI_SOCKET_DIR/comfyui-cpu-health.sock}"
export COMFYUI_CPU_MODEL_DIR="${COMFYUI_CPU_MODEL_DIR:-$ROOT_DIR/runtime/models/comfyui-cpu}"
export COMFYUI_CPU_INPUT_DIR="${COMFYUI_CPU_INPUT_DIR:-$ROOT_DIR/runtime/input/comfyui-cpu}"
export COMFYUI_CPU_OUTPUT_DIR="${COMFYUI_CPU_OUTPUT_DIR:-$ROOT_DIR/runtime/output/comfyui-cpu}"
export COMFYUI_CPU_USER_DIR="${COMFYUI_CPU_USER_DIR:-$ROOT_DIR/runtime/user/comfyui-cpu}"
export COMFYUI_CPU_CUSTOM_NODES_DIR="${COMFYUI_CPU_CUSTOM_NODES_DIR:-$ROOT_DIR/runtime/custom_nodes/comfyui-cpu}"
export COMFYUI_CPU_CHECKPOINT="${COMFYUI_CPU_CHECKPOINT:-DreamShaper8_LCM.safetensors}"
export COMFYUI_CACHE_DIR="${COMFYUI_CACHE_DIR:-$ROOT_DIR/runtime/cache/comfyui}"
export COMFYUI_ASSET_DIR="${COMFYUI_ASSET_DIR:-$ROOT_DIR/runtime/assets/comfyui}"
export COMFYUI_CONTROLNET_AUX_CKPTS_DIR="${COMFYUI_CONTROLNET_AUX_CKPTS_DIR:-$COMFYUI_ASSET_DIR/controlnet_aux/ckpts}"
export COMFYUI_CONTROLNET_AUX_TEMP_DIR="${COMFYUI_CONTROLNET_AUX_TEMP_DIR:-$COMFYUI_CACHE_DIR/controlnet_aux/temp}"

COMFYUI_LEGACY_MODEL_DIR="${COMFYUI_LEGACY_MODEL_DIR:-$ROOT_DIR/runtime/models/comfyui}"
COMFYUI_CUDA_MODE="${COMFYUI_CUDA_MODE:-auto}"
COMFYUI_CUDA_SMOKE_IMAGE="${COMFYUI_CUDA_SMOKE_IMAGE:-nvidia/cuda:12.4.1-base-ubuntu22.04}"
COMFYUI_CUDA_CHECK_TIMEOUT_S="${COMFYUI_CUDA_CHECK_TIMEOUT_S:-45}"
COMFYUI_GPU_VISION_GATE_ENABLED="${COMFYUI_GPU_VISION_GATE_ENABLED:-true}"
COMFYUI_GPU_VISION_GATE_TIMEOUT_S="${COMFYUI_GPU_VISION_GATE_TIMEOUT_S:-90}"
COMFYUI_GPU_VISION_GATE_ARTIFACT="${COMFYUI_GPU_VISION_GATE_ARTIFACT:-$ROOT_DIR/.run/comfyui-gpu-vision-gate.json}"
COMFYUI_VISION_CONTROL_SCRIPT="${COMFYUI_VISION_CONTROL_SCRIPT:-$ROOT_DIR/scripts/llamacpp-vision-control.sh}"
LLAMACPP_VISION_CONTAINER_NAME="${LLAMACPP_VISION_CONTAINER_NAME:-hexe-ai-node-llamacpp-vision}"
LLAMACPP_VISION_SOCKET_PATH="${LLAMACPP_VISION_SOCKET_PATH:-/run/hexe/ai-node/llamacpp-vision.sock}"
LLAMACPP_VISION_HEALTH_SOCKET="${LLAMACPP_VISION_HEALTH_SOCKET:-/run/hexe/ai-node/llamacpp-vision-health.sock}"

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
  printf 'comfyui'
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

target_socket() {
  case "$1" in
    gpu) printf '%s' "$COMFYUI_GPU_SOCKET_PATH" ;;
    cpu) printf '%s' "$COMFYUI_CPU_SOCKET_PATH" ;;
  esac
}

target_health_socket() {
  case "$1" in
    gpu) printf '%s' "$COMFYUI_GPU_HEALTH_SOCKET" ;;
    cpu) printf '%s' "$COMFYUI_CPU_HEALTH_SOCKET" ;;
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

remove_legacy_split_containers() {
  for legacy_name in hexe-ai-node-comfyui-gpu hexe-ai-node-comfyui-cpu; do
    if [[ "$legacy_name" != "$COMFYUI_CONTAINER_NAME" ]]; then
      "$DOCKER_BIN" rm -f "$legacy_name" >/dev/null 2>&1 || true
    fi
  done
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

now_ms() {
  "$PYTHON_BIN" - <<'PY'
import time
print(int(time.time() * 1000))
PY
}

write_vision_gate_artifact() {
  local status="$1"
  local action="$2"
  local unload_seconds="$3"
  local reason="$4"
  mkdir -p "$(dirname "$COMFYUI_GPU_VISION_GATE_ARTIFACT")"
  "$PYTHON_BIN" - "$COMFYUI_GPU_VISION_GATE_ARTIFACT" "$status" "$action" "$unload_seconds" "$reason" <<'PY'
from __future__ import annotations
import json
import sys
from datetime import datetime, timezone

path, status, action, unload_seconds_raw, reason = sys.argv[1:6]
try:
    unload_seconds = None if unload_seconds_raw == "" else round(float(unload_seconds_raw), 3)
except ValueError:
    unload_seconds = None
payload = {
    "runtime": "comfyui-gpu",
    "status": status,
    "action": action,
    "reason": reason or None,
    "vision_unload_seconds": unload_seconds,
    "vision_reload_seconds": None,
    "vision_reload_pending": status == "ok" and action == "unloaded",
    "generated_at": datetime.now(timezone.utc).isoformat(),
}
with open(path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, indent=2, sort_keys=True)
    handle.write("\n")
PY
}

vision_container_pid() {
  local raw
  raw="$("$DOCKER_BIN" inspect --format '{{.State.Pid}}' "$LLAMACPP_VISION_CONTAINER_NAME" 2>/dev/null || true)"
  case "$raw" in
    ''|*[!0-9]*) printf '0' ;;
    *) printf '%s' "$raw" ;;
  esac
}

vision_runtime_present() {
  if [[ -S "$LLAMACPP_VISION_SOCKET_PATH" || -S "$LLAMACPP_VISION_HEALTH_SOCKET" ]]; then
    return 0
  fi
  [[ "$(vision_container_pid)" != "0" ]]
}

wait_vision_unloaded() {
  local deadline
  deadline=$((SECONDS + COMFYUI_GPU_VISION_GATE_TIMEOUT_S))
  while (( SECONDS < deadline )); do
    if ! vision_runtime_present; then
      return 0
    fi
    sleep "${COMFYUI_GPU_VISION_GATE_INTERVAL_S:-1}"
  done
  return 1
}

gate_gpu_on_vision_unload() {
  if ! truthy "$COMFYUI_GPU_VISION_GATE_ENABLED"; then
    write_vision_gate_artifact "ok" "skipped" "" "disabled"
    return
  fi
  if ! vision_runtime_present; then
    write_vision_gate_artifact "ok" "not_needed" "0" "vision_not_resident"
    return
  fi
  if [[ ! -x "$COMFYUI_VISION_CONTROL_SCRIPT" ]]; then
    write_vision_gate_artifact "rejected" "failed" "" "vision_control_script_unavailable"
    echo "GPU ComfyUI gate rejected: vision control script is not executable: $COMFYUI_VISION_CONTROL_SCRIPT" >&2
    return 1
  fi
  local started_ms finished_ms unload_seconds
  started_ms="$(now_ms)"
  if ! "$COMFYUI_VISION_CONTROL_SCRIPT" unload-model; then
    write_vision_gate_artifact "rejected" "failed" "" "vision_unload_failed"
    echo "GPU ComfyUI gate rejected: vision runtime unload failed" >&2
    return 1
  fi
  if ! wait_vision_unloaded; then
    write_vision_gate_artifact "rejected" "failed" "" "vision_unload_timeout"
    echo "GPU ComfyUI gate rejected: vision runtime did not unload before timeout" >&2
    return 1
  fi
  finished_ms="$(now_ms)"
  unload_seconds="$("$PYTHON_BIN" - "$started_ms" "$finished_ms" <<'PY'
import sys
started = int(sys.argv[1])
finished = int(sys.argv[2])
print(round(max(finished - started, 0) / 1000.0, 3))
PY
)"
  write_vision_gate_artifact "ok" "unloaded" "$unload_seconds" "vision_unloaded_for_gpu_comfyui"
}

link_model_file() {
  local source_dir="$1"
  local target_dir="$2"
  local filename="$3"
  local source_path target_path
  if [[ -z "$filename" ]]; then
    return
  fi
  source_path="$source_dir/$filename"
  target_path="$target_dir/$filename"
  mkdir -p "$target_dir"
  if [[ -L "$target_path" ]]; then
    rm -f "$target_path"
  fi
  if [[ -e "$target_path" ]]; then
    return
  fi
  if [[ -f "$source_path" ]]; then
    ln "$source_path" "$target_path" 2>/dev/null || cp "$source_path" "$target_path"
  fi
}

prepare_gpu_runtime_dirs() {
  mkdir -p "$COMFYUI_GPU_MODEL_DIR/checkpoints" "$COMFYUI_GPU_MODEL_DIR/loras"
  mkdir -p "$COMFYUI_GPU_CONTROLNET_DIR" "$COMFYUI_GPU_MODEL_DIR/pulid" "$COMFYUI_GPU_MODEL_DIR/insightface/models/$COMFYUI_GPU_INSIGHTFACE_MODEL_NAME" "$COMFYUI_GPU_INPUT_DIR" "$COMFYUI_GPU_OUTPUT_DIR" "$COMFYUI_GPU_USER_DIR" "$COMFYUI_GPU_CUSTOM_NODES_DIR" "$COMFYUI_ASSET_DIR" "$COMFYUI_CONTROLNET_AUX_CKPTS_DIR" "$COMFYUI_CONTROLNET_AUX_TEMP_DIR" "$COMFYUI_SOCKET_DIR"
  link_model_file "$COMFYUI_LEGACY_MODEL_DIR/checkpoints" "$COMFYUI_GPU_MODEL_DIR/checkpoints" "$COMFYUI_GPU_CHECKPOINT"
  link_model_file "$COMFYUI_LEGACY_MODEL_DIR/loras" "$COMFYUI_GPU_MODEL_DIR/loras" "$COMFYUI_GPU_LORA"
}

prepare_cpu_runtime_dirs() {
  mkdir -p "$COMFYUI_CPU_MODEL_DIR/checkpoints" "$COMFYUI_CPU_MODEL_DIR/loras"
  mkdir -p "$COMFYUI_CPU_INPUT_DIR" "$COMFYUI_CPU_OUTPUT_DIR" "$COMFYUI_CPU_USER_DIR" "$COMFYUI_CPU_CUSTOM_NODES_DIR" "$COMFYUI_ASSET_DIR" "$COMFYUI_CONTROLNET_AUX_CKPTS_DIR" "$COMFYUI_CONTROLNET_AUX_TEMP_DIR" "$COMFYUI_SOCKET_DIR"
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
  curl -fsS --unix-socket "$(target_health_socket "$runtime")" "http://comfyui/health"
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

download_if_missing() {
  local url="$1"
  local target="$2"
  if [[ -f "$target" ]]; then
    echo "Already present: $target"
    return
  fi
  mkdir -p "$(dirname "$target")"
  echo "Downloading $(basename "$target")..."
  curl --fail --location --continue-at - --output "$target.part" "$url"
  mv "$target.part" "$target"
}

download_zip_model_if_missing() {
  local url="$1"
  local target_dir="$2"
  local model_name="$3"
  local marker="$target_dir/.hexe-downloaded"
  if [[ -f "$marker" ]]; then
    echo "Already present: $target_dir"
    return
  fi
  mkdir -p "$target_dir"
  echo "Downloading $model_name..."
  "$PYTHON_BIN" - "$url" "$target_dir" "$model_name" <<'PY'
from __future__ import annotations

import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

url, target_dir_raw, model_name = sys.argv[1:4]
target_dir = Path(target_dir_raw)
with tempfile.TemporaryDirectory() as tmp_raw:
    tmp = Path(tmp_raw)
    archive = tmp / "model.zip"
    urllib.request.urlretrieve(url, archive)
    extract_dir = tmp / "extract"
    extract_root = extract_dir.resolve()
    with zipfile.ZipFile(archive) as handle:
        for member in handle.infolist():
            destination = (extract_dir / member.filename).resolve()
            if destination != extract_root and extract_root not in destination.parents:
                raise RuntimeError(f"unsafe zip path: {member.filename}")
            handle.extract(member, extract_dir)
    candidates = [path for path in extract_dir.rglob("*") if path.is_dir() and path.name == model_name]
    source_dir = candidates[0] if candidates else extract_dir
    for child in source_dir.iterdir():
        destination = target_dir / child.name
        if child.is_dir():
            if destination.exists():
                shutil.rmtree(destination)
            shutil.copytree(child, destination)
        else:
            shutil.copy2(child, destination)
    (target_dir / ".hexe-downloaded").write_text(url + "\n", encoding="utf-8")
PY
}

download_gpu_controlnet_models() {
  prepare_gpu_runtime_dirs
  download_if_missing "$COMFYUI_GPU_CONTROLNET_OPENPOSE_URL" "$COMFYUI_GPU_CONTROLNET_DIR/$COMFYUI_GPU_CONTROLNET_OPENPOSE_FILE"
  download_if_missing "$COMFYUI_GPU_CONTROLNET_CANNY_URL" "$COMFYUI_GPU_CONTROLNET_DIR/$COMFYUI_GPU_CONTROLNET_CANNY_FILE"
  download_if_missing "$COMFYUI_GPU_CONTROLNET_DEPTH_URL" "$COMFYUI_GPU_CONTROLNET_DIR/$COMFYUI_GPU_CONTROLNET_DEPTH_FILE"
}

download_gpu_pulid_models() {
  prepare_gpu_runtime_dirs
  download_if_missing "$COMFYUI_GPU_PULID_MODEL_URL" "$COMFYUI_GPU_MODEL_DIR/pulid/$COMFYUI_GPU_PULID_MODEL_FILE"
  download_zip_model_if_missing "$COMFYUI_GPU_INSIGHTFACE_MODEL_URL" "$COMFYUI_GPU_MODEL_DIR/insightface/models/$COMFYUI_GPU_INSIGHTFACE_MODEL_NAME" "$COMFYUI_GPU_INSIGHTFACE_MODEL_NAME"
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
  gate)
    if [[ "$target" == "cpu" ]]; then
      write_vision_gate_artifact "ok" "skipped" "" "cpu_runtime_not_gated"
    else
      gate_gpu_on_vision_unload
    fi
    ;;
  download-controlnets|download-controlnet-models)
    case "$target" in
      gpu) download_gpu_controlnet_models ;;
      cpu) echo "CPU ComfyUI uses the SD1.5 DreamShaper preset; SDXL ControlNet downloads are GPU-only." ;;
      all) download_gpu_controlnet_models ;;
    esac
    ;;
  download-pulid|download-pulid-models)
    case "$target" in
      gpu) download_gpu_pulid_models ;;
      cpu) echo "PuLID is used by the GPU Simple Avatar Generation template only." ;;
      all) download_gpu_pulid_models ;;
    esac
    ;;
  build)
    prepare_runtime_dirs all
    select_runtime gpu
    compose build comfyui
    ;;
  create)
    prepare_runtime_dirs all
    select_runtime gpu
    remove_legacy_split_containers
    compose up --no-start comfyui
    ;;
  start)
    prepare_runtime_dirs all
    select_runtime gpu
    gate_gpu_on_vision_unload
    remove_legacy_split_containers
    compose up -d --force-recreate comfyui
    ;;
  stop)
    compose stop comfyui
    compose rm -f comfyui
    rm -f "$COMFYUI_GPU_SOCKET_PATH" "$COMFYUI_GPU_HEALTH_SOCKET" "$COMFYUI_CPU_SOCKET_PATH" "$COMFYUI_CPU_HEALTH_SOCKET"
    ;;
  restart)
    "$0" "$target" stop
    "$0" "$target" start
    ;;
  status)
    compose ps comfyui
    for runtime in $(each_target); do
      health_probe "$runtime" || true
    done
    ;;
  logs)
    compose logs --tail "${COMFYUI_LOG_TAIL:-100}" comfyui
    ;;
  ready)
    "$0" "$target" start
    for runtime in $(each_target); do
      wait_ready "$runtime"
    done
    ;;
  *)
    echo "Usage: $0 [gpu|cpu|all] {prepare|gate|download-controlnets|download-pulid|build|create|start|stop|restart|status|logs|ready}" >&2
    echo "       $0 {prepare|gate|download-controlnets|download-pulid|build|create|start|stop|restart|status|logs|ready}  # defaults to gpu" >&2
    exit 2
    ;;
esac
