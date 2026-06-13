import unittest
import tempfile
from pathlib import Path

from ai_node.execution.queue_contract import residency_component_for_lane
from ai_node.runtime.local_scheduler_policy import plan_local_scheduler_request
from ai_node.runtime.local_scheduler_state import component_definitions, observed_component_state


class LocalSchedulerVisualLaneTests(unittest.TestCase):
    def test_visual_gpu_and_cpu_are_distinct_scheduler_components(self):
        components = {item["component_id"]: item for item in component_definitions()}

        self.assertIn("visual_gpu", components)
        self.assertIn("visual_cpu", components)
        self.assertEqual(components["visual_gpu"]["display_name"], "Visual Runtime GPU")
        self.assertEqual(components["visual_cpu"]["display_name"], "Visual Runtime CPU")
        self.assertEqual(residency_component_for_lane("visual_gpu"), "visual_gpu")
        self.assertEqual(residency_component_for_lane("visual_cpu"), "visual_cpu")
        self.assertIsNone(residency_component_for_lane("cloud"))

    def test_visual_gpu_reserves_vram_and_unloads_vision_when_needed(self):
        scheduler_status = {
            "gpu_resources": {"memory_free_mib": 1024},
            "components": [
                {"component_id": "text_llm", "observed_state": "running", "model_state": "loaded", "idle": {"in_flight": 0, "queued": 0}, "usage_statistics": {"current": {"vram_mib": 4096}}},
                {"component_id": "vision_llm", "observed_state": "running", "model_state": "loaded", "idle": {"in_flight": 0, "queued": 0}, "usage_statistics": {"current": {"vram_mib": 4096}}},
                {"component_id": "visual_gpu", "observed_state": "unloaded", "model_state": "unloaded", "idle": {"in_flight": 0, "queued": 0}},
                {"component_id": "visual_cpu", "observed_state": "unloaded", "model_state": "unloaded", "idle": {"in_flight": 0, "queued": 0}},
                {"component_id": "training_runtime", "observed_state": "unloaded", "model_state": "unloaded", "idle": {"in_flight": 0, "queued": 0}},
            ],
        }

        decision = plan_local_scheduler_request(
            scheduler_status=scheduler_status,
            component_id="visual_gpu",
            importance="high",
        )

        self.assertEqual(decision["decision"], "needs_unload")
        self.assertIn("vision_llm", decision["affected_components"])
        self.assertIn(
            {"action": "unload", "component_id": "vision_llm", "reason": "visual_gpu_requires_vision_llm_vram"},
            decision["actions"],
        )

    def test_visual_gpu_does_not_unload_vision_container_when_model_is_unloaded(self):
        scheduler_status = {
            "gpu_resources": {"memory_free_mib": 1024},
            "components": [
                {"component_id": "text_llm", "observed_state": "running", "model_state": "loaded", "idle": {"in_flight": 0, "queued": 0}, "usage_statistics": {"current": {"vram_mib": 4096}}},
                {"component_id": "vision_llm", "observed_state": "running", "model_state": "unloaded", "idle": {"in_flight": 0, "queued": 0}, "usage_statistics": {"current": {"vram_mib": 0}}},
                {"component_id": "visual_gpu", "observed_state": "running", "model_state": "unloaded", "idle": {"in_flight": 0, "queued": 0}},
                {"component_id": "visual_cpu", "observed_state": "unloaded", "model_state": "unloaded", "idle": {"in_flight": 0, "queued": 0}},
                {"component_id": "training_runtime", "observed_state": "unloaded", "model_state": "unloaded", "idle": {"in_flight": 0, "queued": 0}},
            ],
        }

        decision = plan_local_scheduler_request(
            scheduler_status=scheduler_status,
            component_id="visual_gpu",
            importance="high",
        )

        self.assertEqual(decision["decision"], "needs_unload")
        self.assertEqual(decision["affected_components"], ["text_llm"])
        self.assertNotIn("vision_llm", decision["affected_components"])

    def test_visual_cpu_does_not_reserve_gpu_vram(self):
        scheduler_status = {
            "gpu_resources": {"memory_free_mib": 0},
            "components": [
                {"component_id": "text_llm", "observed_state": "running", "idle": {"in_flight": 0, "queued": 0}, "usage_statistics": {"current": {"vram_mib": 4096}}},
                {"component_id": "vision_llm", "observed_state": "running", "idle": {"in_flight": 0, "queued": 0}, "usage_statistics": {"current": {"vram_mib": 4096}}},
                {"component_id": "visual_gpu", "observed_state": "unloaded", "idle": {"in_flight": 0, "queued": 0}},
                {"component_id": "visual_cpu", "observed_state": "unloaded", "idle": {"in_flight": 0, "queued": 0}},
                {"component_id": "training_runtime", "observed_state": "unloaded", "idle": {"in_flight": 0, "queued": 0}},
            ],
        }

        decision = plan_local_scheduler_request(
            scheduler_status=scheduler_status,
            component_id="visual_cpu",
            importance="normal",
        )

        self.assertEqual(decision["decision"], "allowed")
        self.assertEqual(decision["reason"], "compatible")
        self.assertEqual(decision["affected_components"], [])

    def test_observed_visual_lanes_read_separate_comfyui_runtime_services(self):
        services = {
            "comfyui_gpu": {"service_id": "comfyui_gpu", "state": "running", "pid": 123, "vram_mib": 5120},
            "comfyui_cpu": {"service_id": "comfyui_cpu", "state": "stopped", "pid": None},
        }

        gpu = observed_component_state(component_id="visual_gpu", services=services)
        cpu = observed_component_state(component_id="visual_cpu", services=services)

        self.assertEqual(gpu["observed_state"], "running")
        self.assertEqual(cpu["observed_state"], "unloaded")
        self.assertEqual(gpu["resource_snapshot"]["vram_mib"], 5120)

    def test_observed_visual_lane_includes_model_residency_state(self):
        services = {
            "comfyui_gpu": {
                "service_id": "comfyui_gpu",
                "state": "running",
                "pid": 123,
                "model_residency_status": {
                    "container_state": "running",
                    "model_state": "unloaded",
                    "loaded_models": [],
                },
            },
        }

        from ai_node.runtime.local_scheduler_state import LocalSchedulerStateStore

        with tempfile.TemporaryDirectory() as tmp:
            payload = LocalSchedulerStateStore(state_dir=Path(tmp)).status_from_services(services=services)
        components = {item["component_id"]: item for item in payload["components"]}

        self.assertEqual(components["visual_gpu"]["observed_state"], "running")
        self.assertEqual(components["visual_gpu"]["container_state"], "running")
        self.assertEqual(components["visual_gpu"]["model_state"], "unloaded")

    def test_scheduler_model_residency_falls_back_to_observed_state(self):
        services = {
            "gpu_exclusive": {
                "sd_scripts_training_active": True,
            },
        }

        from ai_node.runtime.local_scheduler_state import LocalSchedulerStateStore

        with tempfile.TemporaryDirectory() as tmp:
            payload = LocalSchedulerStateStore(state_dir=Path(tmp)).status_from_services(services=services)
        components = {item["component_id"]: item for item in payload["components"]}

        self.assertEqual(components["training_runtime"]["observed_state"], "running")
        self.assertEqual(components["training_runtime"]["model_state"], "loaded")


if __name__ == "__main__":
    unittest.main()
