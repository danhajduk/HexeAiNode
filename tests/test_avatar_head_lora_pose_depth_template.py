import json
import re
import unittest
from pathlib import Path


WORKFLOW_PATH = Path(
    "config/comfyui/templates/avatar-head-lora-pose-depth-control-realvisxl/api_workflow.json"
)
CATALOG_PATH = Path("config/comfyui/templates/catalog.json")
FACE_PROMPTS_PATH = Path("config/image-studio/face-lora-prompts.json")
TEMPLATE_ID = "template.avatar_head_lora_pose_depth_control.realvisxl.v1"


def _placeholders(value: object) -> set[str]:
    if isinstance(value, dict):
        return {item for child in value.values() for item in _placeholders(child)}
    if isinstance(value, list):
        return {item for child in value for item in _placeholders(child)}
    if isinstance(value, str):
        return set(re.findall(r"{{[^{}]+}}", value))
    return set()


class AvatarHeadLoraPoseDepthTemplateTests(unittest.TestCase):
    def test_depth_is_preprocessed_and_applied_before_openpose(self):
        workflow = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))

        self.assertEqual(workflow["24"]["inputs"]["image"], "{{depth_reference_image}}")
        self.assertEqual(workflow["26"]["class_type"], "DepthAnythingV2Preprocessor")
        self.assertEqual(workflow["26"]["inputs"]["image"], ["25", 0])
        self.assertEqual(workflow["28"]["inputs"]["image"], ["26", 0])
        self.assertEqual(workflow["28"]["inputs"]["strength"], "{{depth_strength}}")
        self.assertEqual(workflow["23"]["inputs"]["positive"], ["28", 0])
        self.assertEqual(workflow["23"]["inputs"]["negative"], ["28", 1])
        self.assertEqual(workflow["6"]["inputs"]["positive"], ["23", 0])

    def test_catalog_declares_every_workflow_placeholder_and_both_controlnets(self):
        workflow = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))
        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        template = next(item for item in catalog["templates"] if item["template_id"] == TEMPLATE_ID)
        variables = {item["name"] for item in template["variables"]}

        self.assertEqual(_placeholders(workflow), {f"{{{{{name}}}}}" for name in variables})
        self.assertEqual(
            template["model_requirements"]["controlnets"],
            [
                "controlnet-openpose-sdxl-1.0.safetensors",
                "controlnet-depth-sdxl-1.0-fp16.safetensors",
            ],
        )
        self.assertEqual(template["defaults"]["depth_strength"], 0.25)

    def test_vertical_pose_catalog_selects_clean_depth_sources(self):
        catalog = json.loads(FACE_PROMPTS_PATH.read_text(encoding="utf-8"))
        poses = {item["pose_id"]: item for item in catalog["poses"]}

        for pose_id in ("slight_down", "slight_up"):
            pose = poses[pose_id]
            self.assertEqual(pose["depth_strength"], 0.25)
            source = Path("config/image-studio/lora-pose-guides") / pose[
                "depth_guide_image"
            ].removeprefix("system/lora-pose-guides/")
            self.assertTrue(source.is_file())


if __name__ == "__main__":
    unittest.main()
