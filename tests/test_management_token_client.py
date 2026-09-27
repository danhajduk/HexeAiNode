import logging
import unittest

import httpx

from ai_node.core_api.management_token_client import ManagementTokenIntrospectionClient


class _Adapter:
    def __init__(self, *, status_code=200, response=None):
        self.status_code = status_code
        self.response = response or {}
        self.url = None
        self.payload = None
        self.headers = None

    async def post_json(self, url, payload, headers):
        self.url = url
        self.payload = payload
        self.headers = headers
        return self.status_code, self.response


class _UnavailableAdapter:
    async def post_json(self, url, payload, headers):
        raise httpx.ConnectError("Core unavailable")


class ManagementTokenIntrospectionClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_introspect_uses_trusted_node_contract(self):
        adapter = _Adapter(response={"active": True, "claims": {"token_use": "node_management"}})
        client = ManagementTokenIntrospectionClient(logger=logging.getLogger("test"), http_adapter=adapter)

        result = await client.introspect(
            core_api_endpoint="http://10.0.0.100:9001/api",
            node_id="node-provider",
            trust_token="node-trust",
            management_token="management-jwt",
            required_scopes=["node.manage.configuration"],
        )

        self.assertTrue(result.active)
        self.assertEqual(adapter.url, "http://10.0.0.100:9001/api/system/nodes/management/introspect")
        self.assertEqual(adapter.headers["X-Node-Id"], "node-provider")
        self.assertEqual(adapter.headers["X-Node-Trust-Token"], "node-trust")
        self.assertEqual(adapter.payload["token"], "management-jwt")
        self.assertEqual(adapter.payload["required_scopes"], ["node.manage.configuration"])

    async def test_introspect_fails_closed_for_core_error(self):
        adapter = _Adapter(status_code=503, response={"error_code": "management_validation_unavailable"})
        client = ManagementTokenIntrospectionClient(logger=logging.getLogger("test"), http_adapter=adapter)

        result = await client.introspect(
            core_api_endpoint="http://core.local:9001",
            node_id="node-provider",
            trust_token="node-trust",
            management_token="management-jwt",
        )

        self.assertFalse(result.active)
        self.assertTrue(result.retryable)
        self.assertEqual(result.error_code, "management_validation_unavailable")

    async def test_transport_failure_is_classified_as_unavailable(self):
        client = ManagementTokenIntrospectionClient(
            logger=logging.getLogger("test"),
            http_adapter=_UnavailableAdapter(),
        )
        result = await client.introspect(
            core_api_endpoint="http://core.local:9001",
            node_id="node-provider",
            trust_token="node-trust",
            management_token="management-jwt",
        )
        self.assertFalse(result.active)
        self.assertTrue(result.retryable)
        self.assertEqual(result.http_status, 503)
        self.assertEqual(result.error_code, "management_validation_unavailable")


if __name__ == "__main__":
    unittest.main()
