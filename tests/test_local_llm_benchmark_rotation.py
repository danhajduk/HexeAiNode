import json
import logging
import tempfile
import unittest
from pathlib import Path

from unittest.mock import patch

from ai_node.runtime.local_llm_benchmark_rotation import LocalLLMBenchmarkRotationRunner


class _FakeWorker:
    def __init__(self):
        self.calls = []

    async def run_pending_for_model(self, *, model_id: str, limit: int = 1):
        self.calls.append({"model_id": model_id, "limit": limit})
        return {"model_id": model_id, "processed": 2, "completed": 2, "failed": 0, "errors": []}


class LocalLLMBenchmarkRotationRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_rotation_loads_next_model_and_runs_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "models.json"
            config_path.write_text(
                json.dumps(
                    {
                        "models": [
                            {
                                "id": "qwen3-8b-q4_k_m",
                                "repo": "Qwen/Qwen3-8B-GGUF",
                                "quantization": "Q4_K_M",
                                "ctx_size": 4096,
                            },
                            {
                                "id": "gemma-3-12b-it-q4_k_m",
                                "repo": "bartowski/google_gemma-3-12b-it-GGUF",
                                "quantization": "Q4_K_M",
                                "ctx_size": 4096,
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            commands = []
            activity_statuses = []

            async def fake_runner(command, env):
                commands.append({"command": command, "env": env})
                activity_statuses.append(runner._activity_status)
                return {"returncode": 0, "stdout": "ready", "stderr": ""}

            worker = _FakeWorker()
            runner = LocalLLMBenchmarkRotationRunner(
                worker=worker,
                logger=logging.getLogger("local-llm-rotation-test"),
                model_config_path=str(config_path),
                state_path=str(Path(tmp) / "rotation.json"),
                control_script="scripts/llamacpp-control.sh",
                model_ids=["qwen3-8b-q4_k_m", "gemma-3-12b-it-q4_k_m"],
                batch_limit=7,
                command_runner=fake_runner,
            )

            with patch.object(LocalLLMBenchmarkRotationRunner, "_live_model_id", return_value=None):
                first = await runner.run_once()
                second = await runner.run_once()
            with patch.object(LocalLLMBenchmarkRotationRunner, "_live_model_id", return_value="gemma-3-12b-it-q4_k_m"):
                loaded = await runner.run_loaded_model()
            with patch.object(LocalLLMBenchmarkRotationRunner, "_live_model_id", return_value="live-model"):
                status = runner.status_payload()

            self.assertEqual(first["model_id"], "qwen3-8b-q4_k_m")
            self.assertEqual(second["model_id"], "gemma-3-12b-it-q4_k_m")
            self.assertIsNotNone(first["switch_result"]["swap_duration_seconds"])
            self.assertEqual(loaded["model_id"], "gemma-3-12b-it-q4_k_m")
            self.assertEqual(loaded["mode"], "loaded_model")
            self.assertEqual(status["current_model_id"], "live-model")
            self.assertEqual(status["activity_status"], "idle")
            self.assertEqual(status["ready_timeout_seconds"], 420)
            self.assertEqual(status["last_swap"]["model_id"], "gemma-3-12b-it-q4_k_m")
            self.assertIsNone(status["last_swap"]["error"])
            self.assertEqual([item["id"] for item in status["models"]], ["qwen3-8b-q4_k_m", "gemma-3-12b-it-q4_k_m"])
            self.assertEqual(
                worker.calls,
                [
                    {"model_id": "qwen3-8b-q4_k_m", "limit": 7},
                    {"model_id": "gemma-3-12b-it-q4_k_m", "limit": 7},
                    {"model_id": "gemma-3-12b-it-q4_k_m", "limit": 7},
                ],
            )
            self.assertEqual(activity_statuses, ["swapping", "swapping"])
            self.assertEqual(commands[0]["command"], ["scripts/llamacpp-control.sh", "ready"])
            self.assertEqual(commands[0]["env"]["LLAMACPP_MODEL_HF"], "Qwen/Qwen3-8B-GGUF:Q4_K_M")
            self.assertEqual(commands[0]["env"]["LLAMACPP_READY_TIMEOUT_S"], "420")
            self.assertEqual(commands[1]["env"]["LLAMACPP_MODEL_ALIAS"], "gemma-3-12b-it-q4_k_m")

    async def test_rotation_prefers_live_model_when_selecting_next_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "models.json"
            config_path.write_text(
                json.dumps(
                    {
                        "models": [
                            {"id": "qwen3-8b-q4_k_m"},
                            {"id": "gemma-3-12b-it-q4_k_m"},
                            {"id": "mistral-nemo-instruct-2407-q4_k_m"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            state_path = Path(tmp) / "rotation.json"
            state_path.write_text(json.dumps({"current_model_id": "qwen3-8b-q4_k_m"}), encoding="utf-8")
            commands = []

            async def fake_runner(command, env):
                commands.append({"command": command, "env": env})
                return {"returncode": 0, "stdout": "ready", "stderr": ""}

            runner = LocalLLMBenchmarkRotationRunner(
                worker=_FakeWorker(),
                logger=logging.getLogger("local-llm-rotation-test"),
                model_config_path=str(config_path),
                state_path=str(state_path),
                model_ids=["qwen3-8b-q4_k_m", "gemma-3-12b-it-q4_k_m", "mistral-nemo-instruct-2407-q4_k_m"],
                command_runner=fake_runner,
            )

            with patch.object(LocalLLMBenchmarkRotationRunner, "_live_model_id", return_value="gemma-3-12b-it-q4_k_m"):
                result = await runner.run_once()

            self.assertEqual(result["model_id"], "mistral-nemo-instruct-2407-q4_k_m")
            self.assertEqual(commands[0]["env"]["LLAMACPP_MODEL_ALIAS"], "mistral-nemo-instruct-2407-q4_k_m")
