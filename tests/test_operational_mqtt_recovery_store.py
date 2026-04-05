import logging
import tempfile
import unittest
from pathlib import Path

from ai_node.runtime.operational_mqtt_recovery_store import OperationalMqttRecoveryStore


class OperationalMqttRecoveryStoreTests(unittest.TestCase):
    def test_record_restart_requested_persists_attempt_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = OperationalMqttRecoveryStore(
                path=str(Path(tmp) / "operational_mqtt_recovery.json"),
                logger=logging.getLogger("operational-mqtt-recovery-store-test"),
            )

            state = store.record_restart_requested(
                error="connection_refused",
                delay_seconds=10,
                max_attempts=3,
            )

            self.assertTrue(state["active"])
            self.assertEqual(state["attempt_count"], 1)
            self.assertEqual(store.snapshot()["attempt_count"], 1)

    def test_clear_resets_to_default_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = OperationalMqttRecoveryStore(
                path=str(Path(tmp) / "operational_mqtt_recovery.json"),
                logger=logging.getLogger("operational-mqtt-recovery-store-test"),
            )
            store.record_restart_requested(
                error="connection_refused",
                delay_seconds=10,
                max_attempts=3,
            )

            store.clear()

            snapshot = store.snapshot()
            self.assertFalse(snapshot["active"])
            self.assertEqual(snapshot["attempt_count"], 0)
            self.assertFalse(snapshot["exhausted"])


if __name__ == "__main__":
    unittest.main()
