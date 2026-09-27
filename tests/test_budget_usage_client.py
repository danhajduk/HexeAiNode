import logging
import unittest

from ai_node.core_api.budget_usage_client import BudgetUsageSummaryClient


class _Adapter:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self.response = payload or {"ok": True}
        self.url = None
        self.payload = None
        self.headers = None

    async def post_json(self, url, payload, headers):
        self.url = url
        self.payload = payload
        self.headers = headers
        return self.status_code, self.response


class BudgetUsageSummaryClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_submit_uses_core_contract_and_excludes_local_queue_metadata(self):
        adapter = _Adapter()
        client = BudgetUsageSummaryClient(logger=logging.getLogger("test"), http_adapter=adapter)

        result = await client.submit(
            core_api_endpoint="http://10.0.0.100:9001",
            trust_token="trust-token",
            node_id="node-001",
            summary={
                "grant_id": "grant-1",
                "service": "ai.inference",
                "used_requests": 1,
                "queued_at": "2026-09-27T00:00:00Z",
            },
        )

        self.assertTrue(result.accepted)
        self.assertEqual(adapter.url, "http://10.0.0.100:9001/api/system/nodes/budgets/usage-summary")
        self.assertEqual(adapter.headers["X-Node-Trust-Token"], "trust-token")
        self.assertEqual(adapter.payload["node_id"], "node-001")
        self.assertNotIn("queued_at", adapter.payload)

    async def test_server_failure_is_retryable(self):
        result = await BudgetUsageSummaryClient(
            logger=logging.getLogger("test"),
            http_adapter=_Adapter(503, {"detail": "unavailable"}),
        ).submit(
            core_api_endpoint="http://core.local:9001",
            trust_token="trust-token",
            node_id="node-001",
            summary={"grant_id": "grant-1"},
        )

        self.assertFalse(result.accepted)
        self.assertTrue(result.retryable)


if __name__ == "__main__":
    unittest.main()
