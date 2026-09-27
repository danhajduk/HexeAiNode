import logging
import unittest
from types import SimpleNamespace

from fastapi.testclient import TestClient

from ai_node.lifecycle.node_lifecycle import NodeLifecycle
from ai_node.runtime.node_control_api import NodeControlState, create_node_control_app, management_scope_for_route


class _TrustStore:
    def load(self):
        return {
            "node_id": "node-provider",
            "core_api_endpoint": "http://core.local:9001",
            "node_trust_token": "node-trust",
        }


class _ManagementClient:
    def __init__(self, *, error_code=None):
        self.error_code = error_code
        self.calls = []

    async def introspect(self, **kwargs):
        self.calls.append(kwargs)
        if self.error_code:
            return SimpleNamespace(active=False, claims=None, error_code=self.error_code)
        scope = kwargs["required_scopes"][0]
        return SimpleNamespace(
            active=True,
            error_code=None,
            claims={
                "token_use": "node_management",
                "aud": "node-management:node-provider",
                "provider_node_id": "node-provider",
                "scp": [scope],
            },
        )


class ManagementRoutePolicyTests(unittest.TestCase):
    def test_route_scope_mapping(self):
        cases = {
            ("GET", "/api/health"): None,
            ("GET", "/api/schemas/client-node/v2"): None,
            ("GET", "/api/schemas/client-node/v2-malicious"): "node.manage.read",
            ("POST", "/api/onboarding/initiate"): None,
            ("POST", "/api/execution/direct"): None,
            ("GET", "/api/node/status"): "node.manage.read",
            ("POST", "/api/providers/config"): "node.manage.configuration",
            ("POST", "/api/providers/openai/credentials"): "node.manage.credentials",
            ("POST", "/api/prompts/services"): "node.manage.assets",
            ("DELETE", "/api/execution/jobs/job-1"): "node.manage.operations",
            ("POST", "/api/services/restart"): "node.manage.lifecycle",
            ("GET", "/debug/execution"): "node.manage.diagnostics",
        }
        for (method, path), expected in cases.items():
            with self.subTest(method=method, path=path):
                self.assertEqual(management_scope_for_route(method=method, path=path), expected)


class ManagementMiddlewareTests(unittest.TestCase):
    def _client(self, management_client):
        state = NodeControlState(
            lifecycle=NodeLifecycle(logger=logging.getLogger("test")),
            config_path="unused.json",
            logger=logging.getLogger("test"),
            trust_state_store=_TrustStore(),
            management_token_introspection_client=management_client,
        )
        return TestClient(create_node_control_app(state=state, logger=logging.getLogger("test")))

    def test_public_health_does_not_require_management_authorization(self):
        client = self._client(_ManagementClient())
        self.assertEqual(client.get("/api/health").status_code, 200)

    def test_management_route_requires_forwarded_header(self):
        management_client = _ManagementClient()
        client = self._client(management_client)

        denied = client.get("/api/node/status")
        allowed = client.get(
            "/api/node/status",
            headers={"X-Hexe-Management-Authorization": "management-jwt"},
        )

        self.assertEqual(denied.status_code, 401)
        self.assertEqual(denied.json()["detail"], "management_authorization_required")
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(management_client.calls[0]["management_token"], "management-jwt")
        self.assertEqual(management_client.calls[0]["required_scopes"], ["node.manage.read"])

    def test_core_validation_outage_fails_closed(self):
        client = self._client(_ManagementClient(error_code="management_validation_unavailable"))
        response = client.get(
            "/api/node/status",
            headers={"X-Hexe-Management-Authorization": "management-jwt"},
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "management_validation_unavailable")

    def test_inactive_token_is_forbidden(self):
        client = self._client(_ManagementClient(error_code="management_scope_insufficient"))
        response = client.get(
            "/api/node/status",
            headers={"X-Hexe-Management-Authorization": "management-jwt"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "management_scope_insufficient")


if __name__ == "__main__":
    unittest.main()
