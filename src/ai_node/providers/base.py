from abc import ABC, abstractmethod
from typing import Any

from ai_node.providers.models import ModelCapability, UnifiedExecutionRequest, UnifiedExecutionResponse


class ProviderAdapter(ABC):
    provider_id: str

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def list_models(self) -> list[ModelCapability]:
        raise NotImplementedError

    @abstractmethod
    async def get_model_capabilities(self, model_id: str) -> ModelCapability | None:
        raise NotImplementedError

    @abstractmethod
    async def execute_prompt(self, request: UnifiedExecutionRequest) -> UnifiedExecutionResponse:
        raise NotImplementedError

    @abstractmethod
    def estimate_cost(
        self,
        *,
        model_id: str,
        prompt_tokens: int,
        completion_tokens: int,
        cached_input_tokens: int = 0,
    ) -> float | None:
        raise NotImplementedError

    @abstractmethod
    def collect_metrics(self) -> dict[str, Any]:
        raise NotImplementedError
