import time
from datetime import datetime, timezone

from ai_node.providers.base import ProviderAdapter
from ai_node.providers.models import ModelCapability, UnifiedExecutionRequest, UnifiedExecutionResponse, UnifiedExecutionUsage


class MockProviderAdapter(ProviderAdapter):
    provider_id = "mock"

    def __init__(self, *, provider_id: str = "mock", model_id: str = "mock-model-v1") -> None:
        self.provider_id = provider_id
        self._model_id = model_id
        self._calls = 0
        self._fail_next = False

    def set_fail_next(self, value: bool) -> None:
        self._fail_next = bool(value)

    async def health_check(self) -> dict:
        return {
            "provider_id": self.provider_id,
            "availability": "available",
            "reachable": True,
            "auth_valid": True,
            "last_successful_check": datetime.now(timezone.utc).isoformat(),
            "last_error": None,
        }

    async def list_models(self) -> list[ModelCapability]:
        return [
            ModelCapability(
                model_id=self._model_id,
                display_name=self._model_id,
                input_modalities=["text"],
                output_modalities=["text"],
                context_window=8192,
                max_output_tokens=2048,
                supports_streaming=True,
                supports_tools=True,
                supports_vision=False,
                supports_json_mode=True,
                pricing_input=0.0,
                pricing_output=0.0,
                status="available",
            )
        ]

    async def get_model_capabilities(self, model_id: str):
        for item in await self.list_models():
            if item.model_id == model_id:
                return item
        return None

    async def execute_prompt(self, request: UnifiedExecutionRequest) -> UnifiedExecutionResponse:
        self._calls += 1
        if self._fail_next:
            self._fail_next = False
            raise RuntimeError("mock_execution_failed")
        started = time.perf_counter()
        text = request.prompt or ""
        latency = round((time.perf_counter() - started) * 1000.0, 3)
        usage = UnifiedExecutionUsage(
            prompt_tokens=max(len(text.split()), 1),
            completion_tokens=4,
            total_tokens=max(len(text.split()), 1) + 4,
        )
        return UnifiedExecutionResponse(
            provider_id=self.provider_id,
            model_id=request.requested_model or self._model_id,
            output_text=f"mock:{text}",
            finish_reason="stop",
            usage=usage,
            latency_ms=latency,
            estimated_cost=0.0,
            raw_provider_response_ref=f"mock:{self._calls}",
        )

    def estimate_cost(self, *, model_id: str, prompt_tokens: int, completion_tokens: int):
        return 0.0

    def collect_metrics(self) -> dict:
        return {
            "provider_id": self.provider_id,
            "total_requests": self._calls,
            "successful_requests": self._calls,
            "failed_requests": 0,
            "success_rate": 1.0 if self._calls else 0.0,
        }
