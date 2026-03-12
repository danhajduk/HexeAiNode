import logging
import tempfile
import unittest
from pathlib import Path

from ai_node.persistence.governance_state_store import GovernanceStateStore, validate_governance_state


def _sample_payload() -> dict:
    return {
        "schema_version": "1.0",
        "policy_version": "1.0",
        "issued_timestamp": "2026-03-11T00:00:00Z",
        "synced_at": "2026-03-11T00:05:00Z",
        "refresh_expectations": {"recommended_interval_seconds": 900, "max_stale_seconds": 3600},
        "generic_node_class_rules": {"allow_task_families": ["summarization"]},
        "feature_gating_defaults": {"prompt_governance_ready": False},
        "telemetry_expectations": {"heartbeat_interval_seconds": 30},
        "raw_response": {"status": "ok"},
    }


class GovernanceStateStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.logger = logging.getLogger("governance-state-store-test")

    def test_validate_accepts_sample_payload(self):
        is_valid, error = validate_governance_state(_sample_payload())
        self.assertTrue(is_valid)
        self.assertIsNone(error)

    def test_store_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "governance_state.json"
            store = GovernanceStateStore(path=str(path), logger=self.logger)
            payload = _sample_payload()
            store.save(payload)
            loaded = store.load()
            self.assertEqual(loaded, payload)

    def test_load_returns_none_for_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "governance_state.json"
            path.write_text("{invalid", encoding="utf-8")
            store = GovernanceStateStore(path=str(path), logger=self.logger)
            self.assertIsNone(store.load())

    def test_validate_rejects_missing_required_field(self):
        payload = _sample_payload()
        del payload["policy_version"]
        is_valid, error = validate_governance_state(payload)
        self.assertFalse(is_valid)
        self.assertEqual(error, "missing_policy_version")


if __name__ == "__main__":
    unittest.main()
