#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from pathlib import Path


def _load_config(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    models = payload.get("models") if isinstance(payload, dict) else []
    return [item for item in models if isinstance(item, dict)]


def _file_size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except OSError:
        return None


def _download_tool() -> str:
    return shutil.which("hf") or shutil.which("huggingface-cli") or "hf"


def main() -> int:
    parser = argparse.ArgumentParser(description="Download configured local LLM GGUF models.")
    parser.add_argument("--config", default="config/local-llm-models.json")
    parser.add_argument("--model-dir", default="runtime/models/llamacpp")
    parser.add_argument("--manifest", default="runtime/models/llamacpp/manifest.json")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-full-repo", action="store_true")
    args = parser.parse_args()

    config_path = Path(args.config)
    model_dir = Path(args.model_dir)
    manifest_path = Path(args.manifest)
    model_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for model in _load_config(config_path):
        model_id = str(model.get("id") or "").strip()
        repo = str(model.get("repo") or "").strip()
        filename = str(model.get("file") or "").strip()
        if not model_id or not repo:
            continue
        target_dir = model_dir / model_id
        target_dir.mkdir(parents=True, exist_ok=True)
        if not filename and not args.allow_full_repo:
            records.append(
                {
                    "id": model_id,
                    "repo": repo,
                    "file": None,
                    "quantization": model.get("quantization"),
                    "role": model.get("role"),
                    "local_dir": str(target_dir),
                    "local_path": None,
                    "size_bytes": None,
                    "download_command": None,
                    "skipped_missing_file": True,
                    "dry_run": bool(args.dry_run),
                }
            )
            continue
        command = [_download_tool(), "download", repo, "--local-dir", str(target_dir)]
        if filename:
            command.insert(3, filename)
        existing = target_dir / filename if filename else None
        skipped = bool(existing and existing.exists())
        if not skipped and not args.dry_run:
            subprocess.run(command, check=True)
        records.append(
            {
                "id": model_id,
                "repo": repo,
                "file": filename or None,
                "quantization": model.get("quantization"),
                "role": model.get("role"),
                "local_dir": str(target_dir),
                "local_path": str(existing) if existing else None,
                "size_bytes": _file_size(existing) if existing else None,
                "download_command": command,
                "skipped_existing": skipped,
                "dry_run": bool(args.dry_run),
            }
        )
    manifest = {
        "schema_version": "1.0",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "models": records,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
