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
    def test_depth_is_preprocessed_and_applied_without_openpose(self):
        workflow = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))

        self.assertEqual(workflow["24"]["inputs"]["image"], "{{depth_reference_image}}")
        self.assertEqual(workflow["26"]["class_type"], "DepthAnythingV2Preprocessor")
        self.assertEqual(workflow["26"]["inputs"]["image"], ["25", 0])
        self.assertEqual(workflow["28"]["inputs"]["image"], ["26", 0])
        self.assertEqual(workflow["28"]["inputs"]["strength"], "{{depth_strength}}")
        self.assertNotIn("23", workflow)
        self.assertEqual(workflow["6"]["inputs"]["positive"], ["28", 0])
        self.assertEqual(workflow["6"]["inputs"]["negative"], ["28", 1])

    def test_catalog_declares_workflow_placeholders_and_depth_controlnet(self):
        workflow = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))
        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        template = next(item for item in catalog["templates"] if item["template_id"] == TEMPLATE_ID)
        variables = {item["name"] for item in template["variables"]}

        self.assertTrue(_placeholders(workflow).issubset({f"{{{{{name}}}}}" for name in variables}))
        self.assertEqual(
            template["model_requirements"]["controlnets"],
            ["controlnet-depth-sdxl-1.0-fp16.safetensors"],
        )
        self.assertEqual(template["defaults"]["depth_strength"], 0.55)
        self.assertEqual(template["defaults"]["depth_end"], 1.0)

    def test_face_pose_catalog_contains_only_reliable_identity_poses(self):
        catalog = json.loads(FACE_PROMPTS_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            [pose["pose_id"] for pose in catalog["poses"]],
            ["front_neutral", "front_smile", "three_quarter_left", "three_quarter_right"],
        )


if __name__ == "__main__":
    unittest.main()
