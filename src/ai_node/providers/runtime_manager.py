from datetime import datetime, timezone
import os

from ai_node.providers.adapters.local_adapter import LocalProviderAdapter
from ai_node.providers.adapters.openai_adapter import OpenAIProviderAdapter
from ai_node.providers.config_loader import ProviderConfigLoader
from ai_node.providers.execution_router import ProviderExecutionRouter
from ai_node.providers.metrics import ProviderMetricsCollector
from ai_node.providers.models import UnifiedExecutionRequest, UnifiedExecutionResponse
from ai_node.providers.openai_catalog import (
    DEFAULT_OPENAI_PRICING_CATALOG_PATH,
    DEFAULT_OPENAI_PRICING_REFRESH_INTERVAL_SECONDS,
    DEFAULT_OPENAI_PRICING_STALE_TOLERANCE_SECONDS,
    OpenAIPricingCatalogService,
    is_regular_openai_model_id,
    resolve_openai_base_model_id,
)
from ai_node.providers.openai_model_catalog import (
    DEFAULT_OPENAI_PROVIDER_MODEL_CATALOG_PATH,
    OpenAIProviderModelCatalogStore,
)
from ai_node.providers.provider_registry import ProviderRegistry


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProviderRuntimeManager:
    def __init__(
        self,
        *,
        logger,
        provider_selection_store=None,
        provider_credentials_store=None,
        registry_path: str = "data/provider_registry.json",
        metrics_path: str = "data/provider_metrics.json",
        pricing_catalog_path: str = DEFAULT_OPENAI_PRICING_CATALOG_PATH,
        pricing_refresh_interval_seconds: int = DEFAULT_OPENAI_PRICING_REFRESH_INTERVAL_SECONDS,
        pricing_stale_tolerance_seconds: int = DEFAULT_OPENAI_PRICING_STALE_TOLERANCE_SECONDS,
        provider_model_catalog_path: str = DEFAULT_OPENAI_PROVIDER_MODEL_CATALOG_PATH,
    ) -> None:
        self._logger = logger
        self._loader = ProviderConfigLoader(
            logger=logger,
            provider_selection_store=provider_selection_store,
            provider_credentials_store=provider_credentials_store,
        )
        self._registry = ProviderRegistry()
        self._registry_path = registry_path
        self._metrics = ProviderMetricsCollector(metrics_path=metrics_path, logger=logger)
        self._metrics_path = metrics_path
        self._pricing_catalog_service = OpenAIPricingCatalogService(
            logger=logger,
            catalog_path=pricing_catalog_path,
            refresh_interval_seconds=pricing_refresh_interval_seconds,
            stale_tolerance_seconds=pricing_stale_tolerance_seconds,
        )
        self._openai_model_catalog_store = OpenAIProviderModelCatalogStore(
            path=provider_model_catalog_path,
            logger=logger,
        )
        self._router = ProviderExecutionRouter(
            registry=self._registry,
            metrics=self._metrics,
            logger=logger,
        )

        self._registry.load(path=self._registry_path)

    async def refresh(self) -> dict:
        config = self._loader.load()
        fallback_provider = None
        unknown_models: list[str] = []
        for provider_id in config.enabled_providers:
            settings = config.providers.get(provider_id)
            if settings is None:
                continue
            adapter = self._build_adapter(provider_id=provider_id, settings=settings)
            self._registry.register_provider(provider_id=provider_id, adapter=adapter)
            health = await adapter.health_check()
            self._registry.set_provider_health(provider_id=provider_id, payload=health)
            models = await adapter.list_models()
            if provider_id == "openai" and self._pricing_catalog_service is not None:
                self._openai_model_catalog_store.save_from_model_ids(
                    model_ids=[getattr(model, "model_id", "") for model in models]
                )
                merged_models, provider_unknown_models = self._pricing_catalog_service.merge_model_capabilities(models)
                models = merged_models
                unknown_models.extend(provider_unknown_models)
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
        payload = self.intelligence_payload()
        payload["pricing_diagnostics"] = self.pricing_diagnostics_payload()
        payload["unknown_priced_models"] = sorted(set(item for item in unknown_models if item))
        return payload

    async def refresh_pricing(self, *, force: bool) -> dict:
        return await self._pricing_catalog_service.refresh(force=force)

    def save_manual_openai_pricing(
        self,
        *,
        model_id: str,
        display_name: str | None = None,
        input_price_per_1m: float | None = None,
        output_price_per_1m: float | None = None,
    ) -> dict:
        return self._pricing_catalog_service.save_manual_pricing(
            model_id=model_id,
            display_name=display_name,
            input_price_per_1m=input_price_per_1m,
            output_price_per_1m=output_price_per_1m,
        )

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
                        "created": model.get("created"),
                        "context_window": model.get("context_window"),
                        "max_output_tokens": model.get("max_output_tokens"),
                        "supports_streaming": bool(model.get("supports_streaming")),
                        "supports_tools": bool(model.get("supports_tools")),
                        "supports_vision": bool(model.get("supports_vision")),
                        "supports_json_mode": bool(model.get("supports_json_mode")),
                        "pricing_input": model.get("pricing_input"),
                        "cached_pricing_input": model.get("cached_pricing_input"),
                        "pricing_output": model.get("pricing_output"),
                        "batch_pricing_input": model.get("batch_pricing_input"),
                        "batch_pricing_output": model.get("batch_pricing_output"),
                        "pricing_status": model.get("pricing_status"),
                        "pricing_source_url": model.get("pricing_source_url"),
                        "pricing_scraped_at": model.get("pricing_scraped_at"),
                        "pricing_notes": model.get("pricing_notes"),
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

    def latest_models_payload(self, *, provider_id: str, limit: int = 3) -> dict:
        models = self._registry.list_models_by_provider(provider_id)
        canonical_models: dict[str, dict] = {}
        for model in models:
            payload = model.model_dump()
            model_id = str(payload.get("model_id") or "").strip()
            if provider_id == "openai" and not is_regular_openai_model_id(model_id):
                continue
            canonical_id = resolve_openai_base_model_id(model_id) if provider_id == "openai" else model_id
            existing = canonical_models.get(canonical_id)
            if existing is None or int(payload.get("created") or 0) >= int(existing.get("created") or 0):
                payload["model_id"] = canonical_id
                payload["base_model_id"] = canonical_id
                canonical_models[canonical_id] = payload
        sorted_models = sorted(
            canonical_models.values(),
            key=lambda item: (int(item.get("created") or 0), str(item.get("model_id") or "")),
            reverse=True,
        )
        return {
            "provider_id": str(provider_id or "").strip(),
            "models": sorted_models[: max(int(limit), 0)],
            "source": "provider_registry",
            "generated_at": _iso_now(),
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

    def pricing_diagnostics_payload(self) -> dict:
        return self._pricing_catalog_service.diagnostics_payload()

    def _build_adapter(self, *, provider_id: str, settings):
        if provider_id == "openai":
            return OpenAIProviderAdapter(
                api_key=settings.api_key or "",
                default_model_id=settings.default_model_id,
                base_url=settings.base_url or "https://api.openai.com/v1",
                timeout_seconds=settings.timeout_seconds,
                pricing_catalog_service=self._pricing_catalog_service,
            )
        return LocalProviderAdapter(provider_id=provider_id)
