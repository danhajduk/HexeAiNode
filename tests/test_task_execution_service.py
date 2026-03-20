import logging
import tempfile
import unittest
from pathlib import Path

from ai_node.execution.task_models import TaskExecutionRequest
from ai_node.persistence.budget_state_store import BudgetStateStore
from ai_node.providers.models import UnifiedExecutionResponse, UnifiedExecutionUsage
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

    async def test_execute_returns_unsupported_for_non_canonical_family(self):
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
                    "task_id": "task-unsupported",
                    "task_family": "task.chat_response",
                    "requested_by": "service.alpha",
                    "inputs": {"text": "hello"},
                    "trace_id": "trace-unsupported",
                }
            )
        )

        self.assertEqual(result.status, "unsupported")
        self.assertEqual(result.error_code, "unsupported_task_family")

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
