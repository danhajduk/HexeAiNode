import asyncio
import json
import os
import socket
import time
import urllib.request
from pathlib import Path
from typing import Awaitable, Callable

from ai_node.persistence.local_llm_benchmark_store import DEFAULT_LOCAL_LLM_BENCHMARK_MODELS
from ai_node.time_utils import local_now_iso


CommandRunner = Callable[[list[str], dict[str, str]], Awaitable[dict]]


class LocalLLMBenchmarkRotationRunner:
    def __init__(
        self,
        *,
        worker,
        logger,
        model_config_path: str = "config/local-llm-models.json",
        state_path: str = ".run/local_llm_benchmark_rotation.json",
        control_script: str = "scripts/llamacpp-control.sh",
        model_ids: list[str] | None = None,
        batch_limit: int = 25,
        command_runner: CommandRunner | None = None,
    ) -> None:
        self._worker = worker
        self._logger = logger
        self._model_config_path = Path(model_config_path)
        self._state_path = Path(state_path)
        self._control_script = str(control_script or "scripts/llamacpp-control.sh")
        self._model_ids = [str(item).strip() for item in (model_ids or DEFAULT_LOCAL_LLM_BENCHMARK_MODELS) if str(item).strip()]
        self._batch_limit = max(int(batch_limit), 1)
        self._command_runner = command_runner or self._run_command
        self._ready_timeout_seconds = max(
            int(os.environ.get("SYNTHIA_LOCAL_LLM_SWAP_READY_TIMEOUT_SECONDS") or os.environ.get("LLAMACPP_READY_TIMEOUT_S") or 420),
            60,
        )
        self._activity_status = "idle"
        self._activity_model_id: str | None = None
        self._swap_started_at: str | None = None
        self._swap_started_monotonic: float | None = None
        self._state_path.parent.mkdir(parents=True, exist_ok=True)

    async def run_once(self) -> dict:
        models = self._load_models()
        if self._pending_count_for_models(models) <= 0:
            return {"status": "skipped", "reason": "no_pending_prompts", "processed": 0}
        model = self._next_model()
        model_id = str(model["id"])
        try:
            self._begin_swap(model_id=model_id)
            try:
                switch_result = await self._load_model(model)
            except Exception as exc:
                self._finish_swap(model_id=model_id, error=str(exc).strip() or type(exc).__name__)
                raise
            last_swap = self._finish_swap(model_id=model_id, error=None)
            switch_result = {
                **switch_result,
                "swap_started_at": last_swap["started_at"],
                "swap_completed_at": last_swap["completed_at"],
                "swap_duration_seconds": last_swap["duration_seconds"],
                "swap_error": last_swap["error"],
                "ready_timeout_seconds": last_swap["ready_timeout_seconds"],
            }
            self._set_activity_status("running", model_id=model_id)
            worker_result = await self._worker.run_pending_for_model(
                model_id=model_id,
                limit=self._batch_limit,
            )
            result = {
                "model_id": model_id,
                "model_repo": model.get("repo"),
                "model_file": model.get("file"),
                "ctx_size": model.get("ctx_size"),
                "switched_at": local_now_iso(),
                "switch_result": switch_result,
                "worker_result": worker_result,
            }
            self._save_state(model_id=model_id, result=result, last_swap=last_swap)
            return result
        finally:
            self._set_activity_status("idle", model_id=None)

    async def run_loaded_model(self) -> dict:
        model_id = self._live_model_id() or str(self._load_state().get("current_model_id") or "").strip()
        if not model_id:
            raise ValueError("loaded_local_llm_model_required")
        try:
            self._set_activity_status("running", model_id=model_id)
            worker_result = await self._worker.run_pending_for_model(
                model_id=model_id,
                limit=self._batch_limit,
            )
            result = {
                "model_id": model_id,
                "mode": "loaded_model",
                "ran_at": local_now_iso(),
                "worker_result": worker_result,
            }
            self._save_state(model_id=model_id, result=result)
            return result
        finally:
            self._set_activity_status("idle", model_id=None)

    def status_payload(self) -> dict:
        state = self._load_state()
        models = self._load_models()
        current_model_id = self._live_model_id() or str(state.get("current_model_id") or "").strip() or None
        return {
            "configured": True,
            "current_model_id": current_model_id,
            "models": models,
            "updated_at": state.get("updated_at"),
            "last_result": state.get("last_result") if isinstance(state.get("last_result"), dict) else None,
            "last_swap": state.get("last_swap") if isinstance(state.get("last_swap"), dict) else None,
            "swap_started_at": self._swap_started_at,
            "swap_elapsed_seconds": self._swap_elapsed_seconds(),
            "ready_timeout_seconds": self._ready_timeout_seconds,
            "activity_status": self._activity_status,
            "activity_model_id": self._activity_model_id,
        }

    def _set_activity_status(self, status: str, *, model_id: str | None) -> None:
        self._activity_status = status
        self._activity_model_id = model_id

    def _begin_swap(self, *, model_id: str) -> None:
        self._swap_started_at = local_now_iso()
        self._swap_started_monotonic = time.monotonic()
        self._set_activity_status("swapping", model_id=model_id)

    def _finish_swap(self, *, model_id: str, error: str | None) -> dict:
        completed_at = local_now_iso()
        duration = self._swap_elapsed_seconds()
        payload = {
            "model_id": model_id,
            "started_at": self._swap_started_at,
            "completed_at": completed_at,
            "duration_seconds": duration,
            "error": error or None,
            "ready_timeout_seconds": self._ready_timeout_seconds,
        }
        self._save_state(model_id=str(self._load_state().get("current_model_id") or ""), result=None, last_swap=payload)
        self._swap_started_at = None
        self._swap_started_monotonic = None
        return payload

    def _swap_elapsed_seconds(self) -> float | None:
        if self._swap_started_monotonic is None:
            return None
        return round(max(time.monotonic() - self._swap_started_monotonic, 0.0), 3)

    @staticmethod
    def _live_model_id() -> str | None:
        transport = str(os.environ.get("SYNTHIA_PROVIDER_LOCAL_TRANSPORT") or "socket").strip().lower()
        try:
            if transport == "socket":
                socket_path = str(os.environ.get("SYNTHIA_PROVIDER_LOCAL_SOCKET") or "/run/hexe/ai-node/llamacpp.sock")
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                    client.settimeout(2)
                    client.connect(socket_path)
                    client.sendall(b"GET /v1/models HTTP/1.1\r\nHost: llamacpp\r\nConnection: close\r\n\r\n")
                    data = b""
                    while True:
                        chunk = client.recv(65536)
                        if not chunk:
                            break
                        data += chunk
                body = data.decode("utf-8", errors="replace").split("\r\n\r\n", 1)[-1]
                payload = json.loads(body)
            else:
                base_url = str(os.environ.get("SYNTHIA_PROVIDER_LOCAL_BASE_URL") or "http://127.0.0.1:8011/v1").rstrip("/")
                with urllib.request.urlopen(f"{base_url}/models", timeout=2) as response:
                    payload = json.loads(response.read().decode("utf-8", errors="replace"))
        except Exception:
            return None
        models = payload.get("data") if isinstance(payload, dict) else []
        if not isinstance(models, list) or not models:
            return None
        first = models[0] if isinstance(models[0], dict) else {}
        return str(first.get("id") or "").strip() or None

    def _next_model(self) -> dict:
        models = self._load_models()
        state = self._load_state()
        previous_id = self._live_model_id() or str(state.get("current_model_id") or "").strip()
        previous_index = next((idx for idx, item in enumerate(models) if str(item.get("id")) == previous_id), -1)
        return models[(previous_index + 1) % len(models)]

    def _load_models(self) -> list[dict]:
        payload = {}
        if self._model_config_path.exists():
            try:
                payload = json.loads(self._model_config_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                payload = {}
        configured = payload.get("models") if isinstance(payload, dict) else []
        models_by_id = {
            str(item.get("id") or "").strip(): dict(item)
            for item in configured
            if isinstance(item, dict) and str(item.get("id") or "").strip()
        }
        selected = [models_by_id[model_id] for model_id in self._model_ids if model_id in models_by_id]
        if selected:
            return selected
        fallback = [
            {"id": model_id, "repo": "", "file": "", "quantization": "", "ctx_size": 4096}
            for model_id in self._model_ids
        ]
        if not fallback:
            raise ValueError("local_llm_benchmark_rotation_models_required")
        return fallback

    def _pending_count_for_models(self, models: list[dict]) -> int:
        model_ids = [str(model.get("id") or "").strip() for model in models if isinstance(model, dict)]
        if hasattr(self._worker, "pending_count_for_models"):
            return int(self._worker.pending_count_for_models(model_ids=model_ids) or 0)
        return 0

    def _load_state(self) -> dict:
        if not self._state_path.exists():
            return {}
        try:
            payload = json.loads(self._state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _save_state(self, *, model_id: str, result: dict | None, last_swap: dict | None = None) -> None:
        existing = self._load_state()
        current_model_id = model_id or str(existing.get("current_model_id") or "").strip()
        payload = {
            "schema_version": "1.0",
            "current_model_id": current_model_id,
            "updated_at": local_now_iso(),
            "last_result": result if result is not None else existing.get("last_result"),
            "last_swap": last_swap if last_swap is not None else existing.get("last_swap"),
        }
        self._state_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    async def _load_model(self, model: dict) -> dict:
        env = dict(os.environ)
        model_id = str(model.get("id") or "").strip()
        repo = str(model.get("repo") or "").strip()
        quantization = str(model.get("quantization") or "").strip()
        if repo and quantization:
            env["LLAMACPP_MODEL_HF"] = f"{repo}:{quantization}"
        env["LLAMACPP_MODEL_ALIAS"] = model_id
        env["LLAMACPP_READY_TIMEOUT_S"] = str(self._ready_timeout_seconds)
        if model.get("ctx_size") is not None:
            env["LLAMACPP_CTX_SIZE"] = str(model.get("ctx_size"))
        command = [self._control_script, "ready"]
        result = await self._command_runner(command, env)
        return {
            "command": command,
            "returncode": int(result.get("returncode") or 0),
            "stdout": str(result.get("stdout") or "")[-2000:],
            "stderr": str(result.get("stderr") or "")[-2000:],
        }

    @staticmethod
    async def _run_command(command: list[str], env: dict[str, str]) -> dict:
        process = await asyncio.create_subprocess_exec(
            *command,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise RuntimeError((stderr or stdout).decode("utf-8", errors="replace").strip() or "local_model_load_failed")
        return {
            "returncode": process.returncode,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
        }
