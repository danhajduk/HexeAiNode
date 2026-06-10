import json
import logging
import re
import tempfile
import unittest
from pathlib import Path

from ai_node.lifecycle.node_lifecycle import NodeLifecycle
from ai_node.runtime.comfyui_template_catalog import load_comfyui_template_catalog
from ai_node.runtime.node_control_api import ManualImageGenerationRequest, NodeControlState


TEMPLATE_PATH = Path("config/comfyui/templates/avatar-lustify-sdxl-inpaint/api_workflow.json")
TEMPLATE_ID = "template.avatar_lustify_sdxl_inpaint.v1"
PLACEHOLDER_PATTERN = re.compile(r"{{[^{}]+}}")
REQUIRED_PLACEHOLDERS = {
    "{{positive_prompt}}",
    "{{negative_prompt}}",
    "{{input_image}}",
    "{{mask_image}}",
    "{{mask_channel}}",
    "{{grow_mask_by}}",
    "{{checkpoint_name}}",
    "{{sampler_name}}",
    "{{scheduler}}",
    "{{seed}}",
    "{{steps}}",
    "{{cfg}}",
    "{{denoise}}",
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


class AvatarLustifyInpaintTemplateTests(unittest.TestCase):
    def test_template_uses_inpaint_checkpoint_with_source_and_mask(self):
        workflow = _template()

        self.assertEqual(workflow["1"]["inputs"]["ckpt_name"], "{{checkpoint_name}}")
        self.assertEqual(workflow["4"]["class_type"], "LoadImage")
        self.assertEqual(workflow["4"]["inputs"]["image"], "{{input_image}}")
        self.assertEqual(workflow["5"]["class_type"], "LoadImageMask")
        self.assertEqual(workflow["5"]["inputs"]["image"], "{{mask_image}}")
        self.assertEqual(workflow["5"]["inputs"]["channel"], "{{mask_channel}}")
        self.assertEqual(workflow["6"]["class_type"], "VAEEncodeForInpaint")
        self.assertEqual(workflow["6"]["inputs"]["pixels"], ["4", 0])
        self.assertEqual(workflow["6"]["inputs"]["mask"], ["5", 0])
        self.assertEqual(workflow["7"]["inputs"]["latent_image"], ["6", 0])
        self.assertEqual(
            workflow["9"]["inputs"]["filename_prefix"],
            "hexe/avatar_lustify_inpaint/{{avatar_name}}_seed{{seed}}",
        )
        self.assertEqual(_collect_placeholders(workflow), REQUIRED_PLACEHOLDERS)

    def test_manual_template_rendering_substitutes_inpaint_values(self):
        payload = load_comfyui_template_catalog(catalog_dir="config/comfyui/templates")
        template = {item["template_id"]: item for item in payload["templates"]}[TEMPLATE_ID]
        with tempfile.TemporaryDirectory() as tmp:
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("avatar-lustify-inpaint-template-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("avatar-lustify-inpaint-template-test"),
                comfyui_template_catalog_dir="config/comfyui/templates",
            )
            workflow = state._manual_image_workflow_from_template(
                template=template,
                payload=ManualImageGenerationRequest(
                    template_id=TEMPLATE_ID,
                    mode="img2img",
                    prompt="masked clothing area, black micro bikini",
                    negative_prompt="out of mask changes",
                    seed=123,
                    steps=20,
                    cfg=5.5,
                    denoise=0.68,
                    input_image="references/avatar/base.png",
                    template_variables={
                        "avatar_name": "Jane Doe",
                        "mask_image": "references/avatar/mask.png",
                        "mask_channel": "alpha",
                        "grow_mask_by": "12",
                        "sampler_name": "euler",
                        "scheduler": "normal",
                    },
                ),
                input_image="references/avatar/base.png",
            )

        self.assertEqual(workflow["1"]["inputs"]["ckpt_name"], "lustifySDXLNSFW_v20-inpainting.safetensors")
        self.assertEqual(workflow["2"]["inputs"]["text"], "masked clothing area, black micro bikini")
        self.assertEqual(workflow["3"]["inputs"]["text"], "out of mask changes")
        self.assertEqual(workflow["4"]["inputs"]["image"], "references/avatar/base.png")
        self.assertEqual(workflow["5"]["inputs"]["image"], "references/avatar/mask.png")
        self.assertEqual(workflow["5"]["inputs"]["channel"], "alpha")
        self.assertEqual(workflow["6"]["inputs"]["grow_mask_by"], 12)
        self.assertEqual(workflow["7"]["inputs"]["steps"], 20)
        self.assertEqual(workflow["7"]["inputs"]["cfg"], 5.5)
        self.assertEqual(workflow["7"]["inputs"]["denoise"], 0.68)
        self.assertEqual(workflow["7"]["inputs"]["sampler_name"], "euler")
        self.assertEqual(workflow["7"]["inputs"]["scheduler"], "normal")
        self.assertEqual(workflow["9"]["inputs"]["filename_prefix"], "hexe/avatar_lustify_inpaint/Jane_Doe_seed123")


if __name__ == "__main__":
    unittest.main()
