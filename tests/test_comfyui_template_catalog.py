import json
import tempfile
import unittest
from pathlib import Path

from ai_node.runtime.comfyui_template_catalog import (
    load_comfyui_template_catalog,
    normalize_comfyui_template_entry,
)


class ComfyUiTemplateCatalogTests(unittest.TestCase):
    def test_load_default_weather_template_catalog(self):
        payload = load_comfyui_template_catalog(catalog_dir="config/comfyui/templates")

        self.assertTrue(payload["configured"])
        self.assertEqual(payload["schema_version"], "1.0")
        self.assertGreaterEqual(len(payload["templates"]), 9)
        templates_by_id = {template["template_id"]: template for template in payload["templates"]}
        template = templates_by_id["template.weather.realvisxl.v1"]
        self.assertEqual(template["runtime_id"], "comfyui_gpu")
        self.assertEqual(template["output_scope"], "normal")
        self.assertEqual(template["model_requirements"]["checkpoint"], "RealVisXL_V5.0_fp16.safetensors")
        self.assertIn("positive_prompt", [item["name"] for item in template["variables"]])
        self.assertTrue(template["validation"]["valid"])
        self.assertEqual(templates_by_id["template.txt2img.realvisxl.v1"]["metadata"]["input_mode"], "text")
        img2img = templates_by_id["template.img2img.realvisxl.v1"]
        self.assertEqual(img2img["metadata"]["input_mode"], "image")
        self.assertIn("input_image", [item["name"] for item in img2img["variables"]])
        transparent_avatar = templates_by_id["template.avatar_identity_reference_transparent.realvisxl.v1"]
        self.assertTrue(transparent_avatar["metadata"]["transparent_background"])
        self.assertEqual(
            transparent_avatar["model_requirements"]["other"]["identity_strength"],
            "fallback_reference_latent_not_faceid",
        )

    def test_validate_rejects_default_without_variable(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            workflow = base / "api.json"
            workflow.write_text(json.dumps({"1": {"class_type": "SaveImage", "inputs": {}}}), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "unknown_template_default"):
                normalize_comfyui_template_entry(
                    {
                        "template_id": "template.bad",
                        "runtime_id": "comfyui_gpu",
                        "api_workflow_path": "api.json",
                        "variables": [{"name": "prompt"}],
                        "defaults": {"missing": "value"},
                    },
                    catalog_dir=base,
                )

    def test_validate_rejects_missing_workflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "api_workflow_not_found"):
                normalize_comfyui_template_entry(
                    {
                        "template_id": "template.bad",
                        "runtime_id": "comfyui_gpu",
                        "api_workflow_path": "missing.json",
                    },
                    catalog_dir=Path(tmp),
                )


if __name__ == "__main__":
    unittest.main()
