import logging
import tempfile
import unittest
from pathlib import Path

from ai_node.providers.openai_model_catalog import (
    OpenAIProviderModelCatalogStore,
    build_openai_provider_model_catalog,
    classify_openai_model_family,
)


class OpenAIProviderModelCatalogTests(unittest.TestCase):
    def test_classify_supported_families(self):
        self.assertEqual(classify_openai_model_family("gpt-5.4-mini"), "llm")
        self.assertEqual(classify_openai_model_family("gpt-image-1-mini"), "image_generation")
        self.assertEqual(classify_openai_model_family("sora-2"), "video_generation")
        self.assertEqual(classify_openai_model_family("gpt-realtime-1.5"), "realtime_voice")
        self.assertEqual(classify_openai_model_family("whisper-1"), "speech_to_text")
        self.assertEqual(classify_openai_model_family("tts-hd-1"), "text_to_speech")
        self.assertEqual(classify_openai_model_family("text-embedding-3-small"), "embeddings")
        self.assertEqual(classify_openai_model_family("omni-moderation-2024-09-26"), "moderation")

    def test_filter_excludes_preview_latest_and_snapshot_variants(self):
        snapshot = build_openai_provider_model_catalog(
            model_ids=[
                "gpt-5.4-mini",
                "gpt-5.4-mini",
                "gpt-5.4-mini-2026-03-05",
                "gpt-5.4-preview",
                "gpt-5-chat-latest",
            ]
        )
        self.assertEqual([entry.model_id for entry in snapshot.models], ["gpt-5.4-mini"])

    def test_store_persists_enabled_state_across_refreshes(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = OpenAIProviderModelCatalogStore(
                path=str(Path(tmp) / "provider_models.json"),
                logger=logging.getLogger("openai-model-catalog-test"),
            )
            first = store.save_from_model_ids(model_ids=["gpt-5.4-mini"])
            first.models[0].enabled = True
            Path(tmp, "provider_models.json").write_text(first.model_dump_json(indent=2), encoding="utf-8")

            second = store.save_from_model_ids(model_ids=["gpt-5.4-mini", "whisper-1"])

            self.assertEqual(len(second.models), 2)
            self.assertTrue(next(entry for entry in second.models if entry.model_id == "gpt-5.4-mini").enabled)


if __name__ == "__main__":
    unittest.main()
