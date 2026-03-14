import logging
import tempfile
import unittest
from pathlib import Path

from ai_node.config.provider_enabled_models_config import ProviderEnabledModelsStore
from ai_node.providers.capability_resolution import resolve_enabled_model_capabilities
from ai_node.providers.model_capability_catalog import (
    ProviderModelCapabilitiesSnapshot,
    ProviderModelCapabilityEntry,
)


class CapabilityResolutionTests(unittest.TestCase):
    def test_provider_enabled_models_store_persists_unique_enabled_models(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ProviderEnabledModelsStore(
                path=str(Path(tmp) / "provider_enabled_models.json"),
                logger=logging.getLogger("capability-resolution-test"),
            )
            snapshot = store.save_enabled_model_ids(model_ids=["gpt-5-mini", "gpt-5-mini", "gpt-4.1"])

            self.assertEqual([entry.model_id for entry in snapshot.models], ["gpt-5-mini", "gpt-4.1"])
            payload = store.payload()
            self.assertEqual([entry["model_id"] for entry in payload["models"]], ["gpt-5-mini", "gpt-4.1"])

    def test_resolve_enabled_model_capabilities_combines_selected_models(self):
        snapshot = ProviderModelCapabilitiesSnapshot(
            classification_model="gpt-5-mini",
            entries=[
                ProviderModelCapabilityEntry(
                    model_id="gpt-5-mini",
                    family="llm",
                    reasoning=True,
                    tool_calling=True,
                    structured_output=True,
                    long_context=True,
                    coding_strength="high",
                    speed_tier="medium",
                    cost_tier="medium",
                    recommended_for=["coding", "automation"],
                ),
                ProviderModelCapabilityEntry(
                    model_id="gpt-4o",
                    family="llm",
                    vision=True,
                    coding_strength="medium",
                    speed_tier="high",
                    cost_tier="low",
                    recommended_for=["vision_analysis", "chat"],
                ),
            ],
        )

        payload = resolve_enabled_model_capabilities(
            snapshot=snapshot,
            enabled_model_ids=["gpt-5-mini", "gpt-4o"],
        )

        self.assertTrue(payload["capabilities"]["reasoning"])
        self.assertTrue(payload["capabilities"]["vision"])
        self.assertEqual(payload["capabilities"]["coding_strength"], "high")
        self.assertEqual(payload["capabilities"]["speed_tier"], "high")
        self.assertEqual(payload["capabilities"]["cost_tier"], "medium")
        self.assertEqual(
            payload["capabilities"]["recommended_for"],
            ["automation", "chat", "coding", "vision_analysis"],
        )


if __name__ == "__main__":
    unittest.main()
