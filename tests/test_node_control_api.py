import asyncio
import logging
import tempfile
import unittest
from pathlib import Path

from ai_node.lifecycle.node_lifecycle import NodeLifecycle, NodeLifecycleState
from ai_node.runtime.node_control_api import NodeControlState


class NodeControlApiTests(unittest.TestCase):
    class _FakeProviderRuntimeManager:
        def __init__(self):
            self.refresh_calls = 0
            self.openai_reload_calls = 0

        async def refresh(self):
            self.refresh_calls += 1
            return {"providers": []}

        async def refresh_openai_models_from_saved_credentials(self):
            self.openai_reload_calls += 1
            return {"status": "refreshed", "provider_id": "openai", "classification_model": "gpt-5-mini"}

        async def refresh_pricing(self, *, force: bool):
            return {"status": "manual_only", "changed": False, "notes": ["live_pricing_scrape_disabled"]}

        def save_manual_openai_pricing(self, *, model_id: str, display_name=None, input_price_per_1m=None, output_price_per_1m=None):
            return {
                "status": "manual_saved",
                "model_id": model_id,
                "display_name": display_name,
                "input_price_per_1m": input_price_per_1m,
                "output_price_per_1m": output_price_per_1m,
            }

        def pricing_diagnostics_payload(self):
            return {
                "configured": True,
                "refresh_state": "manual",
                "stale": False,
                "entry_count": 3,
                "source_urls": ["https://openai.com/api/pricing/"],
                "source_url_used": "manual://local_override",
                "last_refresh_time": "2026-03-13T00:00:00Z",
                "unknown_models": [],
                "last_error": None,
                "notes": ["live_pricing_scrape_disabled"],
            }

    class _FakeBootstrapRunner:
        def __init__(self):
            self.calls = []

        def start(self, **kwargs):
            self.calls.append(kwargs)

    class _FakeNodeIdentityStore:
        def __init__(self, payload=None):
            self._payload = payload

        def load(self):
            return self._payload

    class _FakeProviderSelectionStore:
        def __init__(self):
            self.payload = {
                "schema_version": "1.0",
                "providers": {
                    "supported": {"cloud": ["openai"], "local": [], "future": []},
                    "enabled": [],
                },
                "services": {"enabled": [], "future": []},
            }

        def load_or_create(self, **_kwargs):
            return self.payload

        def save(self, payload):
            self.payload = payload

    class _FakeProviderCredentialsStore:
        def __init__(self):
            self.payload = {"schema_version": "1.0", "providers": {}}

        def load_or_create(self):
            return self.payload

        def save(self, payload):
            self.payload = payload

        def load(self):
            return self.payload

        def upsert_openai_credentials(self, *, api_token: str, service_token: str, project_name: str):
            self.payload["providers"]["openai"] = {
                "api_token": api_token,
                "service_token": service_token,
                "project_name": project_name,
                "default_model_id": self.payload.get("providers", {}).get("openai", {}).get("default_model_id"),
                "selected_model_ids": self.payload.get("providers", {}).get("openai", {}).get("selected_model_ids", []),
                "updated_at": "2026-03-13T00:00:00Z",
            }
            return self.payload

        def update_openai_preferences(self, *, default_model_id=None, selected_model_ids=None):
            self.payload.setdefault("providers", {}).setdefault("openai", {})
            self.payload["providers"]["openai"]["default_model_id"] = default_model_id
            self.payload["providers"]["openai"]["selected_model_ids"] = list(selected_model_ids or ([] if default_model_id is None else [default_model_id]))
            self.payload["providers"]["openai"]["updated_at"] = "2026-03-13T00:00:00Z"
            return self.payload

    class _FakeTaskCapabilitySelectionStore:
        def __init__(self):
            self.payload = {
                "schema_version": "1.0",
                "selected_task_families": [
                    "task.classification.text",
                    "task.summarization.text",
                ],
            }

        def load_or_create(self, **_kwargs):
            return self.payload

        def save(self, payload):
            self.payload = payload

    class _FakeTrustStateStore:
        def __init__(self, payload=None):
            self.payload = payload or {
                "node_id": "123e4567-e89b-42d3-a456-426614174000",
                "node_name": "main-ai-node",
                "node_type": "ai-node",
                "paired_core_id": "core-main",
                "core_api_endpoint": "http://10.0.0.100:9001",
                "node_trust_token": "token",
                "initial_baseline_policy": {"policy_version": "1.0"},
                "baseline_policy_version": "1.0",
                "operational_mqtt_identity": "node:123e4567-e89b-42d3-a456-426614174000",
                "operational_mqtt_token": "mqtt-token",
                "operational_mqtt_host": "10.0.0.100",
                "operational_mqtt_port": 1883,
                "bootstrap_mqtt_host": "10.0.0.100",
                "registration_timestamp": "2026-03-11T00:00:00Z",
            }

        def load(self):
            return self.payload

    class _FakePromptServiceStateStore:
        def __init__(self):
            self.payload = {
                "schema_version": "1.0",
                "prompt_services": [],
                "probation": {"active_prompt_ids": [], "reasons": {}, "updated_at": "2026-03-12T00:00:00Z"},
                "updated_at": "2026-03-12T00:00:00Z",
            }

        def load_or_create(self):
            return self.payload

        def save(self, payload):
            self.payload = payload

    class _FakeCapabilityRunner:
        async def submit_once(self):
            return {"status": "accepted"}

        def status_payload(self):
            return {
                "provider_capability_report": {
                    "providers": [
                        {
                            "provider": "openai",
                            "models": [
                                {
                                    "id": "gpt-5",
                                    "created": 1741046400,
                                    "pricing": {"input_per_1m_tokens": 1.25, "output_per_1m_tokens": 10.0},
                                }
                            ],
                        }
                    ]
                }
            }

    def test_status_is_unconfigured_without_bootstrap_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-test"))
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-test"),
            )
            payload = state.status_payload()
            self.assertEqual(payload["status"], "unconfigured")
            self.assertFalse(payload["bootstrap_configured"])
            self.assertEqual(payload["identity_state"], "unknown")
            self.assertIsNone(payload["node_id"])
            self.assertEqual(payload["startup_mode"], "bootstrap_onboarding")
            self.assertFalse(payload["provider_selection_configured"])
            self.assertIn("capability_setup", payload)
            self.assertFalse(payload["capability_setup"]["declaration_allowed"])

    def test_status_includes_node_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-test"))
            identity_store = self._FakeNodeIdentityStore(
                {"node_id": "123e4567-e89b-42d3-a456-426614174000", "created_at": "2026-03-11T00:00:00Z"}
            )
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-test"),
                node_identity_store=identity_store,
            )
            payload = state.status_payload()
            self.assertEqual(payload["identity_state"], "valid")
            self.assertEqual(payload["node_id"], "123e4567-e89b-42d3-a456-426614174000")

    def test_initiate_onboarding_persists_config_and_moves_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bootstrap_config.json"
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-test"))
            runner = self._FakeBootstrapRunner()
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(path),
                logger=logging.getLogger("node-control-test"),
                bootstrap_runner=runner,
            )
            payload = state.initiate_onboarding(
                mqtt_host="10.0.0.100",
                node_name="main-ai-node",
            )
            self.assertEqual(payload["status"], "bootstrap_connecting")
            self.assertTrue(path.exists())
            self.assertEqual(lifecycle.get_state(), NodeLifecycleState.BOOTSTRAP_CONNECTING)
            self.assertEqual(len(runner.calls), 1)
            self.assertEqual(runner.calls[0]["topic"], "synthia/bootstrap/core")

    def test_existing_config_load_moves_state_to_bootstrap_connecting(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bootstrap_config.json"
            path.write_text(
                '{"bootstrap_host":"10.0.0.100","node_name":"main-ai-node"}',
                encoding="utf-8",
            )
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-test"))
            runner = self._FakeBootstrapRunner()
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(path),
                logger=logging.getLogger("node-control-test"),
                bootstrap_runner=runner,
            )
            payload = state.status_payload()
            self.assertEqual(payload["status"], "bootstrap_connecting")
            self.assertTrue(payload["bootstrap_configured"])
            self.assertEqual(len(runner.calls), 1)

    def test_trusted_startup_skips_persisted_bootstrap_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bootstrap_config.json"
            path.write_text(
                '{"bootstrap_host":"10.0.0.100","node_name":"main-ai-node"}',
                encoding="utf-8",
            )
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-test"))
            lifecycle.transition_to(NodeLifecycleState.TRUSTED, {"source": "test"})
            lifecycle.transition_to(NodeLifecycleState.CAPABILITY_SETUP_PENDING, {"source": "test"})
            runner = self._FakeBootstrapRunner()
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(path),
                logger=logging.getLogger("node-control-test"),
                bootstrap_runner=runner,
                startup_mode="trusted_resume",
                trusted_runtime_context={"paired_core_id": "core-main"},
            )
            payload = state.status_payload()
            self.assertEqual(payload["status"], "capability_setup_pending")
            self.assertFalse(payload["bootstrap_configured"])
            self.assertEqual(payload["startup_mode"], "trusted_resume")
            self.assertEqual(payload["trusted_runtime_context"]["paired_core_id"], "core-main")
            self.assertEqual(len(runner.calls), 0)
            self.assertTrue(payload["capability_setup"]["active"])

    def test_update_provider_selection_toggles_openai(self):
        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-test"))
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-test"),
                provider_selection_store=self._FakeProviderSelectionStore(),
            )
            enabled_payload = state.update_provider_selection(openai_enabled=True)
            self.assertIn("openai", enabled_payload["config"]["providers"]["enabled"])

            disabled_payload = state.update_provider_selection(openai_enabled=False)
            self.assertNotIn("openai", disabled_payload["config"]["providers"]["enabled"])

    def test_update_task_capability_selection_persists_selected_families(self):
        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-test"))
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-test"),
                task_capability_selection_store=self._FakeTaskCapabilitySelectionStore(),
            )
            payload = state.update_task_capability_selection(
                selected_task_families=["task.classification.text", "task.generation.image"]
            )
            self.assertEqual(
                payload["config"]["selected_task_families"],
                ["task.classification.text", "task.generation.image"],
            )

    def test_update_openai_credentials_returns_redacted_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-test"))
            runtime_manager = self._FakeProviderRuntimeManager()
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-test"),
                provider_credentials_store=self._FakeProviderCredentialsStore(),
                provider_runtime_manager=runtime_manager,
            )
            payload = state.update_openai_credentials(
                api_token="token-alpha-1234",
                service_token="service-token-7890",
                project_name="ops-user",
            )
            self.assertTrue(payload["configured"])
            self.assertTrue(payload["credentials"]["has_api_token"])
            self.assertTrue(payload["credentials"]["has_service_token"])
            self.assertTrue(payload["credentials"]["api_token_hint"].endswith("1234"))
            self.assertEqual(payload["credentials"]["project_name"], "ops-user")
            self.assertEqual(runtime_manager.refresh_calls, 0)
            asyncio.run(state.refresh_provider_models_after_openai_credentials_save())
            self.assertEqual(runtime_manager.refresh_calls, 0)
            self.assertEqual(runtime_manager.openai_reload_calls, 1)

    def test_latest_provider_models_payload_returns_latest_three(self):
        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-test"))
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-test"),
                capability_runner=self._FakeCapabilityRunner(),
            )
            payload = state.latest_provider_models_payload(provider_id="openai", limit=3)
            self.assertEqual(payload["provider_id"], "openai")
            self.assertEqual(payload["models"][0]["model_id"], "gpt-5")

    def test_openai_pricing_payloads_proxy_runtime_manager(self):
        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-test"))
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-test"),
                provider_runtime_manager=self._FakeProviderRuntimeManager(),
            )
            diagnostics = state.openai_pricing_diagnostics_payload()
            self.assertEqual(diagnostics["provider_id"], "openai")
            self.assertEqual(diagnostics["entry_count"], 3)

    def test_update_openai_preferences_persists_default_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-test"))
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-test"),
                provider_credentials_store=self._FakeProviderCredentialsStore(),
            )
            payload = state.update_openai_preferences(
                default_model_id="gpt-5.4-pro",
                selected_model_ids=["gpt-5.4-pro", "gpt-5.4-mini"],
            )
            self.assertEqual(payload["credentials"]["default_model_id"], "gpt-5.4-pro")
            self.assertEqual(payload["credentials"]["selected_model_ids"], ["gpt-5.4-pro", "gpt-5.4-mini"])

    def test_capability_declaration_gate_requires_setup_prerequisites(self):
        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-test"))
            lifecycle.transition_to(NodeLifecycleState.TRUSTED, {"source": "test"})
            lifecycle.transition_to(NodeLifecycleState.CAPABILITY_SETUP_PENDING, {"source": "test"})
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-test"),
                capability_runner=self._FakeCapabilityRunner(),
                node_identity_store=self._FakeNodeIdentityStore({"node_id": "node-001"}),
                provider_selection_store=self._FakeProviderSelectionStore(),
                task_capability_selection_store=self._FakeTaskCapabilitySelectionStore(),
                trust_state_store=self._FakeTrustStateStore(),
                startup_mode="trusted_resume",
                trusted_runtime_context={
                    "paired_core_id": "core-main",
                    "core_api_endpoint": "http://10.0.0.100:9001",
                    "operational_mqtt_host": "10.0.0.100",
                    "operational_mqtt_port": 1883,
                },
            )
            payload = state.status_payload()
            self.assertTrue(payload["capability_setup"]["declaration_allowed"])

    def test_capability_declaration_gate_blocks_when_openai_enabled_models_are_not_classified_and_priced(self):
        class _OpenAiIncompleteRuntimeManager:
            def openai_enabled_models_payload(self):
                return {
                    "provider_id": "openai",
                    "models": [{"model_id": "gpt-5-mini", "enabled": True}],
                    "source": "provider_enabled_models",
                    "generated_at": "2026-03-14T00:00:00Z",
                }

            def openai_model_capabilities_payload(self):
                return {
                    "provider_id": "openai",
                    "classification_model": "deterministic_rules",
                    "entries": [],
                    "source": "provider_model_classifications",
                    "generated_at": "2026-03-14T00:00:00Z",
                }

            def pricing_diagnostics_payload(self):
                return {
                    "configured": True,
                    "refresh_state": "missing",
                    "stale": True,
                    "entry_count": 0,
                    "unknown_models": [],
                    "last_error": None,
                }

            def openai_pricing_catalog_payload(self):
                return {
                    "source": "openai_pricing_catalog",
                    "generated_at": "2026-03-14T00:00:00Z",
                    "entries": [],
                }

        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-test"))
            lifecycle.transition_to(NodeLifecycleState.TRUSTED, {"source": "test"})
            lifecycle.transition_to(NodeLifecycleState.CAPABILITY_SETUP_PENDING, {"source": "test"})
            provider_selection_store = self._FakeProviderSelectionStore()
            provider_selection_store.payload["providers"]["enabled"] = ["openai"]
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-test"),
                capability_runner=self._FakeCapabilityRunner(),
                node_identity_store=self._FakeNodeIdentityStore({"node_id": "node-001"}),
                provider_selection_store=provider_selection_store,
                provider_runtime_manager=_OpenAiIncompleteRuntimeManager(),
                task_capability_selection_store=self._FakeTaskCapabilitySelectionStore(),
                trust_state_store=self._FakeTrustStateStore(),
                startup_mode="trusted_resume",
                trusted_runtime_context={
                    "paired_core_id": "core-main",
                    "core_api_endpoint": "http://10.0.0.100:9001",
                    "operational_mqtt_host": "10.0.0.100",
                    "operational_mqtt_port": 1883,
                },
            )
            payload = state.status_payload()
            self.assertFalse(payload["capability_setup"]["declaration_allowed"])
            self.assertIn("openai_enabled_models_not_classified", payload["capability_setup"]["blocking_reasons"])
            self.assertIn("openai_pricing_refresh_not_completed", payload["capability_setup"]["blocking_reasons"])

    def test_prompt_service_registration_probation_and_execution_authorization(self):
        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-test"))
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-test"),
                prompt_service_state_store=self._FakePromptServiceStateStore(),
            )
            registered = state.register_prompt_service(
                prompt_id="prompt.alpha",
                service_id="svc-alpha",
                task_family="task.classification.text",
                metadata={"owner": "ops"},
            )
            self.assertEqual(len(registered["state"]["prompt_services"]), 1)
            allowed = state.authorize_execution(
                prompt_id="prompt.alpha",
                task_family="task.classification.text",
            )
            self.assertTrue(allowed["allowed"])

            probation = state.update_prompt_probation(
                prompt_id="prompt.alpha",
                action="start",
                reason="quality_review",
            )
            self.assertIn("prompt.alpha", probation["state"]["probation"]["active_prompt_ids"])
            denied = state.authorize_execution(
                prompt_id="prompt.alpha",
                task_family="task.classification.text",
            )
            self.assertFalse(denied["allowed"])
            self.assertEqual(denied["reason"], "prompt_in_probation")


if __name__ == "__main__":
    unittest.main()
