import asyncio
import logging
import tempfile
import unittest
from pathlib import Path

from ai_node.config.task_capability_selection_config import TaskCapabilitySelectionConfigStore
from ai_node.execution.task_models import TaskExecutionRequest
from ai_node.lifecycle.node_lifecycle import NodeLifecycle, NodeLifecycleState
from ai_node.providers.models import UnifiedExecutionResponse, UnifiedExecutionUsage
from ai_node.runtime.node_control_api import NodeControlState


class NodeControlApiTests(unittest.TestCase):
    class _FakeProviderRuntimeManager:
        def __init__(self):
            self.refresh_calls = 0
            self.openai_reload_calls = 0
            self.last_execution_request = None
            self._enabled_models = ["gpt-5-mini"]
            self._resolved_tasks = ["task.classification"]

        async def refresh(self):
            self.refresh_calls += 1
            return {"providers": []}

        async def execute(self, request):
            self.last_execution_request = request
            return UnifiedExecutionResponse(
                provider_id=str(request.requested_provider or "openai"),
                model_id=str(request.requested_model or "gpt-5-mini"),
                output_text="mock:hello world",
                usage=UnifiedExecutionUsage(prompt_tokens=2, completion_tokens=4, total_tokens=6),
                latency_ms=12.5,
                estimated_cost=0.001,
            )

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

        def provider_selection_context_payload(self):
            return {
                "enabled_providers": ["openai"],
                "default_provider": "openai",
                "default_model_by_provider": {"openai": "gpt-5-mini"},
                "provider_retry_count": {"openai": 1},
                "provider_health": {"openai": {"availability": "available"}},
                "available_models_by_provider": {"openai": ["gpt-5-mini"]},
                "usable_models_by_provider": {"openai": ["gpt-5-mini"]},
            }

        def node_capabilities_payload(self):
            return {
                "schema_version": "1.0",
                "capability_graph_version": "1.0",
                "enabled_models": list(self._enabled_models),
                "feature_union": {"classification": True},
                "resolved_tasks": list(self._resolved_tasks),
                "enabled_task_capabilities": list(self._resolved_tasks),
                "generated_at": "2026-03-13T00:00:00Z",
                "source": "node_capabilities",
            }

        def save_openai_enabled_models(self, *, model_ids: list[str]):
            self._enabled_models = list(model_ids)
            self._resolved_tasks = ["task.classification", "task.reasoning"] if "gpt-5-pro" in model_ids else ["task.classification"]
            return {
                "provider_id": "openai",
                "models": [
                    {"model_id": model_id, "enabled": True, "selected_at": "2026-03-13T00:00:00Z"}
                    for model_id in model_ids
                ],
                "source": "provider_enabled_models",
                "generated_at": "2026-03-13T00:00:00Z",
            }

        def metrics_snapshot(self):
            return {
                "providers": {
                    "openai": {
                        "models": {
                            "gpt-5-mini": {
                                "avg_latency": 15.0,
                                "p95_latency": 20.0,
                                "total_requests": 20,
                                "successful_requests": 19,
                                "failed_requests": 1,
                                "failure_classes": {"TimeoutError": 1},
                                "success_rate": 0.95,
                            }
                        },
                        "totals": {
                            "total_requests": 20,
                            "successful_requests": 19,
                            "failed_requests": 1,
                            "success_rate": 0.95,
                        },
                    }
                }
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

        def load_or_create(self, migration_node_id=None):
            if self._payload is None and migration_node_id:
                self._payload = {"node_id": migration_node_id}
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
                    "task.classification",
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
        def __init__(self):
            self.redeclare_calls = []

        async def submit_once(self):
            return {"status": "accepted"}

        async def redeclare_if_needed(self, *, reason: str, force: bool = False):
            self.redeclare_calls.append({"reason": reason, "force": force})
            return {"status": "accepted", "reason": reason, "force": force}

        def clear_local_state_for_reonboarding(self):
            self.cleared = True

        def status_payload(self):
            return {
                "accepted_profile": {"declared_task_families": ["task.classification"]},
                "governance_bundle": {"generic_node_class_rules": {"allow_task_families": ["classification"]}},
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

    def test_status_payload_resets_to_unconfigured_when_core_reports_removed(self):
        class _FakeTrustStatusClient:
            def fetch(self, **_kwargs):
                return type(
                    "Result",
                    (),
                    {
                        "status": "removed",
                        "payload": {
                            "node_id": "node-001",
                            "support_state": "removed",
                            "message": "This node was removed by Core and is no longer trusted.",
                        },
                    },
                )()

        class _StoreWithPath:
            def __init__(self, path: Path, payload: dict | None = None):
                self._path = path
                self.payload = payload
                path.write_text("{}", encoding="utf-8")

            def load(self):
                return self.payload

        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-test"))
            lifecycle.transition_to(NodeLifecycleState.TRUSTED)
            trust_store = _StoreWithPath(
                Path(tmp) / "trust_state.json",
                payload={
                    "node_id": "node-001",
                    "core_api_endpoint": "http://10.0.0.100:9001/api",
                    "node_trust_token": "token",
                },
            )
            identity_store = _StoreWithPath(Path(tmp) / "node_identity.json", payload={"node_id": "node-001"})
            governance_store = _StoreWithPath(Path(tmp) / "governance_state.json", payload={"policy_version": "1"})
            prompt_store = _StoreWithPath(Path(tmp) / "prompt_service_state.json", payload={"prompt_services": []})
            bootstrap_path = Path(tmp) / "bootstrap_config.json"
            bootstrap_path.write_text("{}", encoding="utf-8")
            capability_runner = self._FakeCapabilityRunner()
            capability_runner.cleared = False

            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(bootstrap_path),
                logger=logging.getLogger("node-control-test"),
                capability_runner=capability_runner,
                node_identity_store=identity_store,
                trust_state_store=trust_store,
                governance_state_store=governance_store,
                prompt_service_state_store=prompt_store,
                trust_status_client=_FakeTrustStatusClient(),
            )

            payload = state.status_payload()

            self.assertEqual(payload["status"], "unconfigured")
            self.assertIsNone(payload["node_id"])
            self.assertFalse(bootstrap_path.exists())
            self.assertFalse(trust_store._path.exists())
            self.assertFalse(identity_store._path.exists())
            self.assertFalse(governance_store._path.exists())
            self.assertFalse(prompt_store._path.exists())
            self.assertTrue(capability_runner.cleared)
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

    def test_status_rehydrates_trusted_identity_and_runtime_context_from_trust_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-test"))
            lifecycle.transition_to(NodeLifecycleState.TRUSTED, {"source": "test"})
            lifecycle.transition_to(NodeLifecycleState.CAPABILITY_SETUP_PENDING, {"source": "test"})
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-test"),
                node_identity_store=self._FakeNodeIdentityStore(None),
                trust_state_store=self._FakeTrustStateStore(),
                provider_selection_store=self._FakeProviderSelectionStore(),
                task_capability_selection_store=self._FakeTaskCapabilitySelectionStore(),
                startup_mode="bootstrap_onboarding",
                trusted_runtime_context={},
            )

            payload = state.status_payload()

            self.assertEqual(payload["startup_mode"], "trusted_resume")
            self.assertEqual(payload["node_id"], "123e4567-e89b-42d3-a456-426614174000")
            self.assertEqual(payload["identity_state"], "valid")
            self.assertEqual(payload["trusted_runtime_context"]["paired_core_id"], "core-main")
            self.assertTrue(payload["capability_setup"]["readiness_flags"]["node_identity_valid"])
            self.assertTrue(payload["capability_setup"]["readiness_flags"]["core_runtime_context_valid"])

    def test_execute_direct_returns_completed_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-test"))
            runtime_manager = self._FakeProviderRuntimeManager()
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-test"),
                provider_runtime_manager=runtime_manager,
                capability_runner=self._FakeCapabilityRunner(),
                task_capability_selection_store=self._FakeTaskCapabilitySelectionStore(),
                prompt_service_state_store=self._FakePromptServiceStateStore(),
            )

            result = asyncio.run(
                state.execute_direct(
                    request=TaskExecutionRequest.model_validate(
                        {
                            "task_id": "task-001",
                            "task_family": "task.classification",
                            "requested_by": "service.alpha",
                            "requested_provider": "openai",
                            "requested_model": "gpt-5-mini",
                            "inputs": {"text": "hello"},
                            "timeout_s": 45,
                            "trace_id": "trace-001",
                        }
                    )
                )
            )

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["provider_used"], "openai")
            self.assertEqual(result["model_used"], "gpt-5-mini")
            self.assertIsNotNone(runtime_manager.last_execution_request)

            observability = state.execution_observability_payload()
            self.assertTrue(observability["configured"])
            self.assertEqual(len(observability["recent_history"]), 1)
            self.assertEqual(observability["recent_history"][0]["state"], "completed")
            self.assertEqual(observability["provider_usage"]["openai"]["total_requests"], 20)
            self.assertEqual(observability["model_usage"]["openai:gpt-5-mini"]["success_rate"], 0.95)

    def test_execute_direct_requires_runtime_manager(self):
        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-test"))
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-test"),
            )

            with self.assertRaisesRegex(ValueError, "direct execution is not configured"):
                asyncio.run(
                    state.execute_direct(
                        request=TaskExecutionRequest.model_validate(
                            {
                                "task_id": "task-002",
                                "task_family": "task.classification",
                                "requested_by": "service.alpha",
                                "inputs": {"text": "hello"},
                                "trace_id": "trace-002",
                            }
                        )
                    )
                )

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

    def test_initiate_onboarding_preserves_friendly_node_name(self):
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

            state.initiate_onboarding(
                mqtt_host="10.0.0.100",
                node_name="Main AI Node",
            )

            self.assertEqual(runner.calls[0]["node_name"], "Main AI Node")
            self.assertIn('"node_name": "Main AI Node"', path.read_text(encoding="utf-8"))

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

    def test_update_provider_selection_persists_provider_budget_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-test"))
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-test"),
                provider_selection_store=self._FakeProviderSelectionStore(),
            )
            payload = state.update_provider_selection(
                openai_enabled=True,
                provider_budget_limits={"openai": {"max_cost_cents": 2500, "period": "weekly"}},
            )
            self.assertEqual(payload["config"]["providers"]["budget_limits"]["openai"]["max_cost_cents"], 2500)
            self.assertEqual(payload["config"]["providers"]["budget_limits"]["openai"]["period"], "weekly")

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
                selected_task_families=["task.classification", "task.generation.image"]
            )
            self.assertEqual(
                payload["config"]["selected_task_families"],
                ["task.classification", "task.generation.image"],
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

    def test_capability_declaration_gate_accepts_legacy_task_family_aliases_from_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-test"))
            lifecycle.transition_to(NodeLifecycleState.TRUSTED, {"source": "test"})
            lifecycle.transition_to(NodeLifecycleState.CAPABILITY_SETUP_PENDING, {"source": "test"})
            task_config_path = Path(tmp) / "task_capability_selection.json"
            task_config_path.write_text(
                """
{
  "schema_version": "1.0",
  "selected_task_families": [
    "task.classification.text",
    "task.summarization.text"
  ]
}
                """.strip(),
                encoding="utf-8",
            )
            task_capability_store = TaskCapabilitySelectionConfigStore(
                path=str(task_config_path),
                logger=logging.getLogger("node-control-test"),
            )
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-test"),
                capability_runner=self._FakeCapabilityRunner(),
                node_identity_store=self._FakeNodeIdentityStore({"node_id": "node-001"}),
                provider_selection_store=self._FakeProviderSelectionStore(),
                task_capability_selection_store=task_capability_store,
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

            self.assertTrue(payload["capability_setup"]["readiness_flags"]["task_capability_selection_valid"])
            self.assertTrue(payload["capability_setup"]["declaration_allowed"])
            self.assertEqual(
                payload["capability_setup"]["task_capability_selection"]["selected"],
                ["task.classification", "task.summarization.text"],
            )

    def test_capability_declaration_gate_blocks_when_no_openai_models_are_usable(self):
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
            self.assertIn("openai_usable_models_required_before_declare", payload["capability_setup"]["blocking_reasons"])

    def test_enabled_model_update_redeclares_when_resolved_tasks_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-test"))
            capability_runner = self._FakeCapabilityRunner()
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-test"),
                capability_runner=capability_runner,
                provider_runtime_manager=self._FakeProviderRuntimeManager(),
            )

            payload = asyncio.run(state.update_openai_enabled_models_with_redeclaration(model_ids=["gpt-5-mini", "gpt-5-pro"]))

            self.assertTrue(payload["task_surface_changed"])
            self.assertEqual(payload["previous_resolved_tasks"], ["task.classification"])
            self.assertEqual(payload["resolved_tasks"], ["task.classification", "task.reasoning"])
            self.assertEqual(payload["declaration"]["reason"], "enabled_models_changed")
            self.assertEqual(len(capability_runner.redeclare_calls), 1)

    def test_enabled_model_update_skips_redeclare_when_resolved_tasks_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-test"))
            capability_runner = self._FakeCapabilityRunner()
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-test"),
                capability_runner=capability_runner,
                provider_runtime_manager=self._FakeProviderRuntimeManager(),
            )

            payload = asyncio.run(state.update_openai_enabled_models_with_redeclaration(model_ids=["gpt-5-mini"]))

            self.assertFalse(payload["task_surface_changed"])
            self.assertEqual(payload["declaration"]["reason"], "enabled_models_no_task_change")
            self.assertEqual(len(capability_runner.redeclare_calls), 0)

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
                task_family="task.classification",
                prompt_name="Prompt Alpha",
                definition={"system_prompt": "Classify this text."},
                provider_preferences={"preferred_providers": ["openai"], "default_provider": "openai"},
                constraints={"max_timeout_s": 30},
                metadata={"owner": "ops"},
            )
            self.assertEqual(len(registered["state"]["prompt_services"]), 1)
            self.assertEqual(registered["state"]["prompt_services"][0]["current_version"], "v1")

            updated = state.update_prompt_service(
                prompt_id="prompt.alpha",
                definition={"system_prompt": "Classify this text carefully."},
            )
            self.assertEqual(updated["state"]["prompt_services"][0]["current_version"], "v2")

            allowed = state.authorize_execution(
                prompt_id="prompt.alpha",
                task_family="task.classification",
            )
            self.assertTrue(allowed["allowed"])
            self.assertEqual(allowed["prompt_version"], "v2")

            restricted = state.transition_prompt_service(
                prompt_id="prompt.alpha",
                state="restricted",
                reason="manual_review",
            )
            self.assertEqual(restricted["state"]["prompt_services"][0]["status"], "restricted")
            denied_restricted = state.authorize_execution(
                prompt_id="prompt.alpha",
                task_family="task.classification",
            )
            self.assertFalse(denied_restricted["allowed"])
            self.assertEqual(denied_restricted["reason"], "prompt_state_invalid")

            state.transition_prompt_service(
                prompt_id="prompt.alpha",
                state="active",
                reason="review_complete",
            )

            probation = state.update_prompt_probation(
                prompt_id="prompt.alpha",
                action="start",
                reason="quality_review",
            )
            self.assertIn("prompt.alpha", probation["state"]["probation"]["active_prompt_ids"])
            denied = state.authorize_execution(
                prompt_id="prompt.alpha",
                task_family="task.classification",
            )
            self.assertFalse(denied["allowed"])
            self.assertEqual(denied["reason"], "prompt_in_probation")


if __name__ == "__main__":
    unittest.main()
