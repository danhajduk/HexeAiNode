import asyncio
import base64
import json
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
from ai_node.persistence.image_generation_template_store import ImageGenerationTemplateStateStore
from ai_node.runtime.node_control_api import (
    AvatarBodyDepthProfileGenerateRequest,
    AvatarFaceProfileExtractRequest,
    AvatarPrimaryFaceRequest,
    AvatarProfileExtractionUpdateRequest,
    AvatarProfileReferenceUploadRequest,
    AvatarProfileSaveRequest,
    DirectExecutionAdmissionConfig,
    DirectExecutionAdmissionGuard,
    DirectExecutionBusyError,
    ManualImageGenerationRequest,
    ManualImagePoseHelperRequest,
    ManualImagePromptHelperRequest,
    ManualImageReferenceUploadRequest,
    ManualImageVisionDescribeRequest,
    NodeControlState,
)
from ai_node.runtime.execution_queue import ExecutionQueueService
from ai_node.runtime.operational_mqtt_recovery_store import OperationalMqttRecoveryStore
from ai_node.runtime.service_manager import UserSystemdServiceManager


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
                provider_runtime_manager = self._FakeProviderRuntimeManager()
                provider_runtime_manager._resolved_tasks = ["task.image_generation"]
                state = NodeControlState(
                    lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-test")),
                    config_path=str(Path(tmp) / "bootstrap_config.json"),
                    logger=logging.getLogger("node-control-test"),
                    provider_runtime_manager=provider_runtime_manager,
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
                self.assertEqual(preview["local_runtime_assignment"]["runtime_id"], "comfyui_cpu")
                self.assertEqual(preview["local_runtime_assignment"]["checkpoint"], "DreamShaper8_LCM.safetensors")

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
                self.assertEqual(preview["local_runtime_assignment"]["runtime_id"], "comfyui_gpu")
                self.assertEqual(preview["local_runtime_assignment"]["checkpoint"], "RealVisXL_V5.0_fp16.safetensors")
                self.assertEqual(preview["local_runtime_assignment"]["lora"], "sdxl_lightning_4step_lora.safetensors")

        asyncio.run(run_scenario())

    def test_image_generation_prompt_resolves_registered_comfyui_template(self):
        async def run_scenario():
            with tempfile.TemporaryDirectory() as tmp:
                provider_runtime_manager = self._FakeProviderRuntimeManager()
                provider_runtime_manager._resolved_tasks = ["task.image_generation"]
                state = NodeControlState(
                    lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-test")),
                    config_path=str(Path(tmp) / "bootstrap_config.json"),
                    logger=logging.getLogger("node-control-test"),
                    provider_runtime_manager=provider_runtime_manager,
                    prompt_service_state_store=self._FakePromptServiceStateStore(),
                    image_generation_template_state_store=ImageGenerationTemplateStateStore(
                        path=str(Path(tmp) / "image_generation_template_state.json"),
                        logger=logging.getLogger("node-control-test"),
                    ),
                    comfyui_template_catalog_dir="config/comfyui/templates",
                    direct_execution_admission_config=DirectExecutionAdmissionConfig(enabled=False),
                )
                state.register_image_generation_template(
                    template_id="template.avatar_body_depth_reference_transparent.realvisxl.v1",
                    service_id="service.alpha",
                    version="v1",
                    template_version={
                        "runtime_id": "comfyui_gpu",
                        "api_workflow_path": "config/comfyui/templates/avatar-body-depth-reference-transparent-realvisxl/api_workflow.json",
                        "ui_workflow_path": "config/comfyui/templates/avatar-body-depth-reference-transparent-realvisxl/ui_workflow.json",
                        "variables": [
                            "positive_prompt",
                            "face_reference_image",
                            "body_reference_image",
                            "negative_prompt",
                            "width",
                            "height",
                            "seed",
                        ],
                        "defaults": {
                            "negative_prompt": "low quality",
                            "width": 768,
                            "height": 1152,
                            "seed": 42,
                        },
                    },
                )
                state.register_prompt_service(
                    prompt_id="prompt.avatar.image",
                    service_id="service.alpha",
                    task_family="task.image_generation",
                    version="v3.0",
                    definition={
                        "prompt_template": "{{pose}} in {{wardrobe}}, isolated full body avatar reference",
                        "template_variables": ["pose", "wardrobe"],
                    },
                    constraints={
                        "routing_policy": {"mode": "local_only"},
                        "image_template": {
                            "template_id": "template.avatar_body_depth_reference_transparent.realvisxl.v1",
                            "template_version": "v1",
                            "template_runtime": "comfyui_gpu",
                            "allowed_parameter_overrides": ["seed"],
                        },
                    },
                )

                request = TaskExecutionRequest.model_validate(
                    {
                        "task_id": "task-avatar-image-001",
                        "prompt_id": "prompt.avatar.image",
                        "prompt_version": "v3.0",
                        "task_family": "task.image_generation",
                        "requested_by": "service.alpha",
                        "inputs": {
                            "pose": "standing three-quarter pose",
                            "wardrobe": "black lingerie",
                            "face_reference_image": "references/avatar/jane_face.png",
                            "body_reference_image": "references/avatar/jane_body.png",
                            "seed": 7,
                        },
                        "response_mode": "async_if_queued",
                        "priority": "normal",
                        "trace_id": "trace-avatar-image-001",
                    }
                )

                preview = await state.preview_direct_execution_route(request=request)
                resolved = preview["effective_request"]["constraints"]["image_template_resolved"]
                self.assertEqual(resolved["template_id"], "template.avatar_body_depth_reference_transparent.realvisxl.v1")
                self.assertEqual(resolved["template_version"], "v1")
                self.assertEqual(resolved["template_runtime"], "comfyui_gpu")
                self.assertEqual(resolved["output_folder_policy"], "operational")
                self.assertEqual(resolved["variables"]["seed"], 7)
                self.assertIn(
                    "standing three-quarter pose in black lingerie",
                    preview["effective_request"]["constraints"]["image_template_resolved"]["variables"]["positive_prompt"],
                )

                sync_result = await state.execute_direct(
                    request=request.model_copy(update={"task_id": "task-avatar-image-sync-001", "response_mode": "sync"}, deep=True)
                )
                self.assertEqual(sync_result["status"], "degraded")
                self.assertEqual(
                    sync_result["resolution_metadata"]["image_template"]["template_id"],
                    "template.avatar_body_depth_reference_transparent.realvisxl.v1",
                )
                self.assertEqual(
                    sync_result["resolution_metadata"]["image_template"]["output_folder_policy"],
                    "operational",
                )

                queued = await state.execute_direct(request=request)
                self.assertEqual(queued["status"], "queued")
                status = await state.execution_job_status(job_id=queued["job_id"])
                effective_request = status["request"]
                queued_template = effective_request["constraints"]["image_template_resolved"]
                self.assertEqual(queued_template["template_id"], "template.avatar_body_depth_reference_transparent.realvisxl.v1")
                workflow = effective_request["inputs"]["comfyui_workflow"]
                self.assertEqual(workflow["14"]["inputs"]["seed"], 7)
                self.assertEqual(workflow["3"]["inputs"]["width"], 768)
                self.assertEqual(workflow["3"]["inputs"]["height"], 1152)
                self.assertEqual(workflow["6"]["inputs"]["image"], "references/avatar/jane_face.png")
                self.assertEqual(workflow["10"]["inputs"]["image"], "references/avatar/jane_body.png")
                self.assertIn("standing three-quarter pose in black lingerie", workflow["4"]["inputs"]["text"])

        asyncio.run(run_scenario())

    def test_local_runtime_assignment_payload_maps_text_vision_and_image_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-test"),
                provider_runtime_manager=self._FakeProviderRuntimeManager(),
                capability_runner=self._FakeCapabilityRunner(),
            )

            text = state.local_runtime_assignment_payload(task_family="task.classification")
            vision = state.local_runtime_assignment_payload(task_family="task.vision_analysis")
            gpu_image = state.local_runtime_assignment_payload(task_family="task.image_generation", priority="high")
            cpu_image = state.local_runtime_assignment_payload(task_family="task.image_generation", priority="low")
            catalog = state.local_runtime_assignments_payload()

            self.assertEqual(text["runtime_id"], "local_text_llm")
            self.assertEqual(text["model_id"], "qwen3-8b-q4_k_m")
            self.assertEqual(vision["runtime_id"], "local_vision_llm")
            self.assertEqual(vision["model_id"], "qwen2.5-vl-3b-instruct-q4_k_m")
            self.assertEqual(gpu_image["runtime_id"], "comfyui_gpu")
            self.assertEqual(gpu_image["queue"], "local")
            self.assertEqual(cpu_image["runtime_id"], "comfyui_cpu")
            self.assertEqual(cpu_image["queue"], "cpu_comfyui")
            self.assertGreaterEqual(len(catalog["assignments"]), 10)

    def test_vision_route_preview_includes_local_vision_runtime_assignment(self):
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
                            "task_id": "task-vision-001",
                            "task_family": "task.vision_analysis",
                            "requested_by": "service.alpha",
                            "requested_provider": "local",
                            "inputs": {"image": "sample.jpg", "prompt": "describe it"},
                            "response_mode": "async_if_queued",
                            "priority": "normal",
                            "trace_id": "trace-vision-001",
                        }
                    )
                )

                self.assertEqual(preview["local_runtime_assignment"]["runtime_id"], "local_vision_llm")
                self.assertEqual(preview["local_runtime_assignment"]["model_id"], "qwen2.5-vl-3b-instruct-q4_k_m")
                self.assertEqual(preview["local_runtime_assignment"]["queue"], "local")

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

    def test_comfyui_progress_state_uses_cached_websocket_progress(self):
        service_manager = UserSystemdServiceManager(logger=logging.getLogger("node-control-test"))
        with service_manager._comfyui_progress_lock:
            service_manager._comfyui_progress_cache = {
                "value": 3,
                "max": 10,
                "prompt_id": "prompt-progress",
                "node": "8",
                "updated_at_epoch": 123.456,
            }

        progress = service_manager._comfyui_progress_state()

        self.assertTrue(progress["available"])
        self.assertTrue(progress["active"])
        self.assertEqual(progress["value"], 3)
        self.assertEqual(progress["max"], 10)
        self.assertEqual(progress["percent"], 30.0)
        self.assertEqual(progress["prompt_id"], "prompt-progress")
        self.assertEqual(progress["node"], "8")


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

        def ensure_vision_runtime_resident(
            self,
            *,
            local_in_flight: int = 0,
            gpu_comfyui_critical_in_flight: bool = False,
        ):
            payload = {
                "vision_local_in_flight": local_in_flight,
                "gpu_comfyui_critical_in_flight": bool(gpu_comfyui_critical_in_flight),
            }
            self.calls.append(payload)
            return {"started": False, **payload}

        def close_comfyui_webui_if_idle(self):
            payload = {"comfyui_webui_idle_close": True}
            self.calls.append(payload)
            return {"closed": False, "reason": "manual_session_inactive"}

    def test_manual_image_generation_status_includes_relevant_runtime_progress(self):
        class _ManualImageServiceManager:
            def get_status(self):
                return {
                    "comfyui_gpu": {"state": "running"},
                    "comfyui_webui": {
                        "state": "running",
                        "runtime": "gpu",
                        "manual_paths": {"output_dir": "runtime/manual/comfyui-gpu/output"},
                    },
                }

            def comfyui_webui_generation_status(self):
                return {
                    "runtime": "gpu",
                    "session": {
                        "state": "active",
                        "queue_available": True,
                        "queue_active": True,
                        "running_count": 1,
                        "pending_count": 0,
                        "running_prompt_id": "prompt-running",
                    },
                    "progress": {"available": True, "percent": 50.0, "prompt_id": "prompt-running"},
                }

        with tempfile.TemporaryDirectory() as tmp:
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-api-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-api-test"),
                service_manager=_ManualImageServiceManager(),
            )

            payload = state.manual_image_generation_status()

        self.assertEqual(payload["runtime_service"]["state"], "running")
        self.assertEqual(payload["generation_status"]["session"]["running_prompt_id"], "prompt-running")
        self.assertEqual(payload["generation_status"]["progress"]["percent"], 50.0)

    def test_manual_image_generation_status_only_exposes_active_manual_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-api-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-api-test"),
                comfyui_template_catalog_dir="config/comfyui/templates",
            )

            payload = state.manual_image_generation_status()

        self.assertEqual(
            [item["template_id"] for item in payload["templates"]],
            [
                "template.avatar_body_depth_reference_transparent.realvisxl.v1",
                "template.avatar_profile_depth_pulid.realvisxl.v1",
            ],
        )

    def test_manual_image_generation_status_reports_latest_job_completion(self):
        class _ManualImageServiceManager:
            def get_status(self):
                return {
                    "comfyui_gpu": {"state": "running"},
                    "comfyui_webui": {
                        "state": "running",
                        "runtime": "gpu",
                        "manual_paths": {"output_dir": "runtime/manual/comfyui-gpu/output"},
                    },
                }

            def comfyui_webui_generation_status(self):
                return {
                    "runtime": "gpu",
                    "session": {"queue_active": False, "running_count": 0, "pending_count": 0},
                    "progress": {"available": False},
                }

        with tempfile.TemporaryDirectory() as tmp:
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-api-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-api-test"),
                service_manager=_ManualImageServiceManager(),
            )
            state._write_manual_image_latest_job(
                {
                    "status": "submitted",
                    "prompt_id": "prompt-done",
                    "submitted_at": "2026-06-09T12:00:00+00:00",
                    "output_count_before": 0,
                }
            )
            with patch.object(
                state,
                "_manual_image_outputs",
                return_value=[
                    {
                        "relative_path": "hexe/avatar_body_depth_transparent/Jane_seed123_00001_.png",
                        "filename": "Jane_seed123_00001_.png",
                        "modified_at": "2026-06-09T12:00:05+00:00",
                    }
                ],
            ):
                payload = state.manual_image_generation_status()

        self.assertEqual(payload["latest_job"]["prompt_id"], "prompt-done")
        self.assertEqual(payload["latest_job"]["status"], "completed")
        self.assertEqual(payload["latest_job"]["completed_output_count"], 1)

    def test_manual_image_generation_completion_overrides_stale_progress_prompt(self):
        class _ManualImageServiceManager:
            def get_status(self):
                return {
                    "comfyui_gpu": {"state": "running"},
                    "comfyui_webui": {
                        "state": "running",
                        "runtime": "gpu",
                        "manual_paths": {"output_dir": "runtime/manual/comfyui-gpu/output"},
                    },
                }

            def comfyui_webui_generation_status(self):
                return {
                    "runtime": "gpu",
                    "session": {"queue_active": False, "running_count": 0, "pending_count": 0},
                    "progress": {
                        "available": True,
                        "active": True,
                        "value": 20,
                        "max": 20,
                        "percent": 100.0,
                        "prompt_id": "prompt-stale",
                    },
                }

        with tempfile.TemporaryDirectory() as tmp:
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-api-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-api-test"),
                service_manager=_ManualImageServiceManager(),
            )
            state._write_manual_image_latest_job(
                {
                    "status": "running",
                    "prompt_id": "prompt-done",
                    "submitted_at": "2026-06-09T12:00:00+00:00",
                    "output_count_before": 0,
                }
            )
            with patch.object(
                state,
                "_manual_image_outputs",
                return_value=[
                    {
                        "relative_path": "hexe/avatar_body_depth_transparent/Jane_seed123_00001_.png",
                        "filename": "Jane_seed123_00001_.png",
                        "modified_at": "2026-06-09T12:00:05+00:00",
                    }
                ],
            ):
                payload = state.manual_image_generation_status()

        self.assertEqual(payload["latest_job"]["status"], "completed")
        self.assertEqual(payload["latest_job"]["progress"]["percent"], 100.0)

    def test_manual_image_generation_completion_ignores_idle_same_prompt_progress(self):
        class _ManualImageServiceManager:
            def get_status(self):
                return {
                    "comfyui_gpu": {"state": "running"},
                    "comfyui_webui": {
                        "state": "running",
                        "runtime": "gpu",
                        "manual_paths": {"output_dir": "runtime/manual/comfyui-gpu/output"},
                    },
                }

            def comfyui_webui_generation_status(self):
                return {
                    "runtime": "gpu",
                    "session": {"queue_active": False, "running_count": 0, "pending_count": 0},
                    "progress": {
                        "available": True,
                        "active": True,
                        "value": 8,
                        "max": 8,
                        "percent": 100.0,
                        "prompt_id": "prompt-done",
                        "node": "14",
                    },
                }

        with tempfile.TemporaryDirectory() as tmp:
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-api-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-api-test"),
                service_manager=_ManualImageServiceManager(),
                comfyui_template_catalog_dir="config/comfyui/templates",
            )
            state._write_manual_image_latest_job(
                {
                    "status": "running",
                    "template_id": "template.avatar_body_depth_reference_transparent.realvisxl.v1",
                    "prompt_id": "prompt-done",
                    "prompt_ids": ["prompt-done"],
                    "submitted_at": "2026-06-09T12:00:00+00:00",
                    "output_count_before": 0,
                }
            )
            with patch.object(
                state,
                "_manual_image_outputs",
                return_value=[
                    {
                        "relative_path": "hexe/avatar_body_depth_transparent/Jane_seed123_00001_.png",
                        "filename": "Jane_seed123_00001_.png",
                        "modified_at": "2026-06-09T12:00:05+00:00",
                    }
                ],
            ):
                payload = state.manual_image_generation_status()

        self.assertEqual(payload["latest_job"]["status"], "completed")
        self.assertEqual(payload["latest_job"]["progress_detail"]["phase"], "completed")
        self.assertEqual(payload["latest_job"]["progress_detail"]["percent"], 100.0)

    def test_manual_image_generation_status_tracks_batch_prompt_ids(self):
        class _ManualImageServiceManager:
            def __init__(self, output_dir: str):
                self.output_dir = output_dir

            def get_status(self):
                return {
                    "comfyui_gpu": {"state": "running"},
                    "comfyui_webui": {
                        "state": "running",
                        "runtime": "gpu",
                        "manual_paths": {"output_dir": self.output_dir},
                    },
                }

            def comfyui_webui_generation_status(self):
                return {
                    "runtime": "gpu",
                    "session": {
                        "queue_active": True,
                        "running_count": 1,
                        "pending_count": 1,
                        "running_prompt_id": "prompt-batch-2",
                        "pending_prompt_ids": ["prompt-batch-3"],
                    },
                    "progress": {"available": True, "percent": 25.0, "prompt_id": "prompt-batch-2"},
                }

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "manual-output"
            output_dir.mkdir()
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-api-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-api-test"),
                service_manager=_ManualImageServiceManager(str(output_dir)),
            )
            state._write_manual_image_latest_job(
                {
                    "status": "submitted",
                    "template_id": "template.avatar_body_depth_reference_transparent.realvisxl.v1",
                    "prompt_id": "prompt-batch-1",
                    "prompt_ids": ["prompt-batch-1", "prompt-batch-2", "prompt-batch-3"],
                    "batch_count": 3,
                    "submitted_at": "2000-01-01T00:00:00+00:00",
                    "output_count_before": 0,
                }
            )

            payload = state.manual_image_generation_status()

        self.assertEqual(payload["latest_job"]["status"], "running")
        self.assertEqual(payload["latest_job"]["running_count"], 1)
        self.assertEqual(payload["latest_job"]["pending_count"], 1)

    def test_manual_image_generation_status_includes_detailed_progress_node(self):
        class _ManualImageServiceManager:
            def get_status(self):
                return {
                    "comfyui_gpu": {
                        "state": "running",
                        "pid": 123,
                        "restart_count": 0,
                        "started_at": "2026-06-09T11:50:00+00:00",
                    },
                    "comfyui_webui": {
                        "state": "running",
                        "runtime": "gpu",
                        "manual_paths": {"output_dir": "runtime/manual/comfyui-gpu/output"},
                    },
                }

            def comfyui_webui_generation_status(self):
                return {
                    "runtime": "gpu",
                    "session": {
                        "queue_active": True,
                        "running_count": 1,
                        "pending_count": 0,
                        "running_prompt_id": "prompt-detail",
                    },
                    "progress": {
                        "available": True,
                        "active": True,
                        "value": 1,
                        "max": 1,
                        "percent": 100.0,
                        "prompt_id": "prompt-detail",
                        "node": "25",
                        "updated_at_epoch": 1781049600.0,
                    },
                }

        with tempfile.TemporaryDirectory() as tmp:
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-api-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-api-test"),
                service_manager=_ManualImageServiceManager(),
                comfyui_template_catalog_dir="config/comfyui/templates",
            )
            state._write_manual_image_latest_job(
                {
                    "status": "running",
                    "template_id": "template.avatar_body_depth_reference_transparent.realvisxl.v1",
                    "prompt_id": "prompt-detail",
                    "prompt_ids": ["prompt-detail"],
                    "submitted_at": "2026-06-09T12:00:00+00:00",
                    "runtime_pid": 123,
                    "runtime_restart_count": 0,
                }
            )

            payload = state.manual_image_generation_status()

        detail = payload["latest_job"]["progress_detail"]
        self.assertEqual(detail["phase"], "body")
        self.assertEqual(detail["label"], "Build body depth map")
        self.assertEqual(detail["node_id"], "25")
        self.assertEqual(detail["node_class"], "DepthAnythingV2Preprocessor")
        self.assertEqual(payload["generation_status"]["progress_detail"]["label"], "Build body depth map")

    def test_manual_image_generation_marks_runtime_oom_restart_as_failed(self):
        class _ManualImageServiceManager:
            def get_status(self):
                return {
                    "comfyui_gpu": {
                        "state": "running",
                        "pid": 222,
                        "restart_count": 2,
                        "last_oom_killed": True,
                        "started_at": "2026-06-09T12:00:30+00:00",
                    },
                    "comfyui_webui": {
                        "state": "running",
                        "runtime": "gpu",
                        "manual_paths": {"output_dir": "runtime/manual/comfyui-gpu/output"},
                    },
                }

            def comfyui_webui_generation_status(self):
                return {
                    "runtime": "gpu",
                    "session": {"queue_active": False, "running_count": 0, "pending_count": 0},
                    "progress": {"available": False},
                }

        with tempfile.TemporaryDirectory() as tmp:
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-api-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-api-test"),
                service_manager=_ManualImageServiceManager(),
            )
            state._write_manual_image_latest_job(
                {
                    "status": "running",
                    "template_id": "template.avatar_body_depth_reference_transparent.realvisxl.v1",
                    "prompt_id": "prompt-oom",
                    "prompt_ids": ["prompt-oom"],
                    "submitted_at": "2026-06-09T12:00:00+00:00",
                    "runtime_pid": 111,
                    "runtime_restart_count": 1,
                }
            )

            with patch.object(state, "_manual_image_outputs", return_value=[]):
                payload = state.manual_image_generation_status()

        latest_job = payload["latest_job"]
        self.assertEqual(latest_job["status"], "failed")
        self.assertEqual(latest_job["failure"]["reason"], "comfyui_runtime_oom")
        self.assertEqual(latest_job["progress_detail"]["phase"], "failed")
        self.assertEqual(latest_job["progress_detail"]["failure_reason"], "comfyui_runtime_oom")
        self.assertIn("out-of-memory", latest_job["progress_detail"]["message"])

    def test_manual_image_generation_marks_background_removal_rgb_fallback(self):
        class _ManualImageServiceManager:
            def get_status(self):
                return {
                    "comfyui_gpu": {"state": "running"},
                    "comfyui_webui": {
                        "state": "running",
                        "runtime": "gpu",
                        "manual_paths": {"output_dir": "runtime/manual/comfyui-gpu/output"},
                    },
                }

            def comfyui_webui_generation_status(self):
                return {
                    "runtime": "gpu",
                    "session": {"queue_active": False, "running_count": 0, "pending_count": 0},
                    "progress": {"available": False},
                }

        with tempfile.TemporaryDirectory() as tmp:
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-api-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-api-test"),
                service_manager=_ManualImageServiceManager(),
            )
            state._write_manual_image_latest_job(
                {
                    "status": "running",
                    "template_id": "template.avatar_body_depth_reference_transparent.realvisxl.v1",
                    "prompt_id": "prompt-bg-oom",
                    "submitted_at": "2026-06-09T12:00:00+00:00",
                    "output_count_before": 0,
                }
            )
            with patch.object(
                state,
                "_manual_image_outputs",
                return_value=[
                    {
                        "relative_path": "hexe/avatar_body_depth_transparent/Jane_seed123_rgb_00001_.png",
                        "filename": "Jane_seed123_rgb_00001_.png",
                        "modified_at": "2026-06-09T12:00:05+00:00",
                    }
                ],
            ):
                payload = state.manual_image_generation_status()

        latest_job = payload["latest_job"]
        self.assertEqual(latest_job["status"], "completed_with_fallback")
        self.assertEqual(latest_job["latest_output"]["filename"], "Jane_seed123_rgb_00001_.png")
        self.assertEqual(latest_job["completed_output_count"], 1)
        fallback = latest_job["background_removal_fallback"]
        self.assertTrue(fallback["active"])
        self.assertEqual(fallback["kind"], "background_removal_rgb_fallback")
        self.assertEqual(fallback["latest_output"]["filename"], "Jane_seed123_rgb_00001_.png")

    def test_manual_image_generation_deletes_rgb_fallback_when_transparent_output_exists(self):
        class _ManualImageServiceManager:
            def __init__(self, output_dir: str):
                self.output_dir = output_dir

            def get_status(self):
                return {
                    "comfyui_gpu": {"state": "running"},
                    "comfyui_webui": {
                        "state": "running",
                        "runtime": "gpu",
                        "manual_paths": {"output_dir": self.output_dir},
                    },
                }

            def comfyui_webui_generation_status(self):
                return {
                    "runtime": "gpu",
                    "session": {"queue_active": False, "running_count": 0, "pending_count": 0},
                    "progress": {"available": False},
                }

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "manual-output"
            target_dir = output_dir / "hexe" / "avatar_body_depth_transparent"
            target_dir.mkdir(parents=True)
            transparent_path = target_dir / "Jane_seed123_00001_.png"
            rgb_path = target_dir / "Jane_seed123_rgb_00001_.png"
            transparent_path.write_bytes(b"transparent-png")
            rgb_path.write_bytes(b"rgb-png")
            rgb_path.with_suffix(".txt").write_text("caption\n", encoding="utf-8")
            rgb_path.with_suffix(".json").write_text("{}\n", encoding="utf-8")
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-api-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-api-test"),
                service_manager=_ManualImageServiceManager(str(output_dir)),
            )
            state._write_manual_image_latest_job(
                {
                    "status": "running",
                    "template_id": "template.avatar_body_depth_reference_transparent.realvisxl.v1",
                    "prompt_id": "prompt-bg-ok",
                    "submitted_at": "2000-01-01T00:00:00+00:00",
                    "output_count_before": 0,
                }
            )

            payload = state.manual_image_generation_status()

            latest_job = payload["latest_job"]
            self.assertEqual(latest_job["status"], "completed")
            self.assertIsNone(latest_job["background_removal_fallback"])
            self.assertEqual(latest_job["latest_output"]["filename"], "Jane_seed123_00001_.png")
            self.assertEqual(latest_job["completed_output_count"], 1)
            cleanup = latest_job["rgb_fallback_cleanup"]
            self.assertEqual(cleanup["deleted"], ["hexe/avatar_body_depth_transparent/Jane_seed123_rgb_00001_.png"])
            self.assertEqual(cleanup["errors"], [])
            self.assertTrue(transparent_path.exists())
            self.assertFalse(rgb_path.exists())
            self.assertFalse(rgb_path.with_suffix(".txt").exists())
            self.assertFalse(rgb_path.with_suffix(".json").exists())
            self.assertEqual([item["filename"] for item in payload["outputs"]], ["Jane_seed123_00001_.png"])

    def test_manual_image_generation_writes_lora_caption_sidecars(self):
        class _ManualImageServiceManager:
            def __init__(self, output_dir: str):
                self.output_dir = output_dir

            def get_status(self):
                return {
                    "comfyui_gpu": {"state": "running"},
                    "comfyui_webui": {
                        "state": "running",
                        "runtime": "gpu",
                        "manual_paths": {"output_dir": self.output_dir},
                    },
                }

            def comfyui_webui_generation_status(self):
                return {
                    "runtime": "gpu",
                    "session": {"queue_active": False, "running_count": 0, "pending_count": 0},
                    "progress": {"available": False},
                }

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "manual-output"
            image_path = output_dir / "hexe" / "avatar_body_depth_transparent" / "avatar_seed123_00001_.png"
            image_path.parent.mkdir(parents=True)
            image_path.write_bytes(b"png-data")
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-api-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-api-test"),
                service_manager=_ManualImageServiceManager(str(output_dir)),
            )
            state._write_manual_image_latest_job(
                {
                    "status": "submitted",
                    "prompt_id": "prompt-lora",
                    "submitted_at": "2026-06-09T12:00:00+00:00",
                    "output_count_before": 0,
                    "lora_metadata": {
                        "enabled": True,
                        "caption": "same woman as reference, full body, black lingerie",
                        "negative_prompt": "different person",
                        "template_id": "template.avatar_body_depth_reference_transparent.realvisxl.v1",
                        "mode": "txt2img",
                        "width": 768,
                        "height": 1152,
                        "seed": 123,
                        "steps": 20,
                        "cfg": 1.8,
                        "denoise": 0.55,
                    },
                }
            )

            payload = state.manual_image_generation_status()
            caption_path = image_path.with_suffix(".txt")
            json_path = image_path.with_suffix(".json")

            self.assertEqual(payload["latest_job"]["status"], "completed")
            self.assertEqual(caption_path.read_text(encoding="utf-8").strip(), "same woman as reference, full body, black lingerie")
            metadata = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(metadata["purpose"], "lora_training_metadata")
            self.assertEqual(metadata["template_id"], "template.avatar_body_depth_reference_transparent.realvisxl.v1")
            self.assertEqual(metadata["caption_file"], "avatar_seed123_00001_.txt")
            self.assertIn("hexe/avatar_body_depth_transparent/avatar_seed123_00001_.txt", payload["latest_job"]["lora_metadata"]["written"])

    async def test_submit_manual_image_generation_starts_progress_listener(self):
        class _ManualImageServiceManager:
            def __init__(self):
                self.listener_calls = []

            def get_status(self):
                return {
                    "comfyui_gpu": {"state": "running"},
                    "comfyui_webui": {
                        "state": "running",
                        "runtime": "gpu",
                        "socket_path": "/tmp/comfyui.sock",
                        "manual_paths": {"output_dir": "runtime/manual/comfyui-gpu/output"},
                    },
                }

            def ensure_comfyui_progress_listener(self, *, client_id: str | None = None):
                self.listener_calls.append(client_id)
                return {"started": True, "client_id": client_id}

        async def _fake_start_service(*, target: str):
            return {"status": "ok", "services": service_manager.get_status()}

        service_manager = _ManualImageServiceManager()
        with tempfile.TemporaryDirectory() as tmp:
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-api-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-api-test"),
                service_manager=service_manager,
                comfyui_template_catalog_dir="config/comfyui/templates",
            )
            state.start_service = _fake_start_service
            with patch.object(state, "_manual_image_outputs", return_value=[]), patch.object(
                state,
                "_uds_json_request",
                return_value={"prompt_id": "prompt-progress", "number": 1},
            ):
                result = await state.submit_manual_image_generation(
                    payload=ManualImageGenerationRequest(
                        mode="txt2img",
                        prompt="progress listener smoke",
                        template_variables={
                            "face_reference_image": "references/avatar/jane_face.png",
                            "body_reference_image": "references/avatar/jane_body.png",
                        },
                    )
                )

        self.assertEqual(result["prompt_id"], "prompt-progress")
        self.assertEqual(service_manager.listener_calls, ["hexe-node-manual-image-ui"])

    async def test_submit_manual_image_generation_queues_batch_with_randomized_seeds(self):
        class _ManualImageServiceManager:
            def get_status(self):
                return {
                    "comfyui_webui": {
                        "state": "running",
                        "runtime": "gpu",
                        "socket_path": "/tmp/comfyui.sock",
                        "manual_paths": {"output_dir": "runtime/manual/comfyui-gpu/output"},
                    },
                }

            def ensure_comfyui_progress_listener(self, *, client_id: str | None = None):
                return {"started": True, "client_id": client_id}

        async def _fake_start_service(*, target: str):
            return {"status": "ok", "services": service_manager.get_status()}

        request_bodies: list[dict] = []

        def _fake_uds_request(*, socket_path: str, method: str, path: str, body: dict):
            request_bodies.append(body)
            index = len(request_bodies)
            return {"prompt_id": f"prompt-batch-{index}", "number": index, "node_errors": {}}

        service_manager = _ManualImageServiceManager()
        with tempfile.TemporaryDirectory() as tmp:
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-api-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-api-test"),
                service_manager=service_manager,
                comfyui_template_catalog_dir="config/comfyui/templates",
            )
            state.start_service = _fake_start_service
            with patch.object(state, "_manual_image_outputs", return_value=[]), patch.object(
                state,
                "_uds_json_request",
                side_effect=_fake_uds_request,
            ), patch("ai_node.runtime.node_control_api.secrets.randbelow", side_effect=[111, 222, 333]):
                result = await state.submit_manual_image_generation(
                    payload=ManualImageGenerationRequest(
                        mode="txt2img",
                        prompt="batch seed test",
                        batch_count=3,
                        randomize_seed=True,
                        template_variables={
                            "face_reference_image": "references/avatar/jane_face.png",
                            "body_reference_image": "references/avatar/jane_body.png",
                        },
                    )
                )

            latest_job = state._read_manual_image_latest_job()

        self.assertEqual(result["batch_count"], 3)
        self.assertEqual(result["prompt_ids"], ["prompt-batch-1", "prompt-batch-2", "prompt-batch-3"])
        self.assertEqual([body["prompt"]["14"]["inputs"]["seed"] for body in request_bodies], [111, 222, 333])
        self.assertEqual([item["seed"] for item in latest_job["submissions"]], [111, 222, 333])
        self.assertEqual(latest_job["lora_metadata"]["batch_count"], 3)

    def test_manual_image_generation_jitters_avatar_reference_strengths(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-api-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-api-test"),
                comfyui_template_catalog_dir="config/comfyui/templates",
            )
            template = state.get_comfyui_template_catalog_entry(
                template_id="template.avatar_body_depth_reference_transparent.realvisxl.v1"
            )["template"]
            payload = ManualImageGenerationRequest(
                template_id="template.avatar_body_depth_reference_transparent.realvisxl.v1",
                mode="txt2img",
                prompt="jitter test",
                seed=1001,
                randomize_reference_strengths=True,
                reference_strength_jitter=0.05,
                template_variables={
                    "avatar_name": "Jane",
                    "face_reference_image": "references/avatar/jane_face.png",
                    "body_reference_image": "references/avatar/jane_body.png",
                    "face_strength": "0.75",
                    "body_depth_strength": "0.75",
                },
            )

            with patch("ai_node.runtime.node_control_api.secrets.randbelow", side_effect=[2_000_000, 0]):
                item_payload = state._manual_image_batch_item_payload(template=template, payload=payload, batch_index=0)
            workflow = state._manual_image_workflow_from_template(template=template, payload=item_payload, input_image="")

        self.assertEqual(workflow["31"]["inputs"]["weight"], 0.8)
        self.assertEqual(workflow["27"]["inputs"]["strength"], 0.7)

    def test_manual_image_workflow_generates_seed_when_blank(self):
        with tempfile.TemporaryDirectory() as tmp:
            workflow_path = Path(tmp) / "workflow.json"
            workflow_path.write_text(
                json.dumps(
                    {
                        "6": {
                            "class_type": "KSampler",
                            "inputs": {
                                "seed": "{{seed}}",
                                "steps": "{{steps}}",
                                "cfg": "{{cfg}}",
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-api-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-api-test"),
                comfyui_template_catalog_dir="config/comfyui/templates",
            )
            workflow = state._manual_image_workflow_from_template(
                template={
                    "api_workflow_path": str(workflow_path),
                    "variables": [
                        {"name": "positive_prompt", "required": True},
                        {"name": "seed", "required": False},
                        {"name": "steps", "required": False},
                        {"name": "cfg", "required": False},
                    ],
                    "defaults": {"seed": None, "steps": 4, "cfg": 1.6},
                },
                payload=ManualImageGenerationRequest(prompt="seed test", seed=None),
                input_image="",
            )

        self.assertIsInstance(workflow["6"]["inputs"]["seed"], int)
        self.assertGreaterEqual(workflow["6"]["inputs"]["seed"], 0)

    def test_manual_image_workflow_preserves_large_seed_from_string(self):
        large_seed = "8144634414719883838"
        with tempfile.TemporaryDirectory() as tmp:
            workflow_path = Path(tmp) / "workflow.json"
            workflow_path.write_text(
                json.dumps(
                    {
                        "6": {
                            "class_type": "KSampler",
                            "inputs": {
                                "seed": "{{seed}}",
                                "steps": "{{steps}}",
                                "cfg": "{{cfg}}",
                            },
                        },
                        "10": {
                            "class_type": "SaveImage",
                            "inputs": {"filename_prefix": "hexe/test_seed{{seed}}"},
                        },
                    }
                ),
                encoding="utf-8",
            )
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-api-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-api-test"),
                comfyui_template_catalog_dir="config/comfyui/templates",
            )
            workflow = state._manual_image_workflow_from_template(
                template={
                    "api_workflow_path": str(workflow_path),
                    "variables": [
                        {"name": "positive_prompt", "required": True},
                        {"name": "seed", "required": False},
                        {"name": "steps", "required": False},
                        {"name": "cfg", "required": False},
                    ],
                    "defaults": {"seed": None, "steps": 4, "cfg": 1.6},
                },
                payload=ManualImageGenerationRequest(prompt="seed precision test", seed=large_seed),
                input_image="",
            )

        self.assertEqual(workflow["6"]["inputs"]["seed"], int(large_seed))
        self.assertEqual(workflow["10"]["inputs"]["filename_prefix"], f"hexe/test_seed{large_seed}")

    def test_manual_avatar_body_depth_transparent_template_adds_alpha_background_removal(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-api-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-api-test"),
                comfyui_template_catalog_dir="config/comfyui/templates",
            )
            template = state.get_comfyui_template_catalog_entry(
                template_id="template.avatar_body_depth_reference_transparent.realvisxl.v1"
            )["template"]

            workflow = state._manual_image_workflow_from_template(
                template=template,
                payload=ManualImageGenerationRequest(
                    template_id="template.avatar_body_depth_reference_transparent.realvisxl.v1",
                    mode="txt2img",
                    prompt="same woman, isolated full body lingerie pose",
                    seed=1003,
                    template_variables={
                        "avatar_name": "Jane",
                        "face_reference_image": "references/avatar/jane_face.png",
                        "body_reference_image": "references/avatar/jane_body.png",
                    },
                ),
                input_image="",
            )

        self.assertTrue(template["metadata"]["transparent_background"])
        self.assertEqual(workflow["25"]["class_type"], "DepthAnythingV2Preprocessor")
        self.assertEqual(workflow["27"]["class_type"], "ControlNetApplyAdvanced")
        self.assertEqual(workflow["17"]["class_type"], "LoadBackgroundRemovalModel")
        self.assertEqual(workflow["17"]["inputs"]["bg_removal_name"], "birefnet.safetensors")
        self.assertEqual(workflow["18"]["class_type"], "RemoveBackground")
        self.assertEqual(workflow["18"]["inputs"]["image"], ["15", 0])
        self.assertEqual(workflow["20"]["class_type"], "InvertMask")
        self.assertEqual(workflow["20"]["inputs"]["mask"], ["18", 0])
        self.assertEqual(workflow["19"]["class_type"], "JoinImageWithAlpha")
        self.assertEqual(workflow["19"]["inputs"]["alpha"], ["20", 0])
        self.assertEqual(workflow["16"]["inputs"]["images"], ["15", 0])
        self.assertEqual(workflow["16"]["inputs"]["filename_prefix"], "hexe/avatar_body_depth_transparent/Jane_seed1003_rgb")
        self.assertEqual(workflow["24"]["inputs"]["images"], ["19", 0])
        self.assertEqual(workflow["24"]["inputs"]["filename_prefix"], "hexe/avatar_body_depth_transparent/Jane_seed1003")

    def test_manual_image_prompt_helper_uses_local_llm_socket(self):
        class _PromptHelperServiceManager:
            def get_status(self):
                return {
                    "local_llm": {
                        "state": "running",
                        "socket_path": "/tmp/local-llm.sock",
                        "model_id": "qwen3-8b-q4_k_m",
                    }
                }

        with tempfile.TemporaryDirectory() as tmp:
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-api-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-api-test"),
                service_manager=_PromptHelperServiceManager(),
            )
            llm_response = {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "prompt": "cinematic mountain lake, sunrise, detailed reflections",
                                    "negative_prompt": "low quality, blurry",
                                }
                            )
                        }
                    }
                ]
            }
            with patch.object(state, "_uds_json_request", return_value=llm_response) as request:
                result = state.manual_image_prompt_helper(
                    payload=ManualImagePromptHelperRequest(
                        mode="txt2img",
                        prompt="mountain lake",
                        negative_prompt="low quality",
                        width=1280,
                        height=720,
                    )
                )

        self.assertEqual(result["provider"], "local_llm")
        self.assertEqual(result["model_id"], "qwen3-8b-q4_k_m")
        self.assertIn("cinematic mountain lake", result["prompt"])
        request.assert_called_once()
        self.assertEqual(request.call_args.kwargs["socket_path"], "/tmp/local-llm.sock")
        self.assertEqual(request.call_args.kwargs["path"], "/v1/chat/completions")
        messages = request.call_args.kwargs["body"]["messages"]
        self.assertTrue(all("/no_think" in item["content"] for item in messages))

    def test_manual_image_pose_helper_uses_local_llm_and_writes_pose_reference(self):
        class _PoseHelperServiceManager:
            def __init__(self, input_dir: str):
                self.input_dir = input_dir

            def get_status(self):
                return {
                    "comfyui_webui": {
                        "state": "stopped",
                        "runtime": "gpu",
                        "manual_paths": {"input_dir": self.input_dir},
                    },
                    "local_llm": {
                        "state": "running",
                        "socket_path": "/tmp/local-llm.sock",
                        "model_id": "qwen3-8b-q4_k_m",
                    },
                    "vision_llm": {
                        "state": "stopped",
                        "socket_path": "",
                    },
                }

        with tempfile.TemporaryDirectory() as tmp:
            input_dir = Path(tmp) / "manual-input"
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-api-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-api-test"),
                service_manager=_PoseHelperServiceManager(str(input_dir)),
                comfyui_template_catalog_dir="config/comfyui/templates",
            )
            llm_response = {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "body_angle": "three-quarter body angle facing left",
                                    "camera_framing": "full body visible from head to feet",
                                    "head_turn": "head turned toward camera",
                                    "gaze": "eyes looking toward viewer",
                                    "shoulders": "relaxed shoulders",
                                    "hips": "hips angled naturally",
                                    "left_arm": "left elbow angled outward",
                                    "right_arm": "right arm relaxed along the thigh",
                                    "left_hand": "left hand resting on left hip",
                                    "right_hand": "right hand near the thigh",
                                    "legs": "standing stance with right knee softly bent",
                                    "weight_distribution": "weight mostly on the left leg",
                                    "pose_prompt": "full body visible from head to feet, left hand resting on left hip, right knee softly bent",
                                }
                            )
                        }
                    }
                ]
            }
            with patch.object(state, "_uds_json_request", return_value=llm_response) as request:
                result = state.manual_image_pose_helper(
                    payload=ManualImagePoseHelperRequest(
                        pose_text="three-quarter left pose with left hand on hip and right knee bent",
                        avatar_name="Jane",
                        width=512,
                        height=768,
                    )
                )

            reference = result["reference"]
            reference_path = state._manual_image_reference_root() / reference["relative_path"]
            sidecar_path = reference_path.with_suffix(reference_path.suffix + ".json")
            metadata = json.loads(sidecar_path.read_text(encoding="utf-8"))

            self.assertEqual(result["provider"], "local_llm")
            self.assertEqual(result["model_id"], "qwen3-8b-q4_k_m")
            self.assertEqual(result["pose_plan"]["left_hand"], "left hand resting on left hip")
            self.assertIn("left hand resting on left hip", result["pose_prompt"])
            self.assertEqual(reference["category"], "avatar")
            self.assertEqual(reference["role"], "pose")
            self.assertTrue(reference["input_image"].startswith("references/avatar/Jane_pose_"))
            self.assertEqual(result["body_reference_image"], reference["input_image"])
            self.assertTrue(reference_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))
            self.assertEqual(metadata["source"], "manual_pose_helper")
            self.assertEqual(metadata["pose_plan"]["left_hand"], "left hand resting on left hip")
            self.assertEqual(result["references"][0]["relative_path"], reference["relative_path"])
            request.assert_called_once()
            self.assertEqual(request.call_args.kwargs["host"], "local-llm")
            self.assertEqual(request.call_args.kwargs["path"], "/v1/chat/completions")

    def test_manual_image_pose_helper_falls_back_without_starting_vision_or_llm(self):
        class _PoseFallbackServiceManager:
            def __init__(self, input_dir: str):
                self.input_dir = input_dir

            def get_status(self):
                return {
                    "comfyui_webui": {
                        "state": "stopped",
                        "runtime": "gpu",
                        "manual_paths": {"input_dir": self.input_dir},
                    },
                    "local_llm": {
                        "state": "stopped",
                        "socket_path": "",
                    },
                    "vision_llm": {
                        "state": "stopped",
                        "socket_path": "",
                    },
                }

        with tempfile.TemporaryDirectory() as tmp:
            input_dir = Path(tmp) / "manual-input"
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-api-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-api-test"),
                service_manager=_PoseFallbackServiceManager(str(input_dir)),
            )
            with patch.object(state, "_uds_json_request", side_effect=AssertionError("unexpected socket call")):
                result = state.manual_image_pose_helper(
                    payload=ManualImagePoseHelperRequest(
                        pose_text="arms crossed, wide stance, looking away",
                        avatar_name="Jane",
                        generate_reference=True,
                    )
                )

        self.assertEqual(result["provider"], "local_rules")
        self.assertIsNone(result["model_id"])
        self.assertIn("crossing the torso", result["pose_plan"]["left_arm"])
        self.assertIn("wide stance", result["pose_plan"]["legs"])
        self.assertIn("looking away", result["pose_plan"]["gaze"])
        self.assertTrue(result["body_reference_image"].startswith("references/avatar/Jane_pose_"))

    def test_manual_image_reference_upload_stores_local_reference(self):
        class _ReferenceServiceManager:
            def __init__(self, input_dir: str):
                self.input_dir = input_dir

            def get_status(self):
                return {
                    "comfyui_webui": {
                        "state": "running",
                        "runtime": "gpu",
                        "manual_paths": {"input_dir": self.input_dir},
                    }
                }

        with tempfile.TemporaryDirectory() as tmp:
            input_dir = Path(tmp) / "manual-input"
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-api-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-api-test"),
                service_manager=_ReferenceServiceManager(str(input_dir)),
            )

            result = state.upload_manual_image_reference(
                payload=ManualImageReferenceUploadRequest(
                    category="avatar",
                    role="face",
                    name="Jane Doe",
                    filename="avatar.png",
                    data_base64=base64.b64encode(b"png-data").decode("ascii"),
                )
            )
            status = state.manual_image_generation_status()

        reference = result["reference"]
        self.assertEqual(reference["category"], "avatar")
        self.assertEqual(reference["role"], "face")
        self.assertEqual(reference["name"], "Jane Doe")
        self.assertTrue(reference["input_image"].startswith("references/avatar/Jane_Doe_face_"))
        self.assertEqual(status["references"][0]["input_image"], reference["input_image"])

    def test_manual_image_reference_upload_preserves_openpose_role(self):
        class _ReferenceServiceManager:
            def __init__(self, input_dir: str):
                self.input_dir = input_dir

            def get_status(self):
                return {
                    "comfyui_webui": {
                        "state": "running",
                        "runtime": "gpu",
                        "manual_paths": {"input_dir": self.input_dir},
                    }
                }

        with tempfile.TemporaryDirectory() as tmp:
            input_dir = Path(tmp) / "manual-input"
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-api-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-api-test"),
                service_manager=_ReferenceServiceManager(str(input_dir)),
            )

            result = state.upload_manual_image_reference(
                payload=ManualImageReferenceUploadRequest(
                    category="avatar",
                    role="openpose",
                    name="Jane OpenPose",
                    filename="pose.png",
                    data_base64=base64.b64encode(b"png-data").decode("ascii"),
                )
            )

        reference = result["reference"]
        self.assertEqual(reference["category"], "avatar")
        self.assertEqual(reference["role"], "openpose")
        self.assertEqual(reference["name"], "Jane OpenPose")
        self.assertTrue(reference["input_image"].startswith("references/avatar/Jane_OpenPose_openpose_"))

    def test_delete_manual_image_reference_removes_image_and_sidecar(self):
        class _ReferenceServiceManager:
            def __init__(self, input_dir: str):
                self.input_dir = input_dir

            def get_status(self):
                return {
                    "comfyui_webui": {
                        "state": "running",
                        "runtime": "gpu",
                        "manual_paths": {"input_dir": self.input_dir},
                    }
                }

        with tempfile.TemporaryDirectory() as tmp:
            input_dir = Path(tmp) / "manual-input"
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-api-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-api-test"),
                service_manager=_ReferenceServiceManager(str(input_dir)),
            )
            result = state.upload_manual_image_reference(
                payload=ManualImageReferenceUploadRequest(
                    category="avatar",
                    role="body",
                    name="Jane Doe",
                    filename="avatar.png",
                    data_base64=base64.b64encode(b"png-data").decode("ascii"),
                )
            )
            relative_path = result["reference"]["relative_path"]
            reference_path = state._manual_image_reference_root() / relative_path
            sidecar_path = reference_path.with_suffix(reference_path.suffix + ".json")

            delete_result = state.delete_manual_image_reference(relative_path=relative_path)

            self.assertTrue(delete_result["deleted"])
            self.assertFalse(reference_path.exists())
            self.assertFalse(sidecar_path.exists())
            self.assertEqual(delete_result["references"], [])
            with self.assertRaises(ValueError):
                state.delete_manual_image_reference(relative_path="../outside.png")

    def test_avatar_generation_saves_profile_with_face_and_body_images(self):
        class _AvatarProfileServiceManager:
            def __init__(self, input_dir: str):
                self.input_dir = input_dir

            def get_status(self):
                return {
                    "comfyui_webui": {
                        "state": "running",
                        "runtime": "gpu",
                        "manual_paths": {"input_dir": self.input_dir},
                    }
                }

        with tempfile.TemporaryDirectory() as tmp:
            input_dir = Path(tmp) / "manual-input"
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-api-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-api-test"),
                service_manager=_AvatarProfileServiceManager(str(input_dir)),
            )
            face_data = base64.b64encode(b"face-image").decode("ascii")
            body_data = base64.b64encode(b"body-image").decode("ascii")

            result = state.save_avatar_profile(
                payload=AvatarProfileSaveRequest(
                    name="Jane Avatar",
                    description="editable avatar description",
                    face_image_filename="face.webp",
                    face_image_data_base64=face_data,
                    body_image_filename="body.png",
                    body_image_data_base64=body_data,
                )
            )

            profile = result["profile"]
            profile_dir = input_dir / "avatar_profiles" / "Jane_Avatar"
            self.assertEqual(result["status"], "saved")
            self.assertEqual(profile["profile_id"], "Jane_Avatar")
            self.assertEqual(profile["name"], "Jane Avatar")
            self.assertEqual(profile["description"], "editable avatar description")
            self.assertEqual(profile["face_input_image"], "avatar_profiles/Jane_Avatar/face.webp")
            self.assertEqual(profile["body_input_image"], "avatar_profiles/Jane_Avatar/body.png")
            self.assertEqual(profile["face_url"], "/api/avatar-generation/profiles/Jane_Avatar/assets/face.webp")
            self.assertEqual((profile_dir / "face.webp").read_bytes(), b"face-image")
            self.assertEqual((profile_dir / "body.png").read_bytes(), b"body-image")

            status = state.avatar_generation_status()

        self.assertEqual(status["profiles"][0]["profile_id"], "Jane_Avatar")
        self.assertEqual(status["profiles"][0]["description"], "editable avatar description")

    def test_avatar_generation_saves_profile_with_basic_character_information(self):
        class _AvatarProfileServiceManager:
            def __init__(self, input_dir: str):
                self.input_dir = input_dir

            def get_status(self):
                return {
                    "comfyui_webui": {
                        "state": "running",
                        "runtime": "gpu",
                        "manual_paths": {"input_dir": self.input_dir},
                    }
                }

        with tempfile.TemporaryDirectory() as tmp:
            input_dir = Path(tmp) / "manual-input"
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-api-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-api-test"),
                service_manager=_AvatarProfileServiceManager(str(input_dir)),
            )

            result = state.save_avatar_profile(
                payload=AvatarProfileSaveRequest(
                    name="Jane Avatar",
                    gender="female",
                    skin_color="warm olive",
                    hair_color="black",
                    character_type="humanlike",
                    visual_style="semi-real",
                    initial_data="reserved, observant, late twenties",
                    nsfw=True,
                )
            )

            profile = result["profile"]
            profile_path = input_dir / "avatar_profiles" / "Jane_Avatar" / "profile.json"
            metadata = json.loads(profile_path.read_text(encoding="utf-8"))

        self.assertEqual(result["status"], "saved")
        self.assertEqual(profile["profile_id"], "Jane_Avatar")
        self.assertEqual(profile["gender"], "female")
        self.assertEqual(profile["skin_color"], "warm olive")
        self.assertEqual(profile["hair_color"], "black")
        self.assertEqual(profile["character_type"], "humanlike")
        self.assertEqual(profile["visual_style"], "semi-real")
        self.assertEqual(profile["initial_data"], "reserved, observant, late twenties")
        self.assertTrue(profile["nsfw"])
        self.assertEqual(profile["face_url"], "")
        self.assertEqual(profile["body_url"], "")
        self.assertNotIn("face_image", metadata)
        self.assertNotIn("body_image", metadata)

    def test_avatar_generation_selects_and_deletes_profile(self):
        class _AvatarProfileServiceManager:
            def __init__(self, input_dir: str):
                self.input_dir = input_dir

            def get_status(self):
                return {
                    "comfyui_webui": {
                        "state": "running",
                        "runtime": "gpu",
                        "manual_paths": {"input_dir": self.input_dir},
                    }
                }

        with tempfile.TemporaryDirectory() as tmp:
            input_dir = Path(tmp) / "manual-input"
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-api-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-api-test"),
                service_manager=_AvatarProfileServiceManager(str(input_dir)),
            )
            state.save_avatar_profile(
                payload=AvatarProfileSaveRequest(
                    name="Jane Avatar",
                    face_image_filename="face.png",
                    face_image_data_base64=base64.b64encode(b"face-image").decode("ascii"),
                    body_image_filename="body.png",
                    body_image_data_base64=base64.b64encode(b"body-image").decode("ascii"),
                )
            )

            selected = state.select_avatar_profile(profile_id="Jane_Avatar")
            deleted = state.delete_avatar_profile(profile_id="Jane_Avatar")
            status = state.avatar_generation_status()

        self.assertEqual(selected["selected_profile_id"], "Jane_Avatar")
        self.assertTrue(selected["selected_profile"]["selected"])
        self.assertTrue(deleted["deleted"])
        self.assertIsNone(deleted["selected_profile_id"])
        self.assertEqual(status["profiles"], [])
        self.assertIsNone(status["selected_profile_id"])

    def test_avatar_generation_uploads_and_deletes_profile_references(self):
        class _AvatarProfileServiceManager:
            def __init__(self, input_dir: str):
                self.input_dir = input_dir

            def get_status(self):
                return {
                    "comfyui_webui": {
                        "state": "running",
                        "runtime": "gpu",
                        "manual_paths": {"input_dir": self.input_dir},
                    }
                }

        with tempfile.TemporaryDirectory() as tmp:
            input_dir = Path(tmp) / "manual-input"
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-api-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-api-test"),
                service_manager=_AvatarProfileServiceManager(str(input_dir)),
            )
            state.save_avatar_profile(
                payload=AvatarProfileSaveRequest(
                    name="Jane Avatar",
                    face_image_filename="face.png",
                    face_image_data_base64=base64.b64encode(b"face-image").decode("ascii"),
                    body_image_filename="body.png",
                    body_image_data_base64=base64.b64encode(b"body-image").decode("ascii"),
                )
            )

            uploaded = state.upload_avatar_profile_reference(
                profile_id="Jane_Avatar",
                payload=AvatarProfileReferenceUploadRequest(
                    role="body_depth",
                    name="Standing Body",
                    filename="standing.webp",
                    data_base64=base64.b64encode(b"body-depth-reference").decode("ascii"),
                ),
            )
            reference = uploaded["reference"]
            profile = uploaded["profile"]
            reference_path = input_dir / "avatar_profiles" / "Jane_Avatar" / "refs" / "body_depth" / reference["filename"]
            response = state.avatar_profile_reference_response(
                profile_id="Jane_Avatar",
                role="body_depth",
                asset_name=reference["filename"],
            )
            saved_bytes = reference_path.read_bytes()
            deleted = state.delete_avatar_profile_reference(
                profile_id="Jane_Avatar",
                role="body_depth",
                asset_name=reference["filename"],
            )

        self.assertEqual(uploaded["status"], "uploaded")
        self.assertEqual(reference["role"], "body_depth")
        self.assertEqual(reference["name"], "Standing Body")
        self.assertEqual(reference["url"], f"/api/avatar-generation/profiles/Jane_Avatar/references/body_depth/{reference['filename']}")
        self.assertEqual(saved_bytes, b"body-depth-reference")
        self.assertEqual(profile["references"]["body_depth"][0]["filename"], reference["filename"])
        self.assertEqual(str(response.path), str(reference_path))
        self.assertTrue(deleted["deleted"])
        self.assertFalse(reference_path.exists())
        self.assertEqual(deleted["profile"]["references"]["body_depth"], [])

    def test_avatar_generation_sets_primary_face_reference_for_pulid(self):
        class _AvatarProfileServiceManager:
            def __init__(self, input_dir: str):
                self.input_dir = input_dir

            def get_status(self):
                return {
                    "comfyui_webui": {
                        "state": "stopped",
                        "runtime": "gpu",
                        "manual_paths": {"input_dir": self.input_dir},
                    }
                }

        with tempfile.TemporaryDirectory() as tmp:
            input_dir = Path(tmp) / "manual-input"
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-api-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-api-test"),
                service_manager=_AvatarProfileServiceManager(str(input_dir)),
            )
            state.save_avatar_profile(
                payload=AvatarProfileSaveRequest(
                    name="Jane Avatar",
                    face_image_filename="face.png",
                    face_image_data_base64=base64.b64encode(b"base-face").decode("ascii"),
                    body_image_filename="body.png",
                    body_image_data_base64=base64.b64encode(b"body-image").decode("ascii"),
                )
            )
            uploaded = state.upload_avatar_profile_reference(
                profile_id="Jane_Avatar",
                payload=AvatarProfileReferenceUploadRequest(
                    role="face",
                    name="Three Quarter Face",
                    filename="face_3q.png",
                    data_base64=base64.b64encode(b"face-ref").decode("ascii"),
                ),
            )
            selected = state.set_avatar_profile_primary_face(
                profile_id="Jane_Avatar",
                payload=AvatarPrimaryFaceRequest(filename=uploaded["reference"]["filename"]),
            )

        profile = selected["profile"]
        self.assertEqual(profile["primary_face_reference_filename"], uploaded["reference"]["filename"])
        self.assertEqual(profile["primary_face_input_image"], uploaded["reference"]["input_image"])
        self.assertEqual(profile["pulid_face_reference_image"], uploaded["reference"]["input_image"])
        self.assertTrue(profile["references"]["face"][0]["primary"])

    def test_avatar_generation_face_extract_blocks_when_comfyui_webui_running(self):
        class _AvatarProfileServiceManager:
            def __init__(self, input_dir: str):
                self.input_dir = input_dir

            def get_status(self):
                return {
                    "comfyui_webui": {
                        "state": "running",
                        "runtime": "gpu",
                        "manual_session_active": True,
                        "manual_paths": {"input_dir": self.input_dir},
                    },
                    "comfyui_gpu": {"state": "running"},
                    "vision_llm": {"state": "running", "socket_path": "/tmp/vision.sock"},
                }

        with tempfile.TemporaryDirectory() as tmp:
            input_dir = Path(tmp) / "manual-input"
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-api-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-api-test"),
                service_manager=_AvatarProfileServiceManager(str(input_dir)),
            )
            state.save_avatar_profile(
                payload=AvatarProfileSaveRequest(
                    name="Jane Avatar",
                    face_image_filename="face.png",
                    face_image_data_base64=base64.b64encode(b"base-face").decode("ascii"),
                    body_image_filename="body.png",
                    body_image_data_base64=base64.b64encode(b"body-image").decode("ascii"),
                )
            )

            with self.assertRaisesRegex(ValueError, "vision_blocked_by_manual_comfyui_webui"):
                state.extract_avatar_face_profile(
                    profile_id="Jane_Avatar",
                    payload=AvatarFaceProfileExtractRequest(),
                )

    def test_avatar_generation_extracts_combined_face_profile_from_references(self):
        class _AvatarProfileServiceManager:
            def __init__(self, input_dir: str):
                self.input_dir = input_dir

            def get_status(self):
                return {
                    "comfyui_webui": {
                        "state": "stopped",
                        "runtime": "gpu",
                        "manual_paths": {"input_dir": self.input_dir},
                    },
                    "comfyui_gpu": {"state": "stopped"},
                    "vision_llm": {"state": "running", "socket_path": "/tmp/vision.sock", "default_model_id": "vision-model"},
                    "local_llm": {"state": "running", "socket_path": "/tmp/local.sock", "default_model_id": "local-model"},
                }

        with tempfile.TemporaryDirectory() as tmp:
            input_dir = Path(tmp) / "manual-input"
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-api-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-api-test"),
                service_manager=_AvatarProfileServiceManager(str(input_dir)),
            )
            state.save_avatar_profile(
                payload=AvatarProfileSaveRequest(
                    name="Jane Avatar",
                    face_image_filename="face.png",
                    face_image_data_base64=base64.b64encode(b"base-face").decode("ascii"),
                    body_image_filename="body.png",
                    body_image_data_base64=base64.b64encode(b"body-image").decode("ascii"),
                )
            )
            first = state.upload_avatar_profile_reference(
                profile_id="Jane_Avatar",
                payload=AvatarProfileReferenceUploadRequest(
                    role="face",
                    name="Front Face",
                    filename="front.png",
                    data_base64=base64.b64encode(b"front-face").decode("ascii"),
                ),
            )
            second = state.upload_avatar_profile_reference(
                profile_id="Jane_Avatar",
                payload=AvatarProfileReferenceUploadRequest(
                    role="face",
                    name="Side Face",
                    filename="side.png",
                    data_base64=base64.b64encode(b"side-face").decode("ascii"),
                ),
            )
            state.set_avatar_profile_primary_face(
                profile_id="Jane_Avatar",
                payload=AvatarPrimaryFaceRequest(filename=first["reference"]["filename"]),
            )

            def _fake_vision(*, image_bytes, mime_type, image_name, prompt, max_tokens=450, timeout_s=10):
                return f"face observations for {image_name}", "vision-model"

            def _fake_uds_request(*, socket_path: str, method: str, path: str, body: dict, **kwargs):
                return {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "schema_version": "1.0",
                                        "stable_identity": {"face_shape": "oval", "eyes": "green almond eyes"},
                                        "identity_prompt": "same Jane face, oval face, green almond eyes",
                                        "face_prompt": "oval face, green almond eyes, defined brows",
                                        "hair_prompt": "dark wavy hair",
                                        "negative_prompt_terms": ["different person", "changed face"],
                                    }
                                )
                            }
                        }
                    ]
                }

            with patch.object(state, "_vision_describe_image_bytes", side_effect=_fake_vision), patch.object(
                state,
                "_uds_json_request",
                side_effect=_fake_uds_request,
            ):
                result = state.extract_avatar_face_profile(
                    profile_id="Jane_Avatar",
                    payload=AvatarFaceProfileExtractRequest(
                        source_filenames=[first["reference"]["filename"], second["reference"]["filename"]]
                    ),
                )

        face_profile = result["face_profile"]
        profile = result["profile"]
        self.assertEqual(face_profile["reference_count"], 2)
        self.assertEqual(face_profile["vision_model_id"], "vision-model")
        self.assertEqual(face_profile["local_llm_model_id"], "local-model")
        self.assertEqual(face_profile["structured"]["identity_prompt"], "same Jane face, oval face, green almond eyes")
        self.assertEqual(profile["face_profile"]["structured"]["face_prompt"], "oval face, green almond eyes, defined brows")
        self.assertEqual(profile["extraction"]["structured"]["prompt_sections"]["face"], "oval face, green almond eyes, defined brows")

    def test_avatar_generation_face_extract_fallback_stays_prompt_sized(self):
        class _AvatarProfileServiceManager:
            def __init__(self, input_dir: str):
                self.input_dir = input_dir

            def get_status(self):
                return {
                    "comfyui_webui": {
                        "state": "stopped",
                        "runtime": "gpu",
                        "manual_paths": {"input_dir": self.input_dir},
                    },
                    "comfyui_gpu": {"state": "stopped"},
                    "vision_llm": {"state": "running", "socket_path": "/tmp/vision.sock", "default_model_id": "vision-model"},
                    "local_llm": {"state": "running", "socket_path": "/tmp/local.sock", "default_model_id": "local-model"},
                }

        with tempfile.TemporaryDirectory() as tmp:
            input_dir = Path(tmp) / "manual-input"
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-api-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-api-test"),
                service_manager=_AvatarProfileServiceManager(str(input_dir)),
            )
            state.save_avatar_profile(
                payload=AvatarProfileSaveRequest(
                    name="Jane Avatar",
                    face_image_filename="face.png",
                    face_image_data_base64=base64.b64encode(b"base-face").decode("ascii"),
                    body_image_filename="body.png",
                    body_image_data_base64=base64.b64encode(b"body-image").decode("ascii"),
                )
            )
            first = state.upload_avatar_profile_reference(
                profile_id="Jane_Avatar",
                payload=AvatarProfileReferenceUploadRequest(
                    role="face",
                    name="Front Face",
                    filename="front.png",
                    data_base64=base64.b64encode(b"front-face").decode("ascii"),
                ),
            )
            second = state.upload_avatar_profile_reference(
                profile_id="Jane_Avatar",
                payload=AvatarProfileReferenceUploadRequest(
                    role="face",
                    name="Side Face",
                    filename="side.png",
                    data_base64=base64.b64encode(b"side-face").decode("ascii"),
                ),
            )

            def _fake_vision(*, image_bytes, mime_type, image_name, prompt, max_tokens=450, timeout_s=10):
                return (
                    "### Face Shape and Proportions\n"
                    "- Oval face with balanced symmetry, defined cheekbones, angular jaw, and softly rounded chin.\n"
                    "### Eyes\n"
                    "- Large green almond-shaped eyes with even spacing and defined eyelids.\n"
                    "### Eyebrows\n"
                    "- Thick arched eyebrows placed symmetrically.\n"
                    "### Nose\n"
                    "- Straight nose bridge with rounded tip and small nostrils.\n"
                    "### Lips\n"
                    "- Full well-defined lips with a soft natural mouth curve.\n"
                    "### Hair\n"
                    "- Dark brown long wavy hair with natural volume.\n"
                    "### Lighting/Quality\n"
                    "- High-quality image suitable for identity control.\n"
                ), "vision-model"

            with patch.object(state, "_vision_describe_image_bytes", side_effect=_fake_vision), patch.object(
                state,
                "_uds_json_request",
                side_effect=TimeoutError("merge timed out"),
            ):
                result = state.extract_avatar_face_profile(
                    profile_id="Jane_Avatar",
                    payload=AvatarFaceProfileExtractRequest(
                        source_filenames=[first["reference"]["filename"], second["reference"]["filename"]]
                    ),
                )

        structured = result["face_profile"]["structured"]
        self.assertEqual(result["face_profile"]["local_llm_model_id"], "local_rules")
        self.assertLess(len(structured["identity_prompt"]), 900)
        self.assertLess(len(structured["face_prompt"]), 700)
        self.assertIn("same avatar identity", structured["identity_prompt"])
        self.assertIn("green", structured["face_prompt"])
        self.assertNotIn("front.png", structured["identity_prompt"])
        self.assertNotIn("suitable for identity control", structured["identity_prompt"])
        self.assertEqual(structured["reference_quality_notes"]["structured_source"], "vision_descriptions_local_rules")
        self.assertEqual(structured["reference_quality_notes"]["local_llm_model_id"], "local-model")

    def test_avatar_generation_body_cleanup_reduces_average_filler_and_keeps_markdown_headings(self):
        raw_body = (
            "- **Height Impression**: Average height, standing posture.\n"
            "- ****Shoulder-to-waist-to-hip ratio**: The shoulders are slightly wider than average, with a straight and straightened torso.\n"
            "- **Hip Width**: Average hip width, slightly wider than the waist.\n"
            "- ****Bust/Breasts**: The bust is slightly fuller than average, with a round and \u4e30\u6ee1\u7684shape.\n"
            "- **Body-Preservation Notes**: No visible marks, no visible health damage, no visible health deformities, "
            "no visible health marks, no visible health stance."
        )

        cleaned = NodeControlState._clean_avatar_profile_body_description(raw_body)

        self.assertIn("- Height Impression: height, standing posture", cleaned)
        self.assertIn("- Shoulder-to-waist-to-hip ratio: The shoulders are slightly wider, with a straight torso", cleaned)
        self.assertIn("- Hip Width: hip width, slightly wider than the waist", cleaned)
        self.assertIn("- Bust/Breasts: The bust is slightly fuller, with a round shape", cleaned)
        self.assertIn("- Body-Preservation Notes: Preserve visible silhouette", cleaned)
        self.assertNotIn("*", cleaned)
        self.assertNotIn("****:", cleaned)
        self.assertNotIn("health damage", cleaned)
        self.assertNotIn("straightened", cleaned)
        self.assertNotIn("than average", cleaned)
        self.assertNotRegex(cleaned, r"[\u0080-\uffff]")

    def test_avatar_generation_body_depth_profile_submits_preprocess_workflow(self):
        class _AvatarBodyDepthServiceManager:
            def __init__(self, input_dir: Path, output_dir: Path):
                self.input_dir = input_dir
                self.output_dir = output_dir
                self.listener_calls = []

            def get_status(self):
                return {
                    "comfyui_gpu": {"state": "running", "pid": 123, "restart_count": 0},
                    "comfyui_webui": {
                        "state": "running",
                        "runtime": "gpu",
                        "socket_path": "/tmp/comfyui.sock",
                        "manual_paths": {
                            "input_dir": str(self.input_dir),
                            "output_dir": str(self.output_dir),
                        },
                    },
                }

            def ensure_comfyui_progress_listener(self, *, client_id: str | None = None):
                self.listener_calls.append(client_id)
                return {"started": True, "client_id": client_id}

        with tempfile.TemporaryDirectory() as tmp:
            input_dir = Path(tmp) / "manual-input"
            output_dir = Path(tmp) / "manual-output"
            service_manager = _AvatarBodyDepthServiceManager(input_dir=input_dir, output_dir=output_dir)
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-api-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-api-test"),
                service_manager=service_manager,
            )

            async def _fake_start_service(*, target: str):
                return {"status": "ok", "services": service_manager.get_status()}

            request_bodies: list[dict] = []

            def _fake_uds_request(*, socket_path: str, method: str, path: str, body: dict):
                request_bodies.append(body)
                return {"prompt_id": "prompt-body-depth", "number": 1, "node_errors": {}}

            state.start_service = _fake_start_service
            state.save_avatar_profile(
                payload=AvatarProfileSaveRequest(
                    name="Jane Avatar",
                    face_image_filename="face.png",
                    face_image_data_base64=base64.b64encode(b"face-image").decode("ascii"),
                    body_image_filename="body.png",
                    body_image_data_base64=base64.b64encode(b"body-image").decode("ascii"),
                )
            )
            uploaded = state.upload_avatar_profile_reference(
                profile_id="Jane_Avatar",
                payload=AvatarProfileReferenceUploadRequest(
                    role="body_depth",
                    name="Standing Body",
                    filename="standing.png",
                    data_base64=base64.b64encode(b"standing-body").decode("ascii"),
                ),
            )
            with patch.object(state, "_free_manual_image_runtime_models", return_value={"attempted": False}), patch.object(
                state,
                "_uds_json_request",
                side_effect=_fake_uds_request,
            ):
                result = asyncio.run(
                    state.generate_avatar_body_depth_profile(
                        profile_id="Jane_Avatar",
                        payload=AvatarBodyDepthProfileGenerateRequest(
                            source_filenames=[uploaded["reference"]["filename"]],
                            width=512,
                            height=768,
                            depth_resolution=1024,
                        ),
                    )
                )

        workflow = request_bodies[0]["prompt"]
        self.assertEqual(result["status"], "submitted")
        self.assertEqual(result["prompt_id"], "prompt-body-depth")
        self.assertEqual(service_manager.listener_calls, ["hexe-node-avatar-body-depth"])
        self.assertEqual(workflow["1"]["class_type"], "LoadImage")
        self.assertEqual(workflow["1"]["inputs"]["image"], uploaded["reference"]["input_image"])
        self.assertEqual(workflow["2"]["inputs"]["target_width"], 512)
        self.assertEqual(workflow["2"]["inputs"]["target_height"], 768)
        self.assertEqual(workflow["4"]["class_type"], "RemoveBackground")
        self.assertEqual(workflow["6"]["class_type"], "JoinImageWithAlpha")
        self.assertEqual(workflow["8"]["class_type"], "DepthAnythingV2Preprocessor")
        self.assertEqual(workflow["8"]["inputs"]["image"], ["6", 0])
        self.assertIn("avatar_body_", workflow["7"]["inputs"]["filename_prefix"])
        self.assertIn("avatar_body_depth_", workflow["9"]["inputs"]["filename_prefix"])

    def test_avatar_generation_body_depth_profile_imports_outputs_and_replaces_raw_refs(self):
        class _AvatarBodyDepthImportServiceManager:
            def __init__(self, input_dir: Path, output_dir: Path):
                self.input_dir = input_dir
                self.output_dir = output_dir

            def get_status(self):
                return {
                    "comfyui_gpu": {"state": "running", "pid": 123, "restart_count": 0},
                    "comfyui_webui": {
                        "state": "running",
                        "runtime": "gpu",
                        "manual_paths": {
                            "input_dir": str(self.input_dir),
                            "output_dir": str(self.output_dir),
                        },
                    },
                }

            def comfyui_webui_generation_status(self):
                return {
                    "session": {"queue_active": False, "running_count": 0, "pending_count": 0},
                    "progress": {"available": False},
                }

        with tempfile.TemporaryDirectory() as tmp:
            input_dir = Path(tmp) / "manual-input"
            output_dir = Path(tmp) / "manual-output"
            service_manager = _AvatarBodyDepthImportServiceManager(input_dir=input_dir, output_dir=output_dir)
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-api-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-api-test"),
                service_manager=service_manager,
            )
            state.save_avatar_profile(
                payload=AvatarProfileSaveRequest(
                    name="Jane Avatar",
                    face_image_filename="face.png",
                    face_image_data_base64=base64.b64encode(b"face-image").decode("ascii"),
                    body_image_filename="body.png",
                    body_image_data_base64=base64.b64encode(b"body-image").decode("ascii"),
                )
            )
            uploaded = state.upload_avatar_profile_reference(
                profile_id="Jane_Avatar",
                payload=AvatarProfileReferenceUploadRequest(
                    role="body_depth",
                    name="Standing Body",
                    filename="standing.png",
                    data_base64=base64.b64encode(b"standing-body").decode("ascii"),
                ),
            )
            profile_dir = input_dir / "avatar_profiles" / "Jane_Avatar"
            raw_path = profile_dir / "refs" / "body_depth" / uploaded["reference"]["filename"]
            output_body_prefix = "hexe/avatar_profile_body_depth/Jane_Avatar/avatar_body_standing_123_01"
            output_depth_prefix = "hexe/avatar_profile_body_depth/Jane_Avatar/avatar_body_depth_standing_123_01"
            body_output = output_dir / f"{output_body_prefix}_00001_.png"
            depth_output = output_dir / f"{output_depth_prefix}_00001_.png"
            body_output.parent.mkdir(parents=True, exist_ok=True)
            depth_output.parent.mkdir(parents=True, exist_ok=True)
            body_output.write_bytes(b"no-bg-body")
            depth_output.write_bytes(b"depth-map")
            state._write_avatar_body_depth_profile_job(
                profile_dir=profile_dir,
                payload={
                    "schema_version": "1.0",
                    "status": "submitted",
                    "profile_id": "Jane_Avatar",
                    "prompt_id": "prompt-import",
                    "prompt_ids": ["prompt-import"],
                    "submitted_at": "2026-06-09T12:00:00+00:00",
                    "replace_source_images": True,
                    "settings": {"width": 512, "height": 768, "depth_resolution": 1024},
                    "items": [
                        {
                            "source_role": "body_depth",
                            "source_name": "Standing Body",
                            "source_filename": uploaded["reference"]["filename"],
                            "source_input_image": uploaded["reference"]["input_image"],
                            "target_body_filename": "avatar_body_standing_123_01.png",
                            "target_depth_filename": "avatar_body_depth_standing_123_01.png",
                            "nobg_output_prefix": output_body_prefix,
                            "depth_output_prefix": output_depth_prefix,
                            "imported": False,
                        }
                    ],
                },
            )

            status = state.avatar_generation_status()
            profile = status["profiles"][0]
            body_refs = profile["references"]["body_depth"]
            depth_refs = profile["references"]["body_depth_map"]
            body_bytes = (profile_dir / "refs" / "body_depth" / body_refs[0]["filename"]).read_bytes()
            depth_bytes = (profile_dir / "refs" / "body_depth_map" / depth_refs[0]["filename"]).read_bytes()
            raw_exists = raw_path.exists()

        self.assertEqual(profile["body_depth_profile"]["status"], "completed")
        self.assertEqual(profile["body_depth_profile"]["generated_count"], 1)
        self.assertEqual(profile["body_depth_profile"]["depth_map_count"], 1)
        self.assertFalse(raw_exists)
        self.assertEqual(body_refs[0]["filename"], "avatar_body_standing_123_01.png")
        self.assertTrue(body_refs[0]["background_removed"])
        self.assertEqual(depth_refs[0]["filename"], "avatar_body_depth_standing_123_01.png")
        self.assertEqual(body_bytes, b"no-bg-body")
        self.assertEqual(depth_bytes, b"depth-map")

    def test_avatar_generation_updates_extracted_profile_data(self):
        class _AvatarProfileServiceManager:
            def __init__(self, input_dir: str):
                self.input_dir = input_dir

            def get_status(self):
                return {
                    "comfyui_webui": {
                        "state": "running",
                        "runtime": "gpu",
                        "manual_paths": {"input_dir": self.input_dir},
                    }
                }

        with tempfile.TemporaryDirectory() as tmp:
            input_dir = Path(tmp) / "manual-input"
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-api-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-api-test"),
                service_manager=_AvatarProfileServiceManager(str(input_dir)),
            )
            state.save_avatar_profile(
                payload=AvatarProfileSaveRequest(
                    name="Jane Avatar",
                    description="manual note",
                    face_image_filename="face.png",
                    face_image_data_base64=base64.b64encode(b"face-image").decode("ascii"),
                    body_image_filename="body.png",
                    body_image_data_base64=base64.b64encode(b"body-image").decode("ascii"),
                )
            )

            result = state.update_avatar_profile_extraction(
                profile_id="Jane_Avatar",
                payload=AvatarProfileExtractionUpdateRequest(
                    face_description="edited face detail",
                    body_description="edited body detail",
                    structured={
                        "profile_name": "Jane Avatar",
                        "permanent_identity": {"identity_prompt": "edited same Jane identity"},
                        "body_profile": {"body_prompt": "- **Legs**: edited leg detail."},
                        "negative_prompt_terms": ["different person", "no eyes"],
                    },
                ),
            )
            profile_path = input_dir / "avatar_profiles" / "Jane_Avatar" / "profile.json"
            metadata = json.loads(profile_path.read_text(encoding="utf-8"))

        self.assertEqual(result["status"], "updated")
        self.assertEqual(result["extraction"]["status"], "edited")
        self.assertEqual(result["extraction"]["face_description"], "edited face detail")
        self.assertEqual(result["extraction"]["body_description"], "edited body detail")
        self.assertEqual(result["extraction"]["structured"]["identity_prompt"], "edited same Jane identity")
        self.assertEqual(result["extraction"]["structured"]["body_profile"]["legs_feet"], "edited leg detail.")
        self.assertEqual(result["extraction"]["structured"]["negative_prompt_terms"], ["different person"])
        self.assertEqual(metadata["extraction"]["structured"]["schema_version"], "2.0")

    def test_avatar_generation_extracts_structured_profile_data(self):
        class _AvatarProfileServiceManager:
            def __init__(self, input_dir: str):
                self.input_dir = input_dir

            def get_status(self):
                return {
                    "comfyui_webui": {
                        "state": "stopped",
                        "runtime": "gpu",
                        "manual_paths": {"input_dir": self.input_dir},
                    },
                    "vision_llm": {
                        "state": "running",
                        "socket_path": "/tmp/vision.sock",
                        "default_model_id": "vision-model",
                    },
                    "local_llm": {
                        "state": "running",
                        "socket_path": "/tmp/local.sock",
                        "model_id": "local-model",
                    },
                }

        with tempfile.TemporaryDirectory() as tmp:
            input_dir = Path(tmp) / "manual-input"
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-api-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-api-test"),
                service_manager=_AvatarProfileServiceManager(str(input_dir)),
            )
            state.save_avatar_profile(
                payload=AvatarProfileSaveRequest(
                    name="Jane Avatar",
                    description="manual note",
                    face_image_filename="face.png",
                    face_image_data_base64=base64.b64encode(b"face-image").decode("ascii"),
                    body_image_filename="body.png",
                    body_image_data_base64=base64.b64encode(b"body-image").decode("ascii"),
                )
            )
            structured = {
                "schema_version": "2.0",
                "profile_name": "Jane Avatar",
                "permanent_identity": {
                    "face": {"shape": "oval"},
                    "identity_prompt": "same Jane Avatar identity",
                },
                "body_profile": {
                    "shape": "curvy",
                    "body_prompt": (
                        "- **Bust/Breasts**: Visible rounded bust silhouette.\n"
                        "- **Buttocks/Glutes**: Visible rounded glute silhouette.\n"
                        "- **Arms**: Slender arms and long fingers.\n"
                        "- **Legs**: Long legs with tapered calves."
                    ),
                },
                "removable_clothing": {"current": "black dress"},
                "accessories": {"permanent_accessories": ["blue headset"]},
                "pose_reference": {"current_pose": "hands on hips"},
                "prompt_sections": "identity, body, pose",
                "negative_prompt_terms": ["different person", "no eyes", "changed body proportions"],
            }
            responses = [
                {"choices": [{"message": {"content": "face: oval face and dark hair"}}]},
                {"choices": [{"message": {"content": "body: full body hourglass silhouette"}}]},
                {"choices": [{"message": {"content": json.dumps(structured)}}]},
            ]

            with patch.object(state, "_uds_json_request", side_effect=responses) as request:
                result = state.extract_avatar_profile_data(profile_id="Jane_Avatar")

            profile_path = input_dir / "avatar_profiles" / "Jane_Avatar" / "profile.json"
            metadata = json.loads(profile_path.read_text(encoding="utf-8"))

        self.assertEqual(request.call_count, 3)
        face_request = request.call_args_list[0].kwargs
        body_request = request.call_args_list[1].kwargs
        llm_request = request.call_args_list[2].kwargs
        face_prompt = face_request["body"]["messages"][0]["content"][0]["text"]
        body_prompt = body_request["body"]["messages"][0]["content"][0]["text"]
        llm_system_prompt = llm_request["body"]["messages"][0]["content"]
        self.assertEqual(face_request["body"]["max_tokens"], 1200)
        self.assertEqual(face_request["timeout_s"], 45)
        self.assertIn("eyelids", face_prompt)
        self.assertIn("skin texture", face_prompt)
        self.assertEqual(body_request["body"]["max_tokens"], 1700)
        self.assertEqual(body_request["timeout_s"], 60)
        self.assertIn("bust/breasts", body_prompt)
        self.assertIn("buttocks/glutes", body_prompt)
        self.assertIn("finger length", body_prompt)
        self.assertIn("legs", body_prompt)
        self.assertIn("Do not use 'average'", body_prompt)
        self.assertIn("shoulder-to-waist-to-hip ratio", body_prompt)
        self.assertEqual(llm_request["timeout_s"], 90)
        self.assertIn("bust_breasts", llm_system_prompt)
        self.assertIn("buttocks_glutes", llm_system_prompt)
        self.assertIn("arms_hands_fingers", llm_system_prompt)
        self.assertIn("legs_feet", llm_system_prompt)
        self.assertIn("Avoid using average as filler", llm_system_prompt)
        self.assertEqual(result["extraction"]["vision_model_id"], "vision-model")
        self.assertEqual(result["extraction"]["local_llm_model_id"], "local-model")
        self.assertEqual(result["extraction"]["structured"]["identity_prompt"], "same Jane Avatar identity")
        self.assertEqual(result["extraction"]["structured"]["schema_version"], "2.0")
        self.assertIsInstance(result["extraction"]["structured"]["prompt_sections"], dict)
        self.assertEqual(result["extraction"]["structured"]["prompt_sections"]["identity"], "same Jane Avatar identity")
        self.assertEqual(result["extraction"]["structured"]["body_profile"]["shape"], "curvy")
        self.assertEqual(result["extraction"]["structured"]["body_profile"]["bust_breasts"], "Visible rounded bust silhouette.")
        self.assertEqual(result["extraction"]["structured"]["body_profile"]["buttocks_glutes"], "Visible rounded glute silhouette.")
        self.assertEqual(result["extraction"]["structured"]["body_profile"]["arms_hands_fingers"], "Slender arms and long fingers.")
        self.assertEqual(result["extraction"]["structured"]["body_profile"]["legs_feet"], "Long legs with tapered calves.")
        self.assertEqual(result["extraction"]["structured"]["removable_clothing"]["current"], "black dress")
        self.assertEqual(result["extraction"]["structured"]["negative_prompt_terms"], ["different person", "changed body proportions"])
        self.assertEqual(metadata["extraction"]["face_description"], "face: oval face and dark hair")
        self.assertEqual(metadata["extraction"]["body_description"], "body: full body hourglass silhouette")
        self.assertNotIn("no eyes", metadata["extraction"]["structured"]["negative_identity_prompt"])

    def test_avatar_generation_extract_falls_back_when_local_llm_times_out(self):
        class _AvatarProfileServiceManager:
            def __init__(self, input_dir: str):
                self.input_dir = input_dir

            def get_status(self):
                return {
                    "comfyui_webui": {
                        "state": "stopped",
                        "runtime": "gpu",
                        "manual_paths": {"input_dir": self.input_dir},
                    },
                    "vision_llm": {
                        "state": "running",
                        "socket_path": "/tmp/vision.sock",
                        "default_model_id": "vision-model",
                    },
                    "local_llm": {
                        "state": "running",
                        "socket_path": "/tmp/local.sock",
                        "model_id": "local-model",
                    },
                }

        with tempfile.TemporaryDirectory() as tmp:
            input_dir = Path(tmp) / "manual-input"
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-api-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-api-test"),
                service_manager=_AvatarProfileServiceManager(str(input_dir)),
            )
            state.save_avatar_profile(
                payload=AvatarProfileSaveRequest(
                    name="Jane Avatar",
                    description="manual note",
                    face_image_filename="face.png",
                    face_image_data_base64=base64.b64encode(b"face-image").decode("ascii"),
                    body_image_filename="body.png",
                    body_image_data_base64=base64.b64encode(b"body-image").decode("ascii"),
                )
            )
            responses = [
                {"choices": [{"message": {"content": "face: oval face and dark hair"}}]},
                {
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    "body: full body hourglass silhouette\n"
                                    "- **Body-Preservation Notes**: No visible marks, no visible health damage, "
                                    "no visible marks, no visible health deformities, no visible asymmetries."
                                )
                            }
                        }
                    ]
                },
                TimeoutError("timed out"),
            ]

            with patch.object(state, "_uds_json_request", side_effect=responses) as request:
                result = state.extract_avatar_profile_data(profile_id="Jane_Avatar")

            profile_path = input_dir / "avatar_profiles" / "Jane_Avatar" / "profile.json"
            metadata = json.loads(profile_path.read_text(encoding="utf-8"))

        self.assertEqual(request.call_count, 3)
        self.assertEqual(request.call_args_list[0].kwargs["timeout_s"], 45)
        self.assertEqual(request.call_args_list[1].kwargs["timeout_s"], 60)
        self.assertEqual(request.call_args_list[2].kwargs["timeout_s"], 90)
        self.assertEqual(result["extraction"]["local_llm_model_id"], "local_rules")
        self.assertEqual(result["extraction"]["structured"]["schema_version"], "2.0")
        self.assertIsInstance(result["extraction"]["structured"]["prompt_sections"], dict)
        self.assertEqual(result["extraction"]["structured"]["prompt_sections"]["identity"], "manual note")
        self.assertIn("full body hourglass", result["extraction"]["structured"]["prompt_sections"]["body_shape"])
        self.assertNotIn("health damage", result["extraction"]["structured"]["prompt_sections"]["body_shape"])
        self.assertLessEqual(result["extraction"]["structured"]["prompt_sections"]["body_shape"].count("No visible marks"), 1)
        self.assertEqual(
            result["extraction"]["structured"]["source_quality_notes"]["structured_source"],
            "vision_descriptions_local_rules",
        )
        self.assertEqual(result["extraction"]["structured"]["source_quality_notes"]["local_llm_model_id"], "local-model")
        self.assertIn("timed out", result["extraction"]["structured"]["source_quality_notes"]["local_llm_error"])
        self.assertEqual(metadata["extraction"]["structured"]["schema_version"], "2.0")

    def test_manual_image_vision_describe_uses_local_vision_socket(self):
        class _VisionServiceManager:
            def __init__(self, input_dir: str):
                self.input_dir = input_dir

            def get_status(self):
                return {
                    "comfyui_webui": {
                        "state": "running",
                        "runtime": "gpu",
                        "manual_paths": {"input_dir": self.input_dir},
                    },
                    "vision_llm": {
                        "state": "running",
                        "socket_path": "/tmp/vision.sock",
                        "default_model_id": "qwen2.5-vl-3b-instruct-q4_k_m",
                    },
                }

        with tempfile.TemporaryDirectory() as tmp:
            input_dir = Path(tmp) / "manual-input"
            reference_dir = input_dir / "references" / "avatar"
            reference_dir.mkdir(parents=True)
            reference_path = reference_dir / "jane.png"
            reference_path.write_bytes(b"png-data")
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-api-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-api-test"),
                service_manager=_VisionServiceManager(str(input_dir)),
            )
            llm_response = {"choices": [{"message": {"content": "avatar with red hair in a studio scene"}}]}
            with patch.object(state, "_uds_json_request", return_value=llm_response) as request:
                result = state.manual_image_vision_describe(
                    payload=ManualImageVisionDescribeRequest(
                        mode="avatar",
                        reference_relative_path="avatar/jane.png",
                    )
                )

        self.assertEqual(result["provider"], "vision_llm")
        self.assertIn("red hair", result["description"])
        request.assert_called_once()
        body = request.call_args.kwargs["body"]
        self.assertEqual(request.call_args.kwargs["socket_path"], "/tmp/vision.sock")
        self.assertEqual(body["messages"][0]["content"][1]["type"], "image_url")

    def test_delete_manual_image_output_stays_inside_manual_output_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "manual-output"
            image_path = output_dir / "hexe" / "sample.png"
            image_path.parent.mkdir(parents=True)
            image_path.write_bytes(b"png")
            outside_path = Path(tmp) / "outside.png"
            outside_path.write_bytes(b"keep")
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-api-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-api-test"),
            )
            with patch.object(state, "_manual_image_output_dir", return_value=output_dir.resolve()):
                result = state.delete_manual_image_output(relative_path="hexe/sample.png")
                with self.assertRaises(ValueError):
                    state.delete_manual_image_output(relative_path="../outside.png")
                self.assertFalse(image_path.exists())
                self.assertTrue(outside_path.exists())

        self.assertTrue(result["deleted"])

    def test_delete_manual_image_output_uses_container_fallback_on_permission_error(self):
        class _ManualImageServiceManager:
            def get_status(self):
                return {
                    "comfyui_gpu": {"state": "running", "container_name": "hexe-ai-node-comfyui"},
                    "comfyui_webui": {"state": "running", "runtime": "gpu"},
                }

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "manual-output"
            image_path = output_dir / "hexe" / "sample.png"
            image_path.parent.mkdir(parents=True)
            image_path.write_bytes(b"png")
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-api-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-api-test"),
                service_manager=_ManualImageServiceManager(),
            )

            def _unlink_side_effect(path_self: Path):
                if path_self == image_path.resolve():
                    raise PermissionError
                raise FileNotFoundError

            with (
                patch.object(state, "_manual_image_output_dir", return_value=output_dir.resolve()),
                patch.object(Path, "unlink", autospec=True, side_effect=_unlink_side_effect),
                patch("subprocess.run") as run_command,
            ):
                result = state.delete_manual_image_output(relative_path="hexe/sample.png")

        self.assertTrue(result["deleted"])
        run_command.assert_called_once_with(
            ["docker", "exec", "hexe-ai-node-comfyui", "rm", "-f", "--", "/runtime/gpu/output/hexe/sample.png"],
            check=True,
        )

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
            self.assertIn("comfyui_webui_idle_close", payload["tasks"])
            self.assertEqual(payload["tasks"]["comfyui_webui_idle_close"]["schedule_name"], "interval_seconds")

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
            self.assertFalse(service_manager.calls[-1]["gpu_comfyui_critical_in_flight"])

    async def test_comfyui_webui_idle_close_job_calls_service_manager(self):
        with tempfile.TemporaryDirectory() as tmp:
            service_manager = self._FakeServiceManager()
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-test"),
                capability_runner=self._FakeCapabilityRunner(healthy=True),
                service_manager=service_manager,
            )

            result = await state._comfyui_webui_idle_close_job_once()

            self.assertEqual(result["status"], "ok")
            self.assertEqual(service_manager.calls[-1], {"comfyui_webui_idle_close": True})

    async def test_manual_comfyui_takeover_preflight_blocks_local_vision_work(self):
        class _ManualComfyServiceManager:
            def __init__(self):
                self.calls = []

            def get_status(self):
                return {"comfyui_webui": {"state": "stopped"}}

            def start(self, *, target: str):
                self.calls.append({"action": "start", "target": target})
                return {"target": target, "result": "started"}

        with tempfile.TemporaryDirectory() as tmp:
            service_manager = _ManualComfyServiceManager()
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-test"),
                capability_runner=self._FakeCapabilityRunner(healthy=True),
                service_manager=service_manager,
            )
            blocker = asyncio.Event()

            async def _blocked_runner():
                await blocker.wait()
                return {"status": "ok"}

            queued = await state._execution_queue.enqueue(
                queue="local",
                importance="normal",
                job_name="vision-blocker",
                request_payload={
                    "task_id": "vision-blocker",
                    "task_family": "task.vision_analysis",
                    "constraints": {"routing_policy": {"mode": "local_only"}},
                },
                runner=_blocked_runner,
            )
            for _ in range(50):
                status = await state._execution_queue.job_status(job_id=queued["job_id"])
                if status.get("status") == "running":
                    break
                await asyncio.sleep(0.01)
            self.assertEqual(status["status"], "running")

            preflight = await state.manual_comfyui_takeover_preflight()

            self.assertFalse(preflight["ready"])
            self.assertEqual(preflight["reason"], "vision_work_pending")
            self.assertEqual(preflight["vision_work"]["active_count"], 1)
            with self.assertRaises(ValueError):
                await state.start_service(target="comfyui_webui")
            self.assertEqual(service_manager.calls, [])
            blocker.set()
            for _ in range(50):
                status = await state._execution_queue.job_status(job_id=queued["job_id"])
                if status.get("status") == "completed":
                    break
                await asyncio.sleep(0.01)
            self.assertEqual(status["status"], "completed")

    async def test_vision_runtime_residency_job_passes_critical_gpu_comfyui_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            service_manager = self._FakeServiceManager()
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("node-control-test")),
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-test"),
                capability_runner=self._FakeCapabilityRunner(healthy=True),
                service_manager=service_manager,
            )
            blocker = asyncio.Event()

            async def _blocked_runner():
                await blocker.wait()
                return {"status": "ok"}

            await state._execution_queue.enqueue(
                queue="local",
                importance="critical",
                job_name="critical-render",
                request_payload={
                    "task_id": "task-critical-image",
                    "task_family": "task.image_generation",
                },
                runner=_blocked_runner,
            )

            result = await state._vision_runtime_residency_job_once()

            self.assertEqual(result["status"], "ok")
            self.assertTrue(service_manager.calls[-1]["gpu_comfyui_critical_in_flight"])
            blocker.set()

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
