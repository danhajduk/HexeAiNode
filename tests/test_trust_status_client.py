import logging
import unittest

from ai_node.core_api.trust_status_client import TrustStatusClient, _build_trust_status_url


class TrustStatusClientTests(unittest.TestCase):
    class _FakeAdapter:
        def __init__(self, *, status_code: int, payload: dict):
            self.status_code = status_code
            self.payload = payload
            self.last_url = None
            self.last_headers = None

        def get_json(self, url: str, headers: dict) -> tuple[int, dict]:
            self.last_url = url
            self.last_headers = headers
            return self.status_code, self.payload

    def test_build_trust_status_url_respects_api_base_path(self):
        url = _build_trust_status_url(
            core_api_endpoint="http://10.0.0.100:9001/api",
            trust_status_path="/api/system/nodes/trust-status",
            node_id="node-123",
        )
        self.assertEqual(url, "http://10.0.0.100:9001/api/system/nodes/trust-status/node-123")

    def test_fetch_classifies_removed_support_state(self):
        adapter = self._FakeAdapter(
            status_code=200,
            payload={"ok": True, "node_id": "node-123", "support_state": "removed", "message": "removed"},
        )
        client = TrustStatusClient(logger=logging.getLogger("trust-status-test"), http_adapter=adapter)

        result = client.fetch(
            core_api_endpoint="http://10.0.0.100:9001/api",
            trust_token="token",
            node_id="node-123",
        )

        self.assertEqual(result.status, "removed")
        self.assertEqual(adapter.last_headers["X-Node-Trust-Token"], "token")
