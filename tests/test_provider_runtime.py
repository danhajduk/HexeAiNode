import logging
import tempfile
import unittest
from pathlib import Path

from ai_node.providers.adapters.mock_adapter import MockProviderAdapter
from ai_node.providers.execution_router import ProviderExecutionRouter
from ai_node.providers.metrics import ProviderMetricsCollector
from ai_node.providers.models import ModelCapability, UnifiedExecutionRequest
from ai_node.providers.provider_registry import ProviderRegistry
from ai_node.providers.runtime_manager import ProviderRuntimeManager


class _SelectionStore:
    def __init__(self, enabled: list[str]):
        self._payload = {"providers": {"enabled": enabled}}

    def load_or_create(self, **_kwargs):
        return self._payload


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
                    task_family="task.classification.text",
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
                UnifiedExecutionRequest(task_family="task.classification.text", prompt="hello world")
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


if __name__ == "__main__":
    unittest.main()
