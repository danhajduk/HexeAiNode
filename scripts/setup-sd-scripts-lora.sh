#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TRAIN_ROOT="${ROOT_DIR}/runtime/lora-training"
SD_SCRIPTS_DIR="${TRAIN_ROOT}/sd-scripts"
VENV_DIR="${SD_SCRIPTS_DIR}/venv"
REPO_URL="${SD_SCRIPTS_REPO_URL:-https://github.com/kohya-ss/sd-scripts.git}"
TORCH_INDEX_URL="${TORCH_INDEX_URL:-https://download.pytorch.org/whl/cu121}"

mkdir -p "${TRAIN_ROOT}"

if [[ ! -d "${SD_SCRIPTS_DIR}/.git" ]]; then
  git clone "${REPO_URL}" "${SD_SCRIPTS_DIR}"
else
  git -C "${SD_SCRIPTS_DIR}" pull --ff-only
fi

python3 -m venv "${VENV_DIR}"
source "${VENV_DIR}/bin/activate"
python -m pip install --upgrade pip setuptools wheel
python -m pip install --index-url "${TORCH_INDEX_URL}" torch torchvision
cd "${SD_SCRIPTS_DIR}"
python -m pip install -r requirements.txt
python -m pip install accelerate bitsandbytes toml

if [[ ! -f "${SD_SCRIPTS_DIR}/accelerate_config.yaml" ]]; then
  cat > "${SD_SCRIPTS_DIR}/accelerate_config.yaml" <<'YAML'
compute_environment: LOCAL_MACHINE
debug: false
distributed_type: "NO"
downcast_bf16: "no"
gpu_ids: "0"
machine_rank: 0
main_training_function: main
mixed_precision: fp16
num_machines: 1
num_processes: 1
rdzv_backend: static
same_network: true
tpu_env: []
tpu_use_cluster: false
tpu_use_sudo: false
use_cpu: false
YAML
fi

export ACCELERATE_CONFIG_FILE="${SD_SCRIPTS_DIR}/accelerate_config.yaml"
python - <<'PY'
import json
import torch

payload = {
    "torch": torch.__version__,
    "cuda_available": torch.cuda.is_available(),
    "cuda": torch.version.cuda,
    "device_count": torch.cuda.device_count(),
    "device_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "",
}
print(json.dumps(payload, indent=2))
if not torch.cuda.is_available():
    raise SystemExit("cuda_unavailable")
PY

echo "sd-scripts GPU environment ready at ${SD_SCRIPTS_DIR}"
