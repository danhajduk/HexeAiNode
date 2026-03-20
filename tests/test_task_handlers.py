import json
import unittest

from ai_node.providers.models import UnifiedExecutionResponse, UnifiedExecutionUsage
from ai_node.runtime.task_handlers import (
    CLASSIFICATION_TASK_FAMILIES,
    SUMMARIZATION_TASK_FAMILIES,
    ClassificationTaskHandler,
    SummarizationTaskHandler,
)


class _FakeProviderRuntimeManager:
    def __init__(self):
        self.last_request = None

    async def execute(self, request):
        self.last_request = request
        return UnifiedExecutionResponse(
            provider_id=str(request.requested_provider or "openai"),
            model_id=str(request.requested_model or "gpt-5-mini"),
            output_text="ok",
            usage=UnifiedExecutionUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            latency_ms=1.0,
        )


class _FakeTaskExecutor:
    def __init__(self):
        self.last_request = None

    async def execute_classification(self, request):
        self.last_request = request
        return UnifiedExecutionResponse(
            provider_id=str(request.requested_provider or "openai"),
            model_id=str(request.requested_model or "gpt-5-mini"),
            output_text="ok",
            usage=UnifiedExecutionUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            latency_ms=1.0,
        )

    async def execute_summarization(self, request):
        self.last_request = request
        return UnifiedExecutionResponse(
            provider_id=str(request.requested_provider or "openai"),
            model_id=str(request.requested_model or "gpt-5-mini"),
            output_text="ok",
            usage=UnifiedExecutionUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            latency_ms=1.0,
        )


class _Resolution:
    provider_id = "openai"
    model_id = "gpt-5-mini"


class TaskHandlersTests(unittest.IsolatedAsyncioTestCase):
    async def test_classification_handler_supports_existing_broader_family_set(self):
        self.assertIn("task.classification.email", CLASSIFICATION_TASK_FAMILIES)
        executor = _FakeTaskExecutor()
        handler = ClassificationTaskHandler(task_executor=executor)

        request = type(
            "Request",
            (),
            {
                "task_id": "task-001",
                "task_family": "task.classification.email",
                "requested_by": "service.alpha",
                "trace_id": "trace-001",
                "prompt_id": None,
                "lease_id": None,
                "inputs": {"body": "Please classify this message"},
            },
        )()
        await handler(request=request, resolution=_Resolution())

        self.assertEqual(executor.last_request.task_family, "task.classification.email")
        self.assertEqual(executor.last_request.prompt, "Please classify this message")

    async def test_summarization_handler_normalizes_event_payload_to_prompt(self):
        self.assertIn("task.summarization.event", SUMMARIZATION_TASK_FAMILIES)
        executor = _FakeTaskExecutor()
        handler = SummarizationTaskHandler(task_executor=executor)

        request = type(
            "Request",
            (),
            {
                "task_id": "task-002",
                "task_family": "task.summarization.event",
                "requested_by": "service.alpha",
                "trace_id": "trace-002",
                "prompt_id": None,
                "lease_id": None,
                "inputs": {"event": {"title": "Launch", "attendees": 4}},
            },
        )()
        await handler(request=request, resolution=_Resolution())

        self.assertEqual(
            executor.last_request.prompt,
            json.dumps({"attendees": 4, "title": "Launch"}, sort_keys=True),
        )

    async def test_handlers_reject_missing_prompt_and_messages(self):
        executor = _FakeTaskExecutor()
        handler = SummarizationTaskHandler(task_executor=executor)
        request = type(
            "Request",
            (),
            {
                "task_id": "task-003",
                "task_family": "task.summarization.text",
                "requested_by": "service.alpha",
                "trace_id": "trace-003",
                "prompt_id": None,
                "lease_id": None,
                "inputs": {},
            },
        )()

        with self.assertRaises(ValueError) as context:
            await handler(request=request, resolution=_Resolution())

        self.assertEqual(str(context.exception), "invalid_input")

    async def test_email_family_combines_subject_and_body(self):
        executor = _FakeTaskExecutor()
        handler = ClassificationTaskHandler(task_executor=executor)
        request = type(
            "Request",
            (),
            {
                "task_id": "task-004",
                "task_family": "task.classification.email",
                "requested_by": "service.alpha",
                "trace_id": "trace-004",
                "prompt_id": None,
                "lease_id": None,
                "inputs": {"subject": "Hello", "body": "Please classify this"},
            },
        )()

        await handler(request=request, resolution=_Resolution())

        self.assertEqual(executor.last_request.prompt, "Subject: Hello\n\nPlease classify this")
        self.assertEqual(executor.last_request.metadata["email_subject"], "Hello")

    async def test_image_family_accepts_image_only_input(self):
        executor = _FakeTaskExecutor()
        handler = ClassificationTaskHandler(task_executor=executor)
        request = type(
            "Request",
            (),
            {
                "task_id": "task-005",
                "task_family": "task.classification.image",
                "requested_by": "service.alpha",
                "trace_id": "trace-005",
                "prompt_id": None,
                "lease_id": None,
                "inputs": {"image_url": "https://example.com/cat.png"},
            },
        )()

        await handler(request=request, resolution=_Resolution())

        self.assertEqual(executor.last_request.prompt, "Classify the provided image input.")
        self.assertEqual(executor.last_request.metadata["image_url"], "https://example.com/cat.png")


if __name__ == "__main__":
    unittest.main()
