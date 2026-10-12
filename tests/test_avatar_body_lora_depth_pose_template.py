import json
import unittest
from pathlib import Path


CATALOG_PATH = Path("config/comfyui/templates/catalog.json")
WORKFLOW_PATH = Path("config/comfyui/templates/avatar-body-lora-depth-pose-realvisxl/api_workflow.json")
TEMPLATE_ID = "template.avatar_body_lora_depth_pose.realvisxl.v1"


class AvatarBodyLoraDepthPoseTemplateTests(unittest.TestCase):
    def test_workflow_combines_body_depth_and_openpose_without_pulid(self):
        workflow = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))

        classes = [node["class_type"] for node in workflow.values()]
        self.assertIn("DepthAnythingV2Preprocessor", classes)
        self.assertEqual(classes.count("ControlNetApplyAdvanced"), 2)
        self.assertNotIn("ApplyPulidAdvanced", classes)
        self.assertEqual(workflow["30"]["inputs"]["model"], ["2", 0])
        self.assertEqual(workflow["32"]["inputs"]["images"], ["31", 0])

    def test_catalog_registers_body_specific_defaults(self):
        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        template = next(item for item in catalog["templates"] if item["template_id"] == TEMPLATE_ID)

        self.assertEqual(template["api_workflow_path"], "avatar-body-lora-depth-pose-realvisxl/api_workflow.json")
        self.assertEqual(template["defaults"]["width"], 768)
        self.assertEqual(template["defaults"]["height"], 1536)
        self.assertEqual(template["defaults"]["body_depth_strength"], 0.55)
        self.assertEqual(template["defaults"]["pose_strength"], 0.65)


if __name__ == "__main__":
    unittest.main()
