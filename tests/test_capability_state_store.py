import json
import logging
import tempfile
import unittest
from pathlib import Path

from ai_node.persistence.capability_state_store import CapabilityStateStore, validate_capability_state


def _sample_payload() -> dict:
    return {
        "schema_version": "1.0",
        "accepted_declaration_version": "1.0",
        "acceptance_timestamp": "2026-03-11T00:00:00Z",
        "accepted_profile_id": "cap-1",
        "core_restrictions": {"max_requests_per_minute": 120},
        "core_notes": "accepted",
        "raw_response": {"status": "accepted"},
    }


class CapabilityStateStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.logger = logging.getLogger("capability-state-store-test")

    def test_validate_accepts_sample_payload(self):
        is_valid, error = validate_capability_state(_sample_payload())
        self.assertTrue(is_valid)
        self.assertIsNone(error)

    def test_store_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "capability_state.json"
            store = CapabilityStateStore(path=str(path), logger=self.logger)
            payload = _sample_payload()
            store.save(payload)
            loaded = store.load()
            self.assertEqual(loaded, payload)

    def test_load_returns_none_for_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "capability_state.json"
            path.write_text("{invalid", encoding="utf-8")
            store = CapabilityStateStore(path=str(path), logger=self.logger)
            self.assertIsNone(store.load())

    def test_validate_rejects_missing_required_field(self):
        payload = _sample_payload()
        del payload["accepted_declaration_version"]
        is_valid, error = validate_capability_state(payload)
        self.assertFalse(is_valid)
        self.assertEqual(error, "missing_accepted_declaration_version")


if __name__ == "__main__":
    unittest.main()
