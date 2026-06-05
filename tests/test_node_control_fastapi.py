import asyncio
import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from ai_node.lifecycle.node_lifecycle import NodeLifecycle, NodeLifecycleState
from ai_node.persistence.budget_state_store import BudgetStateStore
from ai_node.providers.models import UnifiedExecutionResponse, UnifiedExecutionUsage
from ai_node.runtime.budget_manager import BudgetManager
from ai_node.runtime.node_control_api import (
    DirectExecutionAdmissionConfig,
    DirectExecutionAdmissionGuard,
    NodeControlState,
    create_node_control_app,
)
from ai_node.runtime.execution_queue import ExecutionQueueService


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
                    "task.classification",
                    "task.summarization",
                ],
            }

        def load_or_create(self, **_kwargs):
            return self.payload

        def save(self, payload):
            self.payload = payload

    class _FakeCapabilityRunner:
        def __init__(self):
            self.workflow_notifications = []
            self.redeclare_calls = []
            self.reonboarding_cleared = False

        async def submit_once(self):
            return {"status": "accepted"}

        async def redeclare_if_needed(self, *, reason: str, force: bool = False):
            self.redeclare_calls.append({"reason": reason, "force": force})
            return {"status": "accepted", "reason": reason, "force": force}

        async def refresh_governance_once(self):
            return {"status": "synced"}

        async def refresh_provider_capabilities_once(self, *, force_refresh: bool = False):
            return {"status": "refreshed", "changed": bool(force_refresh)}

        def recover_from_degraded(self):
            return {"status": "recovered", "target_state": "capability_setup_pending"}

        def clear_local_state_for_reonboarding(self):
            self.reonboarding_cleared = True

        def status_payload(self):
            return {
                "status": "idle",
                "accepted_profile": {"declared_task_families": ["task.classification", "task.summarization.text"]},
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
        def __init__(self):
            self.payload = {
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

        def load(self):
            return self.payload

        def clear(self):
            self.payload = None

    class _FakeBudgetDeclarationClient:
        def __init__(self):
            self.calls = []

        async def submit_declaration(self, *, core_api_endpoint: str, trust_token: str, node_id: str, declaration_payload: dict):
            self.calls.append(
                {
                    "core_api_endpoint": core_api_endpoint,
                    "trust_token": trust_token,
                    "node_id": node_id,
                    "declaration_payload": declaration_payload,
                }
            )

            class _Result:
                status = "accepted"
                payload = {"status": "accepted", "declaration_id": "budget-decl-1"}
                retryable = False
                error = None

            return _Result()

    class _FakeServiceManager:
        def __init__(self):
            self.status = {"backend": "running", "frontend": "running", "node": "running"}
            self.local_model_calls = []

        def get_status(self):
            return self.status

        def restart(self, *, target: str):
            return {"target": target, "result": "restarted"}

        def is_local_llm_model(self, *, model_id: str | None):
            return model_id == "mistral-nemo-instruct-2407-q4_k_m"

        def ensure_local_llm_model(self, *, model_id: str | None):
            self.local_model_calls.append(model_id)
            return {"model_id": model_id, "switched": False, "load_seconds": 0.0}

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
            self._enabled_models = ["gpt-5-mini"]
            self._resolved_tasks = ["task.chat", "task.reasoning"]

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

        async def execute_explicit(self, request):
            return await self.execute(request)

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
                    {"model_id": model_id, "enabled": True, "selected_at": "2026-03-13T00:00:00Z"}
                    for model_id in self._enabled_models
                ],
                "source": "provider_enabled_models",
                "generated_at": "2026-03-13T00:00:00Z",
            }

        def save_openai_enabled_models(self, *, model_ids: list[str]):
            self._enabled_models = list(model_ids)
            self._resolved_tasks = (
                ["task.chat", "task.reasoning", "task.vision_analysis"]
                if "gpt-5-pro" in model_ids
                else ["task.chat", "task.reasoning"]
            )
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
                "enabled_models": list(self._enabled_models),
                "feature_union": {"chat": True, "reasoning": True},
                "resolved_tasks": list(self._resolved_tasks),
                "enabled_task_capabilities": list(self._resolved_tasks),
                "generated_at": "2026-03-13T00:00:00Z",
                "source": "node_capabilities",
            }

    def test_client_ai_v2_schema_and_execution_only_benchmark_endpoints(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-fastapi-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-fastapi-test"),
                provider_runtime_manager=self._FakeProviderRuntimeManager(),
                prompt_service_state_store=self._FakePromptServiceStateStore(),
                service_manager=self._FakeServiceManager(),
            )
            app = create_node_control_app(state=state, logger=logging.getLogger("node-control-fastapi-test"))
            client = TestClient(app)

            catalog_response = client.get("/api/schemas/client-ai/v2")

            self.assertEqual(catalog_response.status_code, 200)
            schema_names = [item["name"] for item in catalog_response.json()["schemas"]]
            self.assertIn("benchmark-execution-request.v2.schema.json", schema_names)

            schema_response = client.get("/api/schemas/client-ai/v2/prompt-register.v2.request.schema.json")

            self.assertEqual(schema_response.status_code, 200)
            self.assertEqual(schema_response.json()["title"], "Prompt Register Request V2")

            guide_response = client.get("/api/schemas/client-ai/v2/communication.md")

            self.assertEqual(guide_response.status_code, 200)
            self.assertIn("text/markdown", guide_response.headers["content-type"])
            self.assertIn("Client AI V2 Communication Guide", guide_response.text)
            self.assertNotIn("/api/benchmarks/local-llm", guide_response.text)

            prompt_response = client.post(
                "/api/prompts/services",
                json={
                    "prompt_id": "prompt.mail.classifier.v2",
                    "service_id": "mail-node",
                    "task_family": "task.classification",
                    "version": "v2.0",
                    "definition": {"prompt_template": "Classify {{body}}", "template_variables": ["body"]},
                    "output_contract": {"format": "json", "parse_json_output": True},
                    "benchmark": {"enabled": True, "mode": "execution_only", "owner_evaluates_results": True},
                },
            )

            self.assertEqual(prompt_response.status_code, 200)
            prompt = prompt_response.json()["state"]["prompt_services"][0]
            self.assertEqual(prompt["current_version"], "v2.0")
            self.assertTrue(prompt["metadata"]["benchmark"]["enabled"])
            self.assertEqual(prompt["versions"][0]["metadata"]["output_contract"]["format"], "json")

            benchmark_response = client.post(
                "/api/benchmarks/execution/v2",
                json={
                    "benchmark_id": "bench-001",
                    "prompt_id": "prompt.mail.classifier.v2",
                    "prompt_version": "v2.0",
                    "task_family": "task.classification",
                    "requested_by": "mail-node",
                    "service_id": "mail-node",
                    "trace_id": "trace-bench-001",
                    "inputs": {"body": "Your package has shipped."},
                    "targets": [
                        {"provider": "openai", "model": "gpt-5-mini", "role": "baseline"},
                        {"model": "mistral-nemo-instruct-2407-q4_k_m"},
                    ],
                },
            )

            self.assertEqual(benchmark_response.status_code, 200)
            payload = benchmark_response.json()
            self.assertEqual(payload["benchmark_id"], "bench-001")
            self.assertEqual(payload["prompt_version"], "v2.0")
            self.assertEqual([item["provider"] for item in payload["results"]], ["openai", "local"])
            self.assertNotIn("winner", payload)
            self.assertNotIn("scores", payload)

    def test_provider_models_by_task_endpoint_returns_matching_models(self):
        class _CapabilityMappedRuntimeManager(self._FakeProviderRuntimeManager):
            def node_capabilities_payload(self):
                payload = super().node_capabilities_payload()
                payload["provider_capabilities"] = {
                    "openai": {"enabled_models": ["gpt-5-mini"], "resolved_tasks": ["task.reasoning"]},
                    "local": {"enabled_models": ["qwen3-8b-q4_k_m"], "resolved_tasks": ["task.classification"]},
                }
                return payload

        with tempfile.TemporaryDirectory() as tmp:
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-fastapi-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-fastapi-test"),
                provider_runtime_manager=_CapabilityMappedRuntimeManager(),
            )
            app = create_node_control_app(state=state, logger=logging.getLogger("node-control-fastapi-test"))
            client = TestClient(app)

            response = client.get("/api/providers/models/by-task/task.reasoning")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["task_family"], "task.reasoning")
            self.assertEqual(response.json()["providers"][0]["provider_id"], "openai")
            self.assertEqual(response.json()["providers"][0]["models"][0]["model_id"], "gpt-5-mini")

    def test_status_and_onboarding_endpoints(self):
        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-fastapi-test"))
            runtime_manager = self._FakeProviderRuntimeManager()
            capability_runner = self._FakeCapabilityRunner()
            budget_declaration_client = self._FakeBudgetDeclarationClient()
            trust_state_store = self._FakeTrustStateStore()
            config_path = Path(tmp) / "bootstrap_config.json"
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(config_path),
                logger=logging.getLogger("node-control-fastapi-test"),
                provider_selection_store=self._FakeProviderSelectionStore(),
                provider_credentials_store=self._FakeProviderCredentialsStore(),
                task_capability_selection_store=self._FakeTaskCapabilitySelectionStore(),
                capability_runner=capability_runner,
                trust_state_store=trust_state_store,
                budget_declaration_client=budget_declaration_client,
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
            self.assertTrue(config_path.exists())

            restart_response = client.post("/api/onboarding/restart")
            self.assertEqual(restart_response.status_code, 200)
            self.assertEqual(restart_response.json()["status"], "unconfigured")
            self.assertFalse(restart_response.json()["bootstrap_configured"])
            self.assertFalse(config_path.exists())

            followup_status_response = client.get("/api/node/status")
            self.assertEqual(followup_status_response.status_code, 200)
            self.assertEqual(followup_status_response.json()["status"], "unconfigured")
            self.assertFalse(followup_status_response.json()["bootstrap_configured"])

            provider_get_response = client.get("/api/providers/config")
            self.assertEqual(provider_get_response.status_code, 200)
            self.assertIn("config", provider_get_response.json())

            budget_state_response = client.get("/api/budgets/state")
            self.assertEqual(budget_state_response.status_code, 200)
            self.assertIn("configured", budget_state_response.json())

            provider_set_response = client.post(
                "/api/providers/config",
                json={"openai_enabled": True, "provider_budget_limits": {"openai": {"max_cost_cents": 2500, "period": "weekly"}}},
            )
            self.assertEqual(provider_set_response.status_code, 200)
            self.assertIn("openai", provider_set_response.json()["config"]["providers"]["enabled"])
            self.assertEqual(
                provider_set_response.json()["config"]["providers"]["budget_limits"]["openai"]["max_cost_cents"],
                2500,
            )
            self.assertEqual(
                provider_set_response.json()["config"]["providers"]["budget_limits"]["openai"]["period"],
                "weekly",
            )

            budget_declare_response = client.post("/api/budgets/declare", json={"provider_id": "openai"})
            self.assertEqual(budget_declare_response.status_code, 200)
            self.assertEqual(budget_declare_response.json()["status"], "accepted")
            self.assertEqual(
                budget_declaration_client.calls[0]["declaration_payload"]["service_capacity"],
                {
                    "service": "ai.inference",
                    "period": "weekly",
                    "limits": {"max_cost_cents": 2500},
                },
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
            self.assertFalse(enabled_models_set_response.json()["task_surface_changed"])
            self.assertEqual(enabled_models_set_response.json()["declaration"]["reason"], "enabled_models_no_task_change")

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
            self.assertIn("internal_scheduler", diagnostics_response.json())
            self.assertIn("provider_capability_refresh", diagnostics_response.json()["internal_scheduler"]["tasks"])
            self.assertIn("heartbeat", diagnostics_response.json()["internal_scheduler"]["tasks"])
            self.assertIn("telemetry", diagnostics_response.json()["internal_scheduler"]["tasks"])

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
                json={"selected_task_families": ["task.classification"]},
            )
            self.assertEqual(capability_config_set_response.status_code, 200)
            self.assertEqual(
                capability_config_set_response.json()["config"]["selected_task_families"],
                ["task.classification"],
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

            enabled_models_changed_response = client.post(
                "/api/providers/openai/models/enabled",
                json={"model_ids": ["gpt-5-mini", "gpt-5-pro"]},
            )
            self.assertEqual(enabled_models_changed_response.status_code, 200)
            self.assertTrue(enabled_models_changed_response.json()["task_surface_changed"])
            self.assertEqual(enabled_models_changed_response.json()["declaration"]["reason"], "enabled_models_changed")
            self.assertEqual(capability_runner.redeclare_calls[-1]["reason"], "enabled_models_changed")

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

            node_retrust_response = client.post("/api/node/retrust")
            self.assertEqual(node_retrust_response.status_code, 200)
            self.assertEqual(node_retrust_response.json()["flow"], "trust_rerequest")
            self.assertEqual(node_retrust_response.json()["lifecycle_state"], "bootstrap_connecting")
            self.assertTrue(capability_runner.reonboarding_cleared)
            self.assertIsNone(trust_state_store.load())
            self.assertTrue(config_path.exists())

            prompt_register_response = client.post(
                "/api/prompts/services",
                json={
                    "prompt_id": "prompt.alpha",
                    "service_id": "service.alpha",
                    "task_family": "task.classification",
                    "prompt_name": "Prompt Alpha",
                    "owner_client_id": "service.alpha",
                    "definition": {"system_prompt": "Classify the text."},
                    "constraints": {
                        "max_timeout_s": 30,
                        "structured_output_required": True,
                        "routing_policy": {"mode": "local_preferred"},
                        "importance": {"level": "normal"},
                        "capability_requirements": {"required_features": ["structured_output"]},
                    },
                    "metadata": {"owner": "ops"},
                },
            )
            self.assertEqual(prompt_register_response.status_code, 200)
            prompt_get_response = client.get("/api/prompts/services")
            self.assertEqual(prompt_get_response.status_code, 200)
            self.assertEqual(len(prompt_get_response.json()["state"]["prompt_services"]), 1)
            prompt_constraints = prompt_get_response.json()["state"]["prompt_services"][0]["constraints"]
            self.assertEqual(prompt_constraints["routing_policy"], {"mode": "local_preferred"})
            self.assertEqual(prompt_constraints["importance"], {"level": "normal"})
            self.assertEqual(prompt_constraints["capability_requirements"], {"required_features": ["structured_output"]})

            prompt_update_response = client.put(
                "/api/prompts/services/prompt.alpha",
                json={"definition": {"system_prompt": "Classify the text carefully."}},
            )
            self.assertEqual(prompt_update_response.status_code, 200)
            self.assertEqual(prompt_update_response.json()["state"]["prompt_services"][0]["current_version"], "v2")

            prompt_detail_response = client.get("/api/prompts/services/prompt.alpha")
            self.assertEqual(prompt_detail_response.status_code, 200)
            self.assertEqual(prompt_detail_response.json()["prompt"]["prompt_name"], "Prompt Alpha")

            exec_authorize_response = client.post(
                "/api/execution/authorize",
                json={
                    "prompt_id": "prompt.alpha",
                    "task_family": "task.classification",
                    "requested_by": "service.alpha",
                    "service_id": "service.alpha",
                    "inputs": {"json_schema": {"type": "object"}},
                },
            )
            self.assertEqual(exec_authorize_response.status_code, 200)
            self.assertTrue(exec_authorize_response.json()["allowed"])
            self.assertEqual(exec_authorize_response.json()["prompt_version"], "v2")

            prompt_lifecycle_response = client.post(
                "/api/prompts/services/prompt.alpha/lifecycle",
                json={"state": "restricted", "reason": "manual_review"},
            )
            self.assertEqual(prompt_lifecycle_response.status_code, 200)
            restricted_authorize_response = client.post(
                "/api/execution/authorize",
                json={
                    "prompt_id": "prompt.alpha",
                    "task_family": "task.classification",
                    "requested_by": "service.alpha",
                    "service_id": "service.alpha",
                    "inputs": {"json_schema": {"type": "object"}},
                },
            )
            self.assertEqual(restricted_authorize_response.status_code, 200)
            self.assertFalse(restricted_authorize_response.json()["allowed"])
            self.assertEqual(restricted_authorize_response.json()["reason"], "prompt_state_invalid")

            prompt_lifecycle_clear_response = client.post(
                "/api/prompts/services/prompt.alpha/lifecycle",
                json={"state": "active", "reason": "review_complete"},
            )
            self.assertEqual(prompt_lifecycle_clear_response.status_code, 200)

            prompt_probation_response = client.post(
                "/api/prompts/services/prompt.alpha/probation",
                json={"action": "start", "reason": "manual_review"},
            )
            self.assertEqual(prompt_probation_response.status_code, 200)
            exec_denied_response = client.post(
                "/api/execution/authorize",
                json={
                    "prompt_id": "prompt.alpha",
                    "task_family": "task.classification",
                    "requested_by": "service.alpha",
                    "service_id": "service.alpha",
                },
            )
            self.assertEqual(exec_denied_response.status_code, 200)
            self.assertFalse(exec_denied_response.json()["allowed"])
            self.assertEqual(exec_denied_response.json()["reason"], "prompt_in_probation")

            direct_exec_response = client.post(
                "/api/execution/direct",
                json={
                    "task_id": "task-001",
                    "prompt_id": "prompt.alpha",
                    "task_family": "task.classification",
                    "requested_by": "service.alpha",
                    "service_id": "service.alpha",
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

            prompt_review_due_response = client.post(
                "/api/prompts/services/prompt.alpha/lifecycle",
                json={"state": "review_due", "reason": "policy_refresh"},
            )
            self.assertEqual(prompt_review_due_response.status_code, 200)
            exec_review_due_response = client.post(
                "/api/execution/authorize",
                json={
                    "prompt_id": "prompt.alpha",
                    "task_family": "task.classification",
                    "requested_by": "service.alpha",
                    "service_id": "service.alpha",
                    "inputs": {"json_schema": {"type": "object"}},
                },
            )
            self.assertEqual(exec_review_due_response.status_code, 200)
            self.assertTrue(exec_review_due_response.json()["allowed"])
            self.assertEqual(exec_review_due_response.json()["prompt_state"], "review_due")

            prompt_review_response = client.post(
                "/api/prompts/services/prompt.alpha/review",
                json={"reviewed_by": "ops", "review_reason": "validated", "state": "active"},
            )
            self.assertEqual(prompt_review_response.status_code, 200)
            self.assertEqual(prompt_review_response.json()["state"]["prompt_services"][0]["status"], "active")

            prompt_migration_response = client.post(
                "/api/prompts/services/migrations/review-due",
                json={"reason": "policy_migration_review_due"},
            )
            self.assertEqual(prompt_migration_response.status_code, 200)
            self.assertEqual(prompt_migration_response.json()["state"]["prompt_services"][0]["status"], "review_due")
            self.assertEqual(prompt_migration_response.json()["migration"]["target_state"], "review_due")

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

            debug_prompts_response = client.get("/debug/prompts")
            self.assertEqual(debug_prompts_response.status_code, 200)
            self.assertTrue(debug_prompts_response.json()["configured"])

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
            old_admin_token = os.environ.get("HEXE_ADMIN_TOKEN")
            os.environ["HEXE_ADMIN_TOKEN"] = "admin-token"
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
                    headers={"X-Hexe-Admin-Token": "admin-token"},
                )
                self.assertEqual(authorized_diag.status_code, 200)

                unauthorized_refresh = client.post("/api/capabilities/providers/refresh", json={"force_refresh": True})
                self.assertEqual(unauthorized_refresh.status_code, 403)

                authorized_refresh = client.post(
                    "/api/capabilities/providers/refresh",
                    json={"force_refresh": True},
                    headers={"X-Hexe-Admin-Token": "admin-token"},
                )
                self.assertEqual(authorized_refresh.status_code, 200)

                unauthorized_rebuild = client.post("/api/capabilities/rebuild")
                self.assertEqual(unauthorized_rebuild.status_code, 403)

                authorized_rebuild = client.post(
                    "/api/capabilities/rebuild",
                    headers={"X-Hexe-Admin-Token": "admin-token"},
                )
                self.assertEqual(authorized_rebuild.status_code, 200)

                unauthorized_redeclare = client.post("/api/capabilities/redeclare", json={"force_refresh": False})
                self.assertEqual(unauthorized_redeclare.status_code, 403)

                authorized_redeclare = client.post(
                    "/api/capabilities/redeclare",
                    json={"force_refresh": False},
                    headers={"X-Hexe-Admin-Token": "admin-token"},
                )
                self.assertEqual(authorized_redeclare.status_code, 200)
            finally:
                if old_admin_token is None:
                    os.environ.pop("HEXE_ADMIN_TOKEN", None)
                else:
                    os.environ["HEXE_ADMIN_TOKEN"] = old_admin_token

    def test_openapi_uses_hexe_control_api_title(self):
        with tempfile.TemporaryDirectory() as tmp:
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

            response = client.get("/openapi.json")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["info"]["title"], "Hexe AI Node Control API")

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
                    "task_family": "task.classification",
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

    def test_execution_route_preview_endpoint_does_not_execute_supported_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-fastapi-test"))
            runtime_manager = self._FakeProviderRuntimeManager()
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-fastapi-test"),
                provider_selection_store=self._FakeProviderSelectionStore(),
                task_capability_selection_store=self._FakeTaskCapabilitySelectionStore(),
                capability_runner=self._FakeCapabilityRunner(),
                provider_runtime_manager=runtime_manager,
                prompt_service_state_store=self._FakePromptServiceStateStore(),
            )
            app = create_node_control_app(state=state, logger=logging.getLogger("node-control-fastapi-test"))
            client = TestClient(app)

            response = client.post(
                "/api/execution/route-preview",
                json={
                    "task_id": "task-preview-fastapi",
                    "task_family": "task.classification",
                    "requested_by": "service.alpha",
                    "requested_provider": "openai",
                    "requested_model": "gpt-5-mini",
                    "inputs": {"text": "hello preview"},
                    "response_mode": "async_if_queued",
                    "timeout_s": 45,
                    "trace_id": "trace-preview-fastapi",
                },
            )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["status"], "preview")
            self.assertTrue(payload["dry_run"])
            self.assertTrue(payload["would_queue"])
            self.assertEqual(payload["routing_decision"]["reason"], "explicit_provider")
            self.assertEqual(payload["provider_resolution"]["selected_model"], "gpt-5-mini")
            self.assertIsNone(runtime_manager.last_execution_request)

    def test_execution_job_delete_cancels_queued_job(self):
        async def run_scenario():
            async def blocking_job():
                await release_local.wait()
                return {"ok": True}

            async def wait_for_status(job_id: str, status: str) -> dict:
                for _ in range(50):
                    payload = await execution_queue.job_status(job_id=job_id)
                    if payload.get("status") == status:
                        return payload
                    await asyncio.sleep(0.01)
                raise AssertionError(f"job {job_id} did not reach {status}")

            with tempfile.TemporaryDirectory() as tmp:
                release_local = asyncio.Event()
                execution_queue = ExecutionQueueService(
                    logger=logging.getLogger("node-control-fastapi-test"),
                    local_concurrency=1,
                    cloud_concurrency=1,
                )
                blocker = await execution_queue.enqueue(
                    queue="local",
                    importance="normal",
                    job_name="local blocker",
                    request_payload={"task_id": "local-blocker"},
                    runner=blocking_job,
                )
                await wait_for_status(blocker["job_id"], "running")
                runtime_manager = self._FakeProviderRuntimeManager()
                state = NodeControlState(
                    lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-fastapi-test")),
                    config_path=str(Path(tmp) / "bootstrap_config.json"),
                    logger=logging.getLogger("node-control-fastapi-test"),
                    provider_selection_store=self._FakeProviderSelectionStore(),
                    task_capability_selection_store=self._FakeTaskCapabilitySelectionStore(),
                    capability_runner=self._FakeCapabilityRunner(),
                    provider_runtime_manager=runtime_manager,
                    execution_queue=execution_queue,
                )
                app = create_node_control_app(state=state, logger=logging.getLogger("node-control-fastapi-test"))
                client = TestClient(app)

                queued = client.post(
                    "/api/execution/direct",
                    json={
                        "task_id": "task-cancel-fastapi",
                        "task_family": "task.classification",
                        "requested_by": "service.alpha",
                        "requested_provider": "local",
                        "inputs": {"text": "hello"},
                        "response_mode": "async_if_queued",
                        "trace_id": "trace-cancel-fastapi",
                    },
                )
                self.assertEqual(queued.status_code, 200)

                cancelled = client.request(
                    "DELETE",
                    f"/api/execution/jobs/{queued.json()['job_id']}",
                    json={"reason": "client_cancelled"},
                )

                self.assertEqual(cancelled.status_code, 200)
                self.assertEqual(cancelled.json()["status"], "cancelled")
                self.assertEqual(cancelled.json()["error"]["message"], "client_cancelled")
                self.assertIsNone(runtime_manager.last_execution_request)
                release_local.set()
                await wait_for_status(blocker["job_id"], "completed")

        asyncio.run(run_scenario())

    def test_direct_execution_endpoint_returns_structured_busy_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-fastapi-test"))
            runtime_manager = self._FakeProviderRuntimeManager()
            guard = DirectExecutionAdmissionGuard(
                config=DirectExecutionAdmissionConfig(min_memory_available_mb=1024, retry_after_seconds=31),
                resource_sampler=lambda: {
                    "memory_available_mb": 128,
                    "swap_used_ratio": 0.1,
                    "load_per_cpu": 0.2,
                },
                logger=logging.getLogger("node-control-fastapi-test"),
            )
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-fastapi-test"),
                provider_selection_store=self._FakeProviderSelectionStore(),
                task_capability_selection_store=self._FakeTaskCapabilitySelectionStore(),
                capability_runner=self._FakeCapabilityRunner(),
                provider_runtime_manager=runtime_manager,
                prompt_service_state_store=self._FakePromptServiceStateStore(),
                direct_execution_admission_guard=guard,
            )
            app = create_node_control_app(state=state, logger=logging.getLogger("node-control-fastapi-test"))
            client = TestClient(app)

            response = client.post(
                "/api/execution/direct",
                json={
                    "task_id": "task-guard-fastapi",
                    "task_family": "task.classification",
                    "requested_by": "service.alpha",
                    "requested_provider": "openai",
                    "requested_model": "gpt-5-mini",
                    "inputs": {"text": "hello direct"},
                    "timeout_s": 45,
                    "trace_id": "trace-guard-fastapi",
                },
            )

            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.headers["retry-after"], "31")
            payload = response.json()["detail"]
            self.assertFalse(payload["accepted"])
            self.assertEqual(payload["status"], "busy")
            self.assertEqual(payload["reason"], "memory_available_below_floor")
            self.assertEqual(payload["retry_after_seconds"], 31)
            self.assertIsNone(runtime_manager.last_execution_request)

    def test_execution_admission_endpoint_exposes_max_in_flight(self):
        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-fastapi-test"))
            guard = DirectExecutionAdmissionGuard(
                config=DirectExecutionAdmissionConfig(
                    max_in_flight=7,
                    dynamic_in_flight_enabled=True,
                    min_effective_in_flight=2,
                    warm_memory_available_mb=8192,
                    retry_after_seconds=19,
                ),
                resource_sampler=lambda: {
                    "memory_available_mb": 4096,
                    "swap_used_ratio": 0.1,
                    "load_per_cpu": 0.2,
                },
                logger=logging.getLogger("node-control-fastapi-test"),
            )
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-fastapi-test"),
                direct_execution_admission_guard=guard,
            )
            app = create_node_control_app(state=state, logger=logging.getLogger("node-control-fastapi-test"))
            client = TestClient(app)

            response = client.get("/api/execution/admission")

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertTrue(payload["configured"])
            self.assertTrue(payload["enabled"])
            self.assertEqual(payload["thresholds"]["max_in_flight"], 7)
            self.assertEqual(payload["thresholds"]["configured_max_in_flight"], 7)
            self.assertEqual(payload["thresholds"]["effective_max_in_flight"], 4)
            self.assertEqual(payload["thresholds"]["capacity_tier"], "warm")
            self.assertTrue(payload["thresholds"]["dynamic_in_flight_enabled"])
            self.assertEqual(payload["thresholds"]["retry_after_seconds"], 19)
            self.assertEqual(payload["in_flight"], 0)

    def test_expensive_execution_routes_share_admission_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-fastapi-test"))
            runtime_manager = self._FakeProviderRuntimeManager()
            guard = DirectExecutionAdmissionGuard(
                config=DirectExecutionAdmissionConfig(min_memory_available_mb=1024, retry_after_seconds=29),
                resource_sampler=lambda: {
                    "memory_available_mb": 128,
                    "swap_used_ratio": 0.1,
                    "load_per_cpu": 0.2,
                },
                logger=logging.getLogger("node-control-fastapi-test"),
            )
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-fastapi-test"),
                provider_runtime_manager=runtime_manager,
                direct_execution_admission_guard=guard,
            )
            app = create_node_control_app(state=state, logger=logging.getLogger("node-control-fastapi-test"))
            client = TestClient(app)

            compare_response = client.post(
                "/api/execution/compare",
                json={
                    "task_family": "task.classification",
                    "prompt": "classify hello",
                    "providers": [{"provider": "openai", "model": "gpt-5-mini"}],
                },
            )
            benchmark_response = client.post(
                "/api/benchmarks/execution/v2",
                json={
                    "benchmark_id": "bench-admission",
                    "task_family": "task.classification",
                    "requested_by": "mail-node",
                    "trace_id": "trace-bench-admission",
                    "inputs": {"body": "hello"},
                    "targets": [{"provider": "openai", "model": "gpt-5-mini"}],
                },
            )
            authorize_response = client.post(
                "/api/execution/authorize",
                json={
                    "prompt_id": "missing.prompt",
                    "task_family": "task.classification",
                    "requested_by": "mail-node",
                },
            )
            admission_response = client.get("/api/execution/admission")

            self.assertEqual(compare_response.status_code, 503)
            self.assertEqual(compare_response.headers["retry-after"], "29")
            self.assertEqual(compare_response.json()["detail"]["route"], "compare")
            self.assertEqual(benchmark_response.status_code, 503)
            self.assertEqual(benchmark_response.headers["retry-after"], "29")
            self.assertEqual(benchmark_response.json()["detail"]["route"], "benchmark")
            self.assertEqual(authorize_response.status_code, 200)
            self.assertEqual(admission_response.status_code, 200)
            route_counts = admission_response.json()["route_counts"]
            self.assertEqual(route_counts["compare"]["rejected_count"], 1)
            self.assertEqual(route_counts["benchmark"]["rejected_count"], 1)
            self.assertIsNone(runtime_manager.last_execution_request)


if __name__ == "__main__":
    unittest.main()
