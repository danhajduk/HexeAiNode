import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_node.runtime.local_scheduler_policy import plan_local_scheduler_request
from ai_node.runtime.local_scheduler_state import LocalSchedulerStateStore
from ai_node.runtime.service_manager import UserSystemdServiceManager


class ModelResidencySchedulerTests(unittest.TestCase):
    def test_scheduler_status_separates_container_and_model_state(self):
        services = {
            "local_llm": {
                "state": "running",
                "model_residency": {
                    "container_state": "running",
                    "model_state": "loaded",
                    "loaded_model": "qwen3-8b-q4_k_m",
                    "loaded_models": ["qwen3-8b-q4_k_m"],
                },
            },
            "vision_llm": {
                "state": "running",
                "model_residency": {
                    "container_state": "running",
                    "model_state": "loaded",
                    "loaded_model": "qwen2.5-vl-3b",
                    "loaded_models": ["qwen2.5-vl-3b"],
                },
            },
            "comfyui_gpu": {
                "state": "running",
                "model_residency_status": {
                    "container_state": "running",
                    "model_state": "unloaded",
                    "loaded_model": None,
                    "loaded_models": [],
                },
            },
        }

        with tempfile.TemporaryDirectory() as tmp:
            status = LocalSchedulerStateStore(state_dir=Path(tmp)).status_from_services(services=services)
        components = {item["component_id"]: item for item in status["components"]}

        self.assertEqual(components["text_llm"]["container_state"], "running")
        self.assertEqual(components["text_llm"]["model_state"], "loaded")
        self.assertEqual(components["vision_llm"]["model_state"], "loaded")
        self.assertEqual(components["visual_gpu"]["observed_state"], "running")
        self.assertEqual(components["visual_gpu"]["container_state"], "running")
        self.assertEqual(components["visual_gpu"]["model_state"], "unloaded")
        self.assertEqual(components["training_runtime"]["model_state"], "unloaded")

    def test_vision_request_ignores_visual_container_when_visual_model_unloaded(self):
        decision = plan_local_scheduler_request(
            scheduler_status={
                "components": [
                    {"component_id": "text_llm", "observed_state": "running", "model_state": "loaded", "idle": {"in_flight": 0, "queued": 0}},
                    {"component_id": "vision_llm", "observed_state": "running", "model_state": "unloaded", "idle": {"in_flight": 0, "queued": 0}},
                    {"component_id": "visual_gpu", "observed_state": "running", "model_state": "unloaded", "idle": {"in_flight": 0, "queued": 0}},
                    {"component_id": "visual_cpu", "observed_state": "unloaded", "model_state": "unloaded", "idle": {"in_flight": 0, "queued": 0}},
                    {"component_id": "training_runtime", "observed_state": "unloaded", "model_state": "unloaded", "idle": {"in_flight": 0, "queued": 0}},
                ]
            },
            component_id="vision_llm",
            importance="normal",
        )

        self.assertEqual(decision["decision"], "allowed")
        self.assertEqual(decision["affected_components"], [])

    def test_vision_request_waits_for_active_visual_model(self):
        decision = plan_local_scheduler_request(
            scheduler_status={
                "components": [
                    {"component_id": "text_llm", "observed_state": "running", "model_state": "loaded", "idle": {"in_flight": 0, "queued": 0}},
                    {"component_id": "vision_llm", "observed_state": "running", "model_state": "unloaded", "idle": {"in_flight": 0, "queued": 0}},
                    {"component_id": "visual_gpu", "observed_state": "running", "model_state": "loaded", "idle": {"in_flight": 1, "queued": 0}},
                    {"component_id": "visual_cpu", "observed_state": "unloaded", "model_state": "unloaded", "idle": {"in_flight": 0, "queued": 0}},
                    {"component_id": "training_runtime", "observed_state": "unloaded", "model_state": "unloaded", "idle": {"in_flight": 0, "queued": 0}},
                ]
            },
            component_id="vision_llm",
            importance="normal",
        )

        self.assertEqual(decision["decision"], "waiting_for_idle")
        self.assertEqual(decision["reason"], "visual_gpu_busy")
        self.assertIn(
            {"action": "wait_for_idle", "component_id": "visual_gpu", "reason": "vision_requires_visual_gpu_unloaded"},
            decision["actions"],
        )

    def test_training_request_unloads_incompatible_model_residency(self):
        decision = plan_local_scheduler_request(
            scheduler_status={
                "gpu_resources": {"memory_free_mib": 0},
                "components": [
                    {"component_id": "text_llm", "observed_state": "running", "model_state": "loaded", "idle": {"in_flight": 0, "queued": 0}, "usage_statistics": {"current": {"vram_mib": 5500}}},
                    {"component_id": "vision_llm", "observed_state": "running", "model_state": "loaded", "idle": {"in_flight": 0, "queued": 0}, "usage_statistics": {"current": {"vram_mib": 4100}}},
                    {"component_id": "visual_gpu", "observed_state": "running", "model_state": "loaded", "idle": {"in_flight": 0, "queued": 0}, "usage_statistics": {"current": {"vram_mib": 5120}}},
                    {"component_id": "visual_cpu", "observed_state": "unloaded", "model_state": "unloaded", "idle": {"in_flight": 0, "queued": 0}},
                    {"component_id": "training_runtime", "observed_state": "unloaded", "model_state": "unloaded", "idle": {"in_flight": 0, "queued": 0}},
                ],
            },
            component_id="training_runtime",
            importance="high",
        )

        self.assertEqual(decision["decision"], "needs_unload")
        self.assertEqual(decision["affected_components"], ["text_llm", "vision_llm", "visual_gpu"])

    def test_visual_model_load_does_not_stop_running_container(self):
        manager = UserSystemdServiceManager(logger=logging.getLogger("model-residency-scheduler-test"))

        with (
            patch.object(manager, "_run_comfyui_control") as fake_control,
            patch.object(manager, "stop_comfyui_webui") as fake_stop_webui,
            patch.object(manager, "stop") as fake_stop,
        ):
            result = manager._execute_model_residency_load("visual_gpu")

        self.assertEqual(result["result"], "model_loaded")
        fake_control.assert_called_once_with("gpu", "ready")
        fake_stop_webui.assert_not_called()
        fake_stop.assert_not_called()

    def test_text_unload_uses_container_stop_fallback_only_inside_scheduler(self):
        manager = UserSystemdServiceManager(logger=logging.getLogger("model-residency-scheduler-test"))

        with (
            patch.object(
                manager,
                "unload_model",
                return_value={"status": "blocked", "component_id": "text_llm", "result": "unsupported"},
            ) as fake_unload_model,
            patch.object(manager, "stop", return_value={"target": "local_llm", "result": "stopped"}) as fake_stop,
        ):
            result = manager._execute_model_residency_unload("text_llm")

        self.assertEqual(result["result"], "container_stopped_fallback")
        fake_unload_model.assert_called_once()
        fake_stop.assert_called_once_with(target="local_llm")


if __name__ == "__main__":
    unittest.main()
