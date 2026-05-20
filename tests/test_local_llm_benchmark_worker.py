import logging
import tempfile
import unittest
from pathlib import Path

from ai_node.persistence.local_llm_benchmark_store import LocalLLMBenchmarkStore
from ai_node.providers.models import UnifiedExecutionRequest, UnifiedExecutionResponse, UnifiedExecutionUsage
from ai_node.runtime.local_llm_benchmark_worker import LocalLLMBenchmarkWorker


class _FakeLocalAdapter:
    def __init__(self):
        self.requests = []

    async def execute_prompt(self, request):
        self.requests.append(request)
        return UnifiedExecutionResponse(
            provider_id="local",
            model_id=request.requested_model,
            output_text='{"label":"action_required","confidence":0.75}',
            usage=UnifiedExecutionUsage(prompt_tokens=11, completion_tokens=5, total_tokens=16),
            latency_ms=55.5,
            estimated_cost=0.0,
        )


class _FailingLocalAdapter:
    async def execute_prompt(self, _request):
        raise RuntimeError("local offline")


class LocalLLMBenchmarkWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_worker_runs_pending_record_for_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalLLMBenchmarkStore(
                path=str(Path(tmp) / "local_llm_benchmarks.db"),
                logger=logging.getLogger("local-llm-benchmark-worker-test"),
            )
            store.record_openai_execution(
                request=UnifiedExecutionRequest(
                    task_family="task.classification",
                    prompt="Classify this email",
                    requested_provider="openai",
                    requested_model="gpt-5.4-nano",
                    metadata={"prompt_id": "prompt.email.classifier"},
                ),
                response=UnifiedExecutionResponse(
                    provider_id="openai",
                    model_id="gpt-5.4-nano",
                    output_text='{"label":"action_required","confidence":0.62}',
                ),
                model_ids=["qwen3-8b-q4_k_m"],
            )
            adapter = _FakeLocalAdapter()
            worker = LocalLLMBenchmarkWorker(
                store=store,
                logger=logging.getLogger("local-llm-benchmark-worker-test"),
                adapter_factory=lambda _model_id: adapter,
            )

            result = await worker.run_pending_for_model(model_id="qwen3-8b-q4_k_m")
            payload = store.summary_payload()

            self.assertEqual(result["completed"], 1)
            self.assertEqual(adapter.requests[0].requested_provider, "local")
            self.assertEqual(adapter.requests[0].requested_model, "qwen3-8b-q4_k_m")
            local_result = payload["comparisons"][0]["local_results"][0]
            self.assertEqual(local_result["status"], "completed")
            self.assertEqual(local_result["label"], "action_required")
            self.assertEqual(local_result["total_tokens"], 16)

    async def test_worker_records_failure_for_pending_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalLLMBenchmarkStore(
                path=str(Path(tmp) / "local_llm_benchmarks.db"),
                logger=logging.getLogger("local-llm-benchmark-worker-test"),
            )
            store.record_openai_execution(
                request=UnifiedExecutionRequest(
                    task_family="task.classification",
                    prompt="hello",
                    metadata={"prompt_id": "prompt.email.classifier"},
                ),
                response=UnifiedExecutionResponse(provider_id="openai", model_id="gpt-5.4-nano", output_text="{}"),
                model_ids=["qwen3-8b-q4_k_m"],
            )
            worker = LocalLLMBenchmarkWorker(
                store=store,
                logger=logging.getLogger("local-llm-benchmark-worker-test"),
                adapter_factory=lambda _model_id: _FailingLocalAdapter(),
            )

            result = await worker.run_pending_for_model(model_id="qwen3-8b-q4_k_m")
            local_result = store.summary_payload()["comparisons"][0]["local_results"][0]

            self.assertEqual(result["failed"], 1)
            self.assertEqual(local_result["status"], "failed")
            self.assertEqual(local_result["error"], "local offline")
