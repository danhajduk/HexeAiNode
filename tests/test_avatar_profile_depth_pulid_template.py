import json
import logging
import re
import tempfile
import unittest
from pathlib import Path

from ai_node.lifecycle.node_lifecycle import NodeLifecycle
from ai_node.runtime.comfyui_template_catalog import load_comfyui_template_catalog
from ai_node.runtime.node_control_api import ManualImageGenerationRequest, NodeControlState


TEMPLATE_PATH = Path("config/comfyui/templates/avatar-profile-depth-pulid-realvisxl/api_workflow.json")
TEMPLATE_ID = "template.avatar_profile_depth_pulid.realvisxl.v1"
PLACEHOLDER_PATTERN = re.compile(r"{{[^{}]+}}")
REQUIRED_PLACEHOLDERS = {
    "{{width}}",
    "{{height}}",
    "{{positive_prompt}}",
    "{{negative_prompt}}",
    "{{face_reference_image}}",
    "{{body_depth_image}}",
    "{{pose_reference_image}}",
    "{{face_strength}}",
    "{{pulid_model}}",
    "{{pulid_provider}}",
    "{{pulid_projection}}",
    "{{pulid_fidelity}}",
    "{{pulid_noise}}",
    "{{pulid_start_at}}",
    "{{pulid_end_at}}",
    "{{body_depth_strength}}",
    "{{body_depth_start}}",
    "{{body_depth_end}}",
    "{{body_depth_controlnet}}",
    "{{pose_strength}}",
    "{{pose_start}}",
    "{{pose_end}}",
    "{{pose_controlnet}}",
    "{{seed}}",
    "{{steps}}",
    "{{cfg}}",
    "{{denoise}}",
    "{{bg_removal_model}}",
    "{{avatar_name}}",
}


def _template() -> dict:
    return json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))


def _collect_placeholders(value) -> set[str]:
    placeholders: set[str] = set()
    if isinstance(value, dict):
        for item in value.values():
            placeholders.update(_collect_placeholders(item))
    elif isinstance(value, list):
        for item in value:
            placeholders.update(_collect_placeholders(item))
    elif isinstance(value, str):
        placeholders.update(PLACEHOLDER_PATTERN.findall(value))
    return placeholders


class AvatarProfileDepthPulidTemplateTests(unittest.TestCase):
    def test_template_uses_saved_body_depth_map_without_depth_preprocessor(self):
        workflow = _template()

        self.assertNotIn("25", workflow)
        self.assertEqual(workflow["10"]["class_type"], "LoadImage")
        self.assertEqual(workflow["10"]["inputs"]["image"], "{{body_depth_image}}")
        self.assertEqual(workflow["11"]["class_type"], "ResizeAndPadImage")
        self.assertEqual(workflow["11"]["inputs"]["image"], ["10", 0])
        self.assertEqual(workflow["27"]["inputs"]["image"], ["11", 0])
        self.assertEqual(workflow["32"]["class_type"], "LoadImage")
        self.assertEqual(workflow["32"]["inputs"]["image"], "{{pose_reference_image}}")
        self.assertEqual(workflow["33"]["class_type"], "ResizeAndPadImage")
        self.assertEqual(workflow["33"]["inputs"]["image"], ["32", 0])
        self.assertEqual(workflow["34"]["inputs"]["control_net_name"], "{{pose_controlnet}}")
        self.assertEqual(workflow["35"]["class_type"], "ControlNetApplyAdvanced")
        self.assertEqual(workflow["35"]["inputs"]["positive"], ["27", 0])
        self.assertEqual(workflow["35"]["inputs"]["negative"], ["27", 1])
        self.assertEqual(workflow["35"]["inputs"]["image"], ["33", 0])
        self.assertEqual(workflow["35"]["inputs"]["strength"], "{{pose_strength}}")
        self.assertEqual(workflow["14"]["inputs"]["positive"], ["35", 0])
        self.assertEqual(workflow["14"]["inputs"]["negative"], ["35", 1])
        self.assertEqual(workflow["31"]["inputs"]["image"], ["6", 0])
        self.assertEqual(
            workflow["24"]["inputs"]["filename_prefix"],
            "hexe/avatar_profile_generation/{{avatar_name}}_seed{{seed}}",
        )
        self.assertEqual(_collect_placeholders(workflow), REQUIRED_PLACEHOLDERS)

    def test_manual_template_rendering_substitutes_profile_values(self):
        payload = load_comfyui_template_catalog(catalog_dir="config/comfyui/templates")
        template = {item["template_id"]: item for item in payload["templates"]}[TEMPLATE_ID]
        with tempfile.TemporaryDirectory() as tmp:
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("avatar-profile-template-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("avatar-profile-template-test"),
                comfyui_template_catalog_dir="config/comfyui/templates",
            )
            workflow = state._manual_image_workflow_from_template(
                template=template,
                payload=ManualImageGenerationRequest(
                    template_id=TEMPLATE_ID,
                    mode="txt2img",
                    prompt="same Jane, full body profile prompt",
                    negative_prompt="low quality",
                    seed=123,
                    width=512,
                    height=768,
                    template_variables={
                        "avatar_name": "Jane Doe",
                        "face_reference_image": "avatar_profiles/Jane/refs/face/front.png",
                        "body_depth_image": "avatar_profiles/Jane/refs/body_depth_map/depth.png",
                        "pose_reference_image": "avatar_profiles/Jane/refs/pose/openpose.png",
                        "face_strength": "0.72",
                        "body_depth_strength": "0.82",
                        "body_depth_start": "0.02",
                        "body_depth_end": "0.88",
                        "pose_strength": "0.66",
                        "pose_start": "0.03",
                        "pose_end": "0.75",
                    },
                ),
                input_image="",
            )

        self.assertEqual(workflow["3"]["inputs"]["width"], 512)
        self.assertEqual(workflow["3"]["inputs"]["height"], 768)
        self.assertEqual(workflow["6"]["inputs"]["image"], "avatar_profiles/Jane/refs/face/front.png")
        self.assertEqual(workflow["10"]["inputs"]["image"], "avatar_profiles/Jane/refs/body_depth_map/depth.png")
        self.assertEqual(workflow["32"]["inputs"]["image"], "avatar_profiles/Jane/refs/pose/openpose.png")
        self.assertEqual(workflow["31"]["inputs"]["weight"], 0.72)
        self.assertEqual(workflow["27"]["inputs"]["strength"], 0.82)
        self.assertEqual(workflow["27"]["inputs"]["start_percent"], 0.02)
        self.assertEqual(workflow["27"]["inputs"]["end_percent"], 0.88)
        self.assertEqual(workflow["35"]["inputs"]["strength"], 0.66)
        self.assertEqual(workflow["35"]["inputs"]["start_percent"], 0.03)
        self.assertEqual(workflow["35"]["inputs"]["end_percent"], 0.75)
        self.assertEqual(workflow["24"]["inputs"]["filename_prefix"], "hexe/avatar_profile_generation/Jane_Doe_seed123")


if __name__ == "__main__":
    unittest.main()
