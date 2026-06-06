#!/usr/bin/env bash
set -euo pipefail

GPU_PORT="${COMFYUI_GPU_INTERNAL_PORT:-8188}"
CPU_PORT="${COMFYUI_CPU_INTERNAL_PORT:-8189}"
GPU_BASE_DIR="${COMFYUI_GPU_BASE_DIR:-/runtime/gpu}"
CPU_BASE_DIR="${COMFYUI_CPU_BASE_DIR:-/runtime/cpu}"

mkdir -p \
  "$GPU_BASE_DIR/models" "$GPU_BASE_DIR/input" "$GPU_BASE_DIR/output" "$GPU_BASE_DIR/user" \
  "$GPU_BASE_DIR/temp" "$GPU_BASE_DIR/custom_nodes" \
  "$CPU_BASE_DIR/models" "$CPU_BASE_DIR/input" "$CPU_BASE_DIR/output" "$CPU_BASE_DIR/user" \
  "$CPU_BASE_DIR/temp" "$CPU_BASE_DIR/custom_nodes"

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

terminate() {
  kill "$gpu_pid" "$cpu_pid" >/dev/null 2>&1 || true
  wait "$gpu_pid" "$cpu_pid" >/dev/null 2>&1 || true
}

trap terminate INT TERM

if wait -n "$gpu_pid" "$cpu_pid"; then
  status=0
else
  status=$?
fi
terminate
exit "$status"
