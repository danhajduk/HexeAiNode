#!/usr/bin/env python3
"""Prepare a Hexe avatar head LoRA manifest for kohya-ss/sd-scripts."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import time
import uuid
from pathlib import Path


def _toml_string(value: str) -> str:
    return json.dumps(str(value))


def _toml_bool(value: bool) -> str:
    return "true" if value else "false"


def _safe_token(value: str) -> str:
    token = re.sub(r"[^A-Za-z0-9_]+", "_", value.strip()).strip("_")
    return token or "avatar_face"


def _write_training_config(path: Path, *, values: dict, dataset_dir: Path, output_dir: Path, logging_dir: Path, output_name: str) -> None:
    model = values.get("model") if isinstance(values.get("model"), dict) else {}
    dataset = values.get("dataset") if isinstance(values.get("dataset"), dict) else {}
    training = values.get("training") if isinstance(values.get("training"), dict) else {}
    model_path = Path(str(model.get("pretrained_model_name_or_path") or "")).expanduser()
    if model_path and not model_path.is_absolute():
        model_path = (Path.cwd() / model_path).resolve()
    lines = [
        f"pretrained_model_name_or_path = {_toml_string(model_path.as_posix() if model_path else '')}",
        f"output_dir = {_toml_string(output_dir.as_posix())}",
        f"logging_dir = {_toml_string(logging_dir.as_posix())}",
        f"output_name = {_toml_string(output_name)}",
        'save_model_as = "safetensors"',
        "sdxl = true",
        "no_half_vae = true",
        f"network_module = {_toml_string(training.get('network_module', 'networks.lora'))}",
        f"network_dim = {int(training.get('network_dim', 32))}",
        f"network_alpha = {int(training.get('network_alpha', 16))}",
        f"train_batch_size = {int(training.get('train_batch_size', 1))}",
        f"max_train_epochs = {int(training.get('max_train_epochs', 10))}",
        f"learning_rate = {float(training.get('learning_rate', 0.0001))}",
        f"unet_lr = {float(training.get('unet_lr', training.get('learning_rate', 0.0001)))}",
        f"text_encoder_lr = {float(training.get('text_encoder_lr', 0.0))}",
        f"lr_scheduler = {_toml_string(training.get('lr_scheduler', 'cosine'))}",
        f"lr_warmup_steps = {int(training.get('lr_warmup_steps', 100))}",
        f"optimizer_type = {_toml_string(training.get('optimizer_type', 'AdamW8bit'))}",
        f"mixed_precision = {_toml_string(training.get('mixed_precision', 'fp16'))}",
        f"save_precision = {_toml_string(training.get('save_precision', 'fp16'))}",
        f"cache_latents = {_toml_bool(bool(training.get('cache_latents', True)))}",
        f"cache_latents_to_disk = {_toml_bool(bool(training.get('cache_latents_to_disk', True)))}",
        f"gradient_checkpointing = {_toml_bool(bool(training.get('gradient_checkpointing', True)))}",
        f"persistent_data_loader_workers = {_toml_bool(bool(training.get('persistent_data_loader_workers', False)))}",
        f"max_data_loader_n_workers = {int(training.get('max_data_loader_n_workers', 1))}",
        f"save_every_n_epochs = {int(training.get('save_every_n_epochs', 1))}",
        f"seed = {int(training.get('seed', 1781128029))}",
        f"dataset_config = {_toml_string((path.parent / 'dataset.toml').as_posix())}",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")

    dataset_lines = [
        "[[datasets]]",
        f"resolution = {int(dataset.get('resolution', 512))}",
        f"batch_size = {int(training.get('train_batch_size', 1))}",
        f"keep_tokens = {int(dataset.get('keep_tokens', 1))}",
        "",
        "  [[datasets.subsets]]",
        f"  image_dir = {_toml_string(dataset_dir.as_posix())}",
        f"  caption_extension = {_toml_string(dataset.get('caption_extension', '.txt'))}",
        f"  num_repeats = {int(dataset.get('repeats', 8))}",
        f"  shuffle_caption = {_toml_bool(bool(dataset.get('shuffle_caption', True)))}",
        "",
    ]
    (path.parent / "dataset.toml").write_text("\n".join(dataset_lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--template", default=Path("config/lora-training/avatar-head-sdxl-kohya.json"), type=Path)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--job-id")
    parser.add_argument("--copy", action="store_true", help="Deprecated; images are copied by default.")
    parser.add_argument("--symlink", action="store_true", help="Symlink images instead of copying them.")
    args = parser.parse_args()

    manifest_path = args.manifest.resolve()
    template_path = args.template.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    template = json.loads(template_path.read_text(encoding="utf-8"))
    profile_id = _safe_token(str(manifest.get("profile_id") or manifest_path.parents[3].name))
    section = _safe_token(str(manifest.get("section") or "head_face"))
    trigger_word = _safe_token(str(manifest.get("trigger_word") or profile_id))
    job_id = _safe_token(
        str(args.job_id or manifest.get("job_id") or f"{profile_id}_{section}_{int(time.time())}_{uuid.uuid4().hex[:8]}")
    )
    root = (args.out_dir or Path("runtime/lora-training/jobs") / job_id).resolve()
    dataset_dir = root / "dataset" / f"{int(template.get('dataset', {}).get('repeats', 8))}_{trigger_word}"
    config_dir = root / "config"
    output_dir = root / "output"
    logging_dir = root / "logs"
    for directory in (dataset_dir, config_dir, output_dir, logging_dir):
        directory.mkdir(parents=True, exist_ok=True)

    source_root = Path("runtime/manual/comfyui-gpu/input").resolve()
    items = manifest.get("items") if isinstance(manifest.get("items"), list) else []
    prepared = []
    for index, item in enumerate(items, start=1):
        image_relative = str(item.get("image") or "").strip()
        if not image_relative:
            continue
        source = (source_root / image_relative).resolve()
        if source_root not in source.parents or not source.is_file():
            continue
        pose_id = _safe_token(str(item.get("pose_id") or "pose"))
        stem = f"{index:03d}_{pose_id}_{_safe_token(str(item.get('approved_id') or source.stem))}"
        target = dataset_dir / f"{stem}{source.suffix.lower()}"
        if target.exists() or target.is_symlink():
            target.unlink()
        if args.symlink:
            target.symlink_to(source)
        else:
            shutil.copy2(source, target)
        caption = str(item.get("caption") or "").strip()
        caption = f"{trigger_word}, {pose_id.replace('_', ' ')}, {caption}".strip(", ")
        target.with_suffix(".txt").write_text(caption + "\n", encoding="utf-8")
        prepared.append({"source": source.as_posix(), "image": target.as_posix(), "caption": target.with_suffix(".txt").as_posix()})

    if not prepared:
        raise SystemExit("no training images prepared")

    default_suffix = "head_face_lora" if section == "head_face" else f"{section}_lora"
    configured_suffix = str(template.get("training", {}).get("output_name_suffix") or default_suffix)
    if section != "head_face" and configured_suffix == "head_face_lora":
        configured_suffix = default_suffix
    output_name = f"{trigger_word}_{configured_suffix}"
    config_path = config_dir / "train.toml"
    _write_training_config(
        config_path,
        values=template,
        dataset_dir=dataset_dir,
        output_dir=output_dir,
        logging_dir=logging_dir,
        output_name=output_name,
    )
    run_script = root / "run_train.sh"
    sd_scripts_dir = Path("runtime/lora-training/sd-scripts").resolve()
    run_script.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"ROOT_DIR={json.dumps(Path.cwd().resolve().as_posix())}\n"
        f"JOB_MARKER={json.dumps((root / 'training.active').as_posix())}\n"
        'TRAINING_MARKER="${HEXE_SD_SCRIPTS_TRAINING_MARKER:-${ROOT_DIR}/.run/sd-scripts-training.active}"\n'
        'mkdir -p "$(dirname "${TRAINING_MARKER}")"\n'
        'printf "%s\\n" "$$" >"${TRAINING_MARKER}"\n'
        'printf "%s\\n" "$$" >"${JOB_MARKER}"\n'
        'cleanup_training_marker() { rm -f "${TRAINING_MARKER}" "${JOB_MARKER}"; }\n'
        "trap cleanup_training_marker EXIT\n"
        'if [[ "${HEXE_LOCAL_LLM_GPU_EXCLUSIVE_BLOCKER_ENABLED:-1}" != "0" '
        '&& "${HEXE_LOCAL_LLM_STOP_FOR_GPU_WORKLOADS:-1}" != "0" ]]; then\n'
        '  "${ROOT_DIR}/scripts/llamacpp-control.sh" stop || true\n'
        "fi\n"
        'if [[ "${HEXE_VISION_LLM_GPU_EXCLUSIVE_BLOCKER_ENABLED:-1}" != "0" '
        '&& "${HEXE_VISION_LLM_STOP_FOR_GPU_WORKLOADS:-${HEXE_VISION_LLM_STOP_FOR_SD_SCRIPTS:-1}}" != "0" ]]; then\n'
        '  "${ROOT_DIR}/scripts/llamacpp-vision-control.sh" stop || true\n'
        "fi\n"
        f"cd {json.dumps(sd_scripts_dir.as_posix())}\n"
        "source venv/bin/activate\n"
        f"if [[ -f {json.dumps((sd_scripts_dir / 'accelerate_config.yaml').as_posix())} ]]; then\n"
        f"  export ACCELERATE_CONFIG_FILE={json.dumps((sd_scripts_dir / 'accelerate_config.yaml').as_posix())}\n"
        "fi\n"
        f"accelerate launch --num_cpu_threads_per_process=2 sdxl_train_network.py --config_file {json.dumps(config_path.as_posix())}\n",
        encoding="utf-8",
    )
    run_script.chmod(0o755)
    summary = {
        "status": "ready",
        "job_id": job_id,
        "profile_id": profile_id,
        "section": section,
        "job_dir": root.as_posix(),
        "dataset_dir": dataset_dir.as_posix(),
        "output_dir": output_dir.as_posix(),
        "config": config_path.as_posix(),
        "dataset_config": (config_dir / "dataset.toml").as_posix(),
        "run_script": run_script.as_posix(),
        "image_count": len(prepared),
        "output_name": output_name,
    }
    (root / "prepared.json").write_text(json.dumps({**summary, "items": prepared}, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
