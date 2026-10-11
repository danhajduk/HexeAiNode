import unittest

from ai_node.runtime.image_studio_body_prompt import body_preview_checkpoint, body_preview_sampling_settings, compile_body_preview_prompt


class ImageStudioBodyPromptTests(unittest.TestCase):
    def test_compiles_structured_selections_and_inherited_colors(self):
        prompt = compile_body_preview_prompt(
            selections={"build": ["athletic"], "pubic_hair": ["natural"]},
            face_selections={"skin tone": ["olive"], "hair color": ["auburn"]},
            custom_details="long fingers",
            context={"age_group": "adult (18+)", "gender_identity": "female", "visual_style": "realistic"},
        )

        self.assertIn("athletic build with natural, anatomically coherent body mass", prompt)
        self.assertIn("auburn pubic hair color, inherited from head hair", prompt)
        self.assertIn("INHERITED FACE SKIN TONE: olive", prompt)
        self.assertIn("long fingers", prompt)
        self.assertIn("real living human person", prompt)
        self.assertIn("relaxed anatomical A-pose", prompt)
        self.assertIn("feet hip-width apart", prompt)
        self.assertIn("weight distributed evenly across both legs", prompt)
        self.assertIn("palms facing inward", prompt)
        self.assertIn("extreme long shot", prompt)
        self.assertIn("all ten toes", prompt)
        self.assertIn("no more than 85 percent", prompt)
        self.assertIn("vertical canvas", prompt)
        self.assertNotIn("portrait orientation", prompt)
        self.assertLess(prompt.index("STRICT CAMERA FRAMING"), prompt.index("SELECTED BODY TRAITS"))

    def test_explicit_pubic_hair_color_overrides_inheritance(self):
        prompt = compile_body_preview_prompt(
            selections={"pubic_hair": ["natural"], "pubic_hair_color": ["black"]},
            face_selections={"hair color": ["auburn"]},
            custom_details="",
            context={},
        )
        self.assertIn("black pubic hair color", prompt)
        self.assertNotIn("auburn pubic hair color", prompt)

    def test_custom_pose_replaces_the_default_a_pose(self):
        prompt = compile_body_preview_prompt(
            selections={"build": ["athletic"]},
            face_selections={},
            custom_details="",
            context={"pose_prompt": "natural three-quarter stance with both feet fully visible"},
        )
        self.assertIn("natural three-quarter stance with both feet fully visible", prompt)
        self.assertNotIn("relaxed anatomical A-pose facing the camera squarely", prompt)

    def test_rejects_conflicting_genital_anatomy(self):
        with self.assertRaisesRegex(ValueError, "body_feature_anatomy_conflict"):
            compile_body_preview_prompt(
                selections={"vulva_description": ["natural"], "penis_description": ["average"]},
                face_selections={},
                custom_details="",
                context={},
            )

    def test_rejects_unknown_frontend_selections(self):
        with self.assertRaisesRegex(ValueError, "body_feature_option_invalid:build:robotic"):
            compile_body_preview_prompt(
                selections={"build": ["robotic"]},
                face_selections={},
                custom_details="",
                context={},
            )

    def test_numeric_breast_magnitude_overrides_categorical_size(self):
        prompt = compile_body_preview_prompt(
            selections={"breast_size": ["small"], "breast_shape": ["teardrop"]},
            face_selections={},
            custom_details="",
            context={},
            magnitudes={"breast_size": 0.72},
        )
        self.assertIn("breast anatomy: size magnitude 0.72", prompt)
        self.assertIn("large adult breast volume", prompt)
        self.assertNotIn("small adult breast volume", prompt)
        self.assertIn("teardrop adult breast contour", prompt)
        self.assertIn("shape: teardrop adult breast contour", prompt)
        self.assertNotIn("(breast shape:", prompt)

    def test_rejects_out_of_range_body_magnitude(self):
        with self.assertRaisesRegex(ValueError, "body_feature_magnitude_out_of_range:breast_size"):
            compile_body_preview_prompt(
                selections={}, face_selections={}, custom_details="", context={}, magnitudes={"breast_size": 1.1}
            )

    def test_compiles_continuous_body_magnitudes(self):
        prompt = compile_body_preview_prompt(
            selections={"butt_shape": ["round"]},
            face_selections={}, custom_details="", context={},
            magnitudes={"height": 0.8, "hip_width": 0.7, "butt_size": 0.9},
        )
        self.assertIn("height magnitude: 0.80", prompt)
        self.assertIn("hip width magnitude: 0.70", prompt)
        self.assertIn("butt size magnitude: 0.90", prompt)
        self.assertIn("round gluteal contour", prompt)

    def test_none_pubic_hair_suppresses_explicit_and_inherited_color(self):
        prompt = compile_body_preview_prompt(
            selections={"pubic_hair": ["none"], "pubic_hair_color": ["black"]},
            face_selections={"hair color": ["auburn"]}, custom_details="", context={},
        )
        self.assertNotIn("pubic hair color", prompt)

    def test_misc_no_tattoos_and_head_hair_exclusion_are_compiled(self):
        prompt = compile_body_preview_prompt(
            selections={"misc": ["no tattoos"], "butt_shape": ["heart-shaped"]}, face_selections={}, custom_details="", context={},
        )
        self.assertIn("completely tattoo-free skin", prompt)
        self.assertIn("lower-full A-shaped gluteal contour", prompt)
        self.assertNotIn("heart-shaped gluteal", prompt)
        self.assertIn("No head, scalp, face, facial hair", prompt)
        self.assertIn("no hair hangs down", prompt)

    def test_routes_explicit_adult_anatomy_to_adult_capable_checkpoint(self):
        self.assertEqual(body_preview_checkpoint({"breast_size": ["large"]}), "RealVisXL_V5.0_fp16.safetensors")
        self.assertEqual(body_preview_checkpoint({"vulva_description": ["natural"]}), "lustifySDXLNSFWSFW_v20.safetensors")
        self.assertEqual(body_preview_checkpoint({"penis_description": ["average"]}), "lustifySDXLNSFWSFW_v20.safetensors")
        self.assertEqual(body_preview_sampling_settings({"vulva_description": ["natural"]}), {
            "steps": 28,
            "cfg": 5.5,
            "lightning_strength": 0.0,
            "sampler_name": "dpmpp_2m_sde",
            "scheduler": "karras",
        })


if __name__ == "__main__":
    unittest.main()
