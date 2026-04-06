import json
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from ai_node.providers.adapters.openai_adapter import OpenAIProviderAdapter
from ai_node.providers.openai_catalog import OpenAIPricingCatalogService
from ai_node.providers.models import UnifiedExecutionRequest


TEST_OPENAI_CREDENTIAL = "placeholder-openai-credential"


class OpenAIAdapterCostTests(unittest.TestCase):
    def test_estimate_cost_uses_current_gpt_54_rates(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = OpenAIProviderAdapter(
                api_key=TEST_OPENAI_CREDENTIAL,
                pricing_catalog_service=OpenAIPricingCatalogService(
                    logger=None,
                    catalog_path=str(Path(tmp) / "provider_model_pricing.json"),
                    manual_config_path=str(Path(tmp) / "openai-pricing.yaml"),
                ),
            )

            cost = adapter.estimate_cost(
                model_id="gpt-5.4",
                prompt_tokens=169,
                completion_tokens=127,
            )

            self.assertIsNotNone(cost)
            self.assertAlmostEqual(cost, 0.0023275, places=10)

    def test_estimate_cost_uses_current_gpt_54_mini_rates(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = OpenAIProviderAdapter(
                api_key=TEST_OPENAI_CREDENTIAL,
                pricing_catalog_service=OpenAIPricingCatalogService(
                    logger=None,
                    catalog_path=str(Path(tmp) / "provider_model_pricing.json"),
                    manual_config_path=str(Path(tmp) / "openai-pricing.yaml"),
                ),
            )

            cost = adapter.estimate_cost(
                model_id="gpt-5.4-mini",
                prompt_tokens=250,
                cached_input_tokens=100,
                completion_tokens=50,
            )

            self.assertIsNotNone(cost)
            self.assertAlmostEqual(cost, 0.000345, places=10)

    def test_estimate_cost_uses_current_gpt_54_nano_rates(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = OpenAIProviderAdapter(
                api_key=TEST_OPENAI_CREDENTIAL,
                pricing_catalog_service=OpenAIPricingCatalogService(
                    logger=None,
                    catalog_path=str(Path(tmp) / "provider_model_pricing.json"),
                    manual_config_path=str(Path(tmp) / "openai-pricing.yaml"),
                ),
            )

            cost = adapter.estimate_cost(
                model_id="gpt-5.4-nano",
                prompt_tokens=353,
                completion_tokens=191,
            )

            self.assertIsNotNone(cost)
            self.assertAlmostEqual(cost, 0.00030935, places=10)

    def test_estimate_cost_uses_cached_input_rate_when_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = OpenAIProviderAdapter(
                api_key=TEST_OPENAI_CREDENTIAL,
                pricing_catalog_service=OpenAIPricingCatalogService(
                    logger=None,
                    catalog_path=str(Path(tmp) / "provider_model_pricing.json"),
                    manual_config_path=str(Path(tmp) / "openai-pricing.yaml"),
                ),
            )

            cost = adapter.estimate_cost(
                model_id="gpt-5.4",
                prompt_tokens=250,
                cached_input_tokens=100,
                completion_tokens=50,
            )

            self.assertIsNotNone(cost)
            self.assertAlmostEqual(cost, 0.00115, places=10)


class _FakeResponse:
    def __init__(self, payload: dict, *, status_code: int = 200):
        self.status_code = status_code
        self.headers = {"content-type": "application/json"}
        self._payload = payload

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, *, capture: dict, payload: dict, status_code: int = 200, **_kwargs):
        self._capture = capture
        self._payload = payload
        self._status_code = status_code

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, *, headers=None, json=None):
        self._capture["url"] = url
        self._capture["headers"] = headers
        self._capture["json"] = json
        return _FakeResponse(self._payload, status_code=self._status_code)


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

        adapter = OpenAIProviderAdapter(api_key=TEST_OPENAI_CREDENTIAL)
        request = UnifiedExecutionRequest(
            task_family="task.classification",
            prompt="Classify this email",
            requested_model="gpt-5.4-nano",
        )

        with patch("ai_node.providers.adapters.openai_adapter.httpx.AsyncClient", side_effect=_client_factory):
            response = await adapter.execute_prompt(request)

        self.assertEqual(response.output_text, "{\"label\":\"marketing\"}")
        self.assertEqual(capture["json"]["response_format"], {"type": "json_object"})

    async def test_structured_output_schema_uses_json_schema_response_format(self):
        capture: dict = {}
        response_payload = {
            "id": "resp-789",
            "choices": [{"message": {"content": "{\"primary_label\":\"ORDER\"}"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }

        def _client_factory(*args, **kwargs):
            return _FakeAsyncClient(capture=capture, payload=response_payload, **kwargs)

        adapter = OpenAIProviderAdapter(api_key=TEST_OPENAI_CREDENTIAL)
        request = UnifiedExecutionRequest(
            task_family="task.classification",
            prompt="Analyze this email",
            requested_model="gpt-5.4-mini",
            metadata={
                "prompt_id": "prompt.email.action_decision",
                "prompt_version": "v1.4",
                "structured_output_schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "primary_label": {"type": "string"},
                    },
                    "required": ["primary_label"],
                },
            },
        )

        with patch("ai_node.providers.adapters.openai_adapter.httpx.AsyncClient", side_effect=_client_factory):
            response = await adapter.execute_prompt(request)

        self.assertEqual(response.output_text, "{\"primary_label\":\"ORDER\"}")
        self.assertEqual(capture["json"]["response_format"]["type"], "json_schema")
        self.assertEqual(capture["json"]["response_format"]["json_schema"]["strict"], True)
        self.assertEqual(
            capture["json"]["response_format"]["json_schema"]["schema"]["required"],
            ["primary_label"],
        )
        self.assertAlmostEqual(response.estimated_cost or 0.0, 0.00003, places=12)

    async def test_structured_output_schema_normalizes_optional_object_properties_for_openai(self):
        capture: dict = {}
        response_payload = {
            "id": "resp-790",
            "choices": [{"message": {"content": "{\"match\":{\"vendor_identity\":null}}"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }

        def _client_factory(*args, **kwargs):
            return _FakeAsyncClient(capture=capture, payload=response_payload, **kwargs)

        adapter = OpenAIProviderAdapter(api_key=TEST_OPENAI_CREDENTIAL)
        request = UnifiedExecutionRequest(
            task_family="task.summarization.text",
            prompt="Build template",
            requested_model="gpt-5.4-mini",
            metadata={
                "structured_output_schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "match": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "vendor_identity": {"type": "string"},
                            },
                        }
                    },
                    "required": ["match"],
                },
            },
        )

        with patch("ai_node.providers.adapters.openai_adapter.httpx.AsyncClient", side_effect=_client_factory):
            await adapter.execute_prompt(request)

        normalized_schema = capture["json"]["response_format"]["json_schema"]["schema"]
        self.assertEqual(normalized_schema["properties"]["match"]["required"], ["vendor_identity"])
        self.assertEqual(
            normalized_schema["properties"]["match"]["properties"]["vendor_identity"]["type"],
            ["string", "null"],
        )

    async def test_structured_output_schema_drops_one_of_for_openai_compatibility(self):
        capture: dict = {}
        response_payload = {
            "id": "resp-791",
            "choices": [{"message": {"content": "{\"extract\":{}}"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }

        def _client_factory(*args, **kwargs):
            return _FakeAsyncClient(capture=capture, payload=response_payload, **kwargs)

        adapter = OpenAIProviderAdapter(api_key=TEST_OPENAI_CREDENTIAL)
        request = UnifiedExecutionRequest(
            task_family="task.summarization.text",
            prompt="Build template",
            requested_model="gpt-5.4-mini",
            metadata={
                "structured_output_schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "extract": {
                            "type": "object",
                            "additionalProperties": {
                                "type": "object",
                                "properties": {
                                    "method": {"type": "string"},
                                    "pattern": {"type": "string"},
                                },
                                "required": ["method"],
                                "oneOf": [
                                    {"required": ["method", "pattern"]},
                                ],
                            },
                        }
                    },
                    "required": ["extract"],
                },
            },
        )

        with patch("ai_node.providers.adapters.openai_adapter.httpx.AsyncClient", side_effect=_client_factory):
            await adapter.execute_prompt(request)

        additional_properties = capture["json"]["response_format"]["json_schema"]["schema"]["properties"]["extract"]["additionalProperties"]
        self.assertNotIn("oneOf", additional_properties)

    async def test_structured_output_schema_adds_additional_properties_false_to_bare_objects(self):
        capture: dict = {}
        response_payload = {
            "id": "resp-792",
            "choices": [{"message": {"content": "{\"post_process\":{}}"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }

        def _client_factory(*args, **kwargs):
            return _FakeAsyncClient(capture=capture, payload=response_payload, **kwargs)

        adapter = OpenAIProviderAdapter(api_key=TEST_OPENAI_CREDENTIAL)
        request = UnifiedExecutionRequest(
            task_family="task.summarization.text",
            prompt="Build template",
            requested_model="gpt-5.4-mini",
            metadata={
                "structured_output_schema": {
                    "type": "object",
                    "properties": {
                        "post_process": {"type": "object"},
                    },
                    "required": ["post_process"],
                }
            },
        )

        with patch("ai_node.providers.adapters.openai_adapter.httpx.AsyncClient", side_effect=_client_factory):
            await adapter.execute_prompt(request)

        post_process = capture["json"]["response_format"]["json_schema"]["schema"]["properties"]["post_process"]
        self.assertFalse(post_process["additionalProperties"])

    async def test_non_classification_requests_do_not_force_json_response_format(self):
        capture: dict = {}
        response_payload = {
            "id": "resp-456",
            "choices": [{"message": {"content": "summary text"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }

        def _client_factory(*args, **kwargs):
            return _FakeAsyncClient(capture=capture, payload=response_payload, **kwargs)

        adapter = OpenAIProviderAdapter(api_key=TEST_OPENAI_CREDENTIAL)
        request = UnifiedExecutionRequest(
            task_family="task.summarization.text",
            prompt="Summarize this email",
            requested_model="gpt-5.4-nano",
        )

        with patch("ai_node.providers.adapters.openai_adapter.httpx.AsyncClient", side_effect=_client_factory):
            response = await adapter.execute_prompt(request)

        self.assertEqual(response.output_text, "summary text")
        self.assertNotIn("response_format", capture["json"])

    async def test_structured_extraction_does_not_send_json_schema_response_format(self):
        capture: dict = {}
        response_payload = {
            "id": "resp-793",
            "choices": [{"message": {"content": "{\"template_id\":\"demo\"}"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }

        def _client_factory(*args, **kwargs):
            return _FakeAsyncClient(capture=capture, payload=response_payload, **kwargs)

        adapter = OpenAIProviderAdapter(api_key=TEST_OPENAI_CREDENTIAL)
        request = UnifiedExecutionRequest(
            task_family="task.structured_extraction",
            prompt="Build template",
            requested_model="gpt-5.4-mini",
            metadata={
                "structured_output_schema": {
                    "type": "object",
                    "properties": {"template_id": {"type": "string"}},
                    "required": ["template_id"],
                }
            },
        )

        with patch("ai_node.providers.adapters.openai_adapter.httpx.AsyncClient", side_effect=_client_factory):
            await adapter.execute_prompt(request)

        self.assertNotIn("response_format", capture["json"])

    async def test_http_error_uses_provider_message_field(self):
        capture: dict = {}
        response_payload = {
            "error": {
                "message": "Invalid schema for response_format 'order_template': schema must include additionalProperties: false",
                "type": "invalid_request_error",
                "param": "response_format",
                "code": None,
            }
        }

        def _client_factory(*args, **kwargs):
            return _FakeAsyncClient(capture=capture, payload=response_payload, status_code=400, **kwargs)

        adapter = OpenAIProviderAdapter(api_key=TEST_OPENAI_CREDENTIAL)
        request = UnifiedExecutionRequest(
            task_family="task.structured_extraction",
            prompt="Build template",
            requested_model="gpt-5.4-mini",
            metadata={
                "structured_output_schema": {
                    "type": "object",
                    "properties": {"template_id": {"type": "string"}},
                    "required": ["template_id"],
                }
            },
        )

        with patch("ai_node.providers.adapters.openai_adapter.httpx.AsyncClient", side_effect=_client_factory):
            with self.assertRaisesRegex(RuntimeError, "Invalid schema for response_format"):
                await adapter.execute_prompt(request)

    async def test_debug_aopenai_writes_full_request_and_response_to_separate_log(self):
        capture: dict = {}
        response_payload = {
            "id": "resp-debug",
            "choices": [{"message": {"content": "{\"ok\":true}"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }

        def _client_factory(*args, **kwargs):
            return _FakeAsyncClient(capture=capture, payload=response_payload, **kwargs)

        with tempfile.TemporaryDirectory() as tmp:
            debug_log_path = Path(tmp) / "openai_debug.jsonl"
            adapter = OpenAIProviderAdapter(
                api_key=TEST_OPENAI_CREDENTIAL,
                debug_aopenai=True,
                debug_aopenai_log_path=str(debug_log_path),
            )
            request = UnifiedExecutionRequest(
                task_family="task.classification",
                prompt="Analyze this email",
                requested_model="gpt-5.4-mini",
                metadata={"prompt_id": "prompt.email.action_decision"},
            )

            with patch("ai_node.providers.adapters.openai_adapter.httpx.AsyncClient", side_effect=_client_factory):
                response = await adapter.execute_prompt(request)

            self.assertEqual(response.output_text, "{\"ok\":true}")
            self.assertTrue(debug_log_path.exists())
            records = [json.loads(line) for line in debug_log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["prompt_id"], "prompt.email.action_decision")
            self.assertEqual(records[0]["request_payload"]["model"], "gpt-5.4-mini")
            self.assertEqual(records[0]["response_payload"]["id"], "resp-debug")
            self.assertEqual(records[0]["request_headers"]["Authorization"], "***REDACTED***")


if __name__ == "__main__":
    unittest.main()
