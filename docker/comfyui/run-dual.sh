#!/usr/bin/env bash
set -euo pipefail

GPU_PORT="${COMFYUI_GPU_INTERNAL_PORT:-8188}"
CPU_PORT="${COMFYUI_CPU_INTERNAL_PORT:-8189}"
GPU_BASE_DIR="${COMFYUI_GPU_BASE_DIR:-/runtime/gpu}"
CPU_BASE_DIR="${COMFYUI_CPU_BASE_DIR:-/runtime/cpu}"
SOCKET_DIR="${COMFYUI_SOCKET_DIR:-/run/hexe/ai-node}"
GPU_SOCKET="${COMFYUI_GPU_SOCKET_PATH:-$SOCKET_DIR/comfyui-gpu.sock}"
GPU_HEALTH_SOCKET="${COMFYUI_GPU_HEALTH_SOCKET:-$SOCKET_DIR/comfyui-gpu-health.sock}"
CPU_SOCKET="${COMFYUI_CPU_SOCKET_PATH:-$SOCKET_DIR/comfyui-cpu.sock}"
CPU_HEALTH_SOCKET="${COMFYUI_CPU_HEALTH_SOCKET:-$SOCKET_DIR/comfyui-cpu-health.sock}"

export AUX_ANNOTATOR_CKPTS_PATH="${AUX_ANNOTATOR_CKPTS_PATH:-/runtime/assets/controlnet_aux/ckpts}"
export AUX_TEMP_DIR="${AUX_TEMP_DIR:-/cache/controlnet_aux/temp}"

mkdir -p \
  "$GPU_BASE_DIR/models" "$GPU_BASE_DIR/input" "$GPU_BASE_DIR/output" "$GPU_BASE_DIR/user" \
  "$GPU_BASE_DIR/temp" "$GPU_BASE_DIR/custom_nodes" \
  "$CPU_BASE_DIR/models" "$CPU_BASE_DIR/input" "$CPU_BASE_DIR/output" "$CPU_BASE_DIR/user" \
  "$CPU_BASE_DIR/temp" "$CPU_BASE_DIR/custom_nodes" \
  "$AUX_ANNOTATOR_CKPTS_PATH" "$AUX_TEMP_DIR" \
  "$SOCKET_DIR"

link_packaged_custom_nodes() {
  local base_dir="$1"
  local packaged_dir target
  for packaged_dir in /opt/ComfyUI/custom_nodes/*; do
    [[ -d "$packaged_dir" ]] || continue
    target="$base_dir/custom_nodes/$(basename "$packaged_dir")"
    if [[ -L "$target" && ! -e "$target" ]]; then
      rm -f "$target"
    fi
    if [[ ! -e "$target" ]]; then
      ln -s "$packaged_dir" "$target"
    fi
  done
}

link_packaged_custom_nodes "$GPU_BASE_DIR"
link_packaged_custom_nodes "$CPU_BASE_DIR"

rm -f "$GPU_SOCKET" "$GPU_HEALTH_SOCKET" "$CPU_SOCKET" "$CPU_HEALTH_SOCKET"

start_proxy() {
  local socket_path="$1"
  local port="$2"
  local runtime_id="$3"
  local runtime_label="$4"
  local checkpoint="$5"
  local lora="$6"
  local mode="$7"
  python3 /opt/hexe/comfyui-socket-proxy.py \
    --socket-path "$socket_path" \
    --upstream-port "$port" \
    --runtime-id "$runtime_id" \
    --runtime-label "$runtime_label" \
    --target-checkpoint "$checkpoint" \
    --target-lora "$lora" \
    --mode "$mode" &
  proxy_pid="$!"
}

cd /opt/ComfyUI

python3 main.py \
  --listen 0.0.0.0 \
  --port "$GPU_PORT" \
  --base-directory "$GPU_BASE_DIR" \
  --input-directory "$GPU_BASE_DIR/input" \
  --output-directory "$GPU_BASE_DIR/output" \
  --temp-directory "$GPU_BASE_DIR/temp" \
  --user-directory "$GPU_BASE_DIR/user" \
  --disable-auto-launch \
  ${COMFYUI_GPU_EXTRA_ARGS:-} &
gpu_pid="$!"

start_proxy "$GPU_SOCKET" "$GPU_PORT" "comfyui_gpu" "GPU ComfyUI" "${HEXE_COMFYUI_GPU_TARGET_CHECKPOINT:-}" "${HEXE_COMFYUI_GPU_TARGET_LORA:-}" "api"
gpu_proxy_pid="$proxy_pid"
start_proxy "$GPU_HEALTH_SOCKET" "$GPU_PORT" "comfyui_gpu" "GPU ComfyUI" "${HEXE_COMFYUI_GPU_TARGET_CHECKPOINT:-}" "${HEXE_COMFYUI_GPU_TARGET_LORA:-}" "health"
gpu_health_pid="$proxy_pid"

CUDA_VISIBLE_DEVICES="" python3 main.py \
  --cpu \
  --listen 0.0.0.0 \
  --port "$CPU_PORT" \
  --base-directory "$CPU_BASE_DIR" \
  --input-directory "$CPU_BASE_DIR/input" \
  --output-directory "$CPU_BASE_DIR/output" \
  --temp-directory "$CPU_BASE_DIR/temp" \
  --user-directory "$CPU_BASE_DIR/user" \
  --disable-auto-launch \
  ${COMFYUI_CPU_EXTRA_ARGS:-} &
cpu_pid="$!"

start_proxy "$CPU_SOCKET" "$CPU_PORT" "comfyui_cpu" "CPU ComfyUI" "${HEXE_COMFYUI_CPU_TARGET_CHECKPOINT:-}" "" "api"
cpu_proxy_pid="$proxy_pid"
start_proxy "$CPU_HEALTH_SOCKET" "$CPU_PORT" "comfyui_cpu" "CPU ComfyUI" "${HEXE_COMFYUI_CPU_TARGET_CHECKPOINT:-}" "" "health"
cpu_health_pid="$proxy_pid"

terminate() {
  kill "$gpu_pid" "$cpu_pid" "$gpu_proxy_pid" "$gpu_health_pid" "$cpu_proxy_pid" "$cpu_health_pid" >/dev/null 2>&1 || true
  wait "$gpu_pid" "$cpu_pid" "$gpu_proxy_pid" "$gpu_health_pid" "$cpu_proxy_pid" "$cpu_health_pid" >/dev/null 2>&1 || true
  rm -f "$GPU_SOCKET" "$GPU_HEALTH_SOCKET" "$CPU_SOCKET" "$CPU_HEALTH_SOCKET"
}

trap terminate INT TERM

if wait -n "$gpu_pid" "$cpu_pid"; then
  status=0
else
  status=$?
fi
terminate
exit "$status"
