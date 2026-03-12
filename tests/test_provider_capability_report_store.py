import logging
import tempfile
import unittest
from pathlib import Path

from ai_node.persistence.provider_capability_report_store import (
    ProviderCapabilityReportStore,
    validate_provider_capability_report,
)


def _sample_payload() -> dict:
    return {
        "schema_version": "1.0",
        "report_version": "1.0",
        "generated_at": "2026-03-12T00:00:00Z",
        "enabled_providers": ["openai"],
        "providers": [
            {
                "provider": "openai",
                "status": "available",
                "discovery_source": "provider_api",
                "models": [{"id": "gpt-4o-mini", "normalized_id": "openai:gpt-4o-mini"}],
                "latency": {"sample_count": 1, "average_ms": 12.5, "p95_ms": 12.5, "success_rate": 1.0},
                "_latency_samples": [{"success": True, "duration_ms": 12.5}],
                "last_error": None,
            }
        ],
    }


class ProviderCapabilityReportStoreTests(unittest.TestCase):
    def setUp(self):
        self.logger = logging.getLogger("provider-capability-report-store-test")

    def test_validate_accepts_valid_payload(self):
        is_valid, error = validate_provider_capability_report(_sample_payload())
        self.assertTrue(is_valid)
        self.assertIsNone(error)

    def test_validate_rejects_provider_not_enabled(self):
        payload = _sample_payload()
        payload["enabled_providers"] = []
        is_valid, error = validate_provider_capability_report(payload)
        self.assertFalse(is_valid)
        self.assertEqual(error, "provider_not_enabled")

    def test_save_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "provider_capability_report.json"
            store = ProviderCapabilityReportStore(path=str(path), logger=self.logger)
            payload = _sample_payload()
            store.save(payload)
            loaded = store.load()
            self.assertEqual(loaded["schema_version"], "1.0")
            self.assertEqual(loaded["providers"][0]["provider"], "openai")

    def test_load_invalid_json_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "provider_capability_report.json"
            path.write_text("{bad json", encoding="utf-8")
            store = ProviderCapabilityReportStore(path=str(path), logger=self.logger)
            self.assertIsNone(store.load())


if __name__ == "__main__":
    unittest.main()
