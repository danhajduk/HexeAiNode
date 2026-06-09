import logging
import tempfile
import unittest
from pathlib import Path

from ai_node.persistence.image_generation_template_store import (
    ImageGenerationTemplateStateStore,
    create_image_generation_template_registration,
    create_image_generation_template_state,
    normalize_image_generation_template_state,
    normalize_template_version,
)


class ImageGenerationTemplateStateStoreTests(unittest.TestCase):
    def test_create_state_defaults_to_empty_template_registry(self):
        payload = create_image_generation_template_state()

        self.assertEqual(payload["schema_version"], "1.0")
        self.assertEqual(payload["templates"], [])

    def test_save_and_load_registered_comfyui_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "image_generation_template_state.json"
            store = ImageGenerationTemplateStateStore(
                path=str(path),
                logger=logging.getLogger("image-generation-template-store-test"),
            )
            payload = create_image_generation_template_state()
            payload["templates"] = [
                create_image_generation_template_registration(
                    template_id="template.weather.v1",
                    service_id="weather-node",
                    template_name="Weather Image",
                    version="v1",
                    template_version={
                        "runtime_id": "comfyui_gpu",
                        "api_workflow_path": "runtime/templates/weather/api.json",
                        "ui_workflow_path": "runtime/templates/weather/ui.json",
                        "variables": ["forecast", "style"],
                        "defaults": {"style": "editorial"},
                    },
                )
            ]

            saved = store.save(payload)
            loaded = store.load_or_create()

            self.assertTrue(path.exists())
            self.assertEqual(saved["templates"][0]["template_id"], "template.weather.v1")
            self.assertEqual(loaded["templates"][0]["current_version"], "v1")
            self.assertEqual(loaded["templates"][0]["versions"][0]["runtime_id"], "comfyui_gpu")
            self.assertEqual(loaded["templates"][0]["versions"][0]["variables"], ["forecast", "style"])

    def test_normalize_rejects_invalid_runtime(self):
        with self.assertRaisesRegex(ValueError, "invalid_template_runtime"):
            normalize_template_version(
                {
                    "runtime_id": "stable-diffusion-webui",
                    "api_workflow_path": "runtime/templates/weather/api.json",
                }
            )

    def test_normalize_state_rejects_empty_versions(self):
        with self.assertRaisesRegex(ValueError, "api_workflow_path_required"):
            normalize_image_generation_template_state(
                {
                    "schema_version": "1.0",
                    "templates": [{"template_id": "template.bad", "service_id": "svc", "versions": [{}]}],
                }
            )


if __name__ == "__main__":
    unittest.main()
