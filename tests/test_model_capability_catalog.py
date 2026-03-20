import json
import logging
import tempfile
import unittest
from pathlib import Path

from ai_node.providers.model_capability_catalog import (
    OpenAIModelCapabilityClassifier,
    ProviderModelCapabilitiesStore,
    build_deterministic_entries,
)
from ai_node.providers.openai_model_catalog import OpenAIProviderModelCatalogEntry


class ModelCapabilityCatalogTests(unittest.IsolatedAsyncioTestCase):
    def test_build_deterministic_entries_assigns_family_defaults_and_tiers(self):
        entries = build_deterministic_entries(
            models=[
                OpenAIProviderModelCatalogEntry(model_id="gpt-5.4-pro", family="llm", discovered_at="2026-03-13T00:00:00Z"),
                OpenAIProviderModelCatalogEntry(model_id="gpt-5-mini", family="llm", discovered_at="2026-03-13T00:00:00Z"),
                OpenAIProviderModelCatalogEntry(model_id="gpt-5-nano", family="llm", discovered_at="2026-03-13T00:00:00Z"),
                OpenAIProviderModelCatalogEntry(model_id="whisper-1", family="speech_to_text", discovered_at="2026-03-13T00:00:00Z"),
                OpenAIProviderModelCatalogEntry(model_id="gpt-image-1", family="image_generation", discovered_at="2026-03-13T00:00:00Z"),
            ]
        )

        by_id = {entry.model_id: entry for entry in entries}

        pro = by_id["gpt-5.4-pro"]
        self.assertTrue(pro.text_generation)
        self.assertTrue(pro.reasoning)
        self.assertTrue(pro.vision)
        self.assertEqual(pro.coding_strength, "high")
        self.assertEqual(pro.speed_tier, "slow")
        self.assertEqual(pro.cost_tier, "high")
        self.assertTrue(pro.feature_flags["chat"])
        self.assertTrue(pro.feature_flags["tool_calling"])
        self.assertTrue(pro.feature_flags["code_generation"])
        self.assertFalse(pro.feature_flags["ocr"])

        mini = by_id["gpt-5-mini"]
        self.assertEqual(mini.coding_strength, "medium")
        self.assertEqual(mini.speed_tier, "fast")
        self.assertEqual(mini.cost_tier, "low")

        nano = by_id["gpt-5-nano"]
        self.assertEqual(nano.coding_strength, "low")
        self.assertFalse(nano.feature_flags["code_generation"])
        self.assertTrue(nano.feature_flags["code_explanation"])

        whisper = by_id["whisper-1"]
        self.assertTrue(whisper.audio_input)
        self.assertFalse(whisper.text_generation)
        self.assertEqual(whisper.coding_strength, "none")
        self.assertEqual(whisper.speed_tier, "fast")
        self.assertEqual(whisper.cost_tier, "low")
        self.assertTrue(whisper.feature_flags["speech_to_text"])

        image = by_id["gpt-image-1"]
        self.assertTrue(image.image_generation)
        self.assertFalse(image.text_generation)
        self.assertTrue(image.feature_flags["image_generation"])
        self.assertFalse(image.feature_flags["image_editing"])

    def test_build_deterministic_entries_preserves_selected_models_outside_representative_subset(self):
        entries = build_deterministic_entries(
            models=[
                OpenAIProviderModelCatalogEntry(model_id="gpt-5.4-mini", family="llm", discovered_at="2026-03-13T00:00:00Z"),
                OpenAIProviderModelCatalogEntry(model_id="gpt-5-mini", family="llm", discovered_at="2026-03-13T00:00:00Z"),
                OpenAIProviderModelCatalogEntry(model_id="gpt-5.4-nano", family="llm", discovered_at="2026-03-13T00:00:00Z"),
                OpenAIProviderModelCatalogEntry(model_id="gpt-5-nano", family="llm", discovered_at="2026-03-13T00:00:00Z"),
            ],
            preserve_model_ids=["gpt-5-mini", "gpt-5-nano"],
        )

        self.assertEqual(
            [entry.model_id for entry in entries],
            ["gpt-5-mini", "gpt-5-nano", "gpt-5.4-mini", "gpt-5.4-nano"],
        )

    async def test_classifier_saves_deterministic_snapshot(self):
        models = [
            OpenAIProviderModelCatalogEntry(model_id="gpt-5-mini", family="llm", discovered_at="2026-03-13T00:00:00Z"),
            OpenAIProviderModelCatalogEntry(model_id="whisper-1", family="speech_to_text", discovered_at="2026-03-13T00:00:00Z"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            store = ProviderModelCapabilitiesStore(
                path=str(Path(tmp) / "provider_model_classifications.json"),
                logger=logging.getLogger("model-capability-test"),
                legacy_path=str(Path(tmp) / "provider_model_capabilities.json"),
            )
            classifier = OpenAIModelCapabilityClassifier(
                logger=logging.getLogger("model-capability-test"),
                store=store,
            )
            snapshot = await classifier.classify_and_save(models=models)
            self.assertEqual(snapshot.classification_model, "deterministic_rules")
            self.assertIsNotNone(snapshot.classified_at)
            self.assertEqual([entry.model_id for entry in snapshot.entries], ["gpt-5-mini", "whisper-1"])
            self.assertTrue(Path(tmp, "provider_model_classifications.json").exists())

    def test_store_migrates_legacy_payload_using_deterministic_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            legacy_path = Path(tmp) / "provider_model_capabilities.json"
            legacy_path.write_text(
                json.dumps(
                    {
                        "provider_id": "openai",
                        "updated_at": "2026-03-14T00:00:00Z",
                        "classification_model": "gpt-5-mini",
                        "entries": [
                            {
                                "model_id": "gpt-5-mini",
                                "family": "llm",
                                "text_generation": False,
                                "reasoning": False,
                                "vision": False,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            store = ProviderModelCapabilitiesStore(
                path=str(Path(tmp) / "provider_model_classifications.json"),
                logger=logging.getLogger("model-capability-test"),
                legacy_path=str(legacy_path),
            )

            migrated = store.load()
            self.assertIsNotNone(migrated)
            self.assertEqual(migrated.classification_model, "deterministic_rules")
            self.assertEqual(migrated.entries[0].model_id, "gpt-5-mini")
            self.assertTrue(migrated.entries[0].text_generation)
            self.assertTrue(migrated.entries[0].reasoning)
            self.assertTrue(Path(tmp, "provider_model_classifications.json").exists())


if __name__ == "__main__":
    unittest.main()
