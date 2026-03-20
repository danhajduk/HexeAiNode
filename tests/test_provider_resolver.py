import logging
import tempfile
import unittest
from pathlib import Path

from ai_node.providers.model_capability_catalog import ProviderModelCapabilityEntry
from ai_node.providers.models import ModelCapability
from ai_node.providers.runtime_manager import ProviderRuntimeManager
from ai_node.runtime.provider_resolver import ProviderResolutionRequest, ProviderResolver


class _SelectionStore:
    def __init__(self, enabled: list[str]):
        self._payload = {"providers": {"enabled": enabled}}

    def load_or_create(self, **_kwargs):
        return self._payload


class ProviderResolverTests(unittest.TestCase):
    def test_resolve_prefers_requested_provider_and_requested_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = ProviderRuntimeManager(
                logger=logging.getLogger("provider-resolver-test"),
                provider_selection_store=_SelectionStore(enabled=["openai", "local"]),
                registry_path=str(Path(tmp) / "provider_registry.json"),
                metrics_path=str(Path(tmp) / "provider_metrics.json"),
            )
            runtime._registry.set_provider_health(provider_id="openai", payload={"availability": "available"})  # noqa: SLF001
            runtime._registry.set_provider_health(provider_id="local", payload={"availability": "available"})  # noqa: SLF001
            runtime._registry.set_models_for_provider(  # noqa: SLF001
                provider_id="openai",
                models=[
                    ModelCapability(model_id="gpt-5-mini", display_name="gpt-5-mini", status="available"),
                    ModelCapability(model_id="gpt-5-nano", display_name="gpt-5-nano", status="available"),
                ],
            )
            runtime._registry.set_models_for_provider(  # noqa: SLF001
                provider_id="local",
                models=[ModelCapability(model_id="mock-model-v1", display_name="mock-model-v1", status="available")],
            )
            runtime._provider_enabled_models_store.save_enabled_model_ids(model_ids=["gpt-5-mini", "gpt-5-nano"])  # noqa: SLF001
            runtime._provider_model_capabilities_store.save(  # noqa: SLF001
                classification_model="deterministic_rules",
                entries=[
                    ProviderModelCapabilityEntry(model_id="gpt-5-mini", family="llm"),
                    ProviderModelCapabilityEntry(model_id="gpt-5-nano", family="llm"),
                ],
            )
            resolver = ProviderResolver(runtime_manager=runtime, logger=logging.getLogger("provider-resolver-test"))

            result = resolver.resolve(
                request=ProviderResolutionRequest(
                    task_family="task.classification.text",
                    requested_provider="openai",
                    requested_model="gpt-5-nano",
                    timeout_s=45,
                )
            )

            self.assertTrue(result.allowed)
            self.assertEqual(result.provider_id, "openai")
            self.assertEqual(result.model_id, "gpt-5-nano")
            self.assertEqual(result.fallback_provider_ids, ["local"])

    def test_resolve_falls_back_to_default_model_when_no_allowlist_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = ProviderRuntimeManager(
                logger=logging.getLogger("provider-resolver-test"),
                provider_selection_store=_SelectionStore(enabled=["local"]),
                registry_path=str(Path(tmp) / "provider_registry.json"),
                metrics_path=str(Path(tmp) / "provider_metrics.json"),
            )
            runtime._registry.set_provider_health(provider_id="local", payload={"availability": "available"})  # noqa: SLF001
            runtime._registry.set_models_for_provider(  # noqa: SLF001
                provider_id="local",
                models=[ModelCapability(model_id="mock-model-v1", display_name="mock-model-v1", status="available")],
            )
            resolver = ProviderResolver(runtime_manager=runtime, logger=logging.getLogger("provider-resolver-test"))

            result = resolver.resolve(
                request=ProviderResolutionRequest(
                    task_family="task.classification.text",
                    timeout_s=60,
                )
            )

            self.assertTrue(result.allowed)
            self.assertEqual(result.provider_id, "local")
            self.assertEqual(result.model_id, "mock-model-v1")

    def test_resolve_applies_governance_provider_and_timeout_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = ProviderRuntimeManager(
                logger=logging.getLogger("provider-resolver-test"),
                provider_selection_store=_SelectionStore(enabled=["openai", "local"]),
                registry_path=str(Path(tmp) / "provider_registry.json"),
                metrics_path=str(Path(tmp) / "provider_metrics.json"),
            )
            runtime._registry.set_provider_health(provider_id="openai", payload={"availability": "available"})  # noqa: SLF001
            runtime._registry.set_provider_health(provider_id="local", payload={"availability": "available"})  # noqa: SLF001
            runtime._registry.set_models_for_provider(  # noqa: SLF001
                provider_id="openai",
                models=[ModelCapability(model_id="gpt-5-mini", display_name="gpt-5-mini", status="available")],
            )
            runtime._registry.set_models_for_provider(  # noqa: SLF001
                provider_id="local",
                models=[ModelCapability(model_id="mock-model-v1", display_name="mock-model-v1", status="available")],
            )
            resolver = ProviderResolver(runtime_manager=runtime, logger=logging.getLogger("provider-resolver-test"))

            result = resolver.resolve(
                request=ProviderResolutionRequest(task_family="task.classification.text", timeout_s=90),
                governance_constraints={
                    "approved_providers": ["local"],
                    "routing_policy_constraints": {"max_timeout_s": 20},
                },
            )

            self.assertTrue(result.allowed)
            self.assertEqual(result.provider_id, "local")
            self.assertEqual(result.timeout_s, 20)

    def test_resolve_rejects_when_no_model_is_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = ProviderRuntimeManager(
                logger=logging.getLogger("provider-resolver-test"),
                provider_selection_store=_SelectionStore(enabled=["openai"]),
                registry_path=str(Path(tmp) / "provider_registry.json"),
                metrics_path=str(Path(tmp) / "provider_metrics.json"),
            )
            runtime._registry.set_provider_health(provider_id="openai", payload={"availability": "available"})  # noqa: SLF001
            resolver = ProviderResolver(runtime_manager=runtime, logger=logging.getLogger("provider-resolver-test"))

            result = resolver.resolve(
                request=ProviderResolutionRequest(
                    task_family="task.classification.text",
                    requested_provider="openai",
                    timeout_s=30,
                )
            )

            self.assertFalse(result.allowed)
            self.assertEqual(result.rejection_reason, "no_eligible_model_available")

    def test_resolve_falls_back_to_later_provider_when_first_has_no_eligible_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = ProviderRuntimeManager(
                logger=logging.getLogger("provider-resolver-test"),
                provider_selection_store=_SelectionStore(enabled=["openai", "local"]),
                registry_path=str(Path(tmp) / "provider_registry.json"),
                metrics_path=str(Path(tmp) / "provider_metrics.json"),
            )
            runtime._registry.set_provider_health(provider_id="openai", payload={"availability": "available"})  # noqa: SLF001
            runtime._registry.set_provider_health(provider_id="local", payload={"availability": "available"})  # noqa: SLF001
            runtime._registry.set_models_for_provider(  # noqa: SLF001
                provider_id="openai",
                models=[ModelCapability(model_id="gpt-5-mini", display_name="gpt-5-mini", status="available")],
            )
            runtime._registry.set_models_for_provider(  # noqa: SLF001
                provider_id="local",
                models=[ModelCapability(model_id="mock-model-v1", display_name="mock-model-v1", status="available")],
            )
            resolver = ProviderResolver(runtime_manager=runtime, logger=logging.getLogger("provider-resolver-test"))

            result = resolver.resolve(
                request=ProviderResolutionRequest(
                    task_family="task.classification.text",
                    requested_provider="openai",
                    requested_model="missing-model",
                    timeout_s=30,
                )
            )

            self.assertTrue(result.allowed)
            self.assertEqual(result.provider_id, "local")
            self.assertEqual(result.model_id, "mock-model-v1")
            self.assertIn("openai", result.fallback_provider_ids)


if __name__ == "__main__":
    unittest.main()
