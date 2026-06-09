import json
import logging
import re
import tempfile
import unittest
from pathlib import Path

from ai_node.lifecycle.node_lifecycle import NodeLifecycle
from ai_node.runtime.comfyui_template_catalog import load_comfyui_template_catalog
from ai_node.runtime.node_control_api import ManualImageGenerationRequest, NodeControlState


TEMPLATE_PATH = Path("config/comfyui/templates/avatar-identity-reference-transparent-realvisxl/api_workflow.json")
TEMPLATE_ID = "template.avatar_identity_reference_transparent.realvisxl.v1"
REQUIRED_NODE_IDS = {
    "1",
    "2",
    "3",
    "4",
    "5",
    "6",
    "7",
    "8",
    "9",
    "10",
    "11",
    "12",
    "13",
    "14",
    "15",
    "16",
    "17",
    "18",
    "19",
    "20",
}
EXPECTED_CLASS_TYPES = {
    "1": "CheckpointLoaderSimple",
    "2": "LoraLoader",
    "3": "EmptyLatentImage",
    "4": "CLIPTextEncode",
    "5": "CLIPTextEncode",
    "6": "LoadImage",
    "7": "ImageScale",
    "8": "VAEEncode",
    "9": "ReferenceLatent",
    "10": "LoadImage",
    "11": "ImageScale",
    "12": "VAEEncode",
    "13": "ReferenceLatent",
    "14": "KSampler",
    "15": "VAEDecode",
    "16": "SaveImage",
    "17": "LoadBackgroundRemovalModel",
    "18": "RemoveBackground",
    "19": "JoinImageWithAlpha",
    "20": "InvertMask",
}
REQUIRED_PLACEHOLDERS = {
    "{{width}}",
    "{{height}}",
    "{{positive_prompt}}",
    "{{negative_prompt}}",
    "{{face_reference_image}}",
    "{{body_reference_image}}",
    "{{seed}}",
    "{{steps}}",
    "{{cfg}}",
    "{{bg_removal_model}}",
    "{{avatar_name}}",
}
PLACEHOLDER_PATTERN = re.compile(r"{{[^{}]+}}")


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


def _contains_placeholder(value) -> bool:
    return bool(_collect_placeholders(value))


class AvatarIdentityTransparentTemplateTests(unittest.TestCase):
    def test_template_is_valid_comfyui_api_json_with_required_nodes(self):
        workflow = _template()

        self.assertEqual(set(workflow), REQUIRED_NODE_IDS)
        for node_id, class_type in EXPECTED_CLASS_TYPES.items():
            self.assertEqual(workflow[node_id]["class_type"], class_type)
            self.assertIsInstance(workflow[node_id]["inputs"], dict)

    def test_template_preserves_critical_links_and_placeholders(self):
        workflow = _template()

        self.assertEqual(workflow["2"]["inputs"]["model"], ["1", 0])
        self.assertEqual(workflow["2"]["inputs"]["clip"], ["1", 1])
        self.assertEqual(workflow["4"]["inputs"]["clip"], ["2", 1])
        self.assertEqual(workflow["5"]["inputs"]["clip"], ["2", 1])
        self.assertEqual(workflow["9"]["inputs"]["conditioning"], ["4", 0])
        self.assertEqual(workflow["13"]["inputs"]["conditioning"], ["9", 0])
        self.assertEqual(workflow["14"]["inputs"]["positive"], ["13", 0])
        self.assertEqual(workflow["14"]["inputs"]["negative"], ["5", 0])
        self.assertEqual(workflow["14"]["inputs"]["latent_image"], ["3", 0])
        self.assertEqual(workflow["15"]["inputs"]["samples"], ["14", 0])
        self.assertEqual(workflow["19"]["inputs"]["image"], ["15", 0])
        self.assertEqual(workflow["19"]["inputs"]["alpha"], ["20", 0])
        self.assertEqual(workflow["16"]["inputs"]["images"], ["19", 0])
        self.assertEqual(
            workflow["16"]["inputs"]["filename_prefix"],
            "hexe/avatar_identity_transparent/{{avatar_name}}_seed{{seed}}",
        )

        self.assertEqual(workflow["3"]["inputs"]["width"], "{{width}}")
        self.assertEqual(workflow["3"]["inputs"]["height"], "{{height}}")
        self.assertEqual(workflow["14"]["inputs"]["seed"], "{{seed}}")
        self.assertEqual(workflow["14"]["inputs"]["steps"], "{{steps}}")
        self.assertEqual(workflow["14"]["inputs"]["cfg"], "{{cfg}}")
        self.assertEqual(_collect_placeholders(workflow), REQUIRED_PLACEHOLDERS)

    def test_manual_template_rendering_substitutes_values_and_coerces_runtime_numbers(self):
        payload = load_comfyui_template_catalog(catalog_dir="config/comfyui/templates")
        template = {item["template_id"]: item for item in payload["templates"]}[TEMPLATE_ID]
        with tempfile.TemporaryDirectory() as tmp:
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("avatar-template-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("avatar-template-test"),
                comfyui_template_catalog_dir="config/comfyui/templates",
            )
            workflow = state._manual_image_workflow_from_template(
                template=template,
                payload=ManualImageGenerationRequest(
                    template_id=TEMPLATE_ID,
                    mode="txt2img",
                    prompt="content-agnostic avatar portrait",
                    negative_prompt="low quality",
                    seed=123,
                    width=640,
                    height=960,
                    steps=4,
                    cfg=1.0,
                    template_variables={
                        "avatar_name": "Jane Doe",
                        "face_reference_image": "references/avatar/jane_face.png",
                        "body_reference_image": "references/avatar/jane_body.png",
                        "bg_removal_model": "birefnet.safetensors",
                    },
                ),
                input_image="",
            )

        self.assertFalse(_contains_placeholder(workflow))
        self.assertEqual(workflow["3"]["inputs"]["width"], 640)
        self.assertEqual(workflow["3"]["inputs"]["height"], 960)
        self.assertEqual(workflow["14"]["inputs"]["seed"], 123)
        self.assertEqual(workflow["14"]["inputs"]["steps"], 4)
        self.assertEqual(workflow["14"]["inputs"]["cfg"], 1.0)
        self.assertEqual(workflow["6"]["inputs"]["image"], "references/avatar/jane_face.png")
        self.assertEqual(workflow["10"]["inputs"]["image"], "references/avatar/jane_body.png")
        self.assertEqual(workflow["17"]["inputs"]["bg_removal_name"], "birefnet.safetensors")
        self.assertEqual(workflow["16"]["inputs"]["filename_prefix"], "hexe/avatar_identity_transparent/Jane_Doe_seed123")

    def test_manual_template_rendering_reports_missing_required_reference(self):
        payload = load_comfyui_template_catalog(catalog_dir="config/comfyui/templates")
        template = {item["template_id"]: item for item in payload["templates"]}[TEMPLATE_ID]
        with tempfile.TemporaryDirectory() as tmp:
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("avatar-template-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("avatar-template-test"),
                comfyui_template_catalog_dir="config/comfyui/templates",
            )
            with self.assertRaisesRegex(ValueError, "manual_image_variable_required:body_reference_image"):
                state._manual_image_workflow_from_template(
                    template=template,
                    payload=ManualImageGenerationRequest(
                        template_id=TEMPLATE_ID,
                        mode="txt2img",
                        prompt="content-agnostic avatar portrait",
                        template_variables={
                            "face_reference_image": "references/avatar/jane_face.png",
                        },
                    ),
                    input_image="",
                )


if __name__ == "__main__":
    unittest.main()
