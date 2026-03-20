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
        )

        self.assertEqual(
            http_adapter.url,
            "http://192.168.1.50:9001/api/system/nodes/onboarding/sessions",
        )
        self.assertEqual(http_adapter.payload["node_id"], "123e4567-e89b-42d3-a456-426614174000")
        self.assertEqual(http_adapter.payload["node_type"], "ai-node")
        self.assertEqual(http_adapter.payload["hostname"], "ai-server")
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


if __name__ == "__main__":
    unittest.main()
