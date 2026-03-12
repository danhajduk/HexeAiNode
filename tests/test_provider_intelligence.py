import logging
import os
import unittest

from ai_node.capabilities.provider_intelligence import ProviderIntelligenceService, compact_provider_intelligence_report


class _MemoryStore:
    def __init__(self):
        self.payload = None

    def load(self):
        return self.payload

    def save(self, payload):
        self.payload = payload


class _FakeAdapter:
    def __init__(self):
        self.calls = 0

    async def fetch_openai_models(self, *, api_key: str, base_url: str):
        self.calls += 1
        self.last_api_key = api_key
        self.last_base_url = base_url
        return (
            [
                {
                    "id": "gpt-4o-mini",
                    "context_window": 128000,
                    "modalities": ["text", "image"],
                    "pricing": {"currency": "usd", "input_per_1m_tokens": 0.15, "output_per_1m_tokens": 0.6},
                }
            ],
            {"success": True, "duration_ms": 32.0, "timestamp": "2026-03-12T00:00:00Z"},
        )


class ProviderIntelligenceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._previous_api_key = os.environ.get("OPENAI_API_KEY")
        os.environ["OPENAI_API_KEY"] = "test-key"

    def tearDown(self):
        if self._previous_api_key is None:
            os.environ.pop("OPENAI_API_KEY", None)
        else:
            os.environ["OPENAI_API_KEY"] = self._previous_api_key

    async def test_build_report_discovers_openai_models_and_normalizes(self):
        store = _MemoryStore()
        adapter = _FakeAdapter()
        service = ProviderIntelligenceService(
            logger=logging.getLogger("provider-intelligence-test"),
            cache_store=store,
            adapter=adapter,
            refresh_interval_seconds=14400,
        )
        report, changed = await service.build_provider_capability_report(
            provider_selection_config={"providers": {"enabled": ["openai"]}},
            force_refresh=True,
        )
        self.assertTrue(changed)
        self.assertEqual(report["enabled_providers"], ["openai"])
        self.assertEqual(adapter.calls, 1)
        self.assertEqual(report["providers"][0]["provider"], "openai")
        self.assertEqual(report["providers"][0]["models"][0]["normalized_id"], "openai:gpt-4o-mini")
        self.assertEqual(report["providers"][0]["latency"]["sample_count"], 1)
        compact = compact_provider_intelligence_report(report)
        self.assertIn("fingerprint", compact)
        self.assertNotIn("_latency_samples", compact["providers"][0])

    async def test_build_report_uses_cache_when_fresh(self):
        store = _MemoryStore()
        adapter = _FakeAdapter()
        service = ProviderIntelligenceService(
            logger=logging.getLogger("provider-intelligence-test"),
            cache_store=store,
            adapter=adapter,
            refresh_interval_seconds=14400,
        )
        first_report, first_changed = await service.build_provider_capability_report(
            provider_selection_config={"providers": {"enabled": ["openai"]}},
            force_refresh=True,
        )
        second_report, second_changed = await service.build_provider_capability_report(
            provider_selection_config={"providers": {"enabled": ["openai"]}},
            force_refresh=False,
        )
        self.assertTrue(first_changed)
        self.assertFalse(second_changed)
        self.assertEqual(first_report["fingerprint"], second_report["fingerprint"])
        self.assertEqual(adapter.calls, 1)


if __name__ == "__main__":
    unittest.main()
