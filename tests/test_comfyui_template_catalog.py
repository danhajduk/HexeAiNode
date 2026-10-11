import json
import tempfile
import unittest
from pathlib import Path

from ai_node.runtime.comfyui_template_catalog import (
    load_comfyui_template_catalog,
    normalize_comfyui_template_entry,
)


class ComfyUiTemplateCatalogTests(unittest.TestCase):
    def test_load_default_depth_template_catalog(self):
        payload = load_comfyui_template_catalog(catalog_dir="config/comfyui/templates")

        self.assertTrue(payload["configured"])
        self.assertEqual(payload["schema_version"], "1.0")
        self.assertGreaterEqual(len(payload["templates"]), 19)
        templates_by_id = {template["template_id"]: template for template in payload["templates"]}
        scenery_template = templates_by_id["template.scenery_landscape.realvisxl.v1"]
        self.assertEqual(scenery_template["template_name"], "Landscape Scenery")
        self.assertEqual(scenery_template["metadata"]["domain"], "scenery")
        self.assertEqual(scenery_template["defaults"]["width"], 1344)
        self.assertEqual(scenery_template["defaults"]["height"], 768)
        self.assertEqual(scenery_template["defaults"]["steps"], 4)
        self.assertTrue(scenery_template["validation"]["valid"])
        expected_scenarios = {"scenery", "portrait", "product", "illustration", "icon", "generic"}
        paired_scenarios = {}
        for template in payload["templates"]:
            metadata = template.get("metadata") or {}
            scenario_id = metadata.get("scenario_id")
            runtime_variant = metadata.get("runtime_variant")
            if scenario_id in expected_scenarios and runtime_variant in {"cpu", "gpu"}:
                paired_scenarios.setdefault(scenario_id, set()).add(runtime_variant)
        self.assertEqual(set(paired_scenarios), expected_scenarios)
        self.assertTrue(all(variants == {"cpu", "gpu"} for variants in paired_scenarios.values()))
        cpu_scenery = templates_by_id["template.scenery_landscape.dreamshaper.v1"]
        self.assertEqual(cpu_scenery["runtime_id"], "comfyui_cpu")
        self.assertEqual(cpu_scenery["model_requirements"]["checkpoint"], "DreamShaper8_LCM.safetensors")
        self.assertTrue(cpu_scenery["validation"]["valid"])
        head_face_template = templates_by_id["template.avatar_head_face_preview.realvisxl.v1"]
        self.assertEqual(head_face_template["template_name"], "Avatar Head Face Preview")
        self.assertEqual(head_face_template["runtime_id"], "comfyui_gpu")
        self.assertEqual(head_face_template["output_scope"], "manual")
        self.assertEqual(head_face_template["model_requirements"]["checkpoint"], "RealVisXL_V5.0_fp16.safetensors")
        self.assertEqual(head_face_template["model_requirements"]["loras"], ["sdxl_lightning_4step_lora.safetensors"])
        self.assertEqual(head_face_template["metadata"]["edit_intent"], "avatar_head_face_preview")
        self.assertTrue(head_face_template["metadata"]["transparent_background"])
        self.assertEqual(head_face_template["defaults"]["width"], 512)
        self.assertEqual(head_face_template["defaults"]["height"], 512)
        self.assertEqual(head_face_template["defaults"]["cfg"], 1.2)
        self.assertEqual(head_face_template["defaults"]["bg_removal_model"], "birefnet.safetensors")
        self.assertEqual(head_face_template["model_requirements"]["other"]["background_removal"], "birefnet.safetensors")
        body_preview_template = templates_by_id["template.avatar_upper_torso_preview.realvisxl.v1"]
        self.assertEqual(body_preview_template["defaults"]["pose_reference_image"], "system/neutral-a-pose-openpose.png")
        self.assertEqual(body_preview_template["defaults"]["pose_strength"], 0.8)
        self.assertEqual(body_preview_template["defaults"]["pose_end"], 0.7)
        self.assertEqual(body_preview_template["model_requirements"]["controlnets"], ["controlnet-openpose-sdxl-1.0.safetensors"])
        self.assertIn("ControlNetApplyAdvanced", body_preview_template["model_requirements"]["other"]["nodes"])
        body_preview_workflow = json.loads(Path(body_preview_template["api_workflow_path"]).read_text(encoding="utf-8"))
        self.assertEqual(body_preview_workflow["9"]["class_type"], "LoadImage")
        self.assertEqual(body_preview_workflow["10"]["class_type"], "ResizeAndPadImage")
        self.assertEqual(body_preview_workflow["11"]["class_type"], "ControlNetLoader")
        self.assertEqual(body_preview_workflow["12"]["class_type"], "ControlNetApplyAdvanced")
        self.assertEqual(body_preview_workflow["6"]["inputs"]["positive"], ["12", 0])
        self.assertEqual(body_preview_workflow["6"]["inputs"]["negative"], ["12", 1])
        template = templates_by_id["template.avatar_body_depth_reference_transparent.realvisxl.v1"]
        self.assertEqual(template["template_name"], "Simple Avatar Generation")
        self.assertEqual(template["runtime_id"], "comfyui_gpu")
        self.assertEqual(template["output_scope"], "normal")
        self.assertEqual(template["model_requirements"]["checkpoint"], "RealVisXL_V5.0_fp16.safetensors")
        self.assertEqual(template["model_requirements"]["controlnets"], ["controlnet-depth-sdxl-1.0-fp16.safetensors"])
        self.assertIn("positive_prompt", [item["name"] for item in template["variables"]])
        self.assertTrue(template["validation"]["valid"])
        self.assertEqual(template["metadata"]["input_mode"], "text")
        self.assertTrue(template["metadata"]["transparent_background"])
        self.assertEqual(template["metadata"]["edit_intent"], "simple_avatar_generation_with_pulid_identity_body_depth_transparent_background")
        self.assertEqual(template["defaults"]["cfg"], 1.2)
        self.assertEqual(template["defaults"]["pulid_model"], "ip-adapter_pulid_sdxl_fp16.safetensors")
        self.assertEqual(
            template["model_requirements"]["other"]["identity_strength"],
            "pulid_face_identity",
        )
        synthetic_adult_template = templates_by_id["template.synthetic_adult_body_reference.realvisxl.v1"]
        self.assertEqual(synthetic_adult_template["runtime_id"], "comfyui_gpu")
        self.assertEqual(synthetic_adult_template["output_scope"], "manual")
        self.assertTrue(synthetic_adult_template["metadata"]["synthetic_adult_only"])
        self.assertEqual(synthetic_adult_template["metadata"]["reference_roles"], ["face", "body"])
        self.assertEqual(synthetic_adult_template["defaults"]["output_directory"], "hexe/nsfw")
        self.assertTrue(synthetic_adult_template["validation"]["valid"])
        self.assertEqual(template["model_requirements"]["other"]["identity_model"], "ip-adapter_pulid_sdxl_fp16.safetensors")
        self.assertEqual(template["model_requirements"]["other"]["insightface_model"], "antelopev2")
        self.assertEqual(template["model_requirements"]["other"]["body_preservation"], "depth_anything_v2_controlnet")
        profile_template = templates_by_id["template.avatar_profile_depth_pulid.realvisxl.v1"]
        self.assertEqual(profile_template["template_name"], "Avatar Profile Generation")
        self.assertIn("body_depth_image", [item["name"] for item in profile_template["variables"]])
        self.assertIn("pose_reference_image", [item["name"] for item in profile_template["variables"]])
        self.assertEqual(
            profile_template["model_requirements"]["controlnets"],
            ["controlnet-depth-sdxl-1.0-fp16.safetensors", "controlnet-openpose-sdxl-1.0.safetensors"],
        )
        self.assertEqual(
            profile_template["model_requirements"]["other"]["body_preservation"],
            "precomputed_depth_map_controlnet",
        )
        self.assertEqual(profile_template["model_requirements"]["other"]["pose_preservation"], "openpose_controlnet")
        inpaint_template = templates_by_id["template.avatar_lustify_sdxl_inpaint.v1"]
        self.assertEqual(inpaint_template["template_name"], "Avatar Clothing Inpaint")
        self.assertEqual(
            inpaint_template["model_requirements"]["checkpoint"],
            "lustifySDXLNSFW_v20-inpainting.safetensors",
        )
        self.assertEqual(inpaint_template["metadata"]["input_mode"], "image")
        self.assertEqual(inpaint_template["metadata"]["edit_intent"], "avatar_clothing_or_body_masked_inpaint")
        self.assertIn("input_image", [item["name"] for item in inpaint_template["variables"]])
        self.assertIn("mask_image", [item["name"] for item in inpaint_template["variables"]])
        self.assertEqual(inpaint_template["defaults"]["steps"], 24)
        base_template = templates_by_id["template.avatar_base_unclothed_lustify_inpaint.v1"]
        self.assertEqual(base_template["template_name"], "Avatar Base Unclothed Inpaint")
        self.assertEqual(base_template["metadata"]["domain"], "avatar_inpaint")
        self.assertEqual(base_template["metadata"]["edit_intent"], "synthetic_avatar_unclothed_base_body_inpaint")
        self.assertIn("source_image", [item["name"] for item in base_template["variables"]])
        self.assertEqual(
            base_template["defaults"]["source_image"],
            "references/avatar/avatar_seed2923980995547288489_rgb_00001_source.png",
        )
        self.assertEqual(
            base_template["defaults"]["mask_image"],
            "references/avatar/avatar_seed2923980995547288489_unclothed_mask.png",
        )
        self.assertIn("continuous bare skin", base_template["defaults"]["positive_prompt"])
        self.assertIn("garment outline", base_template["defaults"]["negative_prompt"])
        self.assertEqual(base_template["defaults"]["grow_mask_by"], 20)
        self.assertEqual(base_template["defaults"]["steps"], 32)
        self.assertEqual(base_template["defaults"]["cfg"], 7.5)
        self.assertEqual(base_template["defaults"]["denoise"], 0.9)

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
