import logging
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_node.providers.model_capability_catalog import ProviderModelCapabilityEntry
from ai_node.providers.model_feature_schema import create_default_feature_flags
from ai_node.providers.adapters.mock_adapter import MockProviderAdapter
from ai_node.providers.execution_router import ProviderExecutionRouter
from ai_node.providers.metrics import ProviderMetricsCollector
from ai_node.providers.models import ModelCapability, UnifiedExecutionRequest, UnifiedExecutionResponse
from ai_node.providers.provider_registry import ProviderRegistry
from ai_node.providers.runtime_manager import ProviderRuntimeManager


class _SelectionStore:
    def __init__(self, enabled: list[str], budget_limits: dict | None = None):
        self._payload = {"providers": {"enabled": enabled, "budget_limits": budget_limits or {}}}

    def load_or_create(self, **_kwargs):
        return self._payload


class _CredentialsStore:
    def __init__(self):
        self._payload = {
            "schema_version": "1.0",
            "providers": {
                "openai": {
                    "api_token": "token-alpha-1234",
                    "service_token": "service-token-1234",
                    "project_name": "ops",
                    "selected_model_ids": ["gpt-5-mini"],
                }
            },
        }

    def load_or_create(self):
        return self._payload

    def load(self):
        return self._payload


class _FakeOpenAIAdapter:
    async def health_check(self):
        return {"availability": "available"}

    async def list_models(self):
        return [
            ModelCapability(model_id="gpt-5-mini", display_name="gpt-5-mini", created=1740950000),
            ModelCapability(model_id="gpt-5-mini-2026-03-05", display_name="gpt-5-mini-2026-03-05", created=1741219200),
            ModelCapability(model_id="gpt-5-preview", display_name="gpt-5-preview", created=1741305600),
        ]

    async def execute_prompt(self, _request):
        feature_flags = create_default_feature_flags()
        feature_flags["chat"] = True
        feature_flags["reasoning"] = True
        feature_flags["structured_output"] = True
        return UnifiedExecutionResponse(
            provider_id="openai",
            model_id="gpt-5-nano",
            output_text=json.dumps(
                {
                    "models": [
                        {
                            "model_id": "gpt-5-mini",
                            "family": "llm",
                            "reasoning": True,
                            "vision": False,
                            "image_generation": False,
                            "audio_input": False,
                            "audio_output": False,
                            "realtime": False,
                            "tool_calling": True,
                            "structured_output": True,
                            "long_context": True,
                            "coding_strength": "high",
                            "speed_tier": "medium",
                            "cost_tier": "medium",
                            "feature_flags": feature_flags,
                        }
                    ]
                }
            ),
            latency_ms=1.0,
        )


class _FakeRepresentativeCollisionOpenAIAdapter:
    async def health_check(self):
        return {"availability": "available"}

    async def list_models(self):
        return [
            ModelCapability(model_id="gpt-5.4-mini", display_name="gpt-5.4-mini", created=1741219200, status="available"),
            ModelCapability(model_id="gpt-5-mini", display_name="gpt-5-mini", created=1741132800, status="available"),
            ModelCapability(model_id="gpt-5.4-nano", display_name="gpt-5.4-nano", created=1741219201, status="available"),
            ModelCapability(model_id="gpt-5-nano", display_name="gpt-5-nano", created=1741132801, status="available"),
        ]

    async def execute_prompt(self, _request):
        return UnifiedExecutionResponse(
            provider_id="openai",
            model_id="gpt-5.4-mini",
            output_text="{}",
            latency_ms=1.0,
        )


class _FakePricingCatalogService:
    def __init__(self):
        self.last_model_ids = None
        self.last_force = None

    async def refresh(self, *, force=False, model_ids=None, execute_batch=None):
        self.last_force = force
        self.last_model_ids = list(model_ids or [])
        return {"status": "manual_only", "model_ids": self.last_model_ids}


class ProviderRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_execution_router_falls_back_when_primary_fails(self):
        registry = ProviderRegistry()
        with tempfile.TemporaryDirectory() as tmp:
            metrics = ProviderMetricsCollector(
                metrics_path=str(Path(tmp) / "metrics.json"),
                logger=logging.getLogger("test"),
            )
            primary = MockProviderAdapter(provider_id="mock-primary")
            fallback = MockProviderAdapter(provider_id="mock-fallback")
            primary.set_fail_next(True)
            registry.register_provider(provider_id="mock-primary", adapter=primary)
            registry.register_provider(provider_id="mock-fallback", adapter=fallback)
            registry.set_provider_health(provider_id="mock-primary", payload={"availability": "available"})
            registry.set_provider_health(provider_id="mock-fallback", payload={"availability": "available"})
            router = ProviderExecutionRouter(
                registry=registry,
                metrics=metrics,
                logger=logging.getLogger("test"),
                default_provider="mock-primary",
                fallback_provider="mock-fallback",
                retry_count=0,
            )

            response = await router.execute(
                UnifiedExecutionRequest(
                    task_family="task.classification",
                    prompt="hello",
                    requested_model="mock-model-v1",
                )
            )

            self.assertEqual(response.provider_id, "mock-fallback")
            snapshot = metrics.snapshot()
            self.assertEqual(snapshot["providers"]["mock-primary"]["models"]["mock-model-v1"]["failed_requests"], 1)
            self.assertEqual(snapshot["providers"]["mock-fallback"]["models"]["mock-model-v1"]["successful_requests"], 1)

    async def test_runtime_refresh_persists_registry_and_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry_path = str(Path(tmp) / "provider_registry.json")
            metrics_path = str(Path(tmp) / "provider_metrics.json")
            runtime = ProviderRuntimeManager(
                logger=logging.getLogger("provider-runtime-test"),
                provider_selection_store=_SelectionStore(enabled=["local"]),
                registry_path=registry_path,
                metrics_path=metrics_path,
            )
            report = await runtime.refresh()
            self.assertIn("providers", report)
            self.assertTrue(Path(registry_path).exists())
            self.assertTrue(Path(metrics_path).exists())
            providers_snapshot = runtime.providers_snapshot()
            self.assertEqual(providers_snapshot["providers"][0]["provider_id"], "local")
            self.assertIn("availability", providers_snapshot["providers"][0]["health"])

    async def test_registry_can_reload_models_from_persisted_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "registry.json")
            registry = ProviderRegistry()
            registry.register_provider(provider_id="mock", adapter=MockProviderAdapter(provider_id="mock"))
            registry.set_provider_health(provider_id="mock", payload={"availability": "available"})
            registry.set_models_for_provider(provider_id="mock", models=await MockProviderAdapter().list_models())
            registry.persist(path=path)

            loaded_registry = ProviderRegistry()
            loaded_registry.load(path=path)
            model = loaded_registry.get_model(provider_id="mock", model_id="mock-model-v1")
            self.assertIsNotNone(model)
            self.assertEqual(model.model_id, "mock-model-v1")

    async def test_execution_router_returns_normalized_response_shape(self):
        registry = ProviderRegistry()
        with tempfile.TemporaryDirectory() as tmp:
            metrics = ProviderMetricsCollector(
                metrics_path=str(Path(tmp) / "metrics.json"),
                logger=logging.getLogger("test"),
            )
            provider = MockProviderAdapter(provider_id="mock")
            registry.register_provider(provider_id="mock", adapter=provider)
            registry.set_provider_health(provider_id="mock", payload={"availability": "available"})
            router = ProviderExecutionRouter(
                registry=registry,
                metrics=metrics,
                logger=logging.getLogger("test"),
                default_provider="mock",
                retry_count=0,
            )
            response = await router.execute(
                UnifiedExecutionRequest(task_family="task.classification", prompt="hello world")
            )
            self.assertEqual(response.provider_id, "mock")
            self.assertEqual(response.model_id, "mock-model-v1")
            self.assertTrue(response.output_text.startswith("mock:"))
            self.assertGreaterEqual(response.usage.total_tokens, 1)

    async def test_latest_models_payload_filters_dated_openai_variants(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = ProviderRuntimeManager(
                logger=logging.getLogger("provider-runtime-test"),
                provider_selection_store=_SelectionStore(enabled=["local"]),
                registry_path=str(Path(tmp) / "provider_registry.json"),
                metrics_path=str(Path(tmp) / "provider_metrics.json"),
            )
            runtime._registry.set_models_for_provider(  # noqa: SLF001 - targeted integration test
                provider_id="openai",
                models=[
                    ModelCapability(model_id="gpt-5.4-pro-2026-03-05", display_name="gpt-5.4-pro-2026-03-05", created=1741132800),
                    ModelCapability(model_id="gpt-5.4-pro", display_name="gpt-5.4-pro", created=1741046400),
                    ModelCapability(model_id="gpt-5.4-mini", display_name="gpt-5.4-mini", created=1740950000),
                    ModelCapability(model_id="gpt-5.3-chat-latest", display_name="gpt-5.3-chat-latest", created=1741200000),
                    ModelCapability(model_id="gpt-4-0613", display_name="gpt-4-0613", created=1686588896),
                ],
            )
            payload = runtime.latest_models_payload(provider_id="openai", limit=9)
            self.assertEqual([item["model_id"] for item in payload["models"]], ["gpt-5.4-pro", "gpt-5.4-mini"])

    async def test_openai_model_catalog_payload_returns_saved_filtered_models(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = ProviderRuntimeManager(
                logger=logging.getLogger("provider-runtime-test"),
                provider_selection_store=_SelectionStore(enabled=["local"]),
                registry_path=str(Path(tmp) / "provider_registry.json"),
                metrics_path=str(Path(tmp) / "provider_metrics.json"),
                provider_model_catalog_path=str(Path(tmp) / "provider_models.json"),
            )
            runtime._openai_model_catalog_store.save_from_model_ids(  # noqa: SLF001
                model_ids=["gpt-5-mini", "omni-moderation-2024-09-26"]
            )
            payload = runtime.openai_model_catalog_payload()
            self.assertEqual([item["model_id"] for item in payload["models"]], ["gpt-5-mini", "omni-moderation-2024-09-26"])

    async def test_intelligence_payload_only_exports_filtered_openai_models(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = ProviderRuntimeManager(
                logger=logging.getLogger("provider-runtime-test"),
                provider_selection_store=_SelectionStore(enabled=["local"]),
                registry_path=str(Path(tmp) / "provider_registry.json"),
                metrics_path=str(Path(tmp) / "provider_metrics.json"),
                provider_model_catalog_path=str(Path(tmp) / "provider_models.json"),
            )
            runtime._openai_model_catalog_store.save_from_model_ids(model_ids=["gpt-5-mini", "whisper-1"])  # noqa: SLF001
            runtime._registry.register_provider(provider_id="openai", adapter=MockProviderAdapter(provider_id="openai"))  # noqa: SLF001
            runtime._registry.set_provider_health(provider_id="openai", payload={"availability": "available"})  # noqa: SLF001
            runtime._registry.set_models_for_provider(  # noqa: SLF001
                provider_id="openai",
                models=[
                    ModelCapability(model_id="gpt-5-mini", display_name="gpt-5-mini", created=1740950000),
                    ModelCapability(model_id="whisper-1", display_name="whisper-1", created=1677610602),
                    ModelCapability(model_id="gpt-5.4-pro-2026-03-05", display_name="gpt-5.4-pro-2026-03-05", created=1741132800),
                    ModelCapability(model_id="gpt-5-chat-latest", display_name="gpt-5-chat-latest", created=1741200000),
                ],
            )

            payload = runtime.intelligence_payload()

            self.assertEqual(payload["providers"][0]["provider_id"], "openai")
            self.assertEqual(
                [item["model_id"] for item in payload["providers"][0]["models"]],
                ["gpt-5-mini", "whisper-1"],
            )

    async def test_openai_enabled_models_and_resolved_capabilities_payloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = ProviderRuntimeManager(
                logger=logging.getLogger("provider-runtime-test"),
                provider_selection_store=_SelectionStore(enabled=["local"]),
                registry_path=str(Path(tmp) / "provider_registry.json"),
                metrics_path=str(Path(tmp) / "provider_metrics.json"),
                provider_model_capabilities_path=str(Path(tmp) / "provider_model_capabilities.json"),
                provider_enabled_models_path=str(Path(tmp) / "provider_enabled_models.json"),
            )
            runtime._provider_model_capabilities_store.save(  # noqa: SLF001
                classification_model="deterministic_rules",
                entries=[
                    ProviderModelCapabilityEntry(
                        model_id="gpt-5-mini",
                        family="llm",
                        text_generation=True,
                        reasoning=True,
                        tool_calling=True,
                        structured_output=True,
                        long_context=True,
                        coding_strength="high",
                        speed_tier="medium",
                        cost_tier="medium",
                    )
                ],
            )
            runtime._registry.register_provider(provider_id="openai", adapter=MockProviderAdapter(provider_id="openai"))  # noqa: SLF001
            runtime._registry.set_models_for_provider(  # noqa: SLF001
                provider_id="openai",
                models=[ModelCapability(model_id="gpt-5-mini", display_name="gpt-5-mini", status="available")],
            )
            runtime.save_openai_enabled_models(model_ids=["gpt-5-mini"])

            enabled_payload = runtime.openai_enabled_models_payload()
            usable_payload = runtime.openai_usable_models_payload()
            resolved_payload = runtime.openai_resolved_capabilities_payload()

            self.assertEqual(enabled_payload["models"][0]["model_id"], "gpt-5-mini")
            self.assertEqual(usable_payload["usable_model_ids"], ["gpt-5-mini"])
            self.assertTrue(resolved_payload["capabilities"]["reasoning"])
            self.assertEqual(resolved_payload["capabilities"]["coding_strength"], "high")

    async def test_provider_selection_context_includes_provider_budget_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = ProviderRuntimeManager(
                logger=logging.getLogger("provider-runtime-test"),
                provider_selection_store=_SelectionStore(
                    enabled=["openai"],
                    budget_limits={"openai": {"max_cost_cents": 2500, "period": "weekly"}},
                ),
                provider_credentials_store=_CredentialsStore(),
                registry_path=str(Path(tmp) / "provider_registry.json"),
                metrics_path=str(Path(tmp) / "provider_metrics.json"),
            )
            runtime._registry.register_provider(provider_id="openai", adapter=MockProviderAdapter(provider_id="openai"))  # noqa: SLF001
            runtime._registry.set_provider_health(provider_id="openai", payload={"availability": "available"})  # noqa: SLF001
            runtime._registry.set_models_for_provider(  # noqa: SLF001
                provider_id="openai",
                models=[ModelCapability(model_id="gpt-5-mini", display_name="gpt-5-mini", status="available")],
            )

            payload = runtime.provider_selection_context_payload()

            self.assertEqual(payload["provider_budget_limits"]["openai"]["max_cost_cents"], 2500)
            self.assertEqual(payload["provider_budget_limits"]["openai"]["period"], "weekly")

    async def test_save_enabled_models_persists_node_capabilities(self):
        with tempfile.TemporaryDirectory() as tmp:
            graph_path = Path(tmp) / "task_graph.json"
            graph_path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "capability_graph_version": "1.0",
                        "tasks": {
                            "task.reasoning": {"all_of": ["reasoning"]},
                            "task.chat": {"all_of": ["chat"]},
                        },
                    }
                ),
                encoding="utf-8",
            )
            node_capabilities_path = Path(tmp) / "runtime" / "node_capabilities.json"
            runtime = ProviderRuntimeManager(
                logger=logging.getLogger("provider-runtime-test"),
                provider_selection_store=_SelectionStore(enabled=["openai"]),
                provider_credentials_store=_CredentialsStore(),
                registry_path=str(Path(tmp) / "provider_registry.json"),
                metrics_path=str(Path(tmp) / "provider_metrics.json"),
                provider_model_features_path=str(Path(tmp) / "providers" / "openai" / "provider_model_features.json"),
                provider_enabled_models_path=str(Path(tmp) / "provider_enabled_models.json"),
                node_capabilities_path=str(node_capabilities_path),
                task_graph_path=str(graph_path),
            )
            runtime._provider_model_feature_catalog_store.save_entries(  # noqa: SLF001
                provider="openai",
                classification_model="gpt-5-mini",
                entries=[{"model_id": "gpt-5-mini", "features": {"reasoning": True, "chat": True}}],
            )
            runtime._provider_model_capabilities_store.save(  # noqa: SLF001
                classification_model="gpt-5-mini",
                entries=[
                    ProviderModelCapabilityEntry(
                        model_id="gpt-5-mini",
                        family="llm",
                        text_generation=True,
                        reasoning=True,
                    )
                ],
            )
            runtime._registry.register_provider(provider_id="openai", adapter=MockProviderAdapter(provider_id="openai"))  # noqa: SLF001
            runtime._registry.set_models_for_provider(  # noqa: SLF001
                provider_id="openai",
                models=[ModelCapability(model_id="gpt-5-mini", display_name="gpt-5-mini", status="available")],
            )

            runtime.save_openai_enabled_models(model_ids=["gpt-5-mini"])

            self.assertTrue(node_capabilities_path.exists())
            payload = runtime.node_capabilities_payload()
            self.assertEqual(payload["enabled_models"], ["gpt-5-mini"])
            self.assertEqual(payload["enabled_task_capabilities"], ["task.chat", "task.reasoning"])

    async def test_usable_models_exclude_unavailable_selected_models(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = ProviderRuntimeManager(
                logger=logging.getLogger("provider-runtime-test"),
                provider_selection_store=_SelectionStore(enabled=["openai"]),
                registry_path=str(Path(tmp) / "provider_registry.json"),
                metrics_path=str(Path(tmp) / "provider_metrics.json"),
                provider_model_capabilities_path=str(Path(tmp) / "provider_model_capabilities.json"),
                provider_enabled_models_path=str(Path(tmp) / "provider_enabled_models.json"),
            )
            runtime._provider_model_capabilities_store.save(  # noqa: SLF001
                classification_model="deterministic_rules",
                entries=[
                    ProviderModelCapabilityEntry(
                        model_id="gpt-5-mini",
                        family="llm",
                        text_generation=True,
                    )
                ],
            )
            runtime._registry.register_provider(provider_id="openai", adapter=MockProviderAdapter(provider_id="openai"))  # noqa: SLF001
            runtime._registry.set_models_for_provider(  # noqa: SLF001
                provider_id="openai",
                models=[
                    ModelCapability(model_id="gpt-5-mini", display_name="gpt-5-mini", status="available"),
                    ModelCapability(model_id="gpt-5-pro", display_name="gpt-5-pro", status="unavailable"),
                ],
            )

            runtime.save_openai_enabled_models(model_ids=["gpt-5-mini", "gpt-5-pro"])

            usable_payload = runtime.openai_usable_models_payload()
            self.assertEqual(usable_payload["usable_model_ids"], ["gpt-5-mini"])
            self.assertEqual(usable_payload["blocked_models"][0]["model_id"], "gpt-5-pro")

    async def test_usable_models_allow_free_moderation_model_with_fallback_pricing(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = ProviderRuntimeManager(
                logger=logging.getLogger("provider-runtime-test"),
                provider_selection_store=_SelectionStore(enabled=["openai"]),
                provider_credentials_store=_CredentialsStore(),
                registry_path=str(Path(tmp) / "provider_registry.json"),
                metrics_path=str(Path(tmp) / "provider_metrics.json"),
                provider_enabled_models_path=str(Path(tmp) / "provider_enabled_models.json"),
                provider_model_capabilities_path=str(Path(tmp) / "provider_model_capabilities.json"),
            )
            runtime._registry.register_provider(provider_id="openai", adapter=MockProviderAdapter(provider_id="openai"))  # noqa: SLF001
            runtime._registry.set_models_for_provider(  # noqa: SLF001
                provider_id="openai",
                models=[
                    ModelCapability(
                        model_id="omni-moderation-2024-09-26",
                        display_name="omni-moderation-2024-09-26",
                        status="available",
                        pricing_input=0.0,
                        pricing_output=0.0,
                        pricing_status="fallback_used",
                    ),
                ],
            )
            runtime._provider_model_capabilities_store.save(  # noqa: SLF001
                classification_model="deterministic_rules",
                entries=[
                    ProviderModelCapabilityEntry(
                        model_id="omni-moderation-2024-09-26",
                        family="moderation",
                        cost_tier="low",
                        speed_tier="fast",
                    )
                ],
            )

            runtime.save_openai_enabled_models(model_ids=["omni-moderation-2024-09-26"])

            usable_payload = runtime.openai_usable_models_payload()
            self.assertEqual(usable_payload["usable_model_ids"], ["omni-moderation-2024-09-26"])
            self.assertEqual(usable_payload["blocked_models"], [])

    async def test_refresh_openai_models_runs_filtered_classification_and_saves_feature_catalog(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = ProviderRuntimeManager(
                logger=logging.getLogger("provider-runtime-test"),
                provider_selection_store=_SelectionStore(enabled=["openai"]),
                provider_credentials_store=_CredentialsStore(),
                registry_path=str(Path(tmp) / "provider_registry.json"),
                metrics_path=str(Path(tmp) / "provider_metrics.json"),
                provider_model_catalog_path=str(Path(tmp) / "provider_models.json"),
                provider_model_capabilities_path=str(Path(tmp) / "provider_model_capabilities.json"),
                provider_model_features_path=str(Path(tmp) / "providers" / "openai" / "provider_model_features.json"),
            )
            runtime._build_adapter = lambda **_kwargs: _FakeOpenAIAdapter()  # noqa: SLF001

            payload = await runtime.refresh_openai_models_from_saved_credentials()

            self.assertEqual(payload["status"], "refreshed")
            catalog_payload = runtime.openai_model_catalog_payload()
            self.assertEqual([item["model_id"] for item in catalog_payload["models"]], ["gpt-5-mini"])
            capabilities_payload = runtime.openai_model_capabilities_payload()
            self.assertEqual(capabilities_payload["classification_model"], "deterministic_rules")
            features_payload = runtime.openai_model_features_payload()
            self.assertEqual(features_payload["entries"][0]["model_id"], "gpt-5-mini")
            self.assertTrue(features_payload["entries"][0]["features"]["chat"])

    async def test_refresh_openai_models_preserves_selected_models_in_classification_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = ProviderRuntimeManager(
                logger=logging.getLogger("provider-runtime-test"),
                provider_selection_store=_SelectionStore(enabled=["openai"]),
                provider_credentials_store=_CredentialsStore(),
                registry_path=str(Path(tmp) / "provider_registry.json"),
                metrics_path=str(Path(tmp) / "provider_metrics.json"),
                provider_model_catalog_path=str(Path(tmp) / "provider_models.json"),
                provider_model_capabilities_path=str(Path(tmp) / "provider_model_capabilities.json"),
                provider_model_features_path=str(Path(tmp) / "providers" / "openai" / "provider_model_features.json"),
                provider_enabled_models_path=str(Path(tmp) / "provider_enabled_models.json"),
            )
            runtime._build_adapter = lambda **_kwargs: _FakeRepresentativeCollisionOpenAIAdapter()  # noqa: SLF001
            runtime.save_openai_enabled_models(model_ids=["gpt-5-mini", "gpt-5-nano"])

            await runtime.refresh_openai_models_from_saved_credentials()

            capabilities_payload = runtime.openai_model_capabilities_payload()
            classified_ids = [entry["model_id"] for entry in capabilities_payload["entries"]]
            self.assertIn("gpt-5-mini", classified_ids)
            self.assertIn("gpt-5-nano", classified_ids)

            usable_payload = runtime.openai_usable_models_payload()
            self.assertEqual(usable_payload["usable_model_ids"], ["gpt-5-mini", "gpt-5-nano"])
            self.assertEqual(usable_payload["blocked_models"], [])

    async def test_refresh_pricing_uses_filtered_catalog_models(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"SYNTHIA_OPENAI_API_PRICING_FETCH_ENABLED": "true"}, clear=False
        ):
            runtime = ProviderRuntimeManager(
                logger=logging.getLogger("provider-runtime-test"),
                provider_selection_store=_SelectionStore(enabled=["openai"]),
                provider_credentials_store=_CredentialsStore(),
                registry_path=str(Path(tmp) / "provider_registry.json"),
                metrics_path=str(Path(tmp) / "provider_metrics.json"),
                provider_model_catalog_path=str(Path(tmp) / "provider_models.json"),
                provider_enabled_models_path=str(Path(tmp) / "provider_enabled_models.json"),
            )
            runtime._build_adapter = lambda **_kwargs: _FakeOpenAIAdapter()  # noqa: SLF001
            runtime._pricing_catalog_service = _FakePricingCatalogService()  # noqa: SLF001
            runtime._openai_model_catalog_store.save_from_model_ids(  # noqa: SLF001
                model_ids=["gpt-5-mini", "gpt-5-pro", "gpt-4o", "whisper-1"]
            )
            runtime.save_openai_enabled_models(model_ids=["gpt-5-mini"])

            await runtime.refresh_pricing(force=True)

            self.assertEqual(runtime._pricing_catalog_service.last_model_ids, ["gpt-5-mini", "gpt-5-pro", "whisper-1"])  # noqa: SLF001
            self.assertTrue(runtime._pricing_catalog_service.last_force)  # noqa: SLF001

    async def test_rerun_openai_capabilities_scopes_to_filtered_catalog_models(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"SYNTHIA_OPENAI_API_PRICING_FETCH_ENABLED": "true"}, clear=False
        ):
            runtime = ProviderRuntimeManager(
                logger=logging.getLogger("provider-runtime-test"),
                provider_selection_store=_SelectionStore(enabled=["openai"]),
                provider_credentials_store=_CredentialsStore(),
                registry_path=str(Path(tmp) / "provider_registry.json"),
                metrics_path=str(Path(tmp) / "provider_metrics.json"),
                provider_model_catalog_path=str(Path(tmp) / "provider_models.json"),
                provider_enabled_models_path=str(Path(tmp) / "provider_enabled_models.json"),
            )
            runtime._build_adapter = lambda **_kwargs: _FakeOpenAIAdapter()  # noqa: SLF001
            runtime._openai_model_catalog_store.save_from_model_ids(  # noqa: SLF001
                model_ids=["gpt-5-mini", "gpt-5-pro", "gpt-4o", "whisper-1"]
            )
            runtime.save_openai_enabled_models(model_ids=["gpt-5-mini"])

            captured = {"classified_model_ids": [], "priced_model_ids": []}

            async def _capture_classification(*, models):
                captured["classified_model_ids"] = [str(getattr(entry, "model_id", "")).lower() for entry in models]

            async def _capture_pricing(*, adapter, model_ids, force):
                _ = adapter
                _ = force
                captured["priced_model_ids"] = [str(model_id or "").lower() for model_id in model_ids]

            runtime._refresh_openai_model_capabilities = _capture_classification  # type: ignore[method-assign]  # noqa: SLF001
            runtime._refresh_openai_pricing = _capture_pricing  # type: ignore[method-assign]  # noqa: SLF001

            await runtime.rerun_openai_model_capabilities()

            self.assertEqual(captured["classified_model_ids"], ["gpt-5-mini", "gpt-5-pro", "whisper-1"])
            self.assertEqual(captured["priced_model_ids"], ["gpt-5-mini", "gpt-5-pro", "whisper-1"])

    async def test_refresh_pricing_returns_manual_only_when_api_fetch_disabled(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"SYNTHIA_OPENAI_API_PRICING_FETCH_ENABLED": "false"}, clear=False
        ):
            runtime = ProviderRuntimeManager(
                logger=logging.getLogger("provider-runtime-test"),
                provider_selection_store=_SelectionStore(enabled=["openai"]),
                provider_credentials_store=_CredentialsStore(),
                registry_path=str(Path(tmp) / "provider_registry.json"),
                metrics_path=str(Path(tmp) / "provider_metrics.json"),
                provider_model_catalog_path=str(Path(tmp) / "provider_models.json"),
            )
            payload = await runtime.refresh_pricing(force=True)
            self.assertEqual(payload.get("status"), "manual_only")
            self.assertIn("openai_api_pricing_fetch_disabled", payload.get("notes", []))


if __name__ == "__main__":
    unittest.main()
