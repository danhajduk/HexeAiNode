import logging
import unittest

from ai_node.core_api.budget_declaration_client import BudgetDeclarationClient


class _FakeHttpAdapter:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self.payload = payload
        self.last_url = None
        self.last_payload = None
        self.last_headers = None

    async def post_json(self, url: str, payload: dict, headers: dict):
        self.last_url = url
        self.last_payload = payload
        self.last_headers = headers
        return self.status_code, self.payload


class BudgetDeclarationClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_submit_declaration_posts_expected_payload(self):
        adapter = _FakeHttpAdapter(200, {"status": "accepted", "declaration_id": "budget-decl-1"})
        client = BudgetDeclarationClient(logger=logging.getLogger("budget-declaration-client-test"), http_adapter=adapter)

        result = await client.submit_declaration(
            core_api_endpoint="http://10.0.0.100:9001/api",
            trust_token="secret",
            node_id="node-001",
            declaration_payload={
                "service_capacity": {
                    "service": "ai.inference",
                    "period": "weekly",
                    "limits": {"max_cost_cents": 2500},
                }
            },
        )

        self.assertEqual(result.status, "accepted")
        self.assertEqual(adapter.last_url, "http://10.0.0.100:9001/api/system/nodes/budgets/declaration")
        self.assertEqual(adapter.last_payload["node_id"], "node-001")
        self.assertEqual(adapter.last_payload["service_capacity"]["limits"]["max_cost_cents"], 2500)
        self.assertEqual(adapter.last_headers["X-Synthia-Node-Id"], "node-001")
        self.assertEqual(adapter.last_headers["X-Node-Trust-Token"], "secret")
        self.assertIn("Bearer secret", adapter.last_headers["Authorization"])

    async def test_submit_declaration_returns_rejected_for_4xx(self):
        adapter = _FakeHttpAdapter(422, {"detail": "invalid_budget_declaration"})
        client = BudgetDeclarationClient(logger=logging.getLogger("budget-declaration-client-test"), http_adapter=adapter)

        result = await client.submit_declaration(
            core_api_endpoint="http://10.0.0.100:9001",
            trust_token="secret",
            node_id="node-001",
            declaration_payload={"service_capacity": {"service": "ai.inference"}},
        )

        self.assertEqual(result.status, "rejected")
        self.assertFalse(result.retryable)
        self.assertEqual(result.error, "invalid_budget_declaration")

    async def test_submit_declaration_returns_retryable_for_5xx(self):
        adapter = _FakeHttpAdapter(503, {"detail": "service_unavailable"})
        client = BudgetDeclarationClient(logger=logging.getLogger("budget-declaration-client-test"), http_adapter=adapter)

        result = await client.submit_declaration(
            core_api_endpoint="http://10.0.0.100:9001",
            trust_token="secret",
            node_id="node-001",
            declaration_payload={"service_capacity": {"service": "ai.inference"}},
        )

        self.assertEqual(result.status, "retryable_failure")
        self.assertTrue(result.retryable)


if __name__ == "__main__":
    unittest.main()
