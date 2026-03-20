import json
from datetime import datetime, timezone
import os
from pathlib import Path

from ai_node.capabilities.resolved_task_families import derive_declared_task_families
from ai_node.providers.adapters.local_adapter import LocalProviderAdapter
from ai_node.providers.adapters.openai_adapter import OpenAIProviderAdapter
from ai_node.providers.config_loader import ProviderConfigLoader
from ai_node.providers.execution_router import ProviderExecutionRouter
from ai_node.providers.capability_resolution import resolve_enabled_model_capabilities
from ai_node.providers.model_capability_catalog import (
    DEFAULT_PROVIDER_MODEL_CAPABILITIES_PATH,
    OpenAIModelCapabilityClassifier,
    ProviderModelCapabilitiesStore,
)
from ai_node.providers.model_feature_catalog import (
    DEFAULT_PROVIDER_MODEL_FEATURES_PATH,
    ProviderModelFeatureCatalogStore,
)
from ai_node.runtime.capability_resolver import load_task_graph, resolve_node_capabilities
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
    select_representative_openai_model_ids,
)
from ai_node.config.provider_enabled_models_config import (
    DEFAULT_PROVIDER_ENABLED_MODELS_PATH,
    ProviderEnabledModelsStore,
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
        provider_model_capabilities_path: str = DEFAULT_PROVIDER_MODEL_CAPABILITIES_PATH,
        provider_model_features_path: str = DEFAULT_PROVIDER_MODEL_FEATURES_PATH,
        provider_enabled_models_path: str = DEFAULT_PROVIDER_ENABLED_MODELS_PATH,
        node_capabilities_path: str = "runtime/node_capabilities.json",
        task_graph_path: str = "capabilities/task_graph.json",
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
        self._provider_model_capabilities_store = ProviderModelCapabilitiesStore(
            path=provider_model_capabilities_path,
            logger=logger,
        )
        self._provider_model_feature_catalog_store = ProviderModelFeatureCatalogStore(
            path=provider_model_features_path,
            logger=logger,
        )
        self._provider_enabled_models_store = ProviderEnabledModelsStore(
            path=provider_enabled_models_path,
            logger=logger,
        )
        self._node_capabilities_path = Path(node_capabilities_path)
        self._task_graph_path = task_graph_path
        self._router = ProviderExecutionRouter(
            registry=self._registry,
            metrics=self._metrics,
            logger=logger,
        )

        self._registry.load(path=self._registry_path)

    def _provider_intelligence_allowed_model_ids(self, *, provider_id: str) -> set[str] | None:
        normalized_provider_id = str(provider_id or "").strip().lower()
        if normalized_provider_id != "openai":
            return None
        snapshot = self._openai_model_catalog_store.load()
        if snapshot is None:
            return None
        allowed = {
            str(entry.model_id or "").strip().lower()
            for entry in snapshot.models
            if str(entry.model_id or "").strip()
        }
        return allowed or None

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
                model_catalog_snapshot = self._openai_model_catalog_store.save_from_model_ids(
                    model_ids=[getattr(model, "model_id", "") for model in models]
                )
                processing_model_ids = self._openai_processing_model_ids(
                    catalog_model_ids=[entry.model_id for entry in model_catalog_snapshot.models]
                )
                scoped_models = [
                    entry for entry in model_catalog_snapshot.models if entry.model_id in set(processing_model_ids)
                ]
                await self._refresh_openai_model_capabilities(models=scoped_models)
                if self._openai_api_pricing_fetch_enabled():
                    await self._refresh_openai_pricing(
                        adapter=adapter,
                        model_ids=processing_model_ids,
                        force=False,
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
        if not self._openai_api_pricing_fetch_enabled():
            return {
                "status": "manual_only",
                "changed": False,
                "notes": ["openai_api_pricing_fetch_disabled"],
            }
        settings = (
            self._loader.load_provider_settings(provider_id="openai", enabled=True)
            if hasattr(self._loader, "load_provider_settings")
            else None
        )
        if settings is None or not str(settings.api_key or "").strip():
            return await self._pricing_catalog_service.refresh(force=force)
        adapter = self._build_adapter(provider_id="openai", settings=settings)
        model_catalog_snapshot = self._openai_model_catalog_store.load()
        if model_catalog_snapshot is None or not model_catalog_snapshot.models:
            models = await adapter.list_models()
            model_catalog_snapshot = self._openai_model_catalog_store.save_from_model_ids(
                model_ids=[getattr(model, "model_id", "") for model in models]
            )
        model_ids = self._openai_processing_model_ids(
            catalog_model_ids=[entry.model_id for entry in model_catalog_snapshot.models]
        )
        return await self._pricing_catalog_service.refresh(
            force=force,
            model_ids=model_ids,
            execute_batch=self._build_pricing_execute_batch(adapter=adapter),
        )

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
            allowed_model_ids = self._provider_intelligence_allowed_model_ids(provider_id=provider_id)
            provider_models = []
            for model in provider.get("models") or []:
                if not isinstance(model, dict):
                    continue
                model_id = str(model.get("model_id") or "").strip()
                if allowed_model_ids is not None and model_id.lower() not in allowed_model_ids:
                    continue
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

    def openai_model_catalog_payload(self) -> dict:
        return self._openai_model_catalog_store.payload()

    def openai_model_capabilities_payload(self) -> dict:
        return self._provider_model_capabilities_store.payload()

    def openai_enabled_models_payload(self) -> dict:
        return self._provider_enabled_models_store.payload()

    def openai_usable_models_payload(self) -> dict:
        enabled_snapshot = self._provider_enabled_models_store.load()
        selected_model_ids = [entry.model_id for entry in enabled_snapshot.models] if enabled_snapshot is not None else []
        classified_snapshot = self._provider_model_capabilities_store.load()
        classified_ids = {
            str(entry.model_id or "").strip().lower()
            for entry in (classified_snapshot.entries if classified_snapshot is not None else [])
            if str(entry.model_id or "").strip()
        }
        registry_models = {
            str(model.model_id or "").strip().lower(): model.model_dump()
            for model in self._registry.list_models_by_provider("openai")
            if str(model.model_id or "").strip()
        }
        usable_model_ids: list[str] = []
        blocked_models: list[dict] = []
        for model_id in selected_model_ids:
            normalized_model_id = str(model_id or "").strip().lower()
            blockers: list[str] = []
            if normalized_model_id not in classified_ids:
                blockers.append("not_classified")
            registry_model = registry_models.get(normalized_model_id)
            model_status = str((registry_model or {}).get("status") or "").strip().lower()
            if model_status not in {"available", "degraded"}:
                blockers.append("not_available")
            if blockers:
                blocked_models.append(
                    {
                        "model_id": model_id,
                        "blockers": blockers,
                        "status": model_status or "unknown",
                    }
                )
                continue
            usable_model_ids.append(model_id)
        return {
            "provider_id": "openai",
            "selected_model_ids": selected_model_ids,
            "usable_model_ids": usable_model_ids,
            "blocked_models": blocked_models,
            "generated_at": _iso_now(),
            "source": "provider_enabled_models",
        }

    def provider_selection_context_payload(self) -> dict:
        config = self._loader.load()
        enabled_providers = list(config.enabled_providers or [])
        default_model_by_provider: dict[str, str | None] = {}
        provider_retry_count: dict[str, int] = {}
        provider_health: dict[str, dict] = {}
        available_models_by_provider: dict[str, list[str]] = {}
        usable_models_by_provider: dict[str, list[str]] = {}

        for provider_id in enabled_providers:
            settings = config.providers.get(provider_id)
            default_model_by_provider[provider_id] = settings.default_model_id if settings is not None else None
            provider_retry_count[provider_id] = max(int(settings.retry_count), 0) if settings is not None else 0
            provider_health[provider_id] = self._registry.get_provider_health(provider_id) or {}
            available_models = [
                str(model.model_id or "").strip()
                for model in self._registry.list_models_by_provider(provider_id)
                if str(model.model_id or "").strip() and str(model.status or "").strip().lower() in {"available", "degraded"}
            ]
            available_models_by_provider[provider_id] = available_models
            usable_models_by_provider[provider_id] = list(available_models)

        openai_usable = self.openai_usable_models_payload()
        openai_usable_ids = [str(item or "").strip() for item in list(openai_usable.get("usable_model_ids") or []) if str(item or "").strip()]
        if openai_usable_ids:
            usable_models_by_provider["openai"] = openai_usable_ids

        return {
            "enabled_providers": enabled_providers,
            "default_provider": config.default_provider,
            "default_model_by_provider": default_model_by_provider,
            "provider_retry_count": provider_retry_count,
            "provider_health": provider_health,
            "available_models_by_provider": available_models_by_provider,
            "usable_models_by_provider": usable_models_by_provider,
            "generated_at": _iso_now(),
            "source": "provider_runtime_manager",
        }

    def openai_model_features_payload(self) -> dict:
        return self._provider_model_feature_catalog_store.payload()

    def save_openai_enabled_models(self, *, model_ids: list[str]) -> dict:
        snapshot = self._provider_enabled_models_store.save_enabled_model_ids(model_ids=model_ids)
        self._resolve_and_persist_node_capabilities()
        return {
            "provider_id": snapshot.provider_id,
            "models": [entry.model_dump() for entry in snapshot.models],
            "generated_at": snapshot.updated_at,
            "source": "provider_enabled_models",
        }

    def _openai_processing_model_ids(self, *, catalog_model_ids: list[str]) -> list[str]:
        normalized_catalog: list[str] = []
        for model_id in catalog_model_ids:
            normalized = str(model_id or "").strip().lower()
            if normalized and normalized not in normalized_catalog:
                normalized_catalog.append(normalized)
        selected = select_representative_openai_model_ids(normalized_catalog)
        scoped = sorted(model_id for model_id in normalized_catalog if model_id in selected)
        return scoped or normalized_catalog

    def openai_resolved_capabilities_payload(self) -> dict:
        capabilities_snapshot = self._provider_model_capabilities_store.load()
        usable_payload = self.openai_usable_models_payload()
        enabled_model_ids = list(usable_payload.get("usable_model_ids") or [])
        payload = resolve_enabled_model_capabilities(snapshot=capabilities_snapshot, enabled_model_ids=enabled_model_ids)
        payload["selected_model_ids"] = list(usable_payload.get("selected_model_ids") or [])
        payload["blocked_models"] = list(usable_payload.get("blocked_models") or [])
        payload["task_families"] = derive_declared_task_families(resolved_capabilities=payload)
        return payload

    def node_capabilities_payload(self) -> dict:
        if not self._node_capabilities_path.exists():
            return {
                "schema_version": "1.0",
                "capability_graph_version": "1.0",
                "enabled_models": [],
                "feature_union": {},
                "resolved_tasks": [],
                "enabled_task_capabilities": [],
                "generated_at": _iso_now(),
                "source": "node_capabilities",
            }
        try:
            payload = json.loads(self._node_capabilities_path.read_text(encoding="utf-8"))
        except Exception:
            return {
                "schema_version": "1.0",
                "capability_graph_version": "1.0",
                "enabled_models": [],
                "feature_union": {},
                "resolved_tasks": [],
                "enabled_task_capabilities": [],
                "generated_at": _iso_now(),
                "source": "node_capabilities",
            }
        if not isinstance(payload, dict):
            return {
                "schema_version": "1.0",
                "capability_graph_version": "1.0",
                "enabled_models": [],
                "feature_union": {},
                "resolved_tasks": [],
                "enabled_task_capabilities": [],
                "generated_at": _iso_now(),
                "source": "node_capabilities",
            }
        payload.setdefault("source", "node_capabilities")
        return payload

    def rebuild_node_capabilities(self) -> dict:
        self._resolve_and_persist_node_capabilities()
        payload = self.node_capabilities_payload()
        return {
            "status": "rebuilt",
            "provider_id": "openai",
            "resolved_capabilities": self.openai_resolved_capabilities_payload(),
            "resolved_tasks": list(payload.get("enabled_task_capabilities") or payload.get("resolved_tasks") or []),
            "node_capabilities": payload,
        }

    async def rerun_openai_model_capabilities(self) -> dict:
        config = self._loader.load()
        settings = config.providers.get("openai")
        if settings is None or not settings.enabled:
            raise ValueError("openai provider is not enabled")
        adapter = self._build_adapter(provider_id="openai", settings=settings)
        model_catalog_snapshot = self._openai_model_catalog_store.load()
        if model_catalog_snapshot is None or not model_catalog_snapshot.models:
            models = await adapter.list_models()
            model_catalog_snapshot = self._openai_model_catalog_store.save_from_model_ids(
                model_ids=[getattr(model, "model_id", "") for model in models]
            )
        processing_model_ids = self._openai_processing_model_ids(
            catalog_model_ids=[entry.model_id for entry in model_catalog_snapshot.models]
        )
        scoped_models = [entry for entry in model_catalog_snapshot.models if entry.model_id in set(processing_model_ids)]
        await self._refresh_openai_model_capabilities(models=scoped_models)
        if self._openai_api_pricing_fetch_enabled():
            await self._refresh_openai_pricing(
                adapter=adapter,
                model_ids=processing_model_ids,
                force=True,
            )
        return {"status": "refreshed", **self.openai_model_capabilities_payload()}

    async def refresh_openai_models_from_saved_credentials(self) -> dict:
        settings = (
            self._loader.load_provider_settings(provider_id="openai", enabled=True)
            if hasattr(self._loader, "load_provider_settings")
            else None
        )
        if settings is None or not str(settings.api_key or "").strip():
            raise ValueError("openai credentials are not configured")
        adapter = self._build_adapter(provider_id="openai", settings=settings)
        self._registry.register_provider(provider_id="openai", adapter=adapter)
        health = await adapter.health_check()
        self._registry.set_provider_health(provider_id="openai", payload=health)
        models = await adapter.list_models()
        model_catalog_snapshot = self._openai_model_catalog_store.save_from_model_ids(
            model_ids=[getattr(model, "model_id", "") for model in models]
        )
        processing_model_ids = self._openai_processing_model_ids(
            catalog_model_ids=[entry.model_id for entry in model_catalog_snapshot.models]
        )
        scoped_models = [entry for entry in model_catalog_snapshot.models if entry.model_id in set(processing_model_ids)]
        await self._refresh_openai_model_capabilities(models=scoped_models)
        if self._openai_api_pricing_fetch_enabled():
            await self._refresh_openai_pricing(
                adapter=adapter,
                model_ids=processing_model_ids,
                force=True,
            )
        unknown_models: list[str] = []
        if self._pricing_catalog_service is not None:
            models, unknown_models = self._pricing_catalog_service.merge_model_capabilities(models)
        self._registry.set_models_for_provider(provider_id="openai", models=models)
        self._registry.persist(path=self._registry_path)
        self._metrics.persist()
        return {
            "status": "refreshed",
            "provider_id": "openai",
            "classification_model": self.openai_model_capabilities_payload().get("classification_model"),
            "unknown_priced_models": sorted(set(item for item in unknown_models if item)),
        }

    def _openai_api_pricing_fetch_enabled(self) -> bool:
        raw = str(os.environ.get("SYNTHIA_OPENAI_API_PRICING_FETCH_ENABLED", "")).strip().lower()
        if raw in {"1", "true", "yes", "on"}:
            return True
        if raw in {"0", "false", "no", "off", ""}:
            return False
        return False

    async def _refresh_openai_model_capabilities(self, *, models: list) -> None:
        if not models:
            self._provider_model_capabilities_store.save(classification_model=None, entries=[])
            self._provider_model_feature_catalog_store.save_entries(
                provider="openai",
                classification_model=None,
                entries=[],
            )
            return

        classifier = OpenAIModelCapabilityClassifier(
            logger=self._logger,
            store=self._provider_model_capabilities_store,
        )
        try:
            snapshot = await classifier.classify_and_save(models=models)
            if snapshot is None:
                self._provider_model_feature_catalog_store.save_entries(
                    provider="openai",
                    classification_model=None,
                    entries=[],
                )
                return
            self._provider_model_feature_catalog_store.save_entries(
                provider="openai",
                classification_model=snapshot.classification_model,
                entries=[
                    {
                        "model_id": entry.model_id,
                        "features": entry.feature_flags,
                    }
                    for entry in snapshot.entries
                ],
                classified_at=snapshot.classified_at or snapshot.updated_at,
            )
            self._resolve_and_persist_node_capabilities()
        except Exception as exc:
            if hasattr(self._logger, "warning"):
                self._logger.warning("[provider-model-capability-classification-failed] %s", {"error": str(exc).strip() or type(exc).__name__})

    def _build_pricing_execute_batch(self, *, adapter: OpenAIProviderAdapter):
        async def execute_batch(model_id: str, system_prompt: str, user_prompt: str) -> str:
            response = await adapter.execute_prompt(
                UnifiedExecutionRequest(
                    task_family="task.classification.text",
                    system_prompt=system_prompt,
                    prompt=user_prompt,
                    requested_model=model_id,
                )
            )
            return response.output_text

        return execute_batch

    async def _refresh_openai_pricing(self, *, adapter: OpenAIProviderAdapter, model_ids: list[str], force: bool) -> None:
        if self._pricing_catalog_service is None:
            return
        try:
            await self._pricing_catalog_service.refresh(
                force=force,
                model_ids=model_ids,
                execute_batch=self._build_pricing_execute_batch(adapter=adapter),
            )
        except Exception as exc:
            if hasattr(self._logger, "warning"):
                self._logger.warning("[openai-pricing-refresh-failed] %s", {"error": str(exc).strip() or type(exc).__name__})

    def _resolve_and_persist_node_capabilities(self) -> None:
        try:
            usable_payload = self.openai_usable_models_payload()
            enabled_models = list(usable_payload.get("usable_model_ids") or [])
            task_graph = load_task_graph(path=self._task_graph_path)
            payload = resolve_node_capabilities(
                enabled_models=enabled_models,
                model_feature_catalog=self._provider_model_feature_catalog_store.payload(),
                task_graph=task_graph,
            )
            payload["selected_models"] = list(usable_payload.get("selected_model_ids") or [])
            payload["blocked_models"] = list(usable_payload.get("blocked_models") or [])
            payload["enabled_task_capabilities"] = list(payload.get("resolved_tasks") or [])
            payload["generated_at"] = _iso_now()
            payload["source"] = "node_capabilities"
            self._node_capabilities_path.parent.mkdir(parents=True, exist_ok=True)
            self._node_capabilities_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        except Exception as exc:
            if hasattr(self._logger, "warning"):
                self._logger.warning("[node-capabilities-resolve-failed] %s", {"error": str(exc).strip() or type(exc).__name__})

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

    def openai_pricing_catalog_payload(self) -> dict:
        if self._pricing_catalog_service is None or not hasattr(self._pricing_catalog_service, "load_snapshot"):
            return {"entries": [], "source": "openai_pricing_catalog", "generated_at": _iso_now()}
        snapshot = self._pricing_catalog_service.load_snapshot()
        if snapshot is None:
            return {"entries": [], "source": "openai_pricing_catalog", "generated_at": _iso_now()}
        return {"source": "openai_pricing_catalog", "generated_at": _iso_now(), **snapshot.model_dump()}

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
