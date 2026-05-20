import logging
import tempfile
import unittest
from pathlib import Path

from ai_node.persistence.local_llm_benchmark_store import LocalLLMBenchmarkStore, parse_structured_output_summary
from ai_node.providers.models import UnifiedExecutionRequest, UnifiedExecutionResponse, UnifiedExecutionUsage


class LocalLLMBenchmarkStoreTests(unittest.TestCase):
    def test_records_openai_execution_and_pending_local_models(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalLLMBenchmarkStore(
                path=str(Path(tmp) / "local_llm_benchmarks.db"),
                logger=logging.getLogger("local-llm-benchmark-test"),
            )

            record_id = store.record_openai_execution(
                request=UnifiedExecutionRequest(
                    task_family="task.classification",
                    prompt="Classify this email",
                    requested_provider="openai",
                    requested_model="gpt-5.4-nano",
                    metadata={
                        "prompt_id": "prompt.email.classifier",
                        "prompt_version": "3",
                        "trace_id": "trace-1",
                    },
                ),
                response=UnifiedExecutionResponse(
                    provider_id="openai",
                    model_id="gpt-5.4-nano",
                    output_text='{"label":"action_required","confidence":0.62,"reasoning":"needs a reply"}',
                    usage=UnifiedExecutionUsage(prompt_tokens=10, completion_tokens=4, total_tokens=14),
                    latency_ms=123.4,
                    estimated_cost=0.00001,
                ),
                model_ids=["qwen3-8b-q4_k_m", "gemma-3-12b-it-q4_k_m"],
            )
            store.record_model_result(
                record_id=record_id,
                model_id="qwen3-8b-q4_k_m",
                response=UnifiedExecutionResponse(
                    provider_id="local",
                    model_id="qwen3-8b-q4_k_m",
                    output_text='{"label":"action_required","confidence":0.7}',
                ),
                vram_used_mib=5456,
                gpu_util_percent=42,
            )

            payload = store.summary_payload()

            self.assertTrue(record_id.startswith("openai-"))
            self.assertEqual(payload["status_counts"], {"completed": 1, "pending": 1})
            self.assertEqual(len(payload["comparisons"]), 1)
            comparison = payload["comparisons"][0]
            self.assertEqual(comparison["prompt_id"], "prompt.email.classifier")
            self.assertEqual(comparison["openai"]["label"], "action_required")
            self.assertEqual(comparison["openai"]["reasoning"], "needs a reply")
            self.assertEqual(comparison["openai"]["usage"]["total_tokens"], 14)
            self.assertIsNone(comparison["correct_label"])
            self.assertEqual(
                [item["model_id"] for item in comparison["local_results"]],
                ["gemma-3-12b-it-q4_k_m", "qwen3-8b-q4_k_m"],
            )
            completed = [item for item in comparison["local_results"] if item["model_id"] == "qwen3-8b-q4_k_m"][0]
            self.assertEqual(completed["vram_used_mib"], 5456)
            self.assertEqual(completed["gpu_util_percent"], 42)
            self.assertEqual(payload["running"], [])
            self.assertEqual(store.pending_count_for_models(model_ids=["gemma-3-12b-it-q4_k_m"]), 1)

            correction = store.set_correct_label(record_id=record_id, correct_label="unknown", note="manual review")
            self.assertEqual(correction["correct_label"], "unknown")
            corrected_payload = store.summary_payload()
            self.assertEqual(corrected_payload["comparisons"][0]["correct_label"], "unknown")
            self.assertEqual(corrected_payload["comparisons"][0]["correction_note"], "manual review")

    def test_ignores_non_openai_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalLLMBenchmarkStore(
                path=str(Path(tmp) / "local_llm_benchmarks.db"),
                logger=logging.getLogger("local-llm-benchmark-test"),
            )

            record_id = store.record_openai_execution(
                request=UnifiedExecutionRequest(task_family="task.classification", prompt="hello"),
                response=UnifiedExecutionResponse(provider_id="local", model_id="qwen", output_text="{}"),
            )

            self.assertIsNone(record_id)
            self.assertEqual(store.summary_payload()["comparisons"], [])

    def test_ignores_non_classifier_prompt_for_local_llm_benchmark(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalLLMBenchmarkStore(
                path=str(Path(tmp) / "local_llm_benchmarks.db"),
                logger=logging.getLogger("local-llm-benchmark-test"),
            )

            record_id = store.record_openai_execution(
                request=UnifiedExecutionRequest(
                    task_family="task.classification",
                    prompt="Decide whether to act",
                    metadata={"prompt_id": "prompt.email.action_decision"},
                ),
                response=UnifiedExecutionResponse(provider_id="openai", model_id="gpt-5.4-nano", output_text="{}"),
                model_ids=["qwen3-8b-q4_k_m"],
            )

            self.assertIsNone(record_id)
            self.assertEqual(store.pending_count_for_models(model_ids=["qwen3-8b-q4_k_m"]), 0)
            self.assertIsNone(store.claim_next_pending(model_id="qwen3-8b-q4_k_m"))

    def test_capture_toggle_stops_new_openai_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalLLMBenchmarkStore(
                path=str(Path(tmp) / "local_llm_benchmarks.db"),
                logger=logging.getLogger("local-llm-benchmark-test"),
            )

            store.set_capture_enabled(enabled=False)
            record_id = store.record_openai_execution(
                request=UnifiedExecutionRequest(task_family="task.classification", prompt="hello"),
                response=UnifiedExecutionResponse(provider_id="openai", model_id="gpt-5.4-nano", output_text="{}"),
            )

            payload = store.summary_payload()
            self.assertIsNone(record_id)
            self.assertFalse(payload["capture_enabled"])
            self.assertEqual(payload["comparisons"], [])

    def test_parse_structured_output_summary_is_best_effort(self):
        self.assertEqual(
            parse_structured_output_summary('{"label":"shipment","confidence":"0.95"}'),
            {"label": "shipment", "confidence": 0.95, "reasoning": None},
        )
        self.assertEqual(
            parse_structured_output_summary('```json\n{"label":"unknown","confidence":0.7,"rationale":"not enough signal"}\n```'),
            {"label": "unknown", "confidence": 0.7, "reasoning": "not enough signal"},
        )
        self.assertEqual(parse_structured_output_summary("plain text"), {"label": None, "confidence": None, "reasoning": None})
