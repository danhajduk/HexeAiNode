import unittest

from ai_node.runtime.image_studio_body_prompt import compile_body_preview_prompt


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

    def test_explicit_pubic_hair_color_overrides_inheritance(self):
        prompt = compile_body_preview_prompt(
            selections={"pubic_hair": ["natural"], "pubic_hair_color": ["black"]},
            face_selections={"hair color": ["auburn"]},
            custom_details="",
            context={},
        )
        self.assertIn("black pubic hair color", prompt)
        self.assertNotIn("auburn pubic hair color", prompt)

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


if __name__ == "__main__":
    unittest.main()
