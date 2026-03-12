import logging
import unittest

from ai_node.runtime.operational_mqtt_readiness import OperationalMqttReadinessChecker


class _FakeMqttAdapter:
    def __init__(self, *, ready: bool, error: str | None = None):
        self.ready = ready
        self.error = error
        self.calls = []

    async def connect_and_disconnect(self, **kwargs):
        self.calls.append(kwargs)
        return self.ready, self.error


class OperationalMqttReadinessTests(unittest.IsolatedAsyncioTestCase):
    async def test_check_once_returns_ready_for_valid_operational_credentials(self):
        checker = OperationalMqttReadinessChecker(
            logger=logging.getLogger("operational-readiness-test"),
            mqtt_adapter=_FakeMqttAdapter(ready=True),
        )
        result = await checker.check_once(
            trust_state={
                "operational_mqtt_host": "10.0.0.101",
                "operational_mqtt_port": 1883,
                "operational_mqtt_identity": "node-1",
                "operational_mqtt_token": "token",
                "bootstrap_mqtt_host": "10.0.0.100",
            }
        )
        self.assertTrue(result["ready"])
        self.assertIsNone(result["last_error"])

    async def test_check_once_rejects_bootstrap_host_reuse(self):
        checker = OperationalMqttReadinessChecker(
            logger=logging.getLogger("operational-readiness-test"),
            mqtt_adapter=_FakeMqttAdapter(ready=True),
        )
        result = await checker.check_once(
            trust_state={
                "operational_mqtt_host": "10.0.0.100",
                "operational_mqtt_port": 1883,
                "operational_mqtt_identity": "node-1",
                "operational_mqtt_token": "token",
                "bootstrap_mqtt_host": "10.0.0.100",
            }
        )
        self.assertFalse(result["ready"])
        self.assertEqual(result["last_error"], "operational_mqtt_host_must_differ_from_bootstrap_host")

    async def test_check_once_returns_adapter_failure(self):
        checker = OperationalMqttReadinessChecker(
            logger=logging.getLogger("operational-readiness-test"),
            mqtt_adapter=_FakeMqttAdapter(ready=False, error="connect_timeout"),
        )
        result = await checker.check_once(
            trust_state={
                "operational_mqtt_host": "10.0.0.101",
                "operational_mqtt_port": 1883,
                "operational_mqtt_identity": "node-1",
                "operational_mqtt_token": "token",
                "bootstrap_mqtt_host": "10.0.0.100",
            }
        )
        self.assertFalse(result["ready"])
        self.assertEqual(result["last_error"], "connect_timeout")


if __name__ == "__main__":
    unittest.main()
