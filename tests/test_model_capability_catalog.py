import logging
import tempfile
import unittest
from pathlib import Path

from ai_node.providers.model_capability_catalog import (
    OpenAIModelCapabilityClassifier,
    ProviderModelCapabilitiesStore,
    RECOMMENDED_FOR_OPTIONS,
    build_openai_capability_classification_prompt,
    select_openai_classification_model,
    validate_provider_model_capability_payload,
)
from ai_node.providers.openai_model_catalog import OpenAIProviderModelCatalogEntry


class ModelCapabilityCatalogTests(unittest.IsolatedAsyncioTestCase):
    def test_selects_nano_then_mini_then_smallest_base_model(self):
        self.assertEqual(
            select_openai_classification_model(
                [
                    OpenAIProviderModelCatalogEntry(model_id="gpt-5-mini", family="llm", discovered_at="2026-03-13T00:00:00Z"),
                    OpenAIProviderModelCatalogEntry(model_id="gpt-5-nano", family="llm", discovered_at="2026-03-13T00:00:00Z"),
                ]
            ),
            "gpt-5-nano",
        )
        self.assertEqual(
            select_openai_classification_model(
                [
                    OpenAIProviderModelCatalogEntry(model_id="gpt-5-mini", family="llm", discovered_at="2026-03-13T00:00:00Z"),
                    OpenAIProviderModelCatalogEntry(model_id="gpt-5-pro", family="llm", discovered_at="2026-03-13T00:00:00Z"),
                ]
            ),
            "gpt-5-mini",
        )
        self.assertEqual(
            select_openai_classification_model(
                [
                    OpenAIProviderModelCatalogEntry(model_id="gpt-5.4", family="llm", discovered_at="2026-03-13T00:00:00Z"),
                    OpenAIProviderModelCatalogEntry(model_id="gpt-4.1", family="llm", discovered_at="2026-03-13T00:00:00Z"),
                ]
            ),
            "gpt-4.1",
        )

    def test_prompt_includes_allowed_recommended_values(self):
        models = [
            OpenAIProviderModelCatalogEntry(model_id="gpt-5-mini", family="llm", discovered_at="2026-03-13T00:00:00Z"),
            OpenAIProviderModelCatalogEntry(model_id="whisper-1", family="speech_to_text", discovered_at="2026-03-13T00:00:00Z"),
        ]
        _system_prompt, user_prompt = build_openai_capability_classification_prompt(
            models=models,
            classification_model="gpt-5-mini",
        )
        self.assertIn("gpt-5-mini (llm)", user_prompt)
        self.assertIn("whisper-1 (speech_to_text)", user_prompt)
        self.assertIn(", ".join(RECOMMENDED_FOR_OPTIONS), user_prompt)

    def test_validate_rejects_invalid_recommended_for_values(self):
        models = [OpenAIProviderModelCatalogEntry(model_id="gpt-5-mini", family="llm", discovered_at="2026-03-13T00:00:00Z")]
        with self.assertRaisesRegex(ValueError, "classification_recommended_for_invalid"):
            validate_provider_model_capability_payload(
                payload={
                    "models": [
                        {
                            "model_id": "gpt-5-mini",
                            "family": "llm",
                            "reasoning": True,
                            "vision": False,
                            "image_generation": False,
                            "audio_input": False,
                            "audio_output": False,
                            "realtime": False,
                            "tool_calling": True,
                            "structured_output": True,
                            "long_context": True,
                            "coding_strength": "high",
                            "speed_tier": "medium",
                            "cost_tier": "medium",
                            "recommended_for": ["bad_value"],
                        }
                    ]
                },
                expected_models=models,
            )

    def test_validate_accepts_valid_json_output_and_stabilizes_order(self):
        models = [
            OpenAIProviderModelCatalogEntry(model_id="whisper-1", family="speech_to_text", discovered_at="2026-03-13T00:00:00Z"),
            OpenAIProviderModelCatalogEntry(model_id="gpt-5-mini", family="llm", discovered_at="2026-03-13T00:00:00Z"),
        ]
        payload = {
            "models": [
                {
                    "model_id": "whisper-1",
                    "family": "speech_to_text",
                    "reasoning": False,
                    "vision": False,
                    "image_generation": False,
                    "audio_input": True,
                    "audio_output": False,
                    "realtime": False,
                    "tool_calling": False,
                    "structured_output": False,
                    "long_context": False,
                    "coding_strength": "low",
                    "speed_tier": "high",
                    "cost_tier": "low",
                    "recommended_for": ["speech_recognition", "speech_recognition"],
                },
                {
                    "model_id": "gpt-5-mini",
                    "family": "llm",
                    "reasoning": True,
                    "vision": False,
                    "image_generation": False,
                    "audio_input": False,
                    "audio_output": False,
                    "realtime": False,
                    "tool_calling": True,
                    "structured_output": True,
                    "long_context": True,
                    "coding_strength": "high",
                    "speed_tier": "medium",
                    "cost_tier": "medium",
                    "recommended_for": ["coding", "chat", "coding"],
                },
            ]
        }
        validated = validate_provider_model_capability_payload(payload=payload, expected_models=models)
        self.assertEqual([entry.model_id for entry in validated], ["gpt-5-mini", "whisper-1"])
        self.assertEqual(validated[0].recommended_for, ["chat", "coding"])

    def test_validate_rejects_invalid_schema_payloads(self):
        models = [OpenAIProviderModelCatalogEntry(model_id="gpt-5-mini", family="llm", discovered_at="2026-03-13T00:00:00Z")]
        with self.assertRaisesRegex(ValueError, "classification_payload_invalid"):
            validate_provider_model_capability_payload(payload=[], expected_models=models)
        with self.assertRaisesRegex(ValueError, "classification_models_missing"):
            validate_provider_model_capability_payload(payload={}, expected_models=models)

    def test_validate_rejects_invalid_controlled_vocabulary_for_tiers(self):
        models = [OpenAIProviderModelCatalogEntry(model_id="gpt-5-mini", family="llm", discovered_at="2026-03-13T00:00:00Z")]
        with self.assertRaisesRegex(ValueError, "classification_coding_strength_invalid"):
            validate_provider_model_capability_payload(
                payload={
                    "models": [
                        {
                            "model_id": "gpt-5-mini",
                            "family": "llm",
                            "reasoning": True,
                            "vision": False,
                            "image_generation": False,
                            "audio_input": False,
                            "audio_output": False,
                            "realtime": False,
                            "tool_calling": True,
                            "structured_output": True,
                            "long_context": True,
                            "coding_strength": "expert",
                            "speed_tier": "medium",
                            "cost_tier": "medium",
                            "recommended_for": ["chat"],
                        }
                    ]
                },
                expected_models=models,
            )

    def test_validate_rejects_unknown_feature_flags(self):
        models = [OpenAIProviderModelCatalogEntry(model_id="gpt-5-mini", family="llm", discovered_at="2026-03-13T00:00:00Z")]
        with self.assertRaisesRegex(ValueError, "classification_feature_unknown"):
            validate_provider_model_capability_payload(
                payload={
                    "models": [
                        {
                            "model_id": "gpt-5-mini",
                            "family": "llm",
                            "reasoning": True,
                            "vision": False,
                            "image_generation": False,
                            "audio_input": False,
                            "audio_output": False,
                            "realtime": False,
                            "tool_calling": True,
                            "structured_output": True,
                            "long_context": True,
                            "coding_strength": "high",
                            "speed_tier": "medium",
                            "cost_tier": "medium",
                            "recommended_for": ["chat"],
                            "feature_flags": {"unknown_feature": True},
                        }
                    ]
                },
                expected_models=models,
            )

    async def test_classifier_saves_batch_results(self):
        models = [
            OpenAIProviderModelCatalogEntry(model_id="gpt-5-mini", family="llm", discovered_at="2026-03-13T00:00:00Z"),
            OpenAIProviderModelCatalogEntry(model_id="whisper-1", family="speech_to_text", discovered_at="2026-03-13T00:00:00Z"),
        ]

        async def fake_execute(_classification_model: str, _system_prompt: str, _user_prompt: str) -> str:
            return """
            {
              "models": [
                {
                  "model_id": "gpt-5-mini",
                  "family": "llm",
                  "reasoning": true,
                  "vision": false,
                  "image_generation": false,
                  "audio_input": false,
                  "audio_output": false,
                  "realtime": false,
                  "tool_calling": true,
                  "structured_output": true,
                  "long_context": true,
                  "coding_strength": "high",
                  "speed_tier": "medium",
                  "cost_tier": "medium",
                  "recommended_for": ["chat", "coding"]
                },
                {
                  "model_id": "whisper-1",
                  "family": "speech_to_text",
                  "reasoning": false,
                  "vision": false,
                  "image_generation": false,
                  "audio_input": true,
                  "audio_output": false,
                  "realtime": false,
                  "tool_calling": false,
                  "structured_output": false,
                  "long_context": false,
                  "coding_strength": "low",
                  "speed_tier": "high",
                  "cost_tier": "low",
                  "recommended_for": ["speech_recognition"]
                }
              ]
            }
            """

        with tempfile.TemporaryDirectory() as tmp:
            store = ProviderModelCapabilitiesStore(
                path=str(Path(tmp) / "provider_model_capabilities.json"),
                logger=logging.getLogger("model-capability-test"),
            )
            classifier = OpenAIModelCapabilityClassifier(
                logger=logging.getLogger("model-capability-test"),
                store=store,
                execute_batch=fake_execute,
            )
            snapshot = await classifier.classify_and_save(models=models)
            self.assertEqual(snapshot.classification_model, "gpt-5-mini")
            self.assertEqual(len(snapshot.entries), 2)
            self.assertTrue(Path(tmp, "provider_model_capabilities.json").exists())


if __name__ == "__main__":
    unittest.main()
