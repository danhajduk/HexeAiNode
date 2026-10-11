import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "gpu-dashboard.py"
SPEC = importlib.util.spec_from_file_location("gpu_dashboard", SCRIPT_PATH)
gpu_dashboard = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(gpu_dashboard)


class GpuDashboardTests(unittest.TestCase):
    def test_current_job_is_compact_and_follows_backend_status(self):
        sample = {
            "name": "Test GPU",
            "utilization.gpu": 50,
            "utilization.memory": 25,
            "memory.used": 100,
            "memory.total": 1000,
            "power.draw": 50,
            "power.limit": 100,
            "temperature.gpu": 45,
        }
        queue = {
            "state": "online",
            "running": 1,
            "pending": 0,
            "job_state": "running",
            "queue_number": 103,
            "prompt_id": "hidden-prompt",
            "steps": 4,
            "cfg": 1.16,
            "sampler": "euler / sgm_uniform",
            "seed": 7767315626558688864,
            "checkpoint": "hidden-model",
            "output_prefix": "hidden-output",
        }
        backend = {"available": False, "state": "idle"}

        output = gpu_dashboard.render(sample, queue, backend, {"available": True, "queue_active": True}, False)

        self.assertLess(output.index("IMAGE STUDIO BACKEND"), output.index("CURRENT COMFYUI JOB"))
        self.assertIn("State     running · queue #103", output)
        self.assertIn("Sampling  4 steps · CFG 1.16 · euler / sgm_uniform", output)
        self.assertIn("Seed      7767315626558688864", output)
        self.assertNotIn("Prompt ID", output)
        self.assertNotIn("hidden-model", output)
        self.assertNotIn("hidden-output", output)
        self.assertNotIn("Clocks", output)
        self.assertNotIn("History", output)
        header_lines = output.splitlines()[:7]
        self.assertEqual(header_lines[0].split()[0:4], ["HEXE", "GPU", "+", "COMFYUI"])
        self.assertTrue(header_lines[1].startswith("Compute"))
        self.assertTrue(header_lines[6].startswith("ComfyUI"))
        self.assertNotIn("GPU       Test GPU", output)

    def test_idle_timer_uses_persisted_session_activity(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_path = Path(temporary_directory) / "session.json"
            session_path.write_text(
                json.dumps(
                    {
                        "last_active_epoch": gpu_dashboard.time.time() - 125,
                        "idle_timeout_seconds": 3600,
                    }
                ),
                encoding="utf-8",
            )
            queue = {"running": 0, "pending": 0}

            session = gpu_dashboard.comfy_session(str(session_path), queue)

            self.assertTrue(session["available"])
            self.assertGreaterEqual(session["idle_seconds"], 125)
            self.assertEqual(gpu_dashboard.duration(session["idle_seconds"]), "00:02:05")
            self.assertEqual(gpu_dashboard.duration(session["idle_timeout_seconds"]), "01:00:00")

    def test_image_studio_backend_correlates_local_and_comfyui_state(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            profile_dir = Path(temporary_directory) / "Hexe"
            profile_dir.mkdir()
            profile_path = profile_dir / "profile.json"
            profile = {
                "name": "Hexe",
                "prompt_workspaces": {
                    "head_face": {
                        "lora_dataset": {
                            "active_pose_id": "front_smile",
                            "status": "creating_pose_batch",
                            "updated_at": "2026-10-11T10:00:00+00:00",
                            "dispatch": {"status": "waiting_for_completed_import"},
                            "poses": [
                                {
                                    "pose_id": "front_smile",
                                    "label": "Front Smile",
                                    "items": [
                                        {"status": "completed", "approved": True},
                                        {"status": "local_queued"},
                                    ],
                                }
                            ],
                        }
                    }
                },
            }
            profile_path.write_text(json.dumps(profile), encoding="utf-8")

            local = gpu_dashboard.image_studio_backend(temporary_directory, {"job_state": "idle"})
            self.assertEqual(local["state"], "local queue waiting")
            self.assertEqual(local["local_queued"], 1)
            self.assertEqual(local["completed"], 1)

            profile["prompt_workspaces"]["head_face"]["lora_dataset"]["poses"][0]["items"][1] = {
                "status": "submitted",
                "prompt_id": "prompt-1",
                "placeholder": True,
            }
            profile_path.write_text(json.dumps(profile), encoding="utf-8")
            rendering = gpu_dashboard.image_studio_backend(temporary_directory, {"prompt_id": "prompt-1"})
            self.assertEqual(rendering["state"], "rendering")

            importing = gpu_dashboard.image_studio_backend(temporary_directory, {"job_state": "idle"})
            self.assertEqual(importing["state"], "importing output")


if __name__ == "__main__":
    unittest.main()
