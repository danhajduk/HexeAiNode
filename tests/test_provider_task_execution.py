import unittest

from ai_node.providers.models import UnifiedExecutionRequest, UnifiedExecutionResponse, UnifiedExecutionUsage
from ai_node.providers.task_execution import (
    OllamaProviderTaskExecutor,
    OpenAIProviderTaskExecutor,
    RuntimeManagerProviderTaskExecutor,
)


class _FakeRuntimeManager:
    def __init__(self):
        self.last_request = None

    async def execute(self, request):
        self.last_request = request
        return UnifiedExecutionResponse(
            provider_id="openai",
            model_id=str(request.requested_model or "gpt-5-mini"),
            output_text="ok",
            usage=UnifiedExecutionUsage(total_tokens=1),
            latency_ms=1.0,
        )


class _FakeAdapter:
    def __init__(self):
        self.last_request = None

    async def execute_prompt(self, request):
        self.last_request = request
        return UnifiedExecutionResponse(
            provider_id="openai",
            model_id=str(request.requested_model or "gpt-5-mini"),
            output_text="ok",
            usage=UnifiedExecutionUsage(total_tokens=1),
            latency_ms=1.0,
        )


class ProviderTaskExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_runtime_manager_task_executor_delegates_to_runtime_manager(self):
        runtime_manager = _FakeRuntimeManager()
        executor = RuntimeManagerProviderTaskExecutor(provider_runtime_manager=runtime_manager)
        request = UnifiedExecutionRequest(task_family="task.classification", prompt="hello")

        response = await executor.execute_classification(request)

        self.assertEqual(response.output_text, "ok")
        self.assertIs(runtime_manager.last_request, request)

    async def test_openai_task_executor_delegates_to_adapter(self):
        adapter = _FakeAdapter()
        executor = OpenAIProviderTaskExecutor(adapter=adapter)
        request = UnifiedExecutionRequest(task_family="task.summarization.text", prompt="hello")

        response = await executor.execute_summarization(request)

        self.assertEqual(response.output_text, "ok")
        self.assertIs(adapter.last_request, request)

    async def test_ollama_task_executor_is_explicit_placeholder(self):
        executor = OllamaProviderTaskExecutor()
        request = UnifiedExecutionRequest(task_family="task.classification", prompt="hello")

        with self.assertRaises(RuntimeError) as context:
            await executor.execute_classification(request)

        self.assertEqual(str(context.exception), "ollama_task_executor_not_implemented")


if __name__ == "__main__":
    unittest.main()
