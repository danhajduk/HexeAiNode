from ai_node.providers.metrics import ProviderMetricsCollector
from ai_node.providers.models import UnifiedExecutionRequest, UnifiedExecutionResponse
from ai_node.providers.provider_registry import ProviderRegistry


class ProviderExecutionRouter:
    def __init__(
        self,
        *,
        registry: ProviderRegistry,
        metrics: ProviderMetricsCollector,
        logger,
        default_provider: str | None = None,
        fallback_provider: str | None = None,
        retry_count: int = 0,
    ) -> None:
        self._registry = registry
        self._metrics = metrics
        self._logger = logger
        self._default_provider = default_provider
        self._fallback_provider = fallback_provider
        self._retry_count = max(int(retry_count), 0)

    async def execute(self, request: UnifiedExecutionRequest) -> UnifiedExecutionResponse:
        requested_provider = str(request.requested_provider or "").strip()
        provider_order: list[str] = []
        if requested_provider:
            provider_order.append(requested_provider)
        if self._default_provider and self._default_provider not in provider_order:
            provider_order.append(self._default_provider)
        if self._fallback_provider and self._fallback_provider not in provider_order:
            provider_order.append(self._fallback_provider)
        for provider_id in self._registry.list_providers():
            if provider_id not in provider_order:
                provider_order.append(provider_id)
        if not provider_order:
            raise RuntimeError("no_provider_configured")

        first_error = None
        for index, provider_id in enumerate(provider_order):
            adapter = self._registry.get_provider(provider_id)
            if adapter is None:
                continue
            health = self._registry.get_provider_health(provider_id) or {}
            availability = str(health.get("availability") or "unavailable")
            if availability not in {"available", "degraded"}:
                continue

            attempts = self._retry_count + 1
            while attempts > 0:
                attempts -= 1
                try:
                    response = await adapter.execute_prompt(request)
                    self._metrics.record_success(
                        provider_id=response.provider_id,
                        model_id=response.model_id,
                        latency_ms=response.latency_ms,
                        prompt_tokens=response.usage.prompt_tokens,
                        cached_input_tokens=response.usage.cached_input_tokens,
                        completion_tokens=response.usage.completion_tokens,
                        estimated_cost=response.estimated_cost,
                    )
                    if index > 0 and hasattr(self._logger, "warning"):
                        self._logger.warning(
                            "[provider-fallback] %s",
                            {
                                "reason": "primary_unavailable_or_failed",
                                "selected_provider": response.provider_id,
                                "requested_provider": requested_provider or None,
                            },
                        )
                    return response
                except Exception as exc:
                    self._metrics.record_failure(
                        provider_id=provider_id,
                        model_id=str(request.requested_model or "unknown").strip() or "unknown",
                        error_class=type(exc).__name__,
                    )
                    if first_error is None:
                        first_error = exc
                    if hasattr(self._logger, "warning"):
                        self._logger.warning(
                            "[provider-execution-error] %s",
                            {
                                "provider_id": provider_id,
                                "retry_remaining": attempts,
                                "error_class": type(exc).__name__,
                            },
                        )
                    if attempts <= 0:
                        break
        raise RuntimeError(str(first_error) if first_error is not None else "provider_execution_failed")
