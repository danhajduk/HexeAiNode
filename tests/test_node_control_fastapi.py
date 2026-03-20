import logging
import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from ai_node.lifecycle.node_lifecycle import NodeLifecycle, NodeLifecycleState
from ai_node.persistence.budget_state_store import BudgetStateStore
from ai_node.providers.models import UnifiedExecutionResponse, UnifiedExecutionUsage
from ai_node.runtime.budget_manager import BudgetManager
from ai_node.runtime.node_control_api import NodeControlState, create_node_control_app


class NodeControlFastApiTests(unittest.TestCase):
    @staticmethod
    def _active_budget_policy():
        return {
            "node_id": "node-001",
            "service": "service.alpha",
            "status": "active",
            "budget_policy_version": "bp-001",
            "governance_version": "gov-001",
            "period_start": "2026-03-20T00:00:00+00:00",
            "period_end": "2099-03-21T00:00:00+00:00",
            "issued_at": "2026-03-20T00:00:00+00:00",
            "grants": [
                {
                    "grant_id": "grant-node",
                    "consumer_node_id": "node-001",
                    "service": "service.alpha",
                    "period_start": "2026-03-20T00:00:00+00:00",
                    "period_end": "2099-03-21T00:00:00+00:00",
                    "limits": {"max_cost_cents": 100},
                    "status": "active",
                    "scope_kind": "node",
                    "subject_id": "node-001",
                    "governance_version": "gov-001",
                    "budget_policy_version": "bp-001",
                    "metadata": {},
                    "issued_at": "2026-03-20T00:00:00+00:00",
                }
            ],
        }

    class _FakeProviderSelectionStore:
        def __init__(self):
            self.payload = {
                "schema_version": "1.0",
                "providers": {
                    "supported": {"cloud": ["openai"], "local": [], "future": []},
                    "enabled": [],
                    "budget_limits": {},
                },
                "services": {"enabled": [], "future": []},
            }

        def load_or_create(self, **_kwargs):
            return self.payload

        def save(self, payload):
            self.payload = payload

    class _FakeNodeIdentityStore:
        def load(self):
            return {"node_id": "node-001", "created_at": "2026-03-11T00:00:00Z"}

    class _FakeProviderCredentialsStore:
        def __init__(self):
            self.payload = {"schema_version": "1.0", "providers": {}}

        def load_or_create(self):
            return self.payload

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

    class _FakeCapabilityRunner:
        def __init__(self):
            self.workflow_notifications = []

        async def submit_once(self):
            return {"status": "accepted"}

        async def redeclare_if_needed(self, *, reason: str, force: bool = False):
            return {"status": "accepted", "reason": reason, "force": force}

        async def refresh_governance_once(self):
            return {"status": "synced"}

        async def refresh_provider_capabilities_once(self, *, force_refresh: bool = False):
            return {"status": "refreshed", "changed": bool(force_refresh)}

        def recover_from_degraded(self):
            return {"status": "recovered", "target_state": "capability_setup_pending"}

        def status_payload(self):
            return {
                "status": "idle",
                "accepted_profile": {"declared_task_families": ["task.classification.text", "task.summarization.text"]},
                "last_manifest_payload": {"manifest_version": "1.0"},
                "last_declaration_result": {"status": "accepted"},
                "governance_bundle": {
                    "generic_node_class_rules": {"allow_task_families": ["classification", "summarization"]},
                    "budget_policy": NodeControlFastApiTests._active_budget_policy(),
                },
                "governance_status": {
                    "state": "fresh",
                    "active_governance_version": "1.0",
                    "last_sync_time": "2026-03-11T00:00:00+00:00",
                },
            }

        async def emit_workflow_status_telemetry(self, *, workflow_request: str, workflow_status: str, details=None):
            self.workflow_notifications.append(
                {
                    "workflow_request": workflow_request,
                    "workflow_status": workflow_status,
                    "details": details if isinstance(details, dict) else {},
                }
            )
            return {"published": True, "last_error": None}

    class _FakeTrustStateStore:
        def load(self):
            return {
                "node_id": "node-001",
                "node_name": "main-ai-node",
                "node_type": "ai-node",
                "paired_core_id": "core-main",
                "core_api_endpoint": "http://10.0.0.100:9001",
                "node_trust_token": "token",
                "initial_baseline_policy": {"policy_version": "1.0"},
                "baseline_policy_version": "1.0",
                "operational_mqtt_identity": "node:node-001",
                "operational_mqtt_token": "mqtt-token",
                "operational_mqtt_host": "10.0.0.100",
                "operational_mqtt_port": 1883,
                "bootstrap_mqtt_host": "10.0.0.100",
                "registration_timestamp": "2026-03-11T00:00:00Z",
            }

    class _FakeServiceManager:
        def __init__(self):
            self.status = {"backend": "running", "frontend": "running", "node": "running"}

        def get_status(self):
            return self.status

        def restart(self, *, target: str):
            return {"target": target, "result": "restarted"}

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

    class _FakeProviderRuntimeManager:
        def __init__(self):
            self.refresh_calls = 0
            self.openai_reload_calls = 0
            self.rebuild_calls = 0
            self.last_execution_request = None

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

        async def rerun_openai_model_capabilities(self):
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

        def rebuild_node_capabilities(self):
            self.rebuild_calls += 1
            return {
                "status": "rebuilt",
                "provider_id": "openai",
                "resolved_tasks": ["task.reasoning", "task.classification"],
                "node_capabilities": {
                    "enabled_models": ["gpt-5-mini"],
                    "enabled_task_capabilities": ["task.reasoning", "task.classification"],
                },
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

        def providers_snapshot(self):
            return {"providers": [{"provider_id": "openai", "availability": "available", "models": []}]}

        def models_snapshot(self):
            return {"providers": [{"provider_id": "openai", "models": [{"model_id": "gpt-4o-mini"}]}]}

        def metrics_snapshot(self):
            return {"providers": {"openai": {"totals": {"total_requests": 1}}}}

        def latest_models_payload(self, *, provider_id: str, limit: int = 3):
            return {
                "provider_id": provider_id,
                "models": [
                    {
                        "model_id": "gpt-5",
                        "display_name": "gpt-5",
                        "created": 1741046400,
                        "pricing_input": 1.25,
                        "pricing_output": 10.0,
                        "status": "available",
                    }
                ][:limit],
                "source": "provider_registry",
                "generated_at": "2026-03-13T00:00:00Z",
            }

        def openai_model_catalog_payload(self):
            return {
                "provider_id": "openai",
                "models": [
                    {"model_id": "gpt-5-mini", "family": "llm", "discovered_at": "2026-03-13T00:00:00Z", "enabled": False},
                    {
                        "model_id": "omni-moderation-2024-09-26",
                        "family": "moderation",
                        "discovered_at": "2026-03-13T00:00:00Z",
                        "enabled": False,
                    },
                ],
                "source": "provider_model_catalog",
                "generated_at": "2026-03-13T00:00:00Z",
            }

        def openai_model_capabilities_payload(self):
            return {
                "provider_id": "openai",
                "classification_model": "gpt-5-mini",
                "entries": [
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
                    }
                ],
                "source": "provider_model_capabilities",
                "generated_at": "2026-03-13T00:00:00Z",
            }

        def openai_model_features_payload(self):
            return {
                "schema_version": "1.0",
                "generated_at": "2026-03-13T00:00:00Z",
                "source": "provider_model_features",
                "entries": [
                    {
                        "model_id": "gpt-5-mini",
                        "provider": "openai",
                        "classification_model": "gpt-5-mini",
                        "classified_at": "2026-03-13T00:00:00Z",
                        "features": {"chat": True, "reasoning": True},
                    }
                ],
            }

        def openai_enabled_models_payload(self):
            return {
                "provider_id": "openai",
                "models": [
                    {"model_id": "gpt-5-mini", "enabled": True, "selected_at": "2026-03-13T00:00:00Z"},
                ],
                "source": "provider_enabled_models",
                "generated_at": "2026-03-13T00:00:00Z",
            }

        def save_openai_enabled_models(self, *, model_ids: list[str]):
            return {
                "provider_id": "openai",
                "models": [
                    {"model_id": model_id, "enabled": True, "selected_at": "2026-03-13T00:00:00Z"}
                    for model_id in model_ids
                ],
                "source": "provider_enabled_models",
                "generated_at": "2026-03-13T00:00:00Z",
            }

        def openai_resolved_capabilities_payload(self):
            return {
                "provider_id": "openai",
                "enabled_model_ids": ["gpt-5-mini"],
                "classification_model": "gpt-5-mini",
                "updated_at": "2026-03-13T00:00:00Z",
                "capabilities": {
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
                },
                "enabled_models": [
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
                    }
                ],
            }

        def node_capabilities_payload(self):
            return {
                "schema_version": "1.0",
                "capability_graph_version": "1.0",
                "enabled_models": ["gpt-5-mini"],
                "feature_union": {"chat": True, "reasoning": True},
                "resolved_tasks": ["task.chat", "task.reasoning"],
                "enabled_task_capabilities": ["task.chat", "task.reasoning"],
                "generated_at": "2026-03-13T00:00:00Z",
                "source": "node_capabilities",
            }

    def test_status_and_onboarding_endpoints(self):
        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-fastapi-test"))
            runtime_manager = self._FakeProviderRuntimeManager()
            capability_runner = self._FakeCapabilityRunner()
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-fastapi-test"),
                provider_selection_store=self._FakeProviderSelectionStore(),
                provider_credentials_store=self._FakeProviderCredentialsStore(),
                task_capability_selection_store=self._FakeTaskCapabilitySelectionStore(),
                capability_runner=capability_runner,
                provider_runtime_manager=runtime_manager,
                service_manager=self._FakeServiceManager(),
                prompt_service_state_store=self._FakePromptServiceStateStore(),
            )
            app = create_node_control_app(state=state, logger=logging.getLogger("node-control-fastapi-test"))
            client = TestClient(app)

            status_response = client.get("/api/node/status")
            self.assertEqual(status_response.status_code, 200)
            self.assertEqual(status_response.json()["status"], "unconfigured")
            self.assertIn("node_id", status_response.json())
            self.assertIn("identity_state", status_response.json())
            self.assertIn("pending_node_nonce", status_response.json())
            self.assertIn("startup_mode", status_response.json())

            initiate_response = client.post(
                "/api/onboarding/initiate",
                json={"mqtt_host": "10.0.0.100", "node_name": "main-ai-node"},
            )
            self.assertEqual(initiate_response.status_code, 200)
            self.assertEqual(initiate_response.json()["status"], "bootstrap_connecting")

            provider_get_response = client.get("/api/providers/config")
            self.assertEqual(provider_get_response.status_code, 200)
            self.assertIn("config", provider_get_response.json())

            budget_state_response = client.get("/api/budgets/state")
            self.assertEqual(budget_state_response.status_code, 200)
            self.assertIn("configured", budget_state_response.json())

            provider_set_response = client.post(
                "/api/providers/config",
                json={"openai_enabled": True, "provider_budget_limits": {"openai": {"max_cost_cents": 2500}}},
            )
            self.assertEqual(provider_set_response.status_code, 200)
            self.assertIn("openai", provider_set_response.json()["config"]["providers"]["enabled"])
            self.assertEqual(
                provider_set_response.json()["config"]["providers"]["budget_limits"]["openai"]["max_cost_cents"],
                2500,
            )

            credentials_get_response = client.get("/api/providers/openai/credentials")
            self.assertEqual(credentials_get_response.status_code, 200)
            self.assertFalse(credentials_get_response.json()["configured"])

            credentials_set_response = client.post(
                "/api/providers/openai/credentials",
                json={
                    "api_token": "token-alpha-1234",
                    "service_token": "service-token-7890",
                    "project_name": "ops",
                },
            )
            self.assertEqual(credentials_set_response.status_code, 200)
            self.assertTrue(credentials_set_response.json()["credentials"]["has_api_token"])
            self.assertTrue(credentials_set_response.json()["credentials"]["api_token_hint"].endswith("1234"))
            self.assertEqual(runtime_manager.refresh_calls, 0)
            self.assertEqual(runtime_manager.openai_reload_calls, 1)

            preferences_set_response = client.post(
                "/api/providers/openai/preferences",
                json={"default_model_id": "gpt-5.4-pro", "selected_model_ids": ["gpt-5.4-pro", "gpt-5.4-mini"]},
            )
            self.assertEqual(preferences_set_response.status_code, 200)
            self.assertEqual(preferences_set_response.json()["credentials"]["default_model_id"], "gpt-5.4-pro")
            self.assertEqual(preferences_set_response.json()["credentials"]["selected_model_ids"], ["gpt-5.4-pro", "gpt-5.4-mini"])

            latest_models_response = client.get("/api/providers/openai/models/latest?limit=3")
            self.assertEqual(latest_models_response.status_code, 200)
            self.assertEqual(latest_models_response.json()["models"][0]["model_id"], "gpt-5")

            model_catalog_response = client.get("/api/providers/openai/models/catalog")
            self.assertEqual(model_catalog_response.status_code, 200)
            self.assertEqual(model_catalog_response.json()["models"][1]["family"], "moderation")
            self.assertIn("ui_models", model_catalog_response.json())

            model_capabilities_response = client.get("/api/providers/openai/models/capabilities")
            self.assertEqual(model_capabilities_response.status_code, 200)
            self.assertEqual(model_capabilities_response.json()["classification_model"], "gpt-5-mini")

            model_features_response = client.get("/api/providers/openai/models/features")
            self.assertEqual(model_features_response.status_code, 200)
            self.assertEqual(model_features_response.json()["entries"][0]["model_id"], "gpt-5-mini")

            enabled_models_response = client.get("/api/providers/openai/models/enabled")
            self.assertEqual(enabled_models_response.status_code, 200)
            self.assertEqual(enabled_models_response.json()["models"][0]["model_id"], "gpt-5-mini")

            enabled_models_set_response = client.post(
                "/api/providers/openai/models/enabled",
                json={"model_ids": ["gpt-5-mini", "gpt-4o"]},
            )
            self.assertEqual(enabled_models_set_response.status_code, 200)
            self.assertEqual(len(enabled_models_set_response.json()["models"]), 2)

            capability_resolution_response = client.get("/api/providers/openai/capability-resolution")
            self.assertEqual(capability_resolution_response.status_code, 200)
            self.assertTrue(capability_resolution_response.json()["capabilities"]["reasoning"])

            node_capabilities_response = client.get("/api/capabilities/node/resolved")
            self.assertEqual(node_capabilities_response.status_code, 200)
            self.assertIn("task.reasoning", node_capabilities_response.json()["enabled_task_capabilities"])

            diagnostics_response = client.get("/api/capabilities/diagnostics")
            self.assertEqual(diagnostics_response.status_code, 200)
            self.assertEqual(diagnostics_response.json()["classification_model"], "gpt-5-mini")
            self.assertIn("last_declaration_payload", diagnostics_response.json())
            self.assertIn("feature_catalog", diagnostics_response.json())
            self.assertIn("capability_graph", diagnostics_response.json())
            self.assertIn("resolved_tasks", diagnostics_response.json())

            pricing_diagnostics_response = client.get("/api/providers/openai/pricing/diagnostics")
            self.assertEqual(pricing_diagnostics_response.status_code, 200)
            self.assertEqual(pricing_diagnostics_response.json()["entry_count"], 3)

            pricing_refresh_response = client.post(
                "/api/providers/openai/pricing/refresh",
                json={"force_refresh": True},
            )
            self.assertEqual(pricing_refresh_response.status_code, 200)
            self.assertEqual(pricing_refresh_response.json()["provider_id"], "openai")
            self.assertEqual(pricing_refresh_response.json()["status"], "manual_only")

            manual_pricing_response = client.post(
                "/api/providers/openai/pricing/manual",
                json={"model_id": "gpt-5.4-pro", "input_price_per_1m": 3.0, "output_price_per_1m": 15.0},
            )
            self.assertEqual(manual_pricing_response.status_code, 200)
            self.assertEqual(manual_pricing_response.json()["status"], "manual_saved")

            capability_config_get_response = client.get("/api/capabilities/config")
            self.assertEqual(capability_config_get_response.status_code, 200)
            self.assertIn("selected_task_families", capability_config_get_response.json()["config"])

            capability_config_set_response = client.post(
                "/api/capabilities/config",
                json={"selected_task_families": ["task.classification.text"]},
            )
            self.assertEqual(capability_config_set_response.status_code, 200)
            self.assertEqual(
                capability_config_set_response.json()["config"]["selected_task_families"],
                ["task.classification.text"],
            )

            capability_declare_response = client.post("/api/capabilities/declare")
            self.assertEqual(capability_declare_response.status_code, 409)
            self.assertEqual(
                capability_declare_response.json()["detail"]["error_code"],
                "capability_setup_prerequisites_unmet",
            )

            governance_status_response = client.get("/api/governance/status")
            self.assertEqual(governance_status_response.status_code, 200)
            self.assertEqual(governance_status_response.json()["status"]["state"], "fresh")

            governance_refresh_response = client.post("/api/governance/refresh")
            self.assertEqual(governance_refresh_response.status_code, 200)
            self.assertEqual(governance_refresh_response.json()["status"], "synced")

            provider_refresh_response = client.post(
                "/api/capabilities/providers/refresh",
                json={"force_refresh": True},
            )
            self.assertEqual(provider_refresh_response.status_code, 200)
            self.assertEqual(provider_refresh_response.json()["status"], "refreshed")
            self.assertTrue(provider_refresh_response.json()["changed"])
            self.assertEqual(provider_refresh_response.json()["openai_model_reload"]["classification_model"], "gpt-5-mini")
            self.assertEqual(provider_refresh_response.json()["declaration"]["reason"], "provider_capability_refresh")
            self.assertEqual(runtime_manager.openai_reload_calls, 2)

            classification_refresh_response = client.post("/api/providers/openai/models/classification/refresh")
            self.assertEqual(classification_refresh_response.status_code, 200)
            self.assertEqual(classification_refresh_response.json()["declaration"]["reason"], "capability_catalog_refresh")

            capability_rebuild_response = client.post("/api/capabilities/rebuild")
            self.assertEqual(capability_rebuild_response.status_code, 200)
            self.assertEqual(capability_rebuild_response.json()["status"], "rebuilt")
            self.assertIn("resolved_tasks", capability_rebuild_response.json())

            capability_redeclare_response = client.post("/api/capabilities/redeclare", json={"force_refresh": False})
            self.assertEqual(capability_redeclare_response.status_code, 200)
            self.assertEqual(capability_redeclare_response.json()["reason"], "manual_redeclare")

            node_recover_response = client.post("/api/node/recover")
            self.assertEqual(node_recover_response.status_code, 200)
            self.assertEqual(node_recover_response.json()["status"], "recovered")

            prompt_register_response = client.post(
                "/api/prompts/services",
                json={
                    "prompt_id": "prompt.alpha",
                    "service_id": "svc-alpha",
                    "task_family": "task.classification.text",
                    "metadata": {"owner": "ops"},
                },
            )
            self.assertEqual(prompt_register_response.status_code, 200)
            prompt_get_response = client.get("/api/prompts/services")
            self.assertEqual(prompt_get_response.status_code, 200)
            self.assertEqual(len(prompt_get_response.json()["state"]["prompt_services"]), 1)

            exec_authorize_response = client.post(
                "/api/execution/authorize",
                json={"prompt_id": "prompt.alpha", "task_family": "task.classification.text"},
            )
            self.assertEqual(exec_authorize_response.status_code, 200)
            self.assertTrue(exec_authorize_response.json()["allowed"])

            prompt_probation_response = client.post(
                "/api/prompts/services/prompt.alpha/probation",
                json={"action": "start", "reason": "manual_review"},
            )
            self.assertEqual(prompt_probation_response.status_code, 200)
            exec_denied_response = client.post(
                "/api/execution/authorize",
                json={"prompt_id": "prompt.alpha", "task_family": "task.classification.text"},
            )
            self.assertEqual(exec_denied_response.status_code, 200)
            self.assertFalse(exec_denied_response.json()["allowed"])
            self.assertEqual(exec_denied_response.json()["reason"], "prompt_in_probation")

            direct_exec_response = client.post(
                "/api/execution/direct",
                json={
                    "task_id": "task-001",
                    "prompt_id": "prompt.alpha",
                    "task_family": "task.classification.text",
                    "requested_by": "service.alpha",
                    "requested_provider": "openai",
                    "requested_model": "gpt-5-mini",
                    "inputs": {"text": "hello world"},
                    "timeout_s": 45,
                    "trace_id": "trace-001",
                },
            )
            self.assertEqual(direct_exec_response.status_code, 200)
            self.assertEqual(direct_exec_response.json()["status"], "rejected")
            self.assertEqual(direct_exec_response.json()["error_code"], "prompt_in_probation")

            services_status_response = client.get("/api/services/status")
            self.assertEqual(services_status_response.status_code, 200)
            self.assertEqual(services_status_response.json()["services"]["backend"], "running")

            services_restart_response = client.post("/api/services/restart", json={"target": "backend"})
            self.assertEqual(services_restart_response.status_code, 200)
            self.assertEqual(services_restart_response.json()["target"], "backend")

            debug_providers_response = client.get("/debug/providers")
            self.assertEqual(debug_providers_response.status_code, 200)
            self.assertTrue(debug_providers_response.json()["configured"])
            self.assertEqual(debug_providers_response.json()["providers"][0]["provider_id"], "openai")

            debug_models_response = client.get("/debug/providers/models")
            self.assertEqual(debug_models_response.status_code, 200)
            self.assertEqual(debug_models_response.json()["providers"][0]["models"][0]["model_id"], "gpt-4o-mini")

            debug_metrics_response = client.get("/debug/providers/metrics")
            self.assertEqual(debug_metrics_response.status_code, 200)
            self.assertEqual(debug_metrics_response.json()["providers"]["openai"]["totals"]["total_requests"], 1)

            debug_execution_response = client.get("/debug/execution")
            self.assertEqual(debug_execution_response.status_code, 200)
            self.assertTrue(debug_execution_response.json()["configured"])
            self.assertIn("active_tasks", debug_execution_response.json())
            self.assertIn("recent_history", debug_execution_response.json())
            self.assertTrue(
                any(
                    item["workflow_request"] == "openai_model_classification_refresh"
                    and item["workflow_status"] == "done"
                    for item in capability_runner.workflow_notifications
                )
            )

    def test_capability_declare_succeeds_when_capability_setup_is_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-fastapi-test"))
            lifecycle.transition_to(NodeLifecycleState.TRUSTED, {"source": "test"})
            lifecycle.transition_to(NodeLifecycleState.CAPABILITY_SETUP_PENDING, {"source": "test"})
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-fastapi-test"),
                provider_selection_store=self._FakeProviderSelectionStore(),
                task_capability_selection_store=self._FakeTaskCapabilitySelectionStore(),
                capability_runner=self._FakeCapabilityRunner(),
                node_identity_store=self._FakeNodeIdentityStore(),
                trust_state_store=self._FakeTrustStateStore(),
                startup_mode="trusted_resume",
                trusted_runtime_context={
                    "paired_core_id": "core-main",
                    "core_api_endpoint": "http://10.0.0.100:9001",
                    "operational_mqtt_host": "10.0.0.100",
                    "operational_mqtt_port": 1883,
                },
            )
            app = create_node_control_app(state=state, logger=logging.getLogger("node-control-fastapi-test"))
            client = TestClient(app)
            response = client.post("/api/capabilities/declare")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "accepted")

    def test_admin_routes_require_token_when_configured(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_admin_token = os.environ.get("SYNTHIA_ADMIN_TOKEN")
            os.environ["SYNTHIA_ADMIN_TOKEN"] = "admin-token"
            try:
                lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-fastapi-test"))
                state = NodeControlState(
                    lifecycle=lifecycle,
                    config_path=str(Path(tmp) / "bootstrap_config.json"),
                    logger=logging.getLogger("node-control-fastapi-test"),
                    capability_runner=self._FakeCapabilityRunner(),
                    provider_runtime_manager=self._FakeProviderRuntimeManager(),
                )
                app = create_node_control_app(state=state, logger=logging.getLogger("node-control-fastapi-test"))
                client = TestClient(app)

                unauthorized_diag = client.get("/api/capabilities/diagnostics")
                self.assertEqual(unauthorized_diag.status_code, 403)

                authorized_diag = client.get(
                    "/api/capabilities/diagnostics",
                    headers={"X-Synthia-Admin-Token": "admin-token"},
                )
                self.assertEqual(authorized_diag.status_code, 200)

                unauthorized_refresh = client.post("/api/capabilities/providers/refresh", json={"force_refresh": True})
                self.assertEqual(unauthorized_refresh.status_code, 403)

                authorized_refresh = client.post(
                    "/api/capabilities/providers/refresh",
                    json={"force_refresh": True},
                    headers={"X-Synthia-Admin-Token": "admin-token"},
                )
                self.assertEqual(authorized_refresh.status_code, 200)

                unauthorized_rebuild = client.post("/api/capabilities/rebuild")
                self.assertEqual(unauthorized_rebuild.status_code, 403)

                authorized_rebuild = client.post(
                    "/api/capabilities/rebuild",
                    headers={"X-Synthia-Admin-Token": "admin-token"},
                )
                self.assertEqual(authorized_rebuild.status_code, 200)

                unauthorized_redeclare = client.post("/api/capabilities/redeclare", json={"force_refresh": False})
                self.assertEqual(unauthorized_redeclare.status_code, 403)

                authorized_redeclare = client.post(
                    "/api/capabilities/redeclare",
                    json={"force_refresh": False},
                    headers={"X-Synthia-Admin-Token": "admin-token"},
                )
                self.assertEqual(authorized_redeclare.status_code, 200)
            finally:
                if old_admin_token is None:
                    os.environ.pop("SYNTHIA_ADMIN_TOKEN", None)
                else:
                    os.environ["SYNTHIA_ADMIN_TOKEN"] = old_admin_token

    def test_direct_execution_endpoint_executes_supported_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-fastapi-test"))
            runtime_manager = self._FakeProviderRuntimeManager()
            budget_manager = BudgetManager(
                store=BudgetStateStore(path=str(Path(tmp) / "budget_state.json"), logger=logging.getLogger("node-control-fastapi-test")),
                logger=logging.getLogger("node-control-fastapi-test"),
                provider_runtime_manager=runtime_manager,
            )
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-fastapi-test"),
                provider_selection_store=self._FakeProviderSelectionStore(),
                task_capability_selection_store=self._FakeTaskCapabilitySelectionStore(),
                capability_runner=self._FakeCapabilityRunner(),
                provider_runtime_manager=runtime_manager,
                budget_manager=budget_manager,
                prompt_service_state_store=self._FakePromptServiceStateStore(),
            )
            app = create_node_control_app(state=state, logger=logging.getLogger("node-control-fastapi-test"))
            client = TestClient(app)

            response = client.post(
                "/api/execution/direct",
                json={
                    "task_id": "task-200",
                    "task_family": "task.classification.text",
                    "requested_by": "service.alpha",
                    "requested_provider": "openai",
                    "requested_model": "gpt-5-mini",
                    "inputs": {"text": "hello direct"},
                    "timeout_s": 45,
                    "trace_id": "trace-200",
                },
            )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "completed")
            self.assertEqual(response.json()["provider_used"], "openai")
            self.assertEqual(response.json()["model_used"], "gpt-5-mini")
            self.assertEqual(response.json()["output"]["text"], "mock:hello world")
            self.assertIsNotNone(runtime_manager.last_execution_request)
            self.assertEqual(runtime_manager.last_execution_request.requested_model, "gpt-5-mini")

            budget_state_response = client.get("/api/budgets/state")
            self.assertEqual(budget_state_response.status_code, 200)
            self.assertEqual(budget_state_response.json()["grant_count"], 1)


if __name__ == "__main__":
    unittest.main()
