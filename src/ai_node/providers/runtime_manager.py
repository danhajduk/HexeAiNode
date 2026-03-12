from datetime import datetime, timezone

from ai_node.providers.adapters.local_adapter import LocalProviderAdapter
from ai_node.providers.adapters.openai_adapter import OpenAIProviderAdapter
from ai_node.providers.config_loader import ProviderConfigLoader
from ai_node.providers.execution_router import ProviderExecutionRouter
from ai_node.providers.metrics import ProviderMetricsCollector
from ai_node.providers.models import UnifiedExecutionRequest, UnifiedExecutionResponse
from ai_node.providers.provider_registry import ProviderRegistry


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProviderRuntimeManager:
    def __init__(
        self,
        *,
        logger,
        provider_selection_store=None,
        registry_path: str = "data/provider_registry.json",
        metrics_path: str = "data/provider_metrics.json",
    ) -> None:
        self._logger = logger
        self._loader = ProviderConfigLoader(logger=logger, provider_selection_store=provider_selection_store)
        self._registry = ProviderRegistry()
        self._registry_path = registry_path
        self._metrics = ProviderMetricsCollector(metrics_path=metrics_path, logger=logger)
        self._metrics_path = metrics_path
        self._router = ProviderExecutionRouter(
            registry=self._registry,
            metrics=self._metrics,
            logger=logger,
        )

        self._registry.load(path=self._registry_path)

    async def refresh(self) -> dict:
        config = self._loader.load()
        fallback_provider = None
        for provider_id in config.enabled_providers:
            settings = config.providers.get(provider_id)
            if settings is None:
                continue
            adapter = self._build_adapter(provider_id=provider_id, settings=settings)
            self._registry.register_provider(provider_id=provider_id, adapter=adapter)
            health = await adapter.health_check()
            self._registry.set_provider_health(provider_id=provider_id, payload=health)
            models = await adapter.list_models()
            self._registry.set_models_for_provider(provider_id=provider_id, models=models)
            if fallback_provider is None and provider_id != config.default_provider:
                fallback_provider = provider_id
        self._router = ProviderExecutionRouter(
            registry=self._registry,
            metrics=self._metrics,
            logger=self._logger,
            default_provider=config.default_provider,
            fallback_provider=fallback_provider,
            retry_count=max(max((p.retry_count for p in config.providers.values()), default=0), 0),
        )
        self._registry.persist(path=self._registry_path)
        self._metrics.persist()
        return self.intelligence_payload()

    async def execute(self, request: UnifiedExecutionRequest) -> UnifiedExecutionResponse:
        response = await self._router.execute(request)
        self._metrics.persist()
        if hasattr(self._logger, "info"):
            self._logger.info(
                "[provider-execution] %s",
                {
                    "provider_id": response.provider_id,
                    "model_id": response.model_id,
                    "latency_ms": response.latency_ms,
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "estimated_cost": response.estimated_cost,
                    "success": True,
                },
            )
        return response

    def intelligence_payload(self) -> dict:
        registry_payload = self._registry.snapshot()
        metrics_payload = self._metrics.snapshot()
        metrics_by_provider = metrics_payload.get("providers") if isinstance(metrics_payload, dict) else {}
        providers = []
        for provider in registry_payload.get("providers") or []:
            if not isinstance(provider, dict):
                continue
            provider_id = str(provider.get("provider_id") or "").strip()
            metrics = metrics_by_provider.get(provider_id) if isinstance(metrics_by_provider, dict) else None
            provider_models = []
            for model in provider.get("models") or []:
                if not isinstance(model, dict):
                    continue
                model_id = str(model.get("model_id") or "").strip()
                model_metrics = (metrics or {}).get("models", {}).get(model_id, {}) if isinstance(metrics, dict) else {}
                provider_models.append(
                    {
                        "model_id": model_id,
                        "display_name": model.get("display_name"),
                        "context_window": model.get("context_window"),
                        "max_output_tokens": model.get("max_output_tokens"),
                        "supports_streaming": bool(model.get("supports_streaming")),
                        "supports_tools": bool(model.get("supports_tools")),
                        "supports_vision": bool(model.get("supports_vision")),
                        "supports_json_mode": bool(model.get("supports_json_mode")),
                        "pricing_input": model.get("pricing_input"),
                        "pricing_output": model.get("pricing_output"),
                        "status": model.get("status"),
                        "latency_metrics": {
                            "avg_latency": model_metrics.get("avg_latency"),
                            "p95_latency": model_metrics.get("p95_latency"),
                            "execution_count": model_metrics.get("execution_count", 0),
                            "recent_rolling_samples": model_metrics.get("recent_rolling_samples", []),
                        },
                        "success_metrics": {
                            "total_requests": model_metrics.get("total_requests", 0),
                            "successful_requests": model_metrics.get("successful_requests", 0),
                            "failed_requests": model_metrics.get("failed_requests", 0),
                            "failure_classes": model_metrics.get("failure_classes", {}),
                            "success_rate": model_metrics.get("success_rate", 0.0),
                        },
                        "usage_metrics": {
                            "prompt_tokens": model_metrics.get("prompt_tokens", 0),
                            "completion_tokens": model_metrics.get("completion_tokens", 0),
                            "total_tokens": model_metrics.get("total_tokens", 0),
                            "estimated_cost": model_metrics.get("estimated_cost", 0.0),
                            "cumulative_spend": model_metrics.get("cumulative_spend", 0.0),
                        },
                    }
                )
            providers.append(
                {
                    "provider_id": provider_id,
                    "availability": provider.get("availability"),
                    "health": provider.get("health"),
                    "models": provider_models,
                    "success_metrics": (metrics or {}).get("totals", {}),
                }
            )

        return {
            "generated_at": _iso_now(),
            "providers": providers,
        }

    def providers_snapshot(self) -> dict:
        return self._registry.snapshot()

    def models_snapshot(self) -> dict:
        payload = self._registry.snapshot()
        return {
            "providers": [
                {
                    "provider_id": item.get("provider_id"),
                    "models": item.get("models", []),
                }
                for item in payload.get("providers") or []
                if isinstance(item, dict)
            ]
        }

    def metrics_snapshot(self) -> dict:
        return self._metrics.snapshot()

    @staticmethod
    def _build_adapter(*, provider_id: str, settings):
        if provider_id == "openai":
            return OpenAIProviderAdapter(
                api_key=settings.api_key or "",
                base_url=settings.base_url or "https://api.openai.com/v1",
                timeout_seconds=settings.timeout_seconds,
            )
        return LocalProviderAdapter(provider_id=provider_id)
