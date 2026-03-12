from typing import Any

from ai_node.providers.base import ProviderAdapter
from ai_node.providers.models import ModelCapability, UnifiedExecutionRequest, UnifiedExecutionResponse, UnifiedExecutionUsage


class LocalProviderAdapter(ProviderAdapter):
    provider_id = "local"

    def __init__(self, *, provider_id: str = "local") -> None:
        self.provider_id = str(provider_id or "local").strip()

    async def health_check(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "availability": "unavailable",
            "reachable": False,
            "auth_valid": True,
            "last_successful_check": None,
            "last_error": "local_provider_not_implemented",
        }

    async def list_models(self) -> list[ModelCapability]:
        return []

    async def get_model_capabilities(self, model_id: str) -> ModelCapability | None:
        return None

    async def execute_prompt(self, request: UnifiedExecutionRequest) -> UnifiedExecutionResponse:
        raise RuntimeError("local_provider_not_implemented")

    def estimate_cost(self, *, model_id: str, prompt_tokens: int, completion_tokens: int) -> float | None:
        return 0.0

    def collect_metrics(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "success_rate": 0.0,
            "health": {
                "availability": "unavailable",
                "last_error": "local_provider_not_implemented",
            },
        }
