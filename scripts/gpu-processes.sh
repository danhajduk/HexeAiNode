#!/usr/bin/env bash
set -euo pipefail

interval=2
watch_mode=0
show_sd_progress=0
show_comfyui_status=0
while [[ $# -gt 0 ]]; do
  case "${1:-}" in
    --watch|-w)
      watch_mode=1
      if [[ "${2:-}" =~ ^[0-9]+$ ]]; then
        interval="$2"
        shift
      fi
      ;;
    --sd-progress|--show-sd-progress)
      show_sd_progress=1
      ;;
    --comfyui-status|--comfy-status|--comfyui)
      show_comfyui_status=1
      ;;
    --help|-h)
      cat <<'EOF'
Usage: gpu-processes.sh [--watch [seconds]] [--sd-progress] [--comfyui-status]

Options:
  --watch, -w [seconds]       Refresh continuously.
  --sd-progress               Show tail progress from the active sd-scripts LoRA log when GPU is active.
  --comfyui-status            Show ComfyUI queue/history status from the active UNIX socket.
EOF
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      echo "Usage: gpu-processes.sh [--watch [seconds]] [--sd-progress] [--comfyui-status]" >&2
      exit 2
      ;;
  esac
  shift
done

if ! command -v nvidia-smi >/dev/null 2>&1; then
  echo "nvidia-smi not found" >&2
  exit 1
fi

render() {
  local docker_pid_map gpu_name gpu_total gpu_used gpu_free gpu_free_percent gpu_util gpu_temp logical_cpu_count sd_scripts_gpu_active
  logical_cpu_count="$(nproc 2>/dev/null || getconf _NPROCESSORS_ONLN 2>/dev/null || printf '1')"
  if ! [[ "${logical_cpu_count}" =~ ^[0-9]+$ ]] || [[ "${logical_cpu_count}" -lt 1 ]]; then
    logical_cpu_count=1
  fi
  sd_scripts_gpu_active=0
  IFS=',' read -r gpu_name gpu_total gpu_used gpu_free gpu_util gpu_temp < <(
    nvidia-smi --query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu --format=csv,noheader,nounits | head -1
  )
  gpu_name="$(xargs <<<"${gpu_name:-unknown}")"
  gpu_total="$(xargs <<<"${gpu_total:-0}")"
  gpu_used="$(xargs <<<"${gpu_used:-0}")"
  gpu_free="$(xargs <<<"${gpu_free:-0}")"
  gpu_util="$(xargs <<<"${gpu_util:-0}")"
  gpu_temp="$(xargs <<<"${gpu_temp:-0}")"
  if [[ "${gpu_total}" =~ ^[0-9]+$ && "${gpu_free}" =~ ^[0-9]+$ && "${gpu_total}" -gt 0 ]]; then
    gpu_free_percent="$(( gpu_free * 100 / gpu_total ))"
  else
    gpu_free_percent="0"
  fi

  printf "GPU Processes  %s\n" "$(date '+%Y-%m-%d %H:%M:%S')"
  printf "%s\n" "──────────────────────────────────────────────────────────────────────────────────────────────────────────────"
  printf "%s | VRAM %s/%s MiB used, %s MiB free (%s%%) | util %s%% | %s°C\n" \
    "${gpu_name}" "${gpu_used}" "${gpu_total}" "${gpu_free}" "${gpu_free_percent}" "${gpu_util}" "${gpu_temp}"
  printf "%s\n" "──────────────────────────────────────────────────────────────────────────────────────────────────────────────"
  printf "%-8s %-15s %10s  %6s %6s  %6s %6s  %s\n" "PID" "SERVICE" "VRAM" "GPU%" "GMEM%" "CPU%" "RAM%" "MODEL"

  mapfile -t gpu_rows < <(nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader,nounits 2>/dev/null || true)

  docker_pid_map=""
  docker_name_map=""
  if command -v docker >/dev/null 2>&1; then
    docker_pid_map="$(docker ps -q | xargs -r docker inspect --format '{{.State.Pid}} {{.Name}}' 2>/dev/null || true)"
    docker_name_map="$(docker ps --format '{{.Names}} {{.Status}}' 2>/dev/null || true)"
  fi
  pmon_map="$(nvidia-smi pmon -c 1 -s um 2>/dev/null | awk 'NF >= 10 && $1 !~ /^#/ {print $2, $4, $5}' || true)"
  seen_services=""

  for row in "${gpu_rows[@]}"; do
    pid="$(awk -F',' '{gsub(/^[ \t]+|[ \t]+$/, "", $1); print $1}' <<<"${row}")"
    used_memory="$(awk -F',' '{gsub(/^[ \t]+|[ \t]+$/, "", $2); print $2}' <<<"${row}")"
    container="$(
      awk -v target="${pid}" '$1 == target {print $2; exit}' <<<"${docker_pid_map}"
    )"
    container="${container:-host}"
    command="$(ps -p "${pid}" -o args= 2>/dev/null || true)"
    model=""
    case "${container}" in
      /hexe-ai-node-llamacpp)
        service="text-llm"
        ;;
      /hexe-ai-node-llamacpp-vision)
        service="vision-llm"
        ;;
      /hexe-ai-node-comfyui)
        service="comfyui"
        ;;
      host)
        service="host"
        ;;
      *)
        service="${container#/}"
        ;;
    esac
    if [[ "${command}" =~ sdxl_train_network.py|train_network.py|accelerate[[:space:]]+launch ]]; then
      service="sd-scripts"
    elif [[ "${command}" =~ ComfyUI|main.py.*--base-directory[[:space:]]+/runtime/gpu|main.py.*--port[[:space:]]+8188 ]]; then
      service="comfyui"
    fi
    if [[ "${command}" =~ --alias[[:space:]]+([^[:space:]]+) ]]; then
      model="${BASH_REMATCH[1]}"
    elif [[ "${service}" == "sd-scripts" ]]; then
      model="sdxl-train"
    elif [[ "${service}" == "comfyui" ]]; then
      model="comfyui"
    elif [[ "${command}" =~ python ]]; then
      model="python"
    else
      model="-"
    fi
    seen_services="${seen_services} ${service} "
    read -r sm_util mem_util < <(
      awk -v target="${pid}" '$1 == target {print $2, $3; exit}' <<<"${pmon_map}"
    )
    sm_util="${sm_util:--}"
    mem_util="${mem_util:--}"
    [[ "${sm_util}" == "-" ]] && sm_util="0"
    [[ "${mem_util}" == "-" ]] && mem_util="0"
    if [[ "${service}" == "sd-scripts" && "${sm_util}" =~ ^[0-9]+$ && "${sm_util}" -gt 0 ]]; then
      sd_scripts_gpu_active=1
    fi
    read -r cpu_util_raw ram_util < <(ps -p "${pid}" -o %cpu=,%mem= 2>/dev/null | awk '{print $1, $2}')
    cpu_util_raw="${cpu_util_raw:-0.0}"
    cpu_util="$(awk -v cpu="${cpu_util_raw}" -v cores="${logical_cpu_count}" 'BEGIN { if (cores < 1) cores = 1; printf "%.1f", cpu / cores }')"
    ram_util="${ram_util:-0.0}"
    service="${service:0:15}"
    printf "%-8s %-15s %10s  %5s%% %5s%%  %5s%% %5s%%  %s\n" \
      "${pid}" "${service}" "${used_memory}MiB" "${sm_util}" "${mem_util}" "${cpu_util}" "${ram_util}" "${model}"
  done

  local known_services=(
    "text-llm:hexe-ai-node-llamacpp:qwen3-8b-q4_k_m"
    "vision-llm:hexe-ai-node-llamacpp-vision:qwen2.5-vl-3b"
    "comfyui:hexe-ai-node-comfyui:comfyui"
    "sd-scripts::sdxl-train"
  )
  for entry in "${known_services[@]}"; do
    IFS=":" read -r service docker_name model <<<"${entry}"
    if [[ "${seen_services}" == *" ${service} "* ]]; then
      continue
    fi
    status="not-loaded"
    if [[ -n "${docker_name}" ]]; then
      if grep -q "^${docker_name} " <<<"${docker_name_map}"; then
        status="running-idle"
      elif command -v docker >/dev/null 2>&1 && docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx "${docker_name}"; then
        status="stopped"
      fi
    fi
    printf "%-8s %-15s %10s  %5s  %5s  %5s  %5s  %s (%s)\n" \
      "-" "${service:0:15}" "0MiB" "-" "-" "-" "-" "${model}" "${status}"
  done

  print_llm_status

  local sd_log_path="${HEXE_SD_SCRIPTS_TRAINING_LOG:-}"
  if [[ -z "${sd_log_path}" ]]; then
    sd_log_path="$(find runtime/lora-training/jobs -name train.log -type f -printf '%T@ %p\n' 2>/dev/null | sort -nr | awk 'NR==1 {print $2}')"
  fi
  if [[ "${show_sd_progress}" -eq 1 && "${sd_scripts_gpu_active}" -eq 1 && -f "${sd_log_path}" ]]; then
    printf "\nSD LoRA progress (%s)\n" "${sd_log_path}"
    printf "%s\n" "──────────────────────────────────────────────────────────────────────────────────────────────────────────────"
    tail -c 262144 "${sd_log_path}" | tr '\r' '\n' | awk '
      /^[[:space:]]*epoch[[:space:]]+[0-9]+\/[0-9]+/ {
        sub(/^[[:space:]]+/, "", $0)
        epoch=$0
      }
      /^[[:space:]]*steps:/ {
        sub(/^[[:space:]]+/, "", $0)
        step=$0
      }
      END {
        if (epoch != "") print epoch
        if (step != "") print step
      }
    '
  fi

  if [[ "${show_comfyui_status}" -eq 1 ]]; then
    print_comfyui_status
  fi
}

print_llm_status() {
  local api_base status_file
  api_base="${HEXE_AI_NODE_API_BASE_URL:-http://127.0.0.1:9002}"
  status_file="$(mktemp)"
  if ! curl -fsS --max-time 3 "${api_base%/}/api/services/status" >"${status_file}" 2>/dev/null; then
    rm -f "${status_file}"
    return
  fi
  printf "\nLLM status\n"
  printf "%s\n" "──────────────────────────────────────────────────────────────────────────────────────────────────────────────"
  python3 - "${status_file}" <<'PY'
import json
import sys

path = sys.argv[1]

try:
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
except Exception:
    raise SystemExit(0)

services = payload.get("services") if isinstance(payload, dict) else {}
if not isinstance(services, dict):
    raise SystemExit(0)

def join_models(models):
    if isinstance(models, list):
        values = [str(item).strip() for item in models if str(item).strip()]
        if values:
            return ",".join(values)
    return "-"

def short(value, limit=68):
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 1)] + "…"

def print_local():
    svc = services.get("local_llm")
    if not isinstance(svc, dict):
        return
    always = svc.get("always_on") if isinstance(svc.get("always_on"), dict) else {}
    state = str(svc.get("state") or "unknown")
    model = str(always.get("default_model_id") or svc.get("default_model_id") or "-")
    active = join_models(always.get("active_model_ids"))
    runtime_ready = bool(always.get("runtime_ready"))
    default_loaded = bool(always.get("default_model_loaded"))
    start_in_progress = bool(always.get("start_in_progress"))
    blocked = bool(always.get("gpu_exclusive_blocked"))
    reason = str(always.get("reason") or "")
    if default_loaded:
        phase = "ready"
    elif start_in_progress:
        phase = "loading"
    elif blocked:
        phase = "blocked"
    elif runtime_ready:
        phase = "runtime-ready"
    elif state == "stopped":
        phase = "stopped"
    else:
        phase = state
    detail = reason
    reasons = always.get("gpu_exclusive_reasons")
    if blocked and isinstance(reasons, list) and reasons:
        detail = ",".join(str(item) for item in reasons)
    print(f"text-llm   {state:<9} {phase:<13} model={short(model, 32):<32} active={short(active, 32):<32} {short(detail)}")

def print_vision():
    svc = services.get("vision_llm")
    if not isinstance(svc, dict):
        return
    residency = svc.get("residency") if isinstance(svc.get("residency"), dict) else {}
    state = str(svc.get("state") or "unknown")
    model = str(residency.get("default_model_id") or svc.get("default_model_id") or "-")
    active = join_models(residency.get("active_model_ids"))
    runtime_ready = bool(residency.get("runtime_ready"))
    model_loaded = bool(residency.get("model_loaded"))
    residency_state = str(residency.get("residency_state") or "")
    start_in_progress = bool(residency.get("start_in_progress"))
    blocked = bool(residency.get("gpu_exclusive_blocked"))
    reason = str(residency.get("reason") or "")
    if model_loaded:
        phase = "ready"
    elif residency_state:
        phase = residency_state
    elif start_in_progress:
        phase = "loading"
    elif blocked:
        phase = "blocked"
    elif runtime_ready:
        phase = "runtime-ready"
    elif state == "stopped":
        phase = "stopped"
    else:
        phase = state
    detail = reason
    reasons = residency.get("gpu_exclusive_reasons")
    if blocked and isinstance(reasons, list) and reasons:
        detail = ",".join(str(item) for item in reasons)
    print(f"vision-llm {state:<9} {phase:<13} model={short(model, 32):<32} active={short(active, 32):<32} {short(detail)}")

print_local()
print_vision()
PY
  rm -f "${status_file}"
}

comfyui_socket_path() {
  local candidate
  for candidate in \
    "${HEXE_COMFYUI_SOCKET:-}" \
    "/run/hexe/ai-node/comfyui-gpu.sock" \
    "runtime/comfyui-gpu.sock"
  do
    if [[ -n "${candidate}" && -S "${candidate}" ]]; then
      printf "%s\n" "${candidate}"
      return 0
    fi
  done
  return 1
}

comfyui_get_json() {
  local socket_path="$1"
  local endpoint="$2"
  curl -fsS --max-time 3 --unix-socket "${socket_path}" "http://localhost${endpoint}" 2>/dev/null
}

print_comfyui_status() {
  local socket_path queue_file history_file output_count
  printf "\nComfyUI status\n"
  printf "%s\n" "──────────────────────────────────────────────────────────────────────────────────────────────────────────────"
  if ! socket_path="$(comfyui_socket_path)"; then
    printf "socket: unavailable\n"
    return
  fi
  queue_file="$(mktemp)"
  history_file="$(mktemp)"
  trap 'rm -f "${queue_file:-}" "${history_file:-}"' RETURN
  comfyui_get_json "${socket_path}" "/queue" >"${queue_file}" || true
  comfyui_get_json "${socket_path}" "/history" >"${history_file}" || true
  output_count="$(
    {
      find runtime/manual/comfyui-gpu/output/hexe/avatar_head_face_preview runtime/output/comfyui-gpu/hexe/avatar_head_face_preview \
        -maxdepth 1 -type f -name '*lora_epoch*png' 2>/dev/null || true
    } | wc -l | awk '{print $1}'
  )"
  python3 - "${socket_path}" "${output_count}" "${queue_file}" "${history_file}" <<'PY'
import json
import sys

socket_path = sys.argv[1]
output_count = sys.argv[2]
queue_file = sys.argv[3]
history_file = sys.argv[4]

def loads_file(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            parsed = json.load(handle)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}

queue = loads_file(queue_file)
history = loads_file(history_file)
running = queue.get("queue_running") if isinstance(queue.get("queue_running"), list) else []
pending = queue.get("queue_pending") if isinstance(queue.get("queue_pending"), list) else []

completed = 0
errors = 0
latest_status = ""
latest_error = ""
for _, item in history.items():
    if not isinstance(item, dict):
        continue
    status = item.get("status") if isinstance(item.get("status"), dict) else {}
    status_str = str(status.get("status_str") or "")
    if status.get("completed") is True:
        completed += 1
    if status_str == "error":
        errors += 1
    latest_status = status_str or latest_status
    messages = status.get("messages") if isinstance(status.get("messages"), list) else []
    for message in reversed(messages):
        if isinstance(message, list) and len(message) >= 2 and message[0] == "execution_error" and isinstance(message[1], dict):
            latest_error = str(message[1].get("exception_message") or "").strip().replace("\n", " ")[:180]
            break

def prompt_id(value):
    if isinstance(value, list) and len(value) >= 2:
        return str(value[1])
    if isinstance(value, dict):
        return str(value.get("prompt_id") or value.get("id") or "")
    return ""

running_id = prompt_id(running[0]) if running else ""
print(f"socket: {socket_path}")
print(f"queue: running {len(running)}, pending {len(pending)}, history completed {completed}, errors {errors}, lora review outputs {output_count}")
if running_id:
    print(f"running prompt: {running_id}")
if latest_status:
    print(f"latest history status: {latest_status}")
if latest_error:
    print(f"latest error: {latest_error}")
PY
  rm -f "${queue_file}" "${history_file}"
  trap - RETURN
}

if [[ "${watch_mode}" -eq 1 ]]; then
  while true; do
    clear
    render
    printf "\nRefreshing every %ss. Press Ctrl+C to stop.\n" "${interval}"
    sleep "${interval}"
  done
else
  render
fi
