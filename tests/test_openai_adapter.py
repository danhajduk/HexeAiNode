import unittest
from unittest.mock import patch

from ai_node.providers.adapters.openai_adapter import OpenAIProviderAdapter
from ai_node.providers.models import UnifiedExecutionRequest


class OpenAIAdapterCostTests(unittest.TestCase):
    def test_estimate_cost_uses_current_gpt_54_rates(self):
        adapter = OpenAIProviderAdapter(api_key="test-key")

        cost = adapter.estimate_cost(
            model_id="gpt-5.4",
            prompt_tokens=169,
            completion_tokens=127,
        )

        self.assertIsNotNone(cost)
        self.assertAlmostEqual(cost, 0.0023275, places=10)

    def test_estimate_cost_uses_current_gpt_54_nano_rates(self):
        adapter = OpenAIProviderAdapter(api_key="test-key")

        cost = adapter.estimate_cost(
            model_id="gpt-5.4-nano",
            prompt_tokens=353,
            completion_tokens=191,
        )

        self.assertIsNotNone(cost)
        self.assertAlmostEqual(cost, 0.00030935, places=10)

    def test_estimate_cost_uses_cached_input_rate_when_available(self):
        adapter = OpenAIProviderAdapter(api_key="test-key")

        cost = adapter.estimate_cost(
            model_id="gpt-5.4",
            prompt_tokens=250,
            cached_input_tokens=100,
            completion_tokens=50,
        )

        self.assertIsNotNone(cost)
        self.assertAlmostEqual(cost, 0.00115, places=10)


class _FakeResponse:
    def __init__(self, payload: dict):
        self.status_code = 200
        self.headers = {"content-type": "application/json"}
        self._payload = payload

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, *, capture: dict, payload: dict, **_kwargs):
        self._capture = capture
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, *, headers=None, json=None):
        self._capture["url"] = url
        self._capture["headers"] = headers
        self._capture["json"] = json
        return _FakeResponse(self._payload)


class OpenAIAdapterExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_classification_requests_enable_json_response_format(self):
        capture: dict = {}
        response_payload = {
            "id": "resp-123",
            "choices": [{"message": {"content": "{\"label\":\"marketing\"}"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }

        def _client_factory(*args, **kwargs):
            return _FakeAsyncClient(capture=capture, payload=response_payload, **kwargs)

        adapter = OpenAIProviderAdapter(api_key="test-key")
        request = UnifiedExecutionRequest(
            task_family="task.classification",
            prompt="Classify this email",
            requested_model="gpt-5.4-nano",
        )

        with patch("ai_node.providers.adapters.openai_adapter.httpx.AsyncClient", side_effect=_client_factory):
            response = await adapter.execute_prompt(request)

        self.assertEqual(response.output_text, "{\"label\":\"marketing\"}")
        self.assertEqual(capture["json"]["response_format"], {"type": "json_object"})

    async def test_non_classification_requests_do_not_force_json_response_format(self):
        capture: dict = {}
        response_payload = {
            "id": "resp-456",
            "choices": [{"message": {"content": "summary text"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }

        def _client_factory(*args, **kwargs):
            return _FakeAsyncClient(capture=capture, payload=response_payload, **kwargs)

        adapter = OpenAIProviderAdapter(api_key="test-key")
        request = UnifiedExecutionRequest(
            task_family="task.summarization.text",
            prompt="Summarize this email",
            requested_model="gpt-5.4-nano",
        )

        with patch("ai_node.providers.adapters.openai_adapter.httpx.AsyncClient", side_effect=_client_factory):
            response = await adapter.execute_prompt(request)

        self.assertEqual(response.output_text, "summary text")
        self.assertNotIn("response_format", capture["json"])


if __name__ == "__main__":
    unittest.main()
