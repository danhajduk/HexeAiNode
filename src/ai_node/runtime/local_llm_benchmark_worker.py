import os
import asyncio
from typing import Callable

from ai_node.persistence.local_llm_benchmark_store import LocalLLMBenchmarkStore
from ai_node.providers.adapters.local_adapter import LocalProviderAdapter
from ai_node.providers.models import UnifiedExecutionRequest


class LocalLLMBenchmarkWorker:
    def __init__(
        self,
        *,
        store: LocalLLMBenchmarkStore,
        logger,
        adapter_factory: Callable[[str], object] | None = None,
    ) -> None:
        self._store = store
        self._logger = logger
        self._adapter_factory = adapter_factory or self._build_local_adapter

    async def run_pending_for_model(self, *, model_id: str, limit: int = 1) -> dict:
        normalized_model_id = str(model_id or "").strip()
        if not normalized_model_id:
            raise ValueError("model_id_required")
        processed = 0
        completed = 0
        failed = 0
        errors: list[str] = []
        for _ in range(max(int(limit), 0)):
            record = self._store.claim_next_pending(model_id=normalized_model_id)
            if record is None:
                break
            processed += 1
            record_id = str(record.get("record_id") or "").strip()
            try:
                response = await self._execute_record(record=record, model_id=normalized_model_id)
                gpu_snapshot = await self._gpu_snapshot()
                self._store.record_model_result(
                    record_id=record_id,
                    model_id=normalized_model_id,
                    response=response,
                    vram_used_mib=gpu_snapshot.get("llama_vram_mib"),
                    gpu_util_percent=gpu_snapshot.get("gpu_util_percent"),
                )
                completed += 1
            except Exception as exc:
                failed += 1
                error = str(exc).strip() or type(exc).__name__
                errors.append(error)
                self._store.record_model_failure(
                    record_id=record_id,
                    model_id=normalized_model_id,
                    error=error,
                )
                if hasattr(self._logger, "warning"):
                    self._logger.warning(
                        "[local-llm-benchmark-run-failed] %s",
                        {"record_id": record_id, "model_id": normalized_model_id, "error": error},
                    )
        return {
            "model_id": normalized_model_id,
            "processed": processed,
            "completed": completed,
            "failed": failed,
            "errors": errors[:5],
        }

    def pending_count_for_models(self, *, model_ids: list[str]) -> int:
        if hasattr(self._store, "pending_count_for_models"):
            return self._store.pending_count_for_models(model_ids=model_ids)
        return 0

    def pending_count_for_model(self, *, model_id: str) -> int:
        if hasattr(self._store, "pending_count_for_model"):
            return self._store.pending_count_for_model(model_id=model_id)
        return self.pending_count_for_models(model_ids=[model_id])

    def failed_count_for_models(self, *, model_ids: list[str]) -> int:
        if hasattr(self._store, "failed_count_for_models"):
            return self._store.failed_count_for_models(model_ids=model_ids)
        return 0

    def failed_count_for_model(self, *, model_id: str) -> int:
        if hasattr(self._store, "failed_count_for_model"):
            return self._store.failed_count_for_model(model_id=model_id)
        return self.failed_count_for_models(model_ids=[model_id])

    def reset_failed_for_models(self, *, model_ids: list[str]) -> int:
        if hasattr(self._store, "reset_failed_for_models"):
            return self._store.reset_failed_for_models(model_ids=model_ids)
        return 0

    def reset_failed_for_model(self, *, model_id: str) -> int:
        if hasattr(self._store, "reset_failed_for_model"):
            return self._store.reset_failed_for_model(model_id=model_id)
        return self.reset_failed_for_models(model_ids=[model_id])

    def running_count_for_models(self, *, model_ids: list[str]) -> int:
        if hasattr(self._store, "running_count_for_models"):
            return self._store.running_count_for_models(model_ids=model_ids)
        return 0

    def running_count_for_model(self, *, model_id: str) -> int:
        if hasattr(self._store, "running_count_for_model"):
            return self._store.running_count_for_model(model_id=model_id)
        return self.running_count_for_models(model_ids=[model_id])

    async def _execute_record(self, *, record: dict, model_id: str):
        request_payload = record.get("request_payload") if isinstance(record.get("request_payload"), dict) else {}
        metadata = dict(request_payload.get("metadata") or {}) if isinstance(request_payload.get("metadata"), dict) else {}
        metadata["benchmark_source_record_id"] = record.get("record_id")
        request = UnifiedExecutionRequest(
            task_family=str(request_payload.get("task_family") or "task.classification"),
            prompt=request_payload.get("prompt"),
            system_prompt=request_payload.get("system_prompt"),
            messages=list(request_payload.get("messages") or []) if isinstance(request_payload.get("messages"), list) else [],
            requested_provider="local",
            requested_model=model_id,
            temperature=request_payload.get("temperature"),
            max_tokens=request_payload.get("max_tokens"),
            metadata=metadata,
        )
        adapter = self._adapter_factory(model_id)
        return await adapter.execute_prompt(request)

    @staticmethod
    def _build_local_adapter(model_id: str) -> LocalProviderAdapter:
        return LocalProviderAdapter(
            default_model_id=model_id,
            transport=os.environ.get("SYNTHIA_PROVIDER_LOCAL_TRANSPORT", "socket"),
            socket_path=os.environ.get("SYNTHIA_PROVIDER_LOCAL_SOCKET", "/run/hexe/ai-node/llamacpp.sock"),
            base_url=os.environ.get("SYNTHIA_PROVIDER_LOCAL_BASE_URL", "http://127.0.0.1:8011/v1"),
            timeout_seconds=float(os.environ.get("SYNTHIA_LOCAL_LLM_BENCHMARK_TIMEOUT_SECONDS", "120")),
        )

    @staticmethod
    async def _gpu_snapshot() -> dict:
        try:
            gpu_process = await asyncio.create_subprocess_exec(
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used",
                "--format=csv,noheader,nounits",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            gpu_stdout, _ = await gpu_process.communicate()
            apps_process = await asyncio.create_subprocess_exec(
                "nvidia-smi",
                "--query-compute-apps=pid,process_name,used_memory",
                "--format=csv,noheader,nounits",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            apps_stdout, _ = await apps_process.communicate()
        except Exception:
            return {}
        snapshot: dict[str, float] = {}
        first_gpu_line = gpu_stdout.decode("utf-8", errors="replace").splitlines()[0:1]
        if first_gpu_line:
            parts = [part.strip() for part in first_gpu_line[0].split(",")]
            if len(parts) >= 2:
                try:
                    snapshot["gpu_util_percent"] = float(parts[0])
                    snapshot["gpu_memory_used_mib"] = float(parts[1])
                except ValueError:
                    pass
        llama_vram = 0.0
        for line in apps_stdout.decode("utf-8", errors="replace").splitlines():
            parts = [part.strip() for part in line.split(",")]
            if len(parts) < 3 or "llama" not in parts[1].lower():
                continue
            try:
                llama_vram += float(parts[2])
            except ValueError:
                continue
        if llama_vram > 0:
            snapshot["llama_vram_mib"] = llama_vram
        return snapshot
