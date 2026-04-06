import logging
import tempfile
import unittest
from pathlib import Path

from ai_node.execution.task_models import TaskExecutionRequest
from ai_node.persistence.budget_state_store import BudgetStateStore
from ai_node.providers.models import UnifiedExecutionResponse, UnifiedExecutionUsage
from ai_node.persistence.client_usage_store import ClientUsageStore
from ai_node.runtime.provider_resolver import ProviderResolutionResult
from ai_node.runtime.budget_manager import BudgetManager
from ai_node.runtime.task_execution_service import TaskExecutionService


class _FakeProviderRuntimeManager:
    def __init__(self):
        self.last_request = None

    async def execute(self, request):
        self.last_request = request
        return UnifiedExecutionResponse(
            provider_id=str(request.requested_provider or "openai"),
            model_id=str(request.requested_model or "gpt-5-mini"),
            output_text="mock:hello world",
            usage=UnifiedExecutionUsage(prompt_tokens=2, completion_tokens=4, total_tokens=6),
            latency_ms=12.5,
            estimated_cost=0.001,
        )

    def metrics_snapshot(self):
        return {
            "providers": {
                "openai": {
                    "models": {
                        "gpt-5-mini": {
                            "avg_latency": 15.0,
                            "p95_latency": 20.0,
                            "success_rate": 0.95,
                            "total_requests": 20,
                            "failed_requests": 1,
                        }
                    }
                },
                "local": {
                    "models": {
                        "mock-model-v1": {
                            "avg_latency": 32.0,
                            "p95_latency": 40.0,
                            "success_rate": 0.8,
                            "total_requests": 5,
                            "failed_requests": 1,
                        }
                    }
                },
            }
        }


class _FakeProviderResolver:
    def __init__(self, result: ProviderResolutionResult):
        self._result = result
        self.last_request = None
        self.last_governance = None

    def resolve(self, *, request, governance_constraints=None):
        self.last_request = request
        self.last_governance = governance_constraints
        return self._result


class _FakeExecutionTelemetryPublisher:
    def __init__(self):
        self.calls = []

    async def publish_event(self, *, event_type: str, payload: dict | None = None):
        self.calls.append({"event_type": event_type, "payload": payload if isinstance(payload, dict) else {}})
        return {"published": True}


def _active_budget_policy() -> dict:
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


class TaskExecutionServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_execute_returns_completed_result_for_supported_authorized_task(self):
        runtime_manager = _FakeProviderRuntimeManager()
        telemetry = _FakeExecutionTelemetryPublisher()
        resolver = _FakeProviderResolver(
            ProviderResolutionResult(
                allowed=True,
                provider_id="openai",
                model_id="gpt-5-mini",
                provider_order=["openai"],
                fallback_provider_ids=[],
                model_allowlist_by_provider={"openai": ["gpt-5-mini"]},
                timeout_s=45,
                retry_count=1,
                rejection_reason=None,
            )
        )
        service = TaskExecutionService(
            provider_runtime_manager=runtime_manager,
            provider_resolver=resolver,
            logger=logging.getLogger("task-execution-service-test"),
            prompt_services_state_provider=lambda: {
                "prompt_services": [
                    {"prompt_id": "prompt.alpha", "task_family": "task.classification", "status": "registered"}
                ]
            },
            declared_task_families_provider=lambda: ["task.classification"],
            accepted_capability_profile_provider=lambda: {"declared_task_families": ["task.classification"]},
            execution_telemetry_publisher=telemetry,
        )

        result = await service.execute(
            TaskExecutionRequest.model_validate(
                {
                    "task_id": "task-001",
                    "prompt_id": "prompt.alpha",
                    "task_family": "task.classification",
                    "requested_by": "service.alpha",
                    "requested_provider": "openai",
                    "requested_model": "gpt-5-mini",
                    "inputs": {"text": "hello world"},
                    "timeout_s": 45,
                    "trace_id": "trace-001",
                }
            )
        )

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.provider_used, "openai")
        self.assertEqual(result.model_used, "gpt-5-mini")
        self.assertEqual(result.output, {"text": "mock:hello world"})
        self.assertEqual(runtime_manager.last_request.requested_provider, "openai")
        self.assertEqual(runtime_manager.last_request.requested_model, "gpt-5-mini")
        self.assertEqual(service.lifecycle_tracker.history_payload()["history"][0]["state"], "completed")
        self.assertEqual(service.lifecycle_tracker.history_payload()["history"][0]["details"]["requested_by"], "service.alpha")
        self.assertEqual(service.lifecycle_tracker.history_payload()["history"][0]["details"]["prompt_id"], "prompt.alpha")
        self.assertEqual(service.lifecycle_tracker.history_payload()["history"][0]["details"]["estimated_cost"], 0.001)
        self.assertEqual(result.metrics.provider_avg_latency_ms, 15.0)
        self.assertEqual(result.metrics.provider_p95_latency_ms, 20.0)
        self.assertEqual(result.metrics.provider_success_rate, 0.95)
        self.assertEqual(result.metrics.provider_total_requests, 20)
        self.assertEqual(result.metrics.provider_failed_requests, 1)
        self.assertEqual(
            [item["event_type"] for item in telemetry.calls],
            ["task_received", "provider_selected", "task_started", "task_completed"],
        )

    async def test_execute_emits_provider_fallback_when_resolution_contains_fallbacks(self):
        telemetry = _FakeExecutionTelemetryPublisher()
        service = TaskExecutionService(
            provider_runtime_manager=_FakeProviderRuntimeManager(),
            provider_resolver=_FakeProviderResolver(
                ProviderResolutionResult(
                    allowed=True,
                    provider_id="local",
                    model_id="mock-model-v1",
                    provider_order=["openai", "local"],
                    fallback_provider_ids=["openai"],
                    model_allowlist_by_provider={"local": ["mock-model-v1"]},
                    timeout_s=45,
                    retry_count=1,
                    rejection_reason=None,
                )
            ),
            logger=logging.getLogger("task-execution-service-test"),
            declared_task_families_provider=lambda: ["task.classification"],
            accepted_capability_profile_provider=lambda: {"declared_task_families": ["task.classification"]},
            execution_telemetry_publisher=telemetry,
        )

        result = await service.execute(
            TaskExecutionRequest.model_validate(
                {
                    "task_id": "task-fallback",
                    "task_family": "task.classification",
                    "requested_by": "service.alpha",
                    "inputs": {"text": "hello"},
                    "trace_id": "trace-fallback",
                }
            )
        )

        self.assertEqual(result.status, "completed")
        self.assertIn("provider_fallback", [item["event_type"] for item in telemetry.calls])

    async def test_execute_emits_budget_events_when_budget_manager_is_configured(self):
        with tempfile.TemporaryDirectory() as tmp:
            budget_manager = BudgetManager(
                store=BudgetStateStore(path=str(Path(tmp) / "budget_state.json"), logger=logging.getLogger("budget-test")),
                logger=logging.getLogger("budget-test"),
                provider_runtime_manager=_FakeProviderRuntimeManager(),
            )
            telemetry = _FakeExecutionTelemetryPublisher()
            service = TaskExecutionService(
                provider_runtime_manager=_FakeProviderRuntimeManager(),
                provider_resolver=_FakeProviderResolver(
                    ProviderResolutionResult(
                        allowed=True,
                        provider_id="openai",
                        model_id="gpt-5-mini",
                        provider_order=["openai"],
                        fallback_provider_ids=[],
                        model_allowlist_by_provider={"openai": ["gpt-5-mini"]},
                        timeout_s=45,
                        retry_count=1,
                        rejection_reason=None,
                    )
                ),
                logger=logging.getLogger("task-execution-service-test"),
                budget_manager=budget_manager,
                declared_task_families_provider=lambda: ["task.classification"],
                accepted_capability_profile_provider=lambda: {"declared_task_families": ["task.classification"]},
                governance_bundle_provider=lambda: {"budget_policy": _active_budget_policy()},
                execution_telemetry_publisher=telemetry,
            )

            result = await service.execute(
                TaskExecutionRequest.model_validate(
                    {
                        "task_id": "task-budget-001",
                        "task_family": "task.classification",
                        "requested_by": "service.alpha",
                        "service_id": "service.alpha",
                        "inputs": {"text": "hello world"},
                        "constraints": {"max_cost_cents": 5},
                        "trace_id": "trace-budget-001",
                    }
                )
            )

            self.assertEqual(result.status, "completed")
            self.assertIn("budget_reservation", [item["event_type"] for item in telemetry.calls])
            self.assertIn("budget_finalized", [item["event_type"] for item in telemetry.calls])

    async def test_execute_records_completed_usage_in_client_usage_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            usage_store = ClientUsageStore(
                path=str(Path(tmp) / "client_usage.db"),
                logger=logging.getLogger("client-usage-test"),
            )
            service = TaskExecutionService(
                provider_runtime_manager=_FakeProviderRuntimeManager(),
                provider_resolver=_FakeProviderResolver(
                    ProviderResolutionResult(
                        allowed=True,
                        provider_id="openai",
                        model_id="gpt-5-mini",
                        provider_order=["openai"],
                        fallback_provider_ids=[],
                        model_allowlist_by_provider={"openai": ["gpt-5-mini"]},
                        timeout_s=45,
                        retry_count=1,
                        rejection_reason=None,
                    )
                ),
                logger=logging.getLogger("task-execution-service-test"),
                client_usage_store=usage_store,
                prompt_services_state_provider=lambda: {
                    "prompt_services": [
                        {"prompt_id": "prompt.email.classifier", "task_family": "task.classification", "status": "registered"}
                    ]
                },
                declared_task_families_provider=lambda: ["task.classification"],
                accepted_capability_profile_provider=lambda: {"declared_task_families": ["task.classification"]},
            )

            result = await service.execute(
                TaskExecutionRequest.model_validate(
                    {
                        "task_id": "task-usage-001",
                        "prompt_id": "prompt.email.classifier",
                        "task_family": "task.classification",
                        "requested_by": "node-email",
                        "customer_id": "local-user",
                        "requested_provider": "openai",
                        "requested_model": "gpt-5-mini",
                        "inputs": {"text": "hello world"},
                        "timeout_s": 45,
                        "trace_id": "trace-usage-001",
                    }
                )
            )

            self.assertEqual(result.status, "completed")
            payload = usage_store.summary_payload(month_key=str(result.completed_at)[:7])
            self.assertEqual(payload["clients"][0]["client_id"], "node-email")
            self.assertEqual(payload["clients"][0]["current_month"]["calls"], 1)
            self.assertEqual(payload["clients"][0]["prompts"][0]["prompt_id"], "prompt.email.classifier")
            self.assertEqual(payload["clients"][0]["prompts"][0]["models"][0]["model_id"], "gpt-5-mini")

    async def test_execute_rejects_undeclared_canonical_family(self):
        service = TaskExecutionService(
            provider_runtime_manager=_FakeProviderRuntimeManager(),
            provider_resolver=_FakeProviderResolver(
                ProviderResolutionResult(
                    allowed=True,
                    provider_id="openai",
                    model_id="gpt-5-mini",
                    provider_order=["openai"],
                    fallback_provider_ids=[],
                    model_allowlist_by_provider={"openai": ["gpt-5-mini"]},
                    timeout_s=45,
                    retry_count=0,
                    rejection_reason=None,
                )
            ),
            logger=logging.getLogger("task-execution-service-test"),
            declared_task_families_provider=lambda: ["task.classification"],
            accepted_capability_profile_provider=lambda: {"declared_task_families": ["task.classification"]},
        )

        result = await service.execute(
            TaskExecutionRequest.model_validate(
                {
                    "task_id": "task-rejected",
                    "task_family": "task.chat",
                    "requested_by": "service.alpha",
                    "inputs": {"text": "hello"},
                    "trace_id": "trace-rejected",
                }
            )
        )

        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.error_code, "task_family_not_declared")

    async def test_execute_rejects_prompt_in_probation(self):
        service = TaskExecutionService(
            provider_runtime_manager=_FakeProviderRuntimeManager(),
            provider_resolver=_FakeProviderResolver(
                ProviderResolutionResult(
                    allowed=True,
                    provider_id="openai",
                    model_id="gpt-5-mini",
                    provider_order=["openai"],
                    fallback_provider_ids=[],
                    model_allowlist_by_provider={"openai": ["gpt-5-mini"]},
                    timeout_s=45,
                    retry_count=0,
                    rejection_reason=None,
                )
            ),
            logger=logging.getLogger("task-execution-service-test"),
            prompt_services_state_provider=lambda: {
                "prompt_services": [
                    {"prompt_id": "prompt.alpha", "task_family": "task.classification", "status": "probation"}
                ]
            },
            declared_task_families_provider=lambda: ["task.classification"],
            accepted_capability_profile_provider=lambda: {"declared_task_families": ["task.classification"]},
        )

        result = await service.execute(
            TaskExecutionRequest.model_validate(
                {
                    "task_id": "task-probation",
                    "prompt_id": "prompt.alpha",
                    "task_family": "task.classification",
                    "requested_by": "service.alpha",
                    "inputs": {"text": "hello"},
                    "trace_id": "trace-probation",
                }
            )
        )

        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.error_code, "prompt_in_probation")

    async def test_execute_honors_prompt_constraints_and_definition(self):
        runtime_manager = _FakeProviderRuntimeManager()
        resolver = _FakeProviderResolver(
            ProviderResolutionResult(
                allowed=True,
                provider_id="openai",
                model_id="gpt-5-mini",
                provider_order=["openai"],
                fallback_provider_ids=[],
                model_allowlist_by_provider={"openai": ["gpt-5-mini"]},
                timeout_s=45,
                retry_count=0,
                rejection_reason=None,
            )
        )
        service = TaskExecutionService(
            provider_runtime_manager=runtime_manager,
            provider_resolver=resolver,
            logger=logging.getLogger("task-execution-service-test"),
            prompt_services_state_provider=lambda: {
                "prompt_services": [
                    {
                        "prompt_id": "prompt.alpha",
                        "task_family": "task.classification",
                        "status": "active",
                        "current_version": "v2",
                        "versions": [
                            {"version": "v1", "definition": {"system_prompt": "old prompt"}},
                            {"version": "v2", "definition": {"system_prompt": "new prompt"}},
                        ],
                        "provider_preferences": {"default_provider": "openai", "preferred_providers": ["openai"]},
                        "constraints": {"max_timeout_s": 30},
                    }
                ]
            },
            declared_task_families_provider=lambda: ["task.classification"],
            accepted_capability_profile_provider=lambda: {"declared_task_families": ["task.classification"]},
        )

        result = await service.execute(
            TaskExecutionRequest.model_validate(
                {
                    "task_id": "task-prompt-managed",
                    "prompt_id": "prompt.alpha",
                    "task_family": "task.classification",
                    "requested_by": "service.alpha",
                    "inputs": {"text": "hello"},
                    "timeout_s": 45,
                    "trace_id": "trace-prompt-managed",
                }
            )
        )

        self.assertEqual(result.status, "completed")
        self.assertEqual(resolver.last_request.timeout_s, 30)
        self.assertEqual(runtime_manager.last_request.system_prompt, "new prompt")

    async def test_execute_renders_prompt_template_for_structured_extraction(self):
        runtime_manager = _FakeProviderRuntimeManager()
        resolver = _FakeProviderResolver(
            ProviderResolutionResult(
                allowed=True,
                provider_id="openai",
                model_id="gpt-5.4-mini",
                provider_order=["openai"],
                fallback_provider_ids=[],
                model_allowlist_by_provider={"openai": ["gpt-5.4-mini"]},
                timeout_s=45,
                retry_count=0,
                rejection_reason=None,
            )
        )
        service = TaskExecutionService(
            provider_runtime_manager=runtime_manager,
            provider_resolver=resolver,
            logger=logging.getLogger("task-execution-service-test"),
            prompt_services_state_provider=lambda: {
                "prompt_services": [
                    {
                        "prompt_id": "prompt.extract",
                        "task_family": "task.structured_extraction",
                        "status": "active",
                        "current_version": "v1.0",
                        "versions": [
                            {
                                "version": "v1.0",
                                "definition": {
                                    "system_prompt": "extract deterministically",
                                    "prompt_template": "Template: {{template_id}}\nBody: {{body_text}}\nLinks: {{links_json}}\nEnabled: {{enabled}}",
                                    "template_variables": ["template_id", "body_text", "links_json", "enabled"],
                                    "default_inputs": {"enabled": True, "links_json": "[]"},
                                },
                            }
                        ],
                    }
                ]
            },
            declared_task_families_provider=lambda: ["task.structured_extraction"],
            accepted_capability_profile_provider=lambda: {"declared_task_families": ["task.structured_extraction"]},
        )

        result = await service.execute(
            TaskExecutionRequest.model_validate(
                {
                    "task_id": "task-structured",
                    "prompt_id": "prompt.extract",
                    "task_family": "task.structured_extraction",
                    "requested_by": "node-email",
                    "requested_provider": "openai",
                    "requested_model": "gpt-5.4-mini",
                    "inputs": {
                        "template_id": "recreation_gov.v1",
                        "body_text": "Order Receipt",
                        "links_json": [{"label": "My Reservations", "url": "https://example.com"}],
                        "json_schema": {
                            "type": "object",
                            "properties": {"template_id": {"type": "string"}},
                            "required": ["template_id"],
                        },
                    },
                    "trace_id": "trace-structured",
                }
            )
        )

        self.assertEqual(result.status, "completed")
        self.assertTrue(runtime_manager.last_request.system_prompt.startswith("extract deterministically"))
        self.assertIn("Template: recreation_gov.v1", runtime_manager.last_request.prompt)
        self.assertIn("Body: Order Receipt", runtime_manager.last_request.prompt)
        self.assertIn("\"label\": \"My Reservations\"", runtime_manager.last_request.prompt)
        self.assertIn("Enabled: true", runtime_manager.last_request.prompt)
        self.assertIn("Return exactly one JSON object.", runtime_manager.last_request.system_prompt)
        self.assertIn("Do not wrap the JSON object in a field named text.", runtime_manager.last_request.system_prompt)

    async def test_execute_returns_parsed_output_for_structured_extraction(self):
        class _StructuredProviderRuntimeManager:
            def __init__(self):
                self.last_request = None

            async def execute(self, request):
                self.last_request = request
                return UnifiedExecutionResponse(
                    provider_id=str(request.requested_provider or "openai"),
                    model_id=str(request.requested_model or "gpt-5.4-mini"),
                    output_text='{"schema_version":"order-phase4-template.v1","template_id":"demo","profile_id":"reservation_confirmation","template_version":"v1","enabled":true,"match":{},"extract":{},"required_fields":[],"confidence_rules":{"high_requires":[]},"post_process":{}}',
                    usage=UnifiedExecutionUsage(prompt_tokens=2, completion_tokens=4, total_tokens=6),
                    latency_ms=12.5,
                    estimated_cost=0.001,
                )

            def metrics_snapshot(self):
                return {}

        service = TaskExecutionService(
            provider_runtime_manager=_StructuredProviderRuntimeManager(),
            provider_resolver=_FakeProviderResolver(
                ProviderResolutionResult(
                    allowed=True,
                    provider_id="openai",
                    model_id="gpt-5.4-mini",
                    provider_order=["openai"],
                    fallback_provider_ids=[],
                    model_allowlist_by_provider={"openai": ["gpt-5.4-mini"]},
                    timeout_s=45,
                    retry_count=0,
                    rejection_reason=None,
                )
            ),
            logger=logging.getLogger("task-execution-service-test"),
            declared_task_families_provider=lambda: ["task.structured_extraction"],
            accepted_capability_profile_provider=lambda: {"declared_task_families": ["task.structured_extraction"]},
        )

        result = await service.execute(
            TaskExecutionRequest.model_validate(
                {
                    "task_id": "task-structured-output",
                    "task_family": "task.structured_extraction",
                    "requested_by": "node-email",
                    "inputs": {"text": "fallback input"},
                    "trace_id": "trace-structured-output",
                }
            )
        )

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.output["schema_version"], "order-phase4-template.v1")
        self.assertNotIn("text", result.output)

    async def test_execute_returns_failed_result_for_long_provider_errors(self):
        class _FailingProviderRuntimeManager:
            async def execute(self, _request):
                raise RuntimeError("x" * 6000)

            def metrics_snapshot(self):
                return {}

        service = TaskExecutionService(
            provider_runtime_manager=_FailingProviderRuntimeManager(),
            provider_resolver=_FakeProviderResolver(
                ProviderResolutionResult(
                    allowed=True,
                    provider_id="openai",
                    model_id="gpt-5.4-mini",
                    provider_order=["openai"],
                    fallback_provider_ids=[],
                    model_allowlist_by_provider={"openai": ["gpt-5.4-mini"]},
                    timeout_s=45,
                    retry_count=0,
                    rejection_reason=None,
                )
            ),
            logger=logging.getLogger("task-execution-service-test"),
            declared_task_families_provider=lambda: ["task.structured_extraction"],
            accepted_capability_profile_provider=lambda: {"declared_task_families": ["task.structured_extraction"]},
        )

        result = await service.execute(
            TaskExecutionRequest.model_validate(
                {
                    "task_id": "task-long-provider-error",
                    "task_family": "task.structured_extraction",
                    "requested_by": "node-email",
                    "inputs": {"text": "fallback input"},
                    "trace_id": "trace-long-provider-error",
                }
            )
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_code, "internal_execution_error")
        self.assertLessEqual(len(result.error_message or ""), 4000)
        self.assertTrue((result.error_message or "").endswith("..."))

    async def test_execute_degrades_when_provider_resolution_fails_due_to_provider_unavailability(self):
        service = TaskExecutionService(
            provider_runtime_manager=_FakeProviderRuntimeManager(),
            provider_resolver=_FakeProviderResolver(
                ProviderResolutionResult(
                    allowed=False,
                    provider_id=None,
                    model_id=None,
                    provider_order=[],
                    fallback_provider_ids=[],
                    model_allowlist_by_provider={},
                    timeout_s=45,
                    retry_count=0,
                    rejection_reason="no_eligible_provider_available",
                )
            ),
            logger=logging.getLogger("task-execution-service-test"),
            declared_task_families_provider=lambda: ["task.classification"],
            accepted_capability_profile_provider=lambda: {"declared_task_families": ["task.classification"]},
        )

        result = await service.execute(
            TaskExecutionRequest.model_validate(
                {
                    "task_id": "task-no-provider",
                    "task_family": "task.classification",
                    "requested_by": "service.alpha",
                    "inputs": {"text": "hello"},
                    "trace_id": "trace-no-provider",
                }
            )
        )

        self.assertEqual(result.status, "degraded")
        self.assertEqual(result.error_code, "no_eligible_provider_available")

    async def test_execute_degrades_when_provider_resolution_reports_provider_unavailable(self):
        service = TaskExecutionService(
            provider_runtime_manager=_FakeProviderRuntimeManager(),
            provider_resolver=_FakeProviderResolver(
                ProviderResolutionResult(
                    allowed=False,
                    provider_id="openai",
                    model_id=None,
                    provider_order=["openai"],
                    fallback_provider_ids=["local"],
                    model_allowlist_by_provider={},
                    timeout_s=45,
                    retry_count=1,
                    rejection_reason="no_eligible_provider_available",
                )
            ),
            logger=logging.getLogger("task-execution-service-test"),
            declared_task_families_provider=lambda: ["task.classification"],
            accepted_capability_profile_provider=lambda: {"declared_task_families": ["task.classification"]},
        )

        result = await service.execute(
            TaskExecutionRequest.model_validate(
                {
                    "task_id": "task-provider-degraded",
                    "task_family": "task.classification",
                    "requested_by": "service.alpha",
                    "inputs": {"text": "hello"},
                    "trace_id": "trace-provider-degraded",
                }
            )
        )

        self.assertEqual(result.status, "degraded")
        self.assertEqual(result.error_code, "no_eligible_provider_available")
        self.assertTrue(result.metrics.fallback_used)
        self.assertEqual(result.metrics.retries, 1)
        self.assertEqual(result.metrics.provider_total_requests, 0)

    async def test_execute_degrades_when_governance_status_is_stale(self):
        service = TaskExecutionService(
            provider_runtime_manager=_FakeProviderRuntimeManager(),
            provider_resolver=_FakeProviderResolver(
                ProviderResolutionResult(
                    allowed=True,
                    provider_id="openai",
                    model_id="gpt-5-mini",
                    provider_order=["openai"],
                    fallback_provider_ids=[],
                    model_allowlist_by_provider={"openai": ["gpt-5-mini"]},
                    timeout_s=45,
                    retry_count=0,
                    rejection_reason=None,
                )
            ),
            logger=logging.getLogger("task-execution-service-test"),
            declared_task_families_provider=lambda: ["task.classification"],
            accepted_capability_profile_provider=lambda: {"declared_task_families": ["task.classification"]},
            governance_status_provider=lambda: {"state": "stale"},
        )

        result = await service.execute(
            TaskExecutionRequest.model_validate(
                {
                    "task_id": "task-governance-stale",
                    "task_family": "task.classification",
                    "requested_by": "service.alpha",
                    "inputs": {"text": "hello"},
                    "trace_id": "trace-governance-stale",
                }
            )
        )

        self.assertEqual(result.status, "degraded")
        self.assertEqual(result.error_code, "governance_stale")

    async def test_execute_rejects_when_governance_blocks_task_family(self):
        service = TaskExecutionService(
            provider_runtime_manager=_FakeProviderRuntimeManager(),
            provider_resolver=_FakeProviderResolver(
                ProviderResolutionResult(
                    allowed=True,
                    provider_id="openai",
                    model_id="gpt-5-mini",
                    provider_order=["openai"],
                    fallback_provider_ids=[],
                    model_allowlist_by_provider={"openai": ["gpt-5-mini"]},
                    timeout_s=45,
                    retry_count=0,
                    rejection_reason=None,
                )
            ),
            logger=logging.getLogger("task-execution-service-test"),
            declared_task_families_provider=lambda: ["task.classification"],
            accepted_capability_profile_provider=lambda: {"declared_task_families": ["task.classification"]},
            governance_bundle_provider=lambda: {"generic_node_class_rules": {"allow_task_families": ["summarization"]}},
        )

        result = await service.execute(
            TaskExecutionRequest.model_validate(
                {
                    "task_id": "task-governance-family",
                    "task_family": "task.classification",
                    "requested_by": "service.alpha",
                    "inputs": {"text": "hello"},
                    "trace_id": "trace-governance-family",
                }
            )
        )

        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.error_code, "governance_violation_task_family")

    async def test_execute_rejects_when_governance_blocks_resolved_provider(self):
        service = TaskExecutionService(
            provider_runtime_manager=_FakeProviderRuntimeManager(),
            provider_resolver=_FakeProviderResolver(
                ProviderResolutionResult(
                    allowed=True,
                    provider_id="openai",
                    model_id="gpt-5-mini",
                    provider_order=["openai"],
                    fallback_provider_ids=[],
                    model_allowlist_by_provider={"openai": ["gpt-5-mini"]},
                    timeout_s=45,
                    retry_count=0,
                    rejection_reason=None,
                )
            ),
            logger=logging.getLogger("task-execution-service-test"),
            declared_task_families_provider=lambda: ["task.classification"],
            accepted_capability_profile_provider=lambda: {"declared_task_families": ["task.classification"]},
        )

        result = await service.execute(
            TaskExecutionRequest.model_validate(
                {
                    "task_id": "task-governance-provider",
                    "task_family": "task.classification",
                    "requested_by": "service.alpha",
                    "inputs": {"text": "hello"},
                    "constraints": {"governance": {"approved_providers": ["local"]}},
                    "trace_id": "trace-governance-provider",
                }
            )
        )

        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.error_code, "governance_violation_provider")


if __name__ == "__main__":
    unittest.main()
