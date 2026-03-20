from abc import ABC, abstractmethod

from ai_node.providers.models import UnifiedExecutionRequest, UnifiedExecutionResponse


class ProviderTaskExecutor(ABC):
    @abstractmethod
    async def execute_classification(self, request: UnifiedExecutionRequest) -> UnifiedExecutionResponse:
        raise NotImplementedError

    @abstractmethod
    async def execute_summarization(self, request: UnifiedExecutionRequest) -> UnifiedExecutionResponse:
        raise NotImplementedError


class RuntimeManagerProviderTaskExecutor(ProviderTaskExecutor):
    def __init__(self, *, provider_runtime_manager) -> None:
        self._provider_runtime_manager = provider_runtime_manager

    async def execute_classification(self, request: UnifiedExecutionRequest) -> UnifiedExecutionResponse:
        return await self._provider_runtime_manager.execute(request)

    async def execute_summarization(self, request: UnifiedExecutionRequest) -> UnifiedExecutionResponse:
        return await self._provider_runtime_manager.execute(request)


class OpenAIProviderTaskExecutor(ProviderTaskExecutor):
    def __init__(self, *, adapter) -> None:
        self._adapter = adapter

    async def execute_classification(self, request: UnifiedExecutionRequest) -> UnifiedExecutionResponse:
        return await self._adapter.execute_prompt(request)

    async def execute_summarization(self, request: UnifiedExecutionRequest) -> UnifiedExecutionResponse:
        return await self._adapter.execute_prompt(request)


class OllamaProviderTaskExecutor(ProviderTaskExecutor):
    def __init__(self, *, adapter=None) -> None:
        self._adapter = adapter

    async def execute_classification(self, request: UnifiedExecutionRequest) -> UnifiedExecutionResponse:
        raise RuntimeError("ollama_task_executor_not_implemented")

    async def execute_summarization(self, request: UnifiedExecutionRequest) -> UnifiedExecutionResponse:
        raise RuntimeError("ollama_task_executor_not_implemented")
