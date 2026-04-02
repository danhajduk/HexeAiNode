import json
import logging
import tempfile
import unittest
from pathlib import Path

from ai_node.trust.trust_store import TrustStateStore, redact_trust_state, validate_trust_state


def _sample_trust_state() -> dict:
    return {
        "node_id": "node-123e4567-e89b-42d3-a456-426614174000",
        "node_name": "main-ai-node",
        "node_type": "ai-node",
        "paired_core_id": "core-main",
        "core_api_endpoint": "http://192.168.1.50:9001",
        "node_trust_token": "node-token",
        "initial_baseline_policy": {"policy_version": "v1"},
        "baseline_policy_version": "v1",
        "operational_mqtt_identity": "hn_node-123e4567-e89b-42d3-a456-426614174000",
        "operational_mqtt_token": "mqtt-token",
        "operational_mqtt_host": "192.168.1.50",
        "operational_mqtt_port": 1883,
        "bootstrap_mqtt_host": "192.168.1.10",
        "registration_timestamp": "2026-03-11T18:21:00Z",
    }


class TrustStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.logger = logging.getLogger("trust-store-test")

    def test_validate_trust_state_accepts_canonical_payload(self):
        is_valid, error = validate_trust_state(_sample_trust_state())
        self.assertTrue(is_valid)
        self.assertIsNone(error)

    def test_validate_trust_state_rejects_incomplete_payload(self):
        state = _sample_trust_state()
        del state["node_id"]
        is_valid, error = validate_trust_state(state)
        self.assertFalse(is_valid)
        self.assertEqual(error, "missing_node_id")

    def test_redact_trust_state_masks_sensitive_values(self):
        redacted = redact_trust_state(_sample_trust_state())
        self.assertEqual(redacted["node_trust_token"], "***REDACTED***")
        self.assertEqual(redacted["operational_mqtt_token"], "***REDACTED***")

    def test_save_and_load_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state" / "trust_state.json"
            store = TrustStateStore(path=str(path), logger=self.logger)
            state = _sample_trust_state()
            store.save(state)
            loaded = store.load()
            self.assertEqual(loaded, state)

    def test_load_normalizes_plain_uuid_to_node_uuid(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trust_state.json"
            state = _sample_trust_state()
            state["node_id"] = "123e4567-e89b-42d3-a456-426614174000"
            path.write_text(json.dumps(state), encoding="utf-8")
            store = TrustStateStore(path=str(path), logger=self.logger)
            loaded = store.load()
            self.assertEqual(loaded["node_id"], "node-123e4567-e89b-42d3-a456-426614174000")
            self.assertEqual(loaded["operational_mqtt_identity"], "hn_node-123e4567-e89b-42d3-a456-426614174000")

    def test_load_returns_none_for_corrupt_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trust_state.json"
            path.write_text("{not-json", encoding="utf-8")
            store = TrustStateStore(path=str(path), logger=self.logger)
            loaded = store.load()
            self.assertIsNone(loaded)

    def test_load_returns_none_for_invalid_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trust_state.json"
            invalid = _sample_trust_state()
            del invalid["node_trust_token"]
            path.write_text(json.dumps(invalid), encoding="utf-8")
            store = TrustStateStore(path=str(path), logger=self.logger)
            loaded = store.load()
            self.assertIsNone(loaded)


if __name__ == "__main__":
    unittest.main()
