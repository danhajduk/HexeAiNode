import asyncio
import logging
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_node.config.task_capability_selection_config import TaskCapabilitySelectionConfigStore
from ai_node.execution.task_models import TaskExecutionRequest
from ai_node.lifecycle.node_lifecycle import NodeLifecycle, NodeLifecycleState
from ai_node.providers.models import UnifiedExecutionResponse, UnifiedExecutionUsage
from ai_node.runtime.node_control_api import (
    DirectExecutionAdmissionConfig,
    DirectExecutionAdmissionGuard,
    DirectExecutionBusyError,
    NodeControlState,
)
from ai_node.runtime.execution_queue import ExecutionQueueService
from ai_node.runtime.operational_mqtt_recovery_store import OperationalMqttRecoveryStore


class NodeControlApiTests(unittest.TestCase):
    def test_parse_output_payload_unwraps_tool_wrapper_when_arguments_match_schema(self):
        schema = {
            "type": "object",
            "properties": {
                "label": {"type": "string"},
                "confidence": {"type": "number"},
                "rationale": {"type": "string"},
            },
            "required": ["label", "confidence", "rationale"],
        }
        payload = NodeControlState._parse_output_payload(
            '{"name":"classify_email","parameters":{"label":"action_required","confidence":0.95,"rationale":"Needs a reply."}}',
            expected_schema=schema,
        )

        self.assertEqual(
            payload,
            {"label": "action_required", "confidence": 0.95, "rationale": "Needs a reply."},
        )

    def test_parse_output_payload_does_not_unwrap_input_echo_tool_wrapper(self):
        schema = {
            "type": "object",
            "properties": {
                "label": {"type": "string"},
                "confidence": {"type": "number"},
                "rationale": {"type": "string"},
            },
            "required": ["label", "confidence", "rationale"],
        }
        payload = NodeControlState._parse_output_payload(
            '{"name":"classify_email","parameters":{"email":"from: a@example.com subject: hi body: please help"}}',
            expected_schema=schema,
        )

        self.assertEqual(payload["name"], "classify_email")
        self.assertEqual(payload["parameters"], {"email": "from: a@example.com subject: hi body: please help"})

    class _FakeNotificationService:
        def __init__(self):
            self.calls = []

        def notify(self, **kwargs):
            self.calls.append(kwargs)

    class _FakeProviderRuntimeManager:
        def __init__(self):
            self.refresh_calls = 0
            self.openai_reload_calls = 0
            self.last_execution_request = None
            self.execution_requests = []
            self._enabled_models = ["gpt-5-mini"]
            self._resolved_tasks = ["task.classification"]

        async def refresh(self):
            self.refresh_calls += 1
            return {"providers": []}

        async def execute(self, request):
            self.last_execution_request = request
            self.execution_requests.append(request)
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

    class _SlowProviderRuntimeManager(_FakeProviderRuntimeManager):
        async def execute(self, request):
            self.last_execution_request = request
            self.execution_requests.append(request)
            await asyncio.sleep(0.05)
            return UnifiedExecutionResponse(
                provider_id=str(request.requested_provider or "openai"),
                model_id=str(request.requested_model or "gpt-5-mini"),
                output_text="mock:slow",
                usage=UnifiedExecutionUsage(prompt_tokens=2, completion_tokens=4, total_tokens=6),
                latency_ms=50.0,
                estimated_cost=0.001,
            )

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
                    "task.summarization",
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

    class _FakeBudgetDeclarationClient:
        def __init__(self, response=None):
            self.response = response or {"status": "accepted", "declaration_id": "budget-decl-1"}
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
                payload = self.response
                retryable = False
                error = None

            return _Result()

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

    def test_preview_direct_execution_route_does_not_execute_provider(self):
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

            preview = asyncio.run(
                state.preview_direct_execution_route(
                    request=TaskExecutionRequest.model_validate(
                        {
                            "task_id": "task-preview-001",
                            "task_family": "task.classification",
                            "requested_by": "service.alpha",
                            "requested_provider": "openai",
                            "requested_model": "gpt-5-mini",
                            "inputs": {"text": "hello"},
                            "response_mode": "async_if_queued",
                            "trace_id": "trace-preview-001",
                        }
                    )
                )
            )

            self.assertEqual(preview["status"], "preview")
            self.assertTrue(preview["dry_run"])
            self.assertTrue(preview["would_execute"])
            self.assertTrue(preview["would_queue"])
            self.assertEqual(preview["queue"], "cloud")
            self.assertEqual(preview["routing_decision"]["reason"], "explicit_provider")
            self.assertEqual(preview["provider_resolution"]["selected_provider"], "openai")
            self.assertEqual(preview["provider_resolution"]["selected_model"], "gpt-5-mini")
            self.assertEqual(runtime_manager.execution_requests, [])

    def test_execute_direct_can_queue_async_job(self):
        async def run_scenario():
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

                queued = await state.execute_direct(
                    request=TaskExecutionRequest.model_validate(
                        {
                            "task_id": "task-queued-001",
                            "job_name": "queued classification",
                            "task_family": "task.classification",
                            "requested_by": "service.alpha",
                            "requested_provider": "local",
                            "requested_model": "qwen3-8b-q4_k_m",
                            "inputs": {"text": "hello"},
                            "response_mode": "async_if_queued",
                            "priority": "high",
                            "trace_id": "trace-queued-001",
                        }
                    )
                )

                self.assertEqual(queued["status"], "queued")
                self.assertEqual(queued["job_name"], "queued classification")
                self.assertEqual(queued["queue"], "local")
                self.assertEqual(queued["importance"], "high")
                self.assertEqual(queued["routing_decision"]["reason"], "explicit_provider")
                self.assertEqual(queued["routing_decision"]["selected_queue"], "local")
                self.assertIn("job queued - check in", queued["message"])

                result = await self._wait_for_execution_job(state, queued["job_id"], "completed")
                self.assertEqual(result["result"]["status"], "completed")
                self.assertEqual(result["queue"], "local")
                self.assertEqual(result["routing_decision"]["reason"], "explicit_provider")
                self.assertEqual(len(runtime_manager.execution_requests), 1)

                diagnostics = await state.execution_queue_diagnostics()
                self.assertTrue(diagnostics["configured"])
                self.assertIn("local", diagnostics["queues"])

        asyncio.run(run_scenario())

    def test_cancel_queued_execution_job(self):
        async def run_scenario():
            with tempfile.TemporaryDirectory() as tmp:
                release_local = asyncio.Event()
                execution_queue = ExecutionQueueService(
                    logger=logging.getLogger("node-control-test"),
                    local_concurrency=1,
                    cloud_concurrency=1,
                )
                blocker = await execution_queue.enqueue(
                    queue="local",
                    importance="normal",
                    job_name="local blocker",
                    request_payload={"task_id": "local-blocker"},
                    runner=lambda: self._blocking_queue_job(release=release_local),
                )
                await self._wait_for_queue_status(execution_queue, blocker["job_id"], "running")
                runtime_manager = self._FakeProviderRuntimeManager()
                state = NodeControlState(
                    lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-test")),
                    config_path=str(Path(tmp) / "bootstrap_config.json"),
                    logger=logging.getLogger("node-control-test"),
                    provider_runtime_manager=runtime_manager,
                    execution_queue=execution_queue,
                )

                queued = await state.execute_direct(
                    request=TaskExecutionRequest.model_validate(
                        {
                            "task_id": "task-cancel-queued-001",
                            "task_family": "task.classification",
                            "requested_by": "service.alpha",
                            "requested_provider": "local",
                            "inputs": {"text": "hello"},
                            "response_mode": "async_if_queued",
                            "trace_id": "trace-cancel-queued-001",
                        }
                    )
                )
                cancelled = await state.cancel_execution_job(
                    job_id=queued["job_id"],
                    reason="client_cancelled",
                )
                status = await state.execution_job_status(job_id=queued["job_id"])

                self.assertEqual(cancelled["status"], "cancelled")
                self.assertEqual(status["status"], "cancelled")
                self.assertEqual(status["error"]["message"], "client_cancelled")
                self.assertEqual(len(runtime_manager.execution_requests), 0)
                release_local.set()
                await self._wait_for_queue_status(execution_queue, blocker["job_id"], "completed")

        asyncio.run(run_scenario())

    def test_execute_direct_rejects_async_queue_when_client_pending_limit_is_reached(self):
        async def run_scenario():
            with tempfile.TemporaryDirectory() as tmp:
                release_local = asyncio.Event()
                execution_queue = ExecutionQueueService(
                    logger=logging.getLogger("node-control-test"),
                    local_concurrency=1,
                    cloud_concurrency=1,
                    max_pending_per_client=1,
                )
                blocker = await execution_queue.enqueue(
                    queue="local",
                    importance="normal",
                    job_name="client blocker",
                    request_payload={"task_id": "client-blocker"},
                    runner=lambda: self._blocking_queue_job(release=release_local),
                    client_id="service.alpha",
                )
                await self._wait_for_queue_status(execution_queue, blocker["job_id"], "running")
                state = NodeControlState(
                    lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-test")),
                    config_path=str(Path(tmp) / "bootstrap_config.json"),
                    logger=logging.getLogger("node-control-test"),
                    provider_runtime_manager=self._FakeProviderRuntimeManager(),
                    execution_queue=execution_queue,
                )

                rejected = await state.execute_direct(
                    request=TaskExecutionRequest.model_validate(
                        {
                            "task_id": "task-fairness-001",
                            "task_family": "task.classification",
                            "requested_by": "service.alpha",
                            "requested_provider": "local",
                            "inputs": {"text": "hello"},
                            "response_mode": "async_if_queued",
                            "trace_id": "trace-fairness-001",
                        }
                    )
                )

                self.assertEqual(rejected["status"], "rejected")
                self.assertEqual(rejected["error_code"], "queue_client_limit_exceeded")
                self.assertEqual(rejected["client_id"], "service.alpha")
                release_local.set()
                await self._wait_for_queue_status(execution_queue, blocker["job_id"], "completed")

        asyncio.run(run_scenario())

    def test_low_priority_image_generation_routes_to_cpu_comfyui_queue(self):
        async def run_scenario():
            with tempfile.TemporaryDirectory() as tmp:
                state = NodeControlState(
                    lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-test")),
                    config_path=str(Path(tmp) / "bootstrap_config.json"),
                    logger=logging.getLogger("node-control-test"),
                    provider_runtime_manager=self._FakeProviderRuntimeManager(),
                    capability_runner=self._FakeCapabilityRunner(),
                )

                preview = await state.preview_direct_execution_route(
                    request=TaskExecutionRequest.model_validate(
                        {
                            "task_id": "task-cpu-image-001",
                            "task_family": "task.image_generation",
                            "requested_by": "service.alpha",
                            "requested_provider": "local",
                            "inputs": {"prompt": "low priority render"},
                            "response_mode": "async_if_queued",
                            "priority": "background",
                            "trace_id": "trace-cpu-image-001",
                        }
                    )
                )

                self.assertEqual(preview["queue"], "cpu_comfyui")
                self.assertEqual(preview["importance"], "background")
                self.assertEqual(preview["routing_decision"]["reason"], "cpu_comfyui_background_image_policy")
                self.assertTrue(preview["routing_decision"]["cpu_comfyui_policy"]["selected"])
                self.assertEqual(preview["routing_decision"]["execution_routing_mode"], "local_only")

                diagnostics = await state.execution_queue_diagnostics()
                self.assertIn("cpu_comfyui", diagnostics["queues"])
                self.assertEqual(diagnostics["cpu_comfyui_policy"]["allowed_importance"], ["background", "low"])

        asyncio.run(run_scenario())

    def test_normal_priority_image_generation_does_not_route_to_cpu_comfyui_queue(self):
        async def run_scenario():
            with tempfile.TemporaryDirectory() as tmp:
                state = NodeControlState(
                    lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-test")),
                    config_path=str(Path(tmp) / "bootstrap_config.json"),
                    logger=logging.getLogger("node-control-test"),
                    provider_runtime_manager=self._FakeProviderRuntimeManager(),
                    capability_runner=self._FakeCapabilityRunner(),
                )

                preview = await state.preview_direct_execution_route(
                    request=TaskExecutionRequest.model_validate(
                        {
                            "task_id": "task-gpu-image-001",
                            "task_family": "task.image_generation",
                            "requested_by": "service.alpha",
                            "requested_provider": "local",
                            "inputs": {"prompt": "interactive render"},
                            "response_mode": "async_if_queued",
                            "priority": "normal",
                            "trace_id": "trace-gpu-image-001",
                        }
                    )
                )

                self.assertEqual(preview["queue"], "local")
                self.assertNotEqual(preview["routing_decision"]["selected_queue"], "cpu_comfyui")
                self.assertEqual(preview["routing_decision"]["reason"], "explicit_provider")

        asyncio.run(run_scenario())

    def test_comfyui_gpu_presets_payload_loads_config_catalog(self):
        with tempfile.TemporaryDirectory() as tmp:
            preset_path = Path(tmp) / "presets.json"
            preset_path.write_text(
                """
                {
                  "schema_version": "1.0",
                  "runtime_id": "comfyui_gpu",
                  "default_preset_id": "wide",
                  "base_workflow": {
                    "checkpoint": "RealVisXL_V5.0_fp16.safetensors",
                    "lora": "sdxl_lightning_4step_lora.safetensors"
                  },
                  "presets": [
                    {
                      "id": "wide",
                      "display_name": "Wide",
                      "seed_mode": "fixed",
                      "seed": 123,
                      "steps": 4,
                      "cfg": 1.6,
                      "sampler_name": "euler",
                      "scheduler": "sgm_uniform",
                      "width": 1344,
                      "height": 768,
                      "batch_size": 1,
                      "denoise": 1.0
                    },
                    {
                      "id": "random",
                      "display_name": "Random",
                      "seed_mode": "random",
                      "seed": null,
                      "random_seed": true,
                      "steps": 4,
                      "width": 1024,
                      "height": 1024
                    }
                  ]
                }
                """,
                encoding="utf-8",
            )
            with patch.dict("os.environ", {"HEXE_COMFYUI_GPU_PRESETS_CONFIG": str(preset_path)}, clear=False):
                state = NodeControlState(
                    lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-test")),
                    config_path=str(Path(tmp) / "bootstrap_config.json"),
                    logger=logging.getLogger("node-control-test"),
                    capability_runner=self._FakeCapabilityRunner(),
                )

            payload = state.comfyui_gpu_presets_payload()
            random_preset = state.comfyui_gpu_preset_payload(preset_id="random")

            self.assertTrue(payload["configured"])
            self.assertEqual(payload["preset_count"], 2)
            self.assertEqual(payload["default_preset_id"], "wide")
            self.assertEqual(payload["presets"][0]["checkpoint"], "RealVisXL_V5.0_fp16.safetensors")
            self.assertTrue(random_preset["preset"]["random_seed"])
            self.assertIsNone(random_preset["preset"]["seed"])

    def test_execute_direct_queues_sensitive_v3_prompt_on_local_queue(self):
        async def run_scenario():
            with tempfile.TemporaryDirectory() as tmp:
                lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-test"))
                state = NodeControlState(
                    lifecycle=lifecycle,
                    config_path=str(Path(tmp) / "bootstrap_config.json"),
                    logger=logging.getLogger("node-control-test"),
                    provider_runtime_manager=self._FakeProviderRuntimeManager(),
                    capability_runner=self._FakeCapabilityRunner(),
                    task_capability_selection_store=self._FakeTaskCapabilitySelectionStore(),
                    prompt_service_state_store=self._FakePromptServiceStateStore(),
                )
                state.register_prompt_service(
                    prompt_id="prompt.sensitive",
                    service_id="service.alpha",
                    task_family="task.classification",
                    privacy_class="sensitive",
                    version="v3.0",
                    definition={"system_prompt": "Classify private text locally."},
                )

                queued = await state.execute_direct(
                    request=TaskExecutionRequest.model_validate(
                        {
                            "task_id": "task-sensitive-queued-001",
                            "prompt_id": "prompt.sensitive",
                            "prompt_version": "v3.0",
                            "task_family": "task.classification",
                            "requested_by": "service.alpha",
                            "inputs": {"text": "private"},
                            "response_mode": "async_if_queued",
                            "priority": "high",
                            "trace_id": "trace-sensitive-queued-001",
                        }
                    )
                )

                self.assertEqual(queued["status"], "queued")
                self.assertEqual(queued["queue"], "local")
                self.assertEqual(queued["routing_decision"]["reason"], "routing_policy_local_only")
                self.assertEqual(queued["routing_decision"]["execution_routing_mode"], "local_only")
                await self._wait_for_execution_job(state, queued["job_id"], "completed")

        asyncio.run(run_scenario())

    def test_execute_direct_uses_task_capability_map_for_local_queue_selection(self):
        class _CapabilityMappedRuntimeManager(self._FakeProviderRuntimeManager):
            def node_capabilities_payload(self):
                payload = super().node_capabilities_payload()
                payload["provider_capabilities"] = {
                    "openai": {"resolved_tasks": []},
                    "local": {"resolved_tasks": ["task.classification"]},
                }
                payload["enabled_task_capabilities"] = ["task.classification"]
                payload["resolved_tasks"] = ["task.classification"]
                return payload

        async def run_scenario():
            with tempfile.TemporaryDirectory() as tmp:
                release_local = asyncio.Event()
                execution_queue = ExecutionQueueService(
                    logger=logging.getLogger("node-control-test"),
                    local_concurrency=1,
                    cloud_concurrency=1,
                )
                blocker = await execution_queue.enqueue(
                    queue="local",
                    importance="normal",
                    job_name="local blocker",
                    request_payload={"task_id": "local-blocker"},
                    runner=lambda: self._blocking_queue_job(release=release_local),
                )
                await self._wait_for_queue_status(execution_queue, blocker["job_id"], "running")

                state = NodeControlState(
                    lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-test")),
                    config_path=str(Path(tmp) / "bootstrap_config.json"),
                    logger=logging.getLogger("node-control-test"),
                    provider_runtime_manager=_CapabilityMappedRuntimeManager(),
                    execution_queue=execution_queue,
                )

                queued = await state.execute_direct(
                    request=TaskExecutionRequest.model_validate(
                        {
                            "task_id": "task-capability-local-001",
                            "task_family": "task.classification",
                            "requested_by": "service.alpha",
                            "inputs": {"text": "hello"},
                            "response_mode": "async_if_queued",
                            "trace_id": "trace-capability-local-001",
                        }
                    )
                )
                status = await state.execution_job_status(job_id=queued["job_id"])

                self.assertEqual(queued["queue"], "local")
                self.assertEqual(queued["routing_decision"]["reason"], "task_capability_local")
                self.assertEqual(queued["routing_decision"]["execution_routing_mode"], "local_only")
                self.assertEqual(status["request"]["constraints"]["routing_policy"]["mode"], "local_only")
                release_local.set()
                await self._wait_for_queue_status(execution_queue, blocker["job_id"], "completed")
                await self._wait_for_execution_job(state, queued["job_id"], "completed")

        asyncio.run(run_scenario())

    def test_execute_direct_uses_task_capability_map_to_bypass_local_preferred_queue(self):
        class _CapabilityMappedRuntimeManager(self._FakeProviderRuntimeManager):
            def node_capabilities_payload(self):
                payload = super().node_capabilities_payload()
                payload["provider_capabilities"] = {
                    "openai": {"resolved_tasks": ["task.classification"]},
                    "local": {"resolved_tasks": []},
                }
                payload["enabled_task_capabilities"] = ["task.classification"]
                payload["resolved_tasks"] = ["task.classification"]
                return payload

        async def run_scenario():
            with tempfile.TemporaryDirectory() as tmp:
                state = NodeControlState(
                    lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-test")),
                    config_path=str(Path(tmp) / "bootstrap_config.json"),
                    logger=logging.getLogger("node-control-test"),
                    provider_runtime_manager=_CapabilityMappedRuntimeManager(),
                )

                queued = await state.execute_direct(
                    request=TaskExecutionRequest.model_validate(
                        {
                            "task_id": "task-capability-cloud-001",
                            "task_family": "task.classification",
                            "requested_by": "service.alpha",
                            "inputs": {"text": "hello"},
                            "constraints": {"routing_policy": {"mode": "local_preferred"}},
                            "response_mode": "async_if_queued",
                            "trace_id": "trace-capability-cloud-001",
                        }
                    )
                )

                self.assertEqual(queued["queue"], "cloud")
                self.assertEqual(queued["routing_decision"]["reason"], "task_capability_cloud")
                self.assertEqual(queued["routing_decision"]["execution_routing_mode"], "cloud_only")
                completed = await self._wait_for_execution_job(state, queued["job_id"], "completed")
                self.assertEqual(completed["request"]["constraints"]["routing_policy"]["mode"], "cloud_only")

        asyncio.run(run_scenario())

    def test_execute_direct_spills_high_local_preferred_job_to_cloud_when_local_queue_is_busy(self):
        async def run_scenario():
            with tempfile.TemporaryDirectory() as tmp:
                release_local = asyncio.Event()
                execution_queue = ExecutionQueueService(
                    logger=logging.getLogger("node-control-test"),
                    local_concurrency=1,
                    cloud_concurrency=1,
                )
                blocker = await execution_queue.enqueue(
                    queue="local",
                    importance="normal",
                    job_name="local blocker",
                    request_payload={"task_id": "local-blocker"},
                    runner=lambda: self._blocking_queue_job(release=release_local),
                )
                await self._wait_for_queue_status(execution_queue, blocker["job_id"], "running")

                state = NodeControlState(
                    lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-test")),
                    config_path=str(Path(tmp) / "bootstrap_config.json"),
                    logger=logging.getLogger("node-control-test"),
                    provider_runtime_manager=(runtime_manager := self._FakeProviderRuntimeManager()),
                    execution_queue=execution_queue,
                )
                state._local_preferred_spillover_high_pending = 1  # noqa: SLF001

                queued = await state.execute_direct(
                    request=TaskExecutionRequest.model_validate(
                        {
                            "task_id": "task-spillover-001",
                            "task_family": "task.classification",
                            "requested_by": "service.alpha",
                            "inputs": {"text": "hello"},
                            "constraints": {"routing_policy": {"mode": "local_preferred"}},
                            "response_mode": "async_if_queued",
                            "priority": "high",
                            "trace_id": "trace-spillover-001",
                        }
                    )
                )

                self.assertEqual(queued["queue"], "cloud")
                self.assertEqual(queued["routing_decision"]["reason"], "local_preferred_spillover")
                self.assertEqual(queued["routing_decision"]["original_queue"], "local")
                self.assertEqual(queued["routing_decision"]["selected_queue"], "cloud")
                self.assertEqual(queued["routing_decision"]["execution_routing_mode"], "cloud_only")
                completed = await self._wait_for_execution_job(state, queued["job_id"], "completed")
                self.assertEqual(completed["result"]["provider_used"], "openai")
                self.assertTrue(completed["routing_decision"]["spillover"])
                self.assertEqual(runtime_manager.last_execution_request.requested_provider, "openai")
                release_local.set()
                await self._wait_for_queue_status(execution_queue, blocker["job_id"], "completed")

        asyncio.run(run_scenario())

    def test_execute_direct_does_not_spill_when_cloud_budget_limit_blocks_request(self):
        class _BudgetLimitedProviderRuntimeManager(self._FakeProviderRuntimeManager):
            def provider_selection_context_payload(self):
                payload = super().provider_selection_context_payload()
                payload["provider_budget_limits"] = {"openai": {"max_cost_cents": 1, "period": "monthly"}}
                return payload

        async def run_scenario():
            with tempfile.TemporaryDirectory() as tmp:
                release_local = asyncio.Event()
                execution_queue = ExecutionQueueService(
                    logger=logging.getLogger("node-control-test"),
                    local_concurrency=1,
                    cloud_concurrency=1,
                )
                blocker = await execution_queue.enqueue(
                    queue="local",
                    importance="normal",
                    job_name="local blocker",
                    request_payload={"task_id": "local-blocker"},
                    runner=lambda: self._blocking_queue_job(release=release_local),
                )
                await self._wait_for_queue_status(execution_queue, blocker["job_id"], "running")

                state = NodeControlState(
                    lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-test")),
                    config_path=str(Path(tmp) / "bootstrap_config.json"),
                    logger=logging.getLogger("node-control-test"),
                    provider_runtime_manager=_BudgetLimitedProviderRuntimeManager(),
                    execution_queue=execution_queue,
                )
                state._local_preferred_spillover_high_pending = 1  # noqa: SLF001

                queued = await state.execute_direct(
                    request=TaskExecutionRequest.model_validate(
                        {
                            "task_id": "task-spillover-budget-001",
                            "task_family": "task.classification",
                            "requested_by": "service.alpha",
                            "inputs": {"text": "hello"},
                            "constraints": {
                                "routing_policy": {"mode": "local_preferred"},
                                "budget": {"max_cost_cents": 5},
                            },
                            "response_mode": "async_if_queued",
                            "priority": "high",
                            "trace_id": "trace-spillover-budget-001",
                        }
                    )
                )

                self.assertEqual(queued["queue"], "local")
                self.assertEqual(queued["routing_decision"]["reason"], "routing_policy_local_preferred")
                self.assertFalse(queued["routing_decision"]["spillover"])
                release_local.set()
                await self._wait_for_execution_job(state, queued["job_id"], "completed")
                await self._wait_for_queue_status(execution_queue, blocker["job_id"], "completed")

        asyncio.run(run_scenario())

    def test_execute_direct_does_not_spill_local_only_job_to_cloud(self):
        async def run_scenario():
            with tempfile.TemporaryDirectory() as tmp:
                release_local = asyncio.Event()
                execution_queue = ExecutionQueueService(
                    logger=logging.getLogger("node-control-test"),
                    local_concurrency=1,
                    cloud_concurrency=1,
                )
                blocker = await execution_queue.enqueue(
                    queue="local",
                    importance="normal",
                    job_name="local blocker",
                    request_payload={"task_id": "local-blocker"},
                    runner=lambda: self._blocking_queue_job(release=release_local),
                )
                await self._wait_for_queue_status(execution_queue, blocker["job_id"], "running")

                state = NodeControlState(
                    lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-test")),
                    config_path=str(Path(tmp) / "bootstrap_config.json"),
                    logger=logging.getLogger("node-control-test"),
                    provider_runtime_manager=self._FakeProviderRuntimeManager(),
                    execution_queue=execution_queue,
                )
                state._local_preferred_spillover_high_pending = 1  # noqa: SLF001

                queued = await state.execute_direct(
                    request=TaskExecutionRequest.model_validate(
                        {
                            "task_id": "task-local-only-001",
                            "task_family": "task.classification",
                            "requested_by": "service.alpha",
                            "inputs": {"text": "hello"},
                            "constraints": {"routing_policy": {"mode": "local_only"}},
                            "response_mode": "async_if_queued",
                            "priority": "high",
                            "trace_id": "trace-local-only-001",
                        }
                    )
                )

                self.assertEqual(queued["queue"], "local")
                self.assertEqual(queued["routing_decision"]["reason"], "routing_policy_local_only")
                self.assertFalse(queued["routing_decision"]["spillover"])
                release_local.set()
                await self._wait_for_execution_job(state, queued["job_id"], "completed")
                await self._wait_for_queue_status(execution_queue, blocker["job_id"], "completed")

        asyncio.run(run_scenario())

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

    def test_execute_direct_rejects_when_max_in_flight_is_reached(self):
        async def run_scenario():
            with tempfile.TemporaryDirectory() as tmp:
                lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-test"))
                runtime_manager = self._SlowProviderRuntimeManager()
                guard = DirectExecutionAdmissionGuard(
                    config=DirectExecutionAdmissionConfig(max_in_flight=1, retry_after_seconds=17),
                    resource_sampler=lambda: {
                        "memory_available_mb": 4096,
                        "swap_used_ratio": 0.1,
                        "load_per_cpu": 0.2,
                    },
                    logger=logging.getLogger("node-control-test"),
                )
                state = NodeControlState(
                    lifecycle=lifecycle,
                    config_path=str(Path(tmp) / "bootstrap_config.json"),
                    logger=logging.getLogger("node-control-test"),
                    provider_runtime_manager=runtime_manager,
                    direct_execution_admission_guard=guard,
                )
                request = TaskExecutionRequest.model_validate(
                    {
                        "task_id": "task-guard-001",
                        "task_family": "task.classification",
                        "requested_by": "service.alpha",
                        "inputs": {"text": "hello"},
                        "trace_id": "trace-guard-001",
                    }
                )
                first = asyncio.create_task(state.execute_direct(request=request))
                await asyncio.sleep(0)
                with self.assertRaises(DirectExecutionBusyError) as context:
                    await state.execute_direct(
                        request=request.model_copy(update={"task_id": "task-guard-002", "trace_id": "trace-guard-002"})
                    )
                self.assertEqual(context.exception.payload["reason"], "max_in_flight_exceeded")
                self.assertEqual(context.exception.retry_after_seconds, 17)
                result = await first
                self.assertEqual(result["status"], "completed")
                self.assertEqual(state.direct_execution_admission_payload()["in_flight"], 0)
                self.assertEqual(len(runtime_manager.execution_requests), 1)

        asyncio.run(run_scenario())

    async def _wait_for_execution_job(self, state, job_id: str, status: str) -> dict:
        for _ in range(50):
            payload = await state.execution_job_status(job_id=job_id)
            if payload.get("status") == status:
                return payload
            await asyncio.sleep(0.01)
        raise AssertionError(f"job {job_id} did not reach {status}")

    async def _wait_for_queue_status(self, queue, job_id: str, status: str) -> dict:
        for _ in range(50):
            payload = await queue.job_status(job_id=job_id)
            if payload.get("status") == status:
                return payload
            await asyncio.sleep(0.01)
        raise AssertionError(f"job {job_id} did not reach {status}")

    async def _blocking_queue_job(self, *, release: asyncio.Event) -> dict:
        await release.wait()
        return {"status": "released"}

    def test_execute_direct_rejects_when_memory_or_swap_threshold_is_exceeded(self):
        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-test"))
            runtime_manager = self._FakeProviderRuntimeManager()
            guard = DirectExecutionAdmissionGuard(
                config=DirectExecutionAdmissionConfig(
                    min_memory_available_mb=1024,
                    max_swap_used_ratio=0.9,
                    retry_after_seconds=23,
                ),
                resource_sampler=lambda: {
                    "memory_available_mb": 256,
                    "swap_used_ratio": 0.95,
                    "load_per_cpu": 0.2,
                },
                logger=logging.getLogger("node-control-test"),
            )
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-test"),
                provider_runtime_manager=runtime_manager,
                direct_execution_admission_guard=guard,
            )

            with self.assertRaises(DirectExecutionBusyError) as context:
                asyncio.run(
                    state.execute_direct(
                        request=TaskExecutionRequest.model_validate(
                            {
                                "task_id": "task-guard-003",
                                "task_family": "task.classification",
                                "requested_by": "service.alpha",
                                "inputs": {"text": "hello"},
                                "trace_id": "trace-guard-003",
                            }
                        )
                    )
                )

            self.assertEqual(context.exception.payload["status"], "busy")
            self.assertEqual(context.exception.payload["reason"], "memory_available_below_floor")
            self.assertEqual(context.exception.retry_after_seconds, 23)
            self.assertIsNone(runtime_manager.last_execution_request)
            admission = state.direct_execution_admission_payload()
            self.assertEqual(admission["rejected_count"], 1)
            self.assertEqual(admission["last_rejection"]["reason"], "memory_available_below_floor")

    def test_execute_direct_rejects_when_load_threshold_is_exceeded(self):
        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-test"))
            runtime_manager = self._FakeProviderRuntimeManager()
            guard = DirectExecutionAdmissionGuard(
                config=DirectExecutionAdmissionConfig(max_load_per_cpu=1.0),
                resource_sampler=lambda: {
                    "memory_available_mb": 4096,
                    "swap_used_ratio": 0.1,
                    "load_per_cpu": 1.5,
                },
                logger=logging.getLogger("node-control-test"),
            )
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-test"),
                provider_runtime_manager=runtime_manager,
                direct_execution_admission_guard=guard,
            )

            with self.assertRaises(DirectExecutionBusyError) as context:
                asyncio.run(
                    state.execute_direct(
                        request=TaskExecutionRequest.model_validate(
                            {
                                "task_id": "task-guard-004",
                                "task_family": "task.classification",
                                "requested_by": "service.alpha",
                                "inputs": {"text": "hello"},
                                "trace_id": "trace-guard-004",
                            }
                        )
                    )
                )

            self.assertEqual(context.exception.payload["reason"], "load_average_high")
            self.assertIsNone(runtime_manager.last_execution_request)

    def test_compare_provider_execution_returns_per_provider_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-test"))
            runtime_manager = self._FakeProviderRuntimeManager()
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-test"),
                provider_runtime_manager=runtime_manager,
            )

            result = asyncio.run(
                state.compare_provider_execution(
                    task_family="task.classification",
                    prompt="classify hello",
                    system_prompt=None,
                    messages=None,
                    providers=[
                        {"provider": "openai", "model": "gpt-5-mini"},
                        {"provider": "local", "model": "qwen3-14b-q4_k_m"},
                    ],
                    temperature=0.0,
                    max_tokens=64,
                )
            )

            self.assertEqual(result["status"], "completed")
            self.assertEqual([item["provider"] for item in result["results"]], ["openai", "local"])
            self.assertEqual(result["results"][0]["model"], "gpt-5-mini")
            self.assertEqual(result["results"][1]["model"], "qwen3-14b-q4_k_m")
            self.assertEqual(result["results"][0]["estimated_cost"], 0.001)

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
            self.assertEqual(runner.calls[0]["topic"], "hexe/bootstrap/core")

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

    def test_restart_setup_clears_bootstrap_config_for_followup_status_reads(self):
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
                node_name="main-ai-node",
            )

            restart_payload = state.restart_setup()
            followup_payload = state.status_payload()

            self.assertEqual(restart_payload["status"], "unconfigured")
            self.assertFalse(restart_payload["bootstrap_configured"])
            self.assertEqual(followup_payload["status"], "unconfigured")
            self.assertFalse(followup_payload["bootstrap_configured"])
            self.assertFalse(path.exists())

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
            self.assertTrue(payload["internal_scheduler"]["configured"])
            self.assertIn("provider_capability_refresh", payload["internal_scheduler"]["tasks"])
            self.assertIn("heartbeat", payload["internal_scheduler"]["tasks"])
            self.assertIn("telemetry", payload["internal_scheduler"]["tasks"])
            self.assertIn("operational_mqtt_health", payload["internal_scheduler"]["tasks"])
            self.assertEqual(payload["internal_scheduler"]["tasks"]["heartbeat"]["schedule_name"], "heartbeat_5_seconds")
            self.assertEqual(payload["internal_scheduler"]["tasks"]["telemetry"]["schedule_name"], "telemetry_60_seconds")
            self.assertEqual(
                payload["internal_scheduler"]["tasks"]["operational_mqtt_health"]["schedule_name"],
                "every_10_seconds",
            )

    def test_start_background_jobs_starts_bootstrap_listener_from_trust_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-test"))
            lifecycle.transition_to(NodeLifecycleState.TRUSTED, {"source": "test"})
            lifecycle.transition_to(NodeLifecycleState.CAPABILITY_SETUP_PENDING, {"source": "test"})
            runner = self._FakeBootstrapRunner()
            notifications = self._FakeNotificationService()
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-test"),
                bootstrap_runner=runner,
                provider_runtime_manager=self._FakeProviderRuntimeManager(),
                notification_service=notifications,
                trust_state_store=self._FakeTrustStateStore(),
                startup_mode="trusted_resume",
                trusted_runtime_context={"paired_core_id": "core-main"},
            )

            asyncio.run(state.start_background_jobs())
            asyncio.run(state.stop_background_jobs())

            self.assertEqual(len(runner.calls), 1)
            self.assertEqual(runner.calls[0]["bootstrap_host"], "10.0.0.100")
            self.assertEqual(runner.calls[0]["port"], 1884)
            self.assertEqual(runner.calls[0]["topic"], "hexe/bootstrap/core")
            self.assertEqual(runner.calls[0]["node_name"], "main-ai-node")
            self.assertEqual(state._provider_runtime_manager.refresh_calls, 1)
            self.assertEqual(len(notifications.calls), 1)
            self.assertEqual(notifications.calls[0]["event_type"], "node_back_online")

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

    def test_update_provider_selection_enables_local_on_stale_config(self):
        class _StaleProviderSelectionStore(self._FakeProviderSelectionStore):
            def __init__(self):
                super().__init__()
                self.payload["providers"]["supported"]["local"] = []

        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-test"))
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-test"),
                provider_selection_store=_StaleProviderSelectionStore(),
            )
            payload = state.update_provider_selection(openai_enabled=True, local_enabled=True)

            self.assertIn("local", payload["config"]["providers"]["supported"]["local"])
            self.assertIn("local", payload["config"]["providers"]["enabled"])

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

    def test_declare_budget_to_core_uses_saved_provider_budget(self):
        class _BudgetCapabilityRunner(self._FakeCapabilityRunner):
            def status_payload(self):
                payload = super().status_payload()
                payload["provider_capability_report"] = {
                    "generated_at": "2026-04-02T01:02:03Z",
                    "providers": [
                        {
                            "provider": "openai",
                            "models": [
                                {
                                    "id": "gpt-5-mini",
                                    "status": "available",
                                    "pricing": {"input_per_1m_tokens": 0.25, "output_per_1m_tokens": 2.0},
                                },
                                {"id": "gpt-5-pro", "status": "unavailable"},
                            ],
                        }
                    ],
                }
                return payload

        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-test"))
            client = self._FakeBudgetDeclarationClient()
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-test"),
                provider_selection_store=self._FakeProviderSelectionStore(),
                capability_runner=_BudgetCapabilityRunner(),
                trust_state_store=self._FakeTrustStateStore(),
                budget_declaration_client=client,
            )
            state.update_provider_selection(
                openai_enabled=True,
                provider_budget_limits={"openai": {"max_cost_cents": 2500, "period": "weekly"}},
            )

            payload = asyncio.run(state.declare_budget_to_core(provider_id="openai"))

            self.assertEqual(payload["status"], "accepted")
            self.assertEqual(client.calls[0]["core_api_endpoint"], "http://10.0.0.100:9001")
            self.assertEqual(client.calls[0]["node_id"], "123e4567-e89b-42d3-a456-426614174000")
            self.assertEqual(
                client.calls[0]["declaration_payload"]["service_capacity"],
                {
                    "service": "ai.inference",
                    "period": "weekly",
                    "limits": {"max_cost_cents": 2500},
                },
            )
            self.assertEqual(
                client.calls[0]["declaration_payload"]["provider_intelligence"][0]["capacity"],
                {
                    "period": "weekly",
                    "limits": {"max_cost_cents": 2500},
                },
            )
            self.assertEqual(
                client.calls[0]["declaration_payload"]["provider_intelligence"][0]["available_models"],
                [
                    {
                        "model_id": "gpt-5-mini",
                        "pricing": {"input_per_1m_tokens": 0.25, "output_per_1m_tokens": 2.0},
                    }
                ],
            )

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
                ["task.classification", "task.image_generation"],
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
                ["task.classification", "task.summarization"],
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

    def test_models_for_task_uses_provider_capability_maps(self):
        class _CapabilityMappedRuntimeManager(self._FakeProviderRuntimeManager):
            def provider_selection_context_payload(self):
                payload = super().provider_selection_context_payload()
                payload["enabled_providers"] = ["openai", "local"]
                payload["default_model_by_provider"]["local"] = "qwen3-8b-q4_k_m"
                payload["available_models_by_provider"]["local"] = ["qwen3-8b-q4_k_m"]
                payload["usable_models_by_provider"]["local"] = ["qwen3-8b-q4_k_m"]
                return payload

            def node_capabilities_payload(self):
                payload = super().node_capabilities_payload()
                payload["provider_capabilities"] = {
                    "openai": {
                        "enabled_models": ["gpt-5-mini"],
                        "resolved_tasks": ["task.reasoning"],
                    },
                    "local": {
                        "enabled_models": ["qwen3-8b-q4_k_m"],
                        "resolved_tasks": ["task.classification"],
                    },
                }
                return payload

        with tempfile.TemporaryDirectory() as tmp:
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-test"),
                provider_runtime_manager=_CapabilityMappedRuntimeManager(),
            )

            classification = state.models_for_task_payload(task_family="task.classification")
            reasoning = state.models_for_task_payload(task_family="task.reasoning")

            self.assertEqual(classification["task_family"], "task.classification")
            self.assertEqual(classification["providers"][0]["provider_id"], "local")
            self.assertEqual(classification["providers"][0]["models"][0]["model_id"], "qwen3-8b-q4_k_m")
            self.assertEqual(reasoning["providers"][0]["provider_id"], "openai")
            self.assertEqual(reasoning["providers"][0]["models"][0]["model_id"], "gpt-5-mini")

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
                owner_client_id="svc-alpha",
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
                requested_by="svc-alpha",
                service_id="svc-alpha",
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
                requested_by="svc-alpha",
                service_id="svc-alpha",
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
                requested_by="svc-alpha",
                service_id="svc-alpha",
            )
            self.assertFalse(denied["allowed"])
            self.assertEqual(denied["reason"], "prompt_in_probation")

            state.transition_prompt_service(
                prompt_id="prompt.alpha",
                state="review_due",
                reason="policy_refresh",
            )
            review_due = state.authorize_execution(
                prompt_id="prompt.alpha",
                task_family="task.classification",
                requested_by="svc-alpha",
                service_id="svc-alpha",
            )
            self.assertTrue(review_due["allowed"])
            self.assertEqual(review_due["prompt_state"], "review_due")

            access_denied = state.authorize_execution(
                prompt_id="prompt.alpha",
                task_family="task.classification",
                requested_by="svc-beta",
                service_id="svc-beta",
            )
            self.assertFalse(access_denied["allowed"])
            self.assertEqual(access_denied["reason"], "prompt_access_denied")

    def test_retired_prompt_registration_allows_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-test"))
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-test"),
                prompt_service_state_store=self._FakePromptServiceStateStore(),
            )

            initial = state.register_prompt_service(
                prompt_id="prompt.alpha",
                service_id="svc-alpha",
                task_family="task.classification.email",
                prompt_name="Prompt Alpha",
                definition={"system_prompt": "Old classifier."},
                metadata={"generation": "old"},
            )
            self.assertEqual(initial["state"]["prompt_services"][0]["status"], "active")

            retired = state.transition_prompt_service(
                prompt_id="prompt.alpha",
                state="retired",
                reason="replace_definition",
            )
            self.assertEqual(retired["state"]["prompt_services"][0]["status"], "retired")

            overwritten = state.register_prompt_service(
                prompt_id="prompt.alpha",
                service_id="svc-beta",
                task_family="task.classification.email",
                prompt_name="Prompt Alpha Replacement",
                definition={"system_prompt": "New classifier."},
                metadata={"generation": "new"},
            )
            self.assertEqual(len(overwritten["state"]["prompt_services"]), 1)
            prompt = overwritten["state"]["prompt_services"][0]
            self.assertEqual(prompt["service_id"], "svc-beta")
            self.assertEqual(prompt["status"], "active")
            self.assertEqual(prompt["versions"][0]["definition"]["system_prompt"], "New classifier.")
            self.assertEqual(prompt["metadata"]["generation"], "new")

    def test_migrate_existing_prompts_to_review_due(self):
        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-test"))
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-test"),
                prompt_service_state_store=self._FakePromptServiceStateStore(),
            )
            state.register_prompt_service(
                prompt_id="prompt.alpha",
                service_id="svc-alpha",
                task_family="task.classification",
                prompt_name="Prompt Alpha",
                definition={"system_prompt": "Classifier."},
            )
            migrated = state.migrate_prompt_services_to_review_due()
            prompt = migrated["state"]["prompt_services"][0]
            self.assertEqual(prompt["status"], "review_due")
            self.assertEqual(prompt["lifecycle_history"][-1]["reason"], "policy_migration_review_due")

    def test_supervisor_runtime_payload_includes_local_llm_process_metrics(self):
        class _ServiceManager:
            def get_status(self):
                return {
                    "backend": {"service_id": "backend", "state": "running"},
                    "frontend": {"service_id": "frontend", "state": "running"},
                    "local_llm": {
                        "service_id": "local_llm",
                        "state": "running",
                        "pid": 4242,
                        "cpu_percent": 12.34,
                        "mem_percent": 56.78,
                        "model_states": {
                            "configured": True,
                            "runtime_ready": True,
                            "active_model_ids": ["qwen3-8b-q4_k_m"],
                            "default_model_id": "qwen3-8b-q4_k_m",
                            "models": [
                                {
                                    "model_id": "qwen3-8b-q4_k_m",
                                    "warmth_state": "loaded",
                                    "health_state": "available",
                                }
                            ],
                        },
                    },
                    "node": "running",
                }

        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-test"))
            lifecycle.transition_to(NodeLifecycleState.TRUSTED)
            lifecycle.transition_to(NodeLifecycleState.CAPABILITY_SETUP_PENDING)
            lifecycle.transition_to(NodeLifecycleState.CAPABILITY_DECLARATION_IN_PROGRESS)
            lifecycle.transition_to(NodeLifecycleState.CAPABILITY_DECLARATION_ACCEPTED)
            lifecycle.transition_to(NodeLifecycleState.OPERATIONAL)
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-test"),
                trust_state_store=self._FakeTrustStateStore(),
                service_manager=_ServiceManager(),
            )

            payload = state._supervisor_runtime_payload()

        local_llm = payload["runtime_metadata"]["services"]["local_llm"]
        self.assertEqual(local_llm["pid"], 4242)
        self.assertEqual(local_llm["cpu_percent"], 12.34)
        self.assertEqual(local_llm["mem_percent"], 56.78)
        self.assertEqual(local_llm["model_states"]["models"][0]["warmth_state"], "loaded")


class NodeControlOperationalMqttRecoveryTests(unittest.IsolatedAsyncioTestCase):
    class _FakeCapabilityRunner:
        def __init__(self, *, healthy: bool, error: str | None = None):
            self.healthy = healthy
            self.error = error
            self.unhealthy_calls = []
            self.recover_calls = 0

        async def check_operational_mqtt_health_once(self):
            return {
                "healthy": self.healthy,
                "last_error": None if self.healthy else (self.error or "mqtt_down"),
                "readiness": {"ready": self.healthy, "last_error": self.error},
            }

        def mark_operational_mqtt_unhealthy(self, *, error):
            self.unhealthy_calls.append(str(error))
            return {"last_error": str(error)}

        def recover_from_degraded(self):
            self.recover_calls += 1
            return {"target_state": NodeLifecycleState.OPERATIONAL.value}

        def status_payload(self):
            return {
                "status": "accepted",
                "operational_mqtt_readiness": {"ready": self.healthy, "last_error": self.error},
            }

    class _FakeServiceManager:
        def __init__(self):
            self.calls = []

        def get_status(self):
            return {"backend": "running", "frontend": "running", "node": "running"}

        def schedule_restart(self, *, target: str, delay_seconds: int):
            payload = {"target": target, "delay_seconds": delay_seconds}
            self.calls.append(payload)
            return {"target": target, "result": "scheduled", "delay_seconds": delay_seconds}

        def revert_local_llm_to_default_if_idle(self, *, local_in_flight: int = 0, queued_model_ids=None):
            payload = {"local_in_flight": local_in_flight, "queued_model_ids": list(queued_model_ids or [])}
            self.calls.append(payload)
            return {"switched": False, **payload}

        def ensure_local_llm_always_on(self, *, local_in_flight: int = 0):
            payload = {"local_in_flight": local_in_flight}
            self.calls.append(payload)
            return {"started": False, **payload}

        def ensure_vision_runtime_resident(self, *, local_in_flight: int = 0):
            payload = {"vision_local_in_flight": local_in_flight}
            self.calls.append(payload)
            return {"started": False, **payload}

    async def test_benchmark_v2_switches_local_models_before_timed_execution(self):
        class _LocalBenchmarkServiceManager:
            def __init__(self):
                self.calls = []

            def is_local_llm_model(self, *, model_id: str | None):
                return model_id in {"qwen3-14b-q4_k_m", "gemma-3-12b-it-q4_k_m"}

            def ensure_local_llm_model(self, *, model_id: str | None):
                self.calls.append(model_id)
                return {"model_id": model_id, "switched": True, "load_seconds": 4.25}

        class _LocalBenchmarkRuntimeManager:
            def __init__(self):
                self.execution_requests = []

            async def execute_explicit(self, request):
                self.execution_requests.append(request)
                return UnifiedExecutionResponse(
                    provider_id=str(request.requested_provider or "local"),
                    model_id=str(request.requested_model or "unknown"),
                    output_text="mock:local",
                    usage=UnifiedExecutionUsage(prompt_tokens=2, completion_tokens=4, total_tokens=6),
                    latency_ms=12.5,
                    estimated_cost=0.0,
                )

        with tempfile.TemporaryDirectory() as tmp:
            runtime_manager = _LocalBenchmarkRuntimeManager()
            service_manager = _LocalBenchmarkServiceManager()
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-test"),
                provider_runtime_manager=runtime_manager,
                service_manager=service_manager,
            )

            payload = await state.execute_benchmark_v2(
                benchmark_id="bench-local",
                prompt_id=None,
                prompt_version=None,
                task_family="task.classification",
                requested_by="mail-node",
                service_id="mail-node",
                customer_id=None,
                inputs={"text": "one email"},
                output_contract=None,
                targets=[
                    {"model": "qwen3-14b-q4_k_m"},
                    {"provider": "local", "model": "gemma-3-12b-it-q4_k_m"},
                ],
                timeout_s=60,
                trace_id="trace-local",
            )

        self.assertEqual(service_manager.calls, ["qwen3-14b-q4_k_m", "gemma-3-12b-it-q4_k_m"])
        self.assertEqual([request.requested_provider for request in runtime_manager.execution_requests], ["local", "local"])
        self.assertEqual([item["provider"] for item in payload["results"]], ["local", "local"])
        self.assertEqual(payload["results"][0]["runtime_metrics"]["load_seconds"], 4.25)
        self.assertEqual(payload["results"][0]["latency_ms"], 12.5)

    async def test_benchmark_v2_returns_busy_for_concurrent_local_model_switches(self):
        class _LocalBenchmarkServiceManager:
            def __init__(self):
                self.calls = []
                self.active_switches = 0
                self.max_active_switches = 0
                self.lock = threading.Lock()

            def is_local_llm_model(self, *, model_id: str | None):
                return model_id in {"qwen3-14b-q4_k_m", "qwen3-8b-q4_k_m"}

            def ensure_local_llm_model(self, *, model_id: str | None):
                with self.lock:
                    self.calls.append(model_id)
                    self.active_switches += 1
                    self.max_active_switches = max(self.max_active_switches, self.active_switches)
                time.sleep(0.05)
                with self.lock:
                    self.active_switches -= 1
                return {"model_id": model_id, "switched": True, "load_seconds": 0.05}

        class _LocalBenchmarkRuntimeManager:
            async def execute_explicit(self, request):
                return UnifiedExecutionResponse(
                    provider_id=str(request.requested_provider or "local"),
                    model_id=str(request.requested_model or "unknown"),
                    output_text="mock:local",
                    usage=UnifiedExecutionUsage(prompt_tokens=2, completion_tokens=4, total_tokens=6),
                    latency_ms=12.5,
                    estimated_cost=0.0,
                )

        with tempfile.TemporaryDirectory() as tmp:
            service_manager = _LocalBenchmarkServiceManager()
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-test"),
                provider_runtime_manager=_LocalBenchmarkRuntimeManager(),
                service_manager=service_manager,
            )

            async def run_benchmark(model_id: str):
                return await state.execute_benchmark_v2(
                    benchmark_id=f"bench-{model_id}",
                    prompt_id=None,
                    prompt_version=None,
                    task_family="task.classification",
                    requested_by="mail-node",
                    service_id="mail-node",
                    customer_id=None,
                    inputs={"text": "one email"},
                    output_contract=None,
                    targets=[{"model": model_id}],
                    timeout_s=60,
                    trace_id=f"trace-{model_id}",
                )

            payloads = await asyncio.gather(
                run_benchmark("qwen3-14b-q4_k_m"),
                run_benchmark("qwen3-8b-q4_k_m"),
            )

        self.assertEqual(service_manager.max_active_switches, 1)
        self.assertEqual(len(service_manager.calls), 1)
        result_statuses = [payload["results"][0]["status"] for payload in payloads]
        error_codes = [
            payload["results"][0]["error"]["code"]
            for payload in payloads
            if payload["results"][0].get("error")
        ]
        self.assertEqual(sorted(result_statuses), ["completed", "failed"])
        self.assertEqual(error_codes, ["local_llm_busy"])

    async def test_unhealthy_operational_mqtt_transitions_to_degraded_and_schedules_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-test"))
            lifecycle.transition_to(NodeLifecycleState.TRUSTED)
            lifecycle.transition_to(NodeLifecycleState.CAPABILITY_SETUP_PENDING)
            lifecycle.transition_to(NodeLifecycleState.CAPABILITY_DECLARATION_IN_PROGRESS)
            lifecycle.transition_to(NodeLifecycleState.CAPABILITY_DECLARATION_ACCEPTED)
            lifecycle.transition_to(NodeLifecycleState.OPERATIONAL)
            capability_runner = self._FakeCapabilityRunner(healthy=False, error="connection_refused")
            service_manager = self._FakeServiceManager()
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-test"),
                capability_runner=capability_runner,
                service_manager=service_manager,
                mqtt_recovery_store=OperationalMqttRecoveryStore(
                    path=str(Path(tmp) / "operational_mqtt_recovery.json"),
                    logger=logging.getLogger("node-control-test"),
                ),
                operational_mqtt_health_check_interval_seconds=10,
                operational_mqtt_restart_delay_seconds=1,
                operational_mqtt_restart_max_attempts=3,
            )

            result = await state.check_operational_mqtt_health_once()

            self.assertEqual(lifecycle.get_state(), NodeLifecycleState.DEGRADED)
            self.assertTrue(result["restart_scheduled"])
            self.assertEqual(len(service_manager.calls), 1)
            self.assertEqual(capability_runner.unhealthy_calls[-1], "connection_refused")
            self.assertEqual(state.operational_mqtt_recovery_payload()["attempt_count"], 1)
            self.assertEqual(
                state.internal_scheduler_payload()["tasks"]["operational_mqtt_health"]["schedule_name"],
                "every_10_seconds",
            )

    async def test_unhealthy_operational_mqtt_stops_after_third_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-test"))
            lifecycle.transition_to(NodeLifecycleState.TRUSTED)
            lifecycle.transition_to(NodeLifecycleState.CAPABILITY_SETUP_PENDING)
            lifecycle.transition_to(NodeLifecycleState.CAPABILITY_DECLARATION_IN_PROGRESS)
            lifecycle.transition_to(NodeLifecycleState.CAPABILITY_DECLARATION_ACCEPTED)
            lifecycle.transition_to(NodeLifecycleState.OPERATIONAL)
            capability_runner = self._FakeCapabilityRunner(healthy=False, error="connection_refused")
            service_manager = self._FakeServiceManager()
            recovery_store = OperationalMqttRecoveryStore(
                path=str(Path(tmp) / "operational_mqtt_recovery.json"),
                logger=logging.getLogger("node-control-test"),
            )
            recovery_store.mark_exhausted(error="connection_refused", max_attempts=3)
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-test"),
                capability_runner=capability_runner,
                service_manager=service_manager,
                mqtt_recovery_store=recovery_store,
                operational_mqtt_health_check_interval_seconds=10,
                operational_mqtt_restart_delay_seconds=1,
                operational_mqtt_restart_max_attempts=3,
            )

            result = await state.check_operational_mqtt_health_once()

            self.assertEqual(result["reason"], "restart_attempts_exhausted")
            self.assertFalse(result["restart_scheduled"])
            self.assertEqual(len(service_manager.calls), 0)
            self.assertTrue(state.operational_mqtt_recovery_payload()["exhausted"])

    async def test_healthy_operational_mqtt_clears_recovery_cycle_and_recovers_degraded_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-test"))
            lifecycle.transition_to(NodeLifecycleState.TRUSTED)
            lifecycle.transition_to(NodeLifecycleState.CAPABILITY_SETUP_PENDING)
            lifecycle.transition_to(NodeLifecycleState.CAPABILITY_DECLARATION_IN_PROGRESS)
            lifecycle.transition_to(NodeLifecycleState.CAPABILITY_DECLARATION_ACCEPTED)
            lifecycle.transition_to(NodeLifecycleState.OPERATIONAL)
            lifecycle.transition_to(NodeLifecycleState.DEGRADED)
            capability_runner = self._FakeCapabilityRunner(healthy=True)
            recovery_store = OperationalMqttRecoveryStore(
                path=str(Path(tmp) / "operational_mqtt_recovery.json"),
                logger=logging.getLogger("node-control-test"),
            )
            recovery_store.record_restart_requested(error="connection_refused", delay_seconds=1, max_attempts=3)
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-test"),
                capability_runner=capability_runner,
                service_manager=self._FakeServiceManager(),
                mqtt_recovery_store=recovery_store,
                operational_mqtt_health_check_interval_seconds=10,
                operational_mqtt_restart_delay_seconds=1,
                operational_mqtt_restart_max_attempts=3,
            )

            result = await state.check_operational_mqtt_health_once()

            self.assertEqual(result["status"], "healthy")
            self.assertEqual(capability_runner.recover_calls, 1)
            self.assertFalse(state.operational_mqtt_recovery_payload()["active"])

    async def test_operational_mqtt_health_uses_every_5_minutes_when_stably_operational(self):
        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-test"))
            lifecycle.transition_to(NodeLifecycleState.TRUSTED)
            lifecycle.transition_to(NodeLifecycleState.CAPABILITY_SETUP_PENDING)
            lifecycle.transition_to(NodeLifecycleState.CAPABILITY_DECLARATION_IN_PROGRESS)
            lifecycle.transition_to(NodeLifecycleState.CAPABILITY_DECLARATION_ACCEPTED)
            lifecycle.transition_to(NodeLifecycleState.OPERATIONAL)
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-test"),
                capability_runner=self._FakeCapabilityRunner(healthy=True),
                service_manager=self._FakeServiceManager(),
                mqtt_recovery_store=OperationalMqttRecoveryStore(
                    path=str(Path(tmp) / "operational_mqtt_recovery.json"),
                    logger=logging.getLogger("node-control-test"),
                ),
                operational_mqtt_health_check_interval_seconds=10,
                operational_mqtt_health_normal_interval_seconds=300,
                operational_mqtt_health_fast_window_seconds=0,
            )

            payload = state.internal_scheduler_payload()

            self.assertEqual(payload["tasks"]["operational_mqtt_health"]["schedule_name"], "every_5_minutes")
            self.assertEqual(payload["tasks"]["operational_mqtt_health"]["interval_seconds"], 300)

    async def test_local_llm_default_revert_scheduler_task_is_registered(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-test"),
                capability_runner=self._FakeCapabilityRunner(healthy=True),
                service_manager=self._FakeServiceManager(),
            )

            payload = state.internal_scheduler_payload()

            self.assertIn("local_llm_default_revert", payload["tasks"])
            self.assertEqual(payload["tasks"]["local_llm_default_revert"]["schedule_name"], "interval_seconds")
            self.assertIn("local_llm_always_on", payload["tasks"])
            self.assertEqual(payload["tasks"]["local_llm_always_on"]["schedule_name"], "interval_seconds")
            self.assertIn("vision_runtime_residency", payload["tasks"])
            self.assertEqual(payload["tasks"]["vision_runtime_residency"]["schedule_name"], "interval_seconds")

    async def test_local_llm_default_revert_job_calls_service_manager(self):
        with tempfile.TemporaryDirectory() as tmp:
            service_manager = self._FakeServiceManager()
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-test"),
                capability_runner=self._FakeCapabilityRunner(healthy=True),
                service_manager=service_manager,
            )

            result = await state._local_llm_default_revert_job_once()

            self.assertEqual(result["status"], "ok")
            self.assertEqual(service_manager.calls[-1]["local_in_flight"], 0)

    async def test_local_llm_default_revert_job_waits_while_model_switch_lock_is_held(self):
        with tempfile.TemporaryDirectory() as tmp:
            service_manager = self._FakeServiceManager()
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-test"),
                capability_runner=self._FakeCapabilityRunner(healthy=True),
                service_manager=service_manager,
            )
            await state._local_llm_switch_lock.acquire()
            try:
                result = await state._local_llm_default_revert_job_once()
            finally:
                state._local_llm_switch_lock.release()

            self.assertEqual(result["status"], "ok")
            self.assertEqual(service_manager.calls[-1]["local_in_flight"], 1)

    async def test_local_llm_always_on_job_calls_service_manager(self):
        with tempfile.TemporaryDirectory() as tmp:
            service_manager = self._FakeServiceManager()
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-test"),
                capability_runner=self._FakeCapabilityRunner(healthy=True),
                service_manager=service_manager,
            )

            result = await state._local_llm_always_on_job_once()

            self.assertEqual(result["status"], "ok")
            self.assertEqual(service_manager.calls[-1]["local_in_flight"], 0)

    async def test_local_llm_always_on_job_waits_while_model_switch_lock_is_held(self):
        with tempfile.TemporaryDirectory() as tmp:
            service_manager = self._FakeServiceManager()
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-test"),
                capability_runner=self._FakeCapabilityRunner(healthy=True),
                service_manager=service_manager,
            )
            await state._local_llm_switch_lock.acquire()
            try:
                result = await state._local_llm_always_on_job_once()
            finally:
                state._local_llm_switch_lock.release()

            self.assertEqual(result["status"], "ok")
            self.assertEqual(service_manager.calls[-1]["local_in_flight"], 1)

    async def test_vision_runtime_residency_job_calls_service_manager(self):
        with tempfile.TemporaryDirectory() as tmp:
            service_manager = self._FakeServiceManager()
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-test"),
                capability_runner=self._FakeCapabilityRunner(healthy=True),
                service_manager=service_manager,
            )

            result = await state._vision_runtime_residency_job_once()

            self.assertEqual(result["status"], "ok")
            self.assertEqual(service_manager.calls[-1]["vision_local_in_flight"], 0)

    async def test_vision_runtime_residency_job_waits_while_model_switch_lock_is_held(self):
        with tempfile.TemporaryDirectory() as tmp:
            service_manager = self._FakeServiceManager()
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-test"),
                capability_runner=self._FakeCapabilityRunner(healthy=True),
                service_manager=service_manager,
            )
            await state._local_llm_switch_lock.acquire()
            try:
                result = await state._vision_runtime_residency_job_once()
            finally:
                state._local_llm_switch_lock.release()

            self.assertEqual(result["status"], "ok")
            self.assertEqual(service_manager.calls[-1]["vision_local_in_flight"], 1)

    async def test_operational_mqtt_health_uses_fast_interval_for_five_minutes_after_startup(self):
        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-test"))
            lifecycle.transition_to(NodeLifecycleState.TRUSTED)
            lifecycle.transition_to(NodeLifecycleState.CAPABILITY_SETUP_PENDING)
            lifecycle.transition_to(NodeLifecycleState.CAPABILITY_DECLARATION_IN_PROGRESS)
            lifecycle.transition_to(NodeLifecycleState.CAPABILITY_DECLARATION_ACCEPTED)
            lifecycle.transition_to(NodeLifecycleState.OPERATIONAL)
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-test"),
                capability_runner=self._FakeCapabilityRunner(healthy=True),
                service_manager=self._FakeServiceManager(),
                mqtt_recovery_store=OperationalMqttRecoveryStore(
                    path=str(Path(tmp) / "operational_mqtt_recovery.json"),
                    logger=logging.getLogger("node-control-test"),
                ),
                operational_mqtt_health_check_interval_seconds=10,
                operational_mqtt_health_normal_interval_seconds=300,
                operational_mqtt_health_fast_window_seconds=300,
            )

            payload = state.internal_scheduler_payload()

            self.assertEqual(payload["tasks"]["operational_mqtt_health"]["schedule_name"], "every_10_seconds")
            self.assertEqual(payload["tasks"]["operational_mqtt_health"]["interval_seconds"], 10)

    async def test_operational_mqtt_health_switches_back_to_fast_interval_during_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-test"))
            lifecycle.transition_to(NodeLifecycleState.TRUSTED)
            lifecycle.transition_to(NodeLifecycleState.CAPABILITY_SETUP_PENDING)
            lifecycle.transition_to(NodeLifecycleState.CAPABILITY_DECLARATION_IN_PROGRESS)
            lifecycle.transition_to(NodeLifecycleState.CAPABILITY_DECLARATION_ACCEPTED)
            lifecycle.transition_to(NodeLifecycleState.OPERATIONAL)
            recovery_store = OperationalMqttRecoveryStore(
                path=str(Path(tmp) / "operational_mqtt_recovery.json"),
                logger=logging.getLogger("node-control-test"),
            )
            recovery_store.record_restart_requested(error="connection_refused", delay_seconds=1, max_attempts=3)
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-test"),
                capability_runner=self._FakeCapabilityRunner(healthy=True),
                service_manager=self._FakeServiceManager(),
                mqtt_recovery_store=recovery_store,
                operational_mqtt_health_check_interval_seconds=10,
                operational_mqtt_health_normal_interval_seconds=300,
            )

            payload = state.internal_scheduler_payload()

            self.assertEqual(payload["tasks"]["operational_mqtt_health"]["schedule_name"], "every_10_seconds")
            self.assertEqual(payload["tasks"]["operational_mqtt_health"]["interval_seconds"], 10)

    async def test_operational_mqtt_health_keeps_fast_interval_after_recovery_to_operational(self):
        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-test"))
            lifecycle.transition_to(NodeLifecycleState.TRUSTED)
            lifecycle.transition_to(NodeLifecycleState.CAPABILITY_SETUP_PENDING)
            lifecycle.transition_to(NodeLifecycleState.CAPABILITY_DECLARATION_IN_PROGRESS)
            lifecycle.transition_to(NodeLifecycleState.CAPABILITY_DECLARATION_ACCEPTED)
            lifecycle.transition_to(NodeLifecycleState.OPERATIONAL)
            lifecycle.transition_to(NodeLifecycleState.DEGRADED)
            class _RecoveryCapabilityRunner(self._FakeCapabilityRunner):
                def recover_from_degraded(self_inner):
                    self_inner.recover_calls += 1
                    lifecycle.transition_to(NodeLifecycleState.OPERATIONAL)
                    return {"target_state": NodeLifecycleState.OPERATIONAL.value}

            recovery_store = OperationalMqttRecoveryStore(
                path=str(Path(tmp) / "operational_mqtt_recovery.json"),
                logger=logging.getLogger("node-control-test"),
            )
            recovery_store.record_restart_requested(error="connection_refused", delay_seconds=1, max_attempts=3)
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-test"),
                capability_runner=_RecoveryCapabilityRunner(healthy=True),
                service_manager=self._FakeServiceManager(),
                mqtt_recovery_store=recovery_store,
                operational_mqtt_health_check_interval_seconds=10,
                operational_mqtt_health_normal_interval_seconds=300,
                operational_mqtt_health_fast_window_seconds=300,
            )

            result = await state.check_operational_mqtt_health_once()
            payload = state.internal_scheduler_payload()

            self.assertEqual(result["status"], "healthy")
            self.assertEqual(lifecycle.get_state(), NodeLifecycleState.OPERATIONAL)
            self.assertEqual(payload["tasks"]["operational_mqtt_health"]["schedule_name"], "every_10_seconds")
            self.assertEqual(payload["tasks"]["operational_mqtt_health"]["interval_seconds"], 10)


if __name__ == "__main__":
    unittest.main()
