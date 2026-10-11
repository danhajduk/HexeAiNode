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
