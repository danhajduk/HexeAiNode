import logging
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from ai_node.execution.input_schema_validation import PromptInputValidationFailure, validate_prompt_inputs
from ai_node.execution.task_models import TaskExecutionRequest
from ai_node.lifecycle.node_lifecycle import NodeLifecycle
from ai_node.runtime.node_control_api import NodeControlState, create_node_control_app


SCHEMA_DIR = Path(__file__).resolve().parents[1] / "docs/json-schemas/client-node-v2"


class _PromptStore:
    def __init__(self):
        self.payload = {
            "schema_version": "1.0",
            "prompt_services": [],
            "probation": {"active_prompt_ids": [], "reasons": {}, "updated_at": None},
            "updated_at": None,
        }

    def load_or_create(self):
        return self.payload

    def save(self, payload):
        self.payload = payload


class _ProviderRuntimeManager:
    def __init__(self):
        self.execution_count = 0

    async def execute(self, _request):
        self.execution_count += 1
        raise AssertionError("invalid prompt inputs reached the provider")


class PromptInputSchemaValidationTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _registered_weather_state(tmp: str) -> tuple[NodeControlState, _ProviderRuntimeManager]:
        runtime = _ProviderRuntimeManager()
        state = NodeControlState(
            lifecycle=NodeLifecycle(logger=logging.getLogger("prompt-schema-test")),
            config_path=str(Path(tmp) / "bootstrap.json"),
            logger=logging.getLogger("prompt-schema-test"),
            prompt_service_state_store=_PromptStore(),
            provider_runtime_manager=runtime,
        )
        state.register_prompt_service(
            prompt_id="prompt.weather.scenery",
            service_id="weather-node",
            owner_service="weather-node",
            owner_client_id="weather-node",
            task_family="task.image_generation",
            metadata={
                "input_schema_url": "/api/schemas/client-node/v2/weather-scenery-inputs.v1.schema.json"
            },
        )
        return state, runtime

    def test_weather_schema_accepts_valid_inputs(self):
        validate_prompt_inputs(
            inputs={"image_type": "scenery", "condition": "rain", "day_night": "night"},
            version_metadata={
                "input_schema_id": "https://hexe.local/schemas/client-node-v2/weather-scenery-inputs.v1.schema.json",
                "input_schema_url": "/api/schemas/client-node/v2/weather-scenery-inputs.v1.schema.json",
            },
            schema_dir=SCHEMA_DIR,
        )

    def test_weather_schema_reports_missing_and_unknown_fields(self):
        with self.assertRaises(PromptInputValidationFailure) as raised:
            validate_prompt_inputs(
                inputs={"image_type": "scenery", "condition": "rain", "unexpected": True},
                version_metadata={
                    "input_schema_url": "/api/schemas/client-node/v2/weather-scenery-inputs.v1.schema.json"
                },
                schema_dir=SCHEMA_DIR,
            )

        self.assertEqual(raised.exception.error_code, "prompt_input_validation_failed")
        keywords = {item["keyword"] for item in raised.exception.diagnostics}
        self.assertEqual(keywords, {"required", "unevaluatedProperties"})

    def test_image_schema_reports_type_and_range_errors(self):
        with self.assertRaises(PromptInputValidationFailure) as raised:
            validate_prompt_inputs(
                inputs={"image_type": "portrait", "width": 128, "randomize_seed": "yes"},
                version_metadata={
                    "input_schema_id": "https://hexe.local/schemas/client-node-v2/image-generation-inputs.v1.schema.json"
                },
                schema_dir=SCHEMA_DIR,
            )

        diagnostics = {(item["path"], item["keyword"]) for item in raised.exception.diagnostics}
        self.assertIn(("/width", "minimum"), diagnostics)
        self.assertIn(("/randomize_seed", "type"), diagnostics)

    def test_untrusted_or_mismatched_schema_references_fail_closed(self):
        for metadata, expected in (
            ({"input_schema_url": "https://example.test/schema.json"}, "prompt_input_schema_untrusted"),
            (
                {
                    "input_schema_id": "https://hexe.local/schemas/client-node-v2/image-generation-inputs.v1.schema.json",
                    "input_schema_url": "/api/schemas/client-node/v2/weather-scenery-inputs.v1.schema.json",
                },
                "prompt_input_schema_reference_mismatch",
            ),
        ):
            with self.subTest(expected=expected), self.assertRaises(PromptInputValidationFailure) as raised:
                validate_prompt_inputs(inputs={}, version_metadata=metadata, schema_dir=SCHEMA_DIR)
            self.assertEqual(raised.exception.error_code, expected)

    async def test_sync_and_queued_requests_fail_before_provider_or_queue(self):
        for response_mode in ("sync", "async_if_queued"):
            with self.subTest(response_mode=response_mode), tempfile.TemporaryDirectory() as tmp:
                state, runtime = self._registered_weather_state(tmp)
                request = TaskExecutionRequest(
                    task_id=f"task-{response_mode}",
                    prompt_id="prompt.weather.scenery",
                    task_family="task.image_generation",
                    requested_by="weather-node",
                    service_id="weather-node",
                    requested_provider="local",
                    inputs={"image_type": "scenery", "condition": "rain"},
                    response_mode=response_mode,
                    trace_id=f"trace-{response_mode}",
                )

                with self.assertRaises(PromptInputValidationFailure):
                    await state.execute_direct(request=request)

                self.assertEqual(runtime.execution_count, 0)
                self.assertEqual((await state.execution_queue_diagnostics())["job_count"], 0)

    async def test_direct_and_route_preview_return_field_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmp:
            state, runtime = self._registered_weather_state(tmp)
            app = create_node_control_app(state=state, logger=logging.getLogger("prompt-schema-test"))
            payload = {
                "task_id": "task-invalid",
                "prompt_id": "prompt.weather.scenery",
                "task_family": "task.image_generation",
                "requested_by": "weather-node",
                "service_id": "weather-node",
                "requested_provider": "local",
                "inputs": {"image_type": "scenery", "condition": "rain"},
                "trace_id": "trace-invalid",
            }
            with TestClient(app) as client:
                direct = client.post("/api/execution/direct", json=payload)
                preview = client.post("/api/execution/route-preview", json=payload)
                authorization = client.post(
                    "/api/execution/authorize",
                    json={
                        "prompt_id": payload["prompt_id"],
                        "task_family": payload["task_family"],
                        "requested_by": payload["requested_by"],
                        "service_id": payload["service_id"],
                        "requested_provider": payload["requested_provider"],
                        "inputs": payload["inputs"],
                    },
                )

            for response in (direct, preview):
                self.assertEqual(response.status_code, 422)
                detail = response.json()["detail"]
                self.assertEqual(detail["error_code"], "prompt_input_validation_failed")
                self.assertTrue(any(item["keyword"] == "required" for item in detail["diagnostics"]))
            self.assertEqual(authorization.status_code, 200)
            self.assertFalse(authorization.json()["allowed"])
            self.assertEqual(authorization.json()["reason"], "prompt_input_validation_failed")
            self.assertTrue(authorization.json()["diagnostics"])
            self.assertEqual(runtime.execution_count, 0)


if __name__ == "__main__":
    unittest.main()
