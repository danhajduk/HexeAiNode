import logging
import unittest

from ai_node.runtime.execution_telemetry import ExecutionTelemetryPublisher


class _FakeStatusPublisher:
    def __init__(self):
        self.calls = []

    def status_payload(self):
        return {"published": bool(self.calls), "last_topic": "synthia/nodes/node-1/status"}

    async def publish_status(self, **kwargs):
        self.calls.append(kwargs)
        return {"published": True, "last_error": None, "last_topic": "synthia/nodes/node-1/status"}


class ExecutionTelemetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_publish_event_uses_existing_trusted_status_transport(self):
        status_publisher = _FakeStatusPublisher()
        publisher = ExecutionTelemetryPublisher(
            logger=logging.getLogger("execution-telemetry-test"),
            node_id="node-1",
            trust_state_provider=lambda: {"operational_mqtt_host": "10.0.0.1"},
            status_publisher=status_publisher,
        )

        result = await publisher.publish_event(
            event_type="task_received",
            payload={"task_id": "task-1", "task_family": "task.classification"},
        )

        self.assertTrue(result["published"])
        self.assertEqual(status_publisher.calls[0]["node_id"], "node-1")
        self.assertEqual(status_publisher.calls[0]["payload"]["event_type"], "task_received")
        self.assertEqual(status_publisher.calls[0]["payload"]["task_id"], "task-1")


if __name__ == "__main__":
    unittest.main()
