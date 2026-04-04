import logging
import tempfile
import unittest
from pathlib import Path

from ai_node.lifecycle.node_lifecycle import NodeLifecycle, NodeLifecycleState
from ai_node.trust.trust_store import TrustStateStore
from ai_node.trust.trusted_startup import TrustedStartupManager


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


class TrustedStartupTests(unittest.TestCase):
    def test_valid_trust_state_skips_bootstrap_and_moves_to_capability_setup_pending(self):
        logger = logging.getLogger("trusted-startup-test")
        lifecycle = NodeLifecycle(logger=logger)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trust_state.json"
            store = TrustStateStore(path=str(path), logger=logger)
            store.save(_sample_trust_state())

            manager = TrustedStartupManager(trust_store=store, lifecycle=lifecycle, logger=logger)
            decision = manager.resolve_startup_path()

            self.assertEqual(decision.mode, "trusted_resume")
            self.assertIsNotNone(decision.trust_state)
            self.assertEqual(lifecycle.get_state(), NodeLifecycleState.CAPABILITY_SETUP_PENDING)

    def test_missing_or_invalid_state_starts_bootstrap_onboarding(self):
        logger = logging.getLogger("trusted-startup-test")
        lifecycle = NodeLifecycle(logger=logger)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trust_state.json"
            store = TrustStateStore(path=str(path), logger=logger)

            manager = TrustedStartupManager(trust_store=store, lifecycle=lifecycle, logger=logger)
            decision = manager.resolve_startup_path()

            self.assertEqual(decision.mode, "bootstrap_onboarding")
            self.assertIsNone(decision.trust_state)
            self.assertEqual(lifecycle.get_state(), NodeLifecycleState.BOOTSTRAP_CONNECTING)


if __name__ == "__main__":
    unittest.main()
