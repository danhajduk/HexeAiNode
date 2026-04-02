import logging
import unittest

from ai_node.runtime.trusted_status_telemetry import TrustedStatusTelemetryPublisher


class _FakeAdapter:
    def __init__(self, published=True, error=None):
        self.published = published
        self.error = error
        self.calls = []

    async def publish_json(self, **kwargs):
        self.calls.append(kwargs)
        return self.published, self.error


class TrustedStatusTelemetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_publish_status_uses_operational_channel(self):
        adapter = _FakeAdapter()
        publisher = TrustedStatusTelemetryPublisher(
            logger=logging.getLogger("telemetry-test"),
            mqtt_adapter=adapter,
        )
        result = await publisher.publish_status(
            trust_state={
                "operational_mqtt_host": "10.0.0.101",
                "operational_mqtt_port": 1883,
                "operational_mqtt_identity": "node-1",
                "operational_mqtt_token": "token",
            },
            node_id="node-1",
            payload={
                "health_status": "healthy",
                "lifecycle_state": "operational",
                "ready": True,
                "checks": {"capability_state": "accepted"},
                "details": {"overall_status": "operational"},
            },
        )
        self.assertTrue(result["published"])
        self.assertEqual(adapter.calls[0]["topic"], "hexe/nodes/node-1/status")
        self.assertTrue(adapter.calls[0]["retain"])
        self.assertEqual(adapter.calls[0]["message_expiry_interval_seconds"], 1800)
        self.assertEqual(adapter.calls[0]["payload"]["node_id"], "node-1")
        self.assertEqual(adapter.calls[0]["payload"]["health_status"], "healthy")
        self.assertIn("reported_at", adapter.calls[0]["payload"])
        self.assertEqual(adapter.calls[0]["payload"]["ttl_s"], 300)

    async def test_publish_status_rejects_missing_credentials(self):
        adapter = _FakeAdapter()
        publisher = TrustedStatusTelemetryPublisher(
            logger=logging.getLogger("telemetry-test"),
            mqtt_adapter=adapter,
        )
        result = await publisher.publish_status(
            trust_state={},
            node_id="node-1",
            payload={"health_status": "healthy"},
        )
        self.assertFalse(result["published"])
        self.assertEqual(result["last_error"], "invalid_operational_mqtt_credentials")
        self.assertEqual(len(adapter.calls), 0)


if __name__ == "__main__":
    unittest.main()
