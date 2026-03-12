import logging
import unittest

from ai_node.core_api.governance_client import GovernanceSyncClient


class _FakeHttpAdapter:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self.payload = payload
        self.last_url = None
        self.last_headers = None

    async def get_json(self, url: str, headers: dict):
        self.last_url = url
        self.last_headers = headers
        return self.status_code, self.payload


class GovernanceClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_governance_returns_synced(self):
        adapter = _FakeHttpAdapter(
            200,
            {
                "policy_version": "1.0",
                "issued_timestamp": "2026-03-11T00:00:00Z",
                "refresh_expectations": {},
                "generic_node_class_rules": {},
                "feature_gating_defaults": {},
                "telemetry_expectations": {},
            },
        )
        client = GovernanceSyncClient(logger=logging.getLogger("governance-client-test"), http_adapter=adapter)
        result = await client.fetch_baseline_governance(
            core_api_endpoint="http://10.0.0.100:9001/api",
            trust_token="secret",
            node_id="node-001",
        )
        self.assertEqual(result.status, "synced")
        self.assertFalse(result.retryable)
        self.assertEqual(adapter.last_url, "http://10.0.0.100:9001/api/system/nodes/governance/baseline")
        self.assertEqual(adapter.last_headers["X-Synthia-Node-Id"], "node-001")
        self.assertIn("Bearer secret", adapter.last_headers["Authorization"])

    async def test_fetch_governance_returns_rejected_for_4xx(self):
        adapter = _FakeHttpAdapter(403, {"detail": "forbidden"})
        client = GovernanceSyncClient(logger=logging.getLogger("governance-client-test"), http_adapter=adapter)
        result = await client.fetch_baseline_governance(
            core_api_endpoint="http://10.0.0.100:9001",
            trust_token="secret",
            node_id="node-001",
        )
        self.assertEqual(result.status, "rejected")
        self.assertFalse(result.retryable)
        self.assertEqual(result.error, "forbidden")

    async def test_fetch_governance_returns_retryable_for_5xx(self):
        adapter = _FakeHttpAdapter(503, {"detail": "service_unavailable"})
        client = GovernanceSyncClient(logger=logging.getLogger("governance-client-test"), http_adapter=adapter)
        result = await client.fetch_baseline_governance(
            core_api_endpoint="http://10.0.0.100:9001",
            trust_token="secret",
            node_id="node-001",
        )
        self.assertEqual(result.status, "retryable_failure")
        self.assertTrue(result.retryable)


if __name__ == "__main__":
    unittest.main()
