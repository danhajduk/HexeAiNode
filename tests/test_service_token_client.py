import logging
import unittest

from ai_node.core_api.service_token_client import ServiceTokenIntrospectionClient


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


class ServiceTokenIntrospectionClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_introspect_uses_provider_identity_and_scope_contract(self):
        adapter = _Adapter(
            response={
                "active": True,
                "claims": {
                    "sub": "node-caller",
                    "aud": "node-service:node-provider:openai",
                    "scp": ["service.execute:task.classification"],
                },
            }
        )
        client = ServiceTokenIntrospectionClient(logger=logging.getLogger("test"), http_adapter=adapter)

        result = await client.introspect(
            core_api_endpoint="http://10.0.0.100:9001",
            node_id="node-provider",
            trust_token="provider-trust",
            service_token="issued-jwt",
            required_scopes=["service.execute:task.classification"],
        )

        self.assertTrue(result.active)
        self.assertEqual(adapter.url, "http://10.0.0.100:9001/api/system/nodes/services/introspect")
        self.assertEqual(adapter.headers["X-Node-Id"], "node-provider")
        self.assertEqual(adapter.headers["X-Node-Trust-Token"], "provider-trust")
        self.assertNotIn("Authorization", adapter.headers)
        self.assertEqual(adapter.payload["token"], "issued-jwt")
        self.assertEqual(adapter.payload["required_scopes"], ["service.execute:task.classification"])

    async def test_introspect_fails_closed_for_core_error(self):
        adapter = _Adapter(status_code=503, response={"error_code": "token_validation_unavailable"})
        client = ServiceTokenIntrospectionClient(logger=logging.getLogger("test"), http_adapter=adapter)

        result = await client.introspect(
            core_api_endpoint="http://core.local:9001",
            node_id="node-provider",
            trust_token="provider-trust",
            service_token="issued-jwt",
        )

        self.assertFalse(result.active)
        self.assertTrue(result.retryable)
        self.assertEqual(result.error_code, "token_validation_unavailable")


if __name__ == "__main__":
    unittest.main()
