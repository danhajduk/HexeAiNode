import logging
import unittest

from ai_node.core_api.capability_client import CapabilityDeclarationClient


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


class CapabilityClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_submit_manifest_returns_accepted(self):
        adapter = _FakeHttpAdapter(200, {"status": "accepted", "accepted_profile_id": "profile-1"})
        client = CapabilityDeclarationClient(logger=logging.getLogger("capability-client-test"), http_adapter=adapter)
        result = await client.submit_manifest(
            core_api_endpoint="http://10.0.0.100:9001/api",
            trust_token="secret",
            node_id="node-001",
            capability_manifest={"manifest_version": "1.0"},
        )
        self.assertEqual(result.status, "accepted")
        self.assertFalse(result.retryable)
        self.assertEqual(adapter.last_url, "http://10.0.0.100:9001/api/system/nodes/capabilities/declaration")
        self.assertEqual(adapter.last_payload, {"manifest": {"manifest_version": "1.0"}})
        self.assertEqual(adapter.last_headers["X-Synthia-Node-Id"], "node-001")
        self.assertEqual(adapter.last_headers["X-Node-Trust-Token"], "secret")
        self.assertIn("Bearer secret", adapter.last_headers["Authorization"])

    async def test_submit_manifest_returns_rejected_for_4xx(self):
        adapter = _FakeHttpAdapter(422, {"detail": "invalid_manifest"})
        client = CapabilityDeclarationClient(logger=logging.getLogger("capability-client-test"), http_adapter=adapter)
        result = await client.submit_manifest(
            core_api_endpoint="http://10.0.0.100:9001",
            trust_token="secret",
            node_id="node-001",
            capability_manifest={"manifest_version": "1.0"},
        )
        self.assertEqual(result.status, "rejected")
        self.assertFalse(result.retryable)
        self.assertEqual(result.error, "invalid_manifest")

    async def test_submit_manifest_returns_retryable_for_5xx(self):
        adapter = _FakeHttpAdapter(503, {"detail": "service_unavailable"})
        client = CapabilityDeclarationClient(logger=logging.getLogger("capability-client-test"), http_adapter=adapter)
        result = await client.submit_manifest(
            core_api_endpoint="http://10.0.0.100:9001",
            trust_token="secret",
            node_id="node-001",
            capability_manifest={"manifest_version": "1.0"},
        )
        self.assertEqual(result.status, "retryable_failure")
        self.assertTrue(result.retryable)

    async def test_submit_provider_intelligence_uses_expected_payload(self):
        adapter = _FakeHttpAdapter(200, {"status": "accepted"})
        client = CapabilityDeclarationClient(logger=logging.getLogger("capability-client-test"), http_adapter=adapter)
        result = await client.submit_provider_intelligence(
            core_api_endpoint="http://10.0.0.100:9001",
            trust_token="secret",
            node_id="node-001",
            provider_intelligence_report={
                "schema_version": "1.0",
                "report_version": "1.0",
                "generated_at": "2026-03-12T00:00:00Z",
                "enabled_providers": ["openai"],
                "providers": [],
            },
        )
        self.assertEqual(result.status, "accepted")
        self.assertEqual(adapter.last_url, "http://10.0.0.100:9001/api/system/nodes/providers/capabilities/report")
        self.assertEqual(
            adapter.last_payload,
            {
                "node_id": "node-001",
                "provider_intelligence": [],
                "observed_at": "2026-03-12T00:00:00Z",
                "node_available": True,
            },
        )

    async def test_submit_provider_intelligence_uses_structured_mode_when_models_present(self):
        adapter = _FakeHttpAdapter(200, {"status": "accepted"})
        client = CapabilityDeclarationClient(logger=logging.getLogger("capability-client-test"), http_adapter=adapter)
        result = await client.submit_provider_intelligence(
            core_api_endpoint="http://10.0.0.100:9001",
            trust_token="secret",
            node_id="node-001",
            provider_intelligence_report={
                "generated_at": "2026-03-12T00:00:00Z",
                "providers": [
                    {
                        "provider_id": "openai",
                        "availability": "available",
                        "success_metrics": {"success_rate": 1.0},
                        "models": [
                            {
                                "model_id": "gpt-4o-mini",
                                "display_name": "gpt-4o-mini",
                                "context_window": 128000,
                                "max_output_tokens": 4096,
                                "supports_streaming": True,
                                "supports_tools": True,
                                "supports_vision": True,
                                "supports_json_mode": True,
                                "pricing_input": 0.15,
                                "pricing_output": 0.60,
                                "status": "available",
                                "latency_metrics": {"p95_latency": 120.0},
                                "usage_metrics": {"total_tokens": 100},
                                "success_metrics": {"success_rate": 1.0},
                            }
                        ],
                    }
                ],
            },
        )
        self.assertEqual(result.status, "accepted")
        self.assertEqual(adapter.last_payload["node_id"], "node-001")
        provider_intelligence = adapter.last_payload["provider_intelligence"]
        self.assertIsInstance(provider_intelligence, list)
        self.assertEqual(provider_intelligence[0]["provider"], "openai")
        self.assertEqual(provider_intelligence[0]["available_models"][0]["model_id"], "gpt-4o-mini")
        self.assertEqual(provider_intelligence[0]["available_models"][0]["pricing"]["input_per_1m_tokens"], 0.15)
        self.assertIn("metrics_snapshot", adapter.last_payload)

    async def test_submit_provider_intelligence_filters_unavailable_models_from_available_models(self):
        adapter = _FakeHttpAdapter(200, {"status": "accepted"})
        client = CapabilityDeclarationClient(logger=logging.getLogger("capability-client-test"), http_adapter=adapter)

        await client.submit_provider_intelligence(
            core_api_endpoint="http://10.0.0.100:9001",
            trust_token="secret",
            node_id="node-001",
            provider_intelligence_report={
                "generated_at": "2026-03-12T00:00:00Z",
                "providers": [
                    {
                        "provider_id": "openai",
                        "availability": "available",
                        "models": [
                            {"model_id": "gpt-4o-mini", "status": "available", "pricing_input": 0.15, "pricing_output": 0.60},
                            {"model_id": "gpt-5-pro", "status": "unavailable", "pricing_input": None, "pricing_output": None},
                        ],
                    }
                ],
            },
        )

        provider_intelligence = adapter.last_payload["provider_intelligence"]
        self.assertEqual([item["model_id"] for item in provider_intelligence[0]["available_models"]], ["gpt-4o-mini"])

    async def test_submit_provider_intelligence_keeps_degraded_models_and_excludes_blocked_models(self):
        adapter = _FakeHttpAdapter(200, {"status": "accepted"})
        client = CapabilityDeclarationClient(logger=logging.getLogger("capability-client-test"), http_adapter=adapter)

        await client.submit_provider_intelligence(
            core_api_endpoint="http://10.0.0.100:9001",
            trust_token="secret",
            node_id="node-001",
            provider_intelligence_report={
                "generated_at": "2026-03-12T00:00:00Z",
                "providers": [
                    {
                        "provider_id": "openai",
                        "availability": "available",
                        "models": [
                            {
                                "model_id": "gpt-5-mini",
                                "status": "available",
                                "pricing_input": 0.25,
                                "pricing_output": 2.0,
                                "latency_metrics": {"p95_latency": 140.0},
                            },
                            {
                                "model_id": "gpt-5.4",
                                "status": "degraded",
                                "pricing_input": 1.25,
                                "pricing_output": 10.0,
                                "latency_metrics": {"p95_latency": 420.0},
                            },
                            {
                                "model_id": "gpt-5-pro",
                                "status": "unavailable",
                                "pricing_input": None,
                                "pricing_output": None,
                                "latency_metrics": {"p95_latency": None},
                            },
                        ],
                    }
                ],
            },
        )

        provider_intelligence = adapter.last_payload["provider_intelligence"]
        self.assertEqual(
            [item["model_id"] for item in provider_intelligence[0]["available_models"]],
            ["gpt-5-mini", "gpt-5.4"],
        )
        metrics_models = adapter.last_payload["metrics_snapshot"]["providers"][0]["models"]
        self.assertEqual(
            metrics_models[1]["latency_metrics"]["p95_latency"],
            420.0,
        )


if __name__ == "__main__":
    unittest.main()
