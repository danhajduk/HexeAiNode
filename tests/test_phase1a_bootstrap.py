import logging
import unittest

from ai_node.bootstrap.bootstrap_client import BootstrapClient
from ai_node.bootstrap.bootstrap_parser import (
    build_registration_url,
    parse_bootstrap_payload,
    validate_bootstrap_payload,
)
from ai_node.config.bootstrap_config import create_bootstrap_config
from ai_node.lifecycle.node_lifecycle import NodeLifecycle, NodeLifecycleState


class _FakeMqttClient:
    def __init__(self) -> None:
        self._handler = None
        self.subscribed_topic = None

    async def subscribe(self, topic: str) -> None:
        self.subscribed_topic = topic

    def on_message(self, handler) -> None:
        self._handler = handler

    async def publish_message(self, topic: str, payload: str) -> None:
        await self._handler(topic, payload)

    async def close(self) -> None:
        return None


class _FakeMqttAdapter:
    def __init__(self, client: _FakeMqttClient) -> None:
        self.client = client

    async def connect(self, _options: dict):
        return self.client


class Phase1ABootstrapTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.logger = logging.getLogger("phase1a-test")

    def test_create_bootstrap_config_defaults_and_validation(self):
        config = create_bootstrap_config({"bootstrap_host": "10.0.0.100", "node_name": "node-a"})
        self.assertEqual(config.bootstrap_host, "10.0.0.100")
        self.assertEqual(config.node_name, "node-a")
        self.assertEqual(config.port, 1884)
        self.assertTrue(config.anonymous)
        self.assertEqual(config.topic, "synthia/bootstrap/core")

        with self.assertRaisesRegex(ValueError, "required"):
            create_bootstrap_config({"bootstrap_host": "", "node_name": "node-a"})

    def test_lifecycle_transitions(self):
        lifecycle = NodeLifecycle(logger=self.logger)
        lifecycle.transition_to(NodeLifecycleState.BOOTSTRAP_CONNECTING)
        lifecycle.transition_to(NodeLifecycleState.BOOTSTRAP_CONNECTED)
        lifecycle.transition_to(NodeLifecycleState.CORE_DISCOVERED)
        self.assertEqual(lifecycle.get_state(), NodeLifecycleState.CORE_DISCOVERED)
        self.assertTrue(lifecycle.can_transition_to(NodeLifecycleState.REGISTRATION_PENDING))

        with self.assertRaisesRegex(ValueError, "invalid state transition"):
            lifecycle.transition_to(NodeLifecycleState.TRUSTED)

    def test_bootstrap_payload_validation(self):
        sample = {
            "topic": "synthia/bootstrap/core",
            "bootstrap_version": 1,
            "core_id": "core-main",
            "core_name": "Synthia Core",
            "core_version": "1.0.0",
            "api_base": "http://192.168.1.50:9001",
            "mqtt_host": "192.168.1.50",
            "mqtt_port": 1884,
            "onboarding_endpoints": {"register": "/api/nodes/register"},
            "onboarding_mode": "api",
            "emitted_at": "2026-03-11T18:21:00Z",
        }
        parsed_ok, parsed_value = parse_bootstrap_payload(str(sample).replace("'", '"'))
        self.assertTrue(parsed_ok)
        valid_ok, valid_value = validate_bootstrap_payload(parsed_value)
        self.assertTrue(valid_ok)
        self.assertEqual(valid_value["registration_url"], "http://192.168.1.50:9001/api/nodes/register")

        invalid_ok, invalid_error = validate_bootstrap_payload({**sample, "onboarding_mode": "mqtt"})
        self.assertFalse(invalid_ok)
        self.assertEqual(invalid_error, "unsupported_onboarding_mode")

    def test_build_registration_url(self):
        self.assertEqual(
            build_registration_url("http://core.local:9001", "/api/nodes/register"),
            "http://core.local:9001/api/nodes/register",
        )
        self.assertEqual(
            build_registration_url("http://core.local:9001/api/", "nodes/register"),
            "http://core.local:9001/api/nodes/register",
        )

    async def test_bootstrap_client_discovers_core_payload(self):
        lifecycle = NodeLifecycle(logger=self.logger)
        fake_client = _FakeMqttClient()
        adapter = _FakeMqttAdapter(fake_client)
        client = BootstrapClient(
            lifecycle=lifecycle,
            mqtt_adapter=adapter,
            logger=self.logger,
        )
        discovered = []
        config = create_bootstrap_config({"bootstrap_host": "10.0.0.100", "node_name": "node-a"})

        await client.connect(config, on_core_discovered=lambda payload: discovered.append(payload))

        payload = {
            "topic": "synthia/bootstrap/core",
            "bootstrap_version": 1,
            "core_id": "core-main",
            "core_name": "Synthia Core",
            "core_version": "1.0.0",
            "api_base": "http://192.168.1.50:9001",
            "mqtt_host": "192.168.1.50",
            "mqtt_port": 1884,
            "onboarding_endpoints": {"register": "/api/nodes/register"},
            "onboarding_mode": "api",
            "emitted_at": "2026-03-11T18:21:00Z",
        }
        await fake_client.publish_message("synthia/bootstrap/core", str(payload).replace("'", '"'))
        self.assertEqual(len(discovered), 1)
        self.assertEqual(lifecycle.get_state(), NodeLifecycleState.CORE_DISCOVERED)


if __name__ == "__main__":
    unittest.main()
