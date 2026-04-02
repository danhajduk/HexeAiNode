import logging
import unittest

from ai_node.lifecycle.node_lifecycle import NodeLifecycle, NodeLifecycleState
from ai_node.registration.registration_client import RegistrationClient


class _FakeHttpAdapter:
    def __init__(self):
        self.url = None
        self.payload = None

    async def post_json(self, url: str, payload: dict):
        self.url = url
        self.payload = payload
        return {"status": "pending_approval", "approval_url": "http://core.local/ui/nodes/pending"}


class RegistrationClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_register_builds_payload_and_moves_to_registration_pending(self):
        logger = logging.getLogger("registration-client-test")
        lifecycle = NodeLifecycle(logger=logger)
        lifecycle.transition_to(NodeLifecycleState.BOOTSTRAP_CONNECTING)
        lifecycle.transition_to(NodeLifecycleState.BOOTSTRAP_CONNECTED)
        lifecycle.transition_to(NodeLifecycleState.CORE_DISCOVERED)

        http_adapter = _FakeHttpAdapter()
        client = RegistrationClient(lifecycle=lifecycle, http_adapter=http_adapter, logger=logger)
        result = await client.register(
            bootstrap_payload={
                "api_base": "http://192.168.1.50:9001",
                "onboarding_endpoints": {
                    "register_session": "/api/system/nodes/onboarding/sessions",
                    "register": "/api/nodes/register",
                },
            },
            node_id="123e4567-e89b-42d3-a456-426614174000",
            node_name="main-ai-node",
            node_software_version="0.1.0",
            protocol_version=1,
            node_nonce="abcd1234-1234-5678-90ab-1234567890ab",
            hostname="ai-server",
            ui_endpoint="http://ai-server:8081/",
            api_base_url="http://ai-server:9002",
        )

        self.assertEqual(
            http_adapter.url,
            "http://192.168.1.50:9001/api/system/nodes/onboarding/sessions",
        )
        self.assertEqual(http_adapter.payload["node_id"], "123e4567-e89b-42d3-a456-426614174000")
        self.assertEqual(http_adapter.payload["node_type"], "ai-node")
        self.assertEqual(http_adapter.payload["hostname"], "ai-server")
        self.assertEqual(http_adapter.payload["ui_endpoint"], "http://ai-server:8081/")
        self.assertEqual(http_adapter.payload["api_base_url"], "http://ai-server:9002")
        self.assertEqual(result["status"], "pending_approval")
        self.assertEqual(lifecycle.get_state(), NodeLifecycleState.REGISTRATION_PENDING)

    async def test_register_falls_back_to_legacy_register_endpoint(self):
        logger = logging.getLogger("registration-client-test")
        lifecycle = NodeLifecycle(logger=logger)
        lifecycle.transition_to(NodeLifecycleState.BOOTSTRAP_CONNECTING)
        lifecycle.transition_to(NodeLifecycleState.BOOTSTRAP_CONNECTED)
        lifecycle.transition_to(NodeLifecycleState.CORE_DISCOVERED)

        http_adapter = _FakeHttpAdapter()
        client = RegistrationClient(lifecycle=lifecycle, http_adapter=http_adapter, logger=logger)
        await client.register(
            bootstrap_payload={
                "api_base": "http://192.168.1.50:9001",
                "onboarding_endpoints": {"register": "/api/nodes/register"},
            },
            node_id="123e4567-e89b-42d3-a456-426614174000",
            node_name="main-ai-node",
            node_software_version="0.1.0",
            protocol_version=1,
            node_nonce="abcd1234-1234-5678-90ab-1234567890ab",
        )

        self.assertEqual(http_adapter.url, "http://192.168.1.50:9001/api/nodes/register")

    async def test_register_rejects_non_absolute_ui_endpoint(self):
        logger = logging.getLogger("registration-client-test")
        lifecycle = NodeLifecycle(logger=logger)
        lifecycle.transition_to(NodeLifecycleState.BOOTSTRAP_CONNECTING)
        lifecycle.transition_to(NodeLifecycleState.BOOTSTRAP_CONNECTED)
        lifecycle.transition_to(NodeLifecycleState.CORE_DISCOVERED)

        http_adapter = _FakeHttpAdapter()
        client = RegistrationClient(lifecycle=lifecycle, http_adapter=http_adapter, logger=logger)

        with self.assertRaisesRegex(ValueError, "ui_endpoint must be an absolute http/https URL"):
            await client.register(
                bootstrap_payload={
                    "api_base": "http://192.168.1.50:9001",
                    "onboarding_endpoints": {
                        "register_session": "/api/system/nodes/onboarding/sessions",
                    },
                },
                node_id="123e4567-e89b-42d3-a456-426614174000",
                node_name="main-ai-node",
                node_software_version="0.1.0",
                protocol_version=1,
                node_nonce="abcd1234-1234-5678-90ab-1234567890ab",
                ui_endpoint="ai-server/ui",
            )

    async def test_register_rejects_non_absolute_api_base_url(self):
        logger = logging.getLogger("registration-client-test")
        lifecycle = NodeLifecycle(logger=logger)
        lifecycle.transition_to(NodeLifecycleState.BOOTSTRAP_CONNECTING)
        lifecycle.transition_to(NodeLifecycleState.BOOTSTRAP_CONNECTED)
        lifecycle.transition_to(NodeLifecycleState.CORE_DISCOVERED)

        http_adapter = _FakeHttpAdapter()
        client = RegistrationClient(lifecycle=lifecycle, http_adapter=http_adapter, logger=logger)

        with self.assertRaisesRegex(ValueError, "api_base_url must be an absolute http/https URL"):
            await client.register(
                bootstrap_payload={
                    "api_base": "http://192.168.1.50:9001",
                    "onboarding_endpoints": {
                        "register_session": "/api/system/nodes/onboarding/sessions",
                    },
                },
                node_id="123e4567-e89b-42d3-a456-426614174000",
                node_name="main-ai-node",
                node_software_version="0.1.0",
                protocol_version=1,
                node_nonce="abcd1234-1234-5678-90ab-1234567890ab",
                api_base_url="ai-server:9002",
            )


if __name__ == "__main__":
    unittest.main()
