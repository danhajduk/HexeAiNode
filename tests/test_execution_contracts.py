import logging
import unittest

from ai_node.execution.task_models import TaskExecutionRequest, TaskExecutionResult
from ai_node.providers.models import UnifiedExecutionResponse, UnifiedExecutionUsage
from ai_node.runtime.execution_telemetry import ExecutionTelemetryPublisher
from ai_node.runtime.lease_execution_mode import LeaseExecutionModeRunner
from ai_node.runtime.provider_resolver import ProviderResolutionResult
from ai_node.runtime.task_execution_service import TaskExecutionService


class _FakeProviderRuntimeManager:
    def __init__(self):
        self.last_request = None

    async def execute(self, request):
        self.last_request = request
        return UnifiedExecutionResponse(
            provider_id=str(request.requested_provider or "openai"),
            model_id=str(request.requested_model or "gpt-5-mini"),
            output_text="contract:ok",
            usage=UnifiedExecutionUsage(prompt_tokens=4, completion_tokens=6, total_tokens=10),
            latency_ms=18.0,
            estimated_cost=0.002,
        )

    def metrics_snapshot(self):
        return {
            "providers": {
                "openai": {
                    "models": {
                        "gpt-5-mini": {
                            "avg_latency": 20.0,
                            "p95_latency": 28.0,
                            "success_rate": 0.98,
                            "total_requests": 40,
                            "failed_requests": 1,
                        }
                    },
                    "totals": {
                        "total_requests": 40,
                        "successful_requests": 39,
                        "failed_requests": 1,
                        "success_rate": 0.975,
                    },
                },
                "local": {
                    "models": {
                        "mock-model-v1": {
                            "avg_latency": 30.0,
                            "p95_latency": 44.0,
                            "success_rate": 0.8,
                            "total_requests": 10,
                            "failed_requests": 2,
                        }
                    },
                    "totals": {
                        "total_requests": 10,
                        "successful_requests": 8,
                        "failed_requests": 2,
                        "success_rate": 0.8,
                    },
                },
            }
        }


class _FakeProviderResolver:
    def __init__(self, result: ProviderResolutionResult):
        self._result = result

    def resolve(self, *, request, governance_constraints=None):
        return self._result


class _FakeExecutionTelemetryPublisher:
    def __init__(self):
        self.calls = []

    async def publish_event(self, *, event_type: str, payload: dict | None = None):
        self.calls.append({"event_type": event_type, "payload": payload if isinstance(payload, dict) else {}})
        return {"published": True}


class _FakeStatusPublisher:
    def __init__(self):
        self.calls = []

    def status_payload(self):
        return {"published": bool(self.calls), "last_topic": "hexe/nodes/node-001/status"}

    async def publish_status(self, **kwargs):
        self.calls.append(kwargs)
        return {"published": True, "last_error": None, "last_topic": "hexe/nodes/node-001/status"}


class _FakeLeaseIntegration:
    def __init__(self, *, heartbeat_status="ok"):
        self.heartbeat_status = heartbeat_status
        self.calls = []

    async def request_lease(self, **kwargs):
        self.calls.append(("request_lease", kwargs))
        return type(
            "LeaseResult",
            (),
            {
                "status": "ok",
                "retryable": False,
                "payload": {
                    "lease": {"lease_id": "lease-001"},
                    "job": {
                        "job_id": "job-001",
                        "payload": {
                            "task_request": {
                                "task_id": "task-lease-001",
                                "task_family": "task.classification",
                                "requested_by": "scheduler.core",
                                "inputs": {"text": "lease hello"},
                                "trace_id": "trace-lease-001",
                            }
                        },
                    },
                },
            },
        )()

    async def heartbeat(self, **kwargs):
        self.calls.append(("heartbeat", kwargs))
        status = self.heartbeat_status
        return type(
            "HeartbeatResult",
            (),
            {
                "status": "ok" if status == "ok" else "rejected",
                "error": None if status == "ok" else "lease_expired",
                "payload": {"status": status},
            },
        )()

    async def report_progress(self, **kwargs):
        self.calls.append(("report_progress", kwargs))
        return type("ReportResult", (), {"status": "ok", "error": None, "payload": {"status": "ok"}})()

    async def complete(self, **kwargs):
        self.calls.append(("complete", kwargs))
        return type("CompleteResult", (), {"status": "ok", "error": None, "payload": {"status": "ok"}})()

    @staticmethod
    def bind_lease_to_task_request(*, request, lease_id: str):
        return request.model_copy(update={"lease_id": lease_id})


class _FakeTaskExecutionService:
    def __init__(self, *, status="completed", delay_s: float = 0.0):
        self.status = status
        self.delay_s = delay_s
        self.last_request = None

    async def execute(self, request):
        self.last_request = request
        if self.delay_s > 0:
            import asyncio

            await asyncio.sleep(self.delay_s)
        return TaskExecutionResult.model_validate(
            {
                "task_id": request.task_id,
                "status": self.status,
                "output": {"text": "lease:ok"} if self.status in {"completed", "degraded"} else None,
                "error_code": None if self.status == "completed" else "internal_execution_error",
                "error_message": None if self.status == "completed" else "failed",
                "provider_used": "openai",
                "model_used": "gpt-5-mini",
                "completed_at": "2026-03-19T17:00:00Z",
            }
        )


class ExecutionContractsTests(unittest.IsolatedAsyncioTestCase):
    async def test_valid_task_execution_contract(self):
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
            logger=logging.getLogger("execution-contracts-test"),
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
                    "inputs": {"text": "hello"},
                    "timeout_s": 45,
                    "trace_id": "trace-001",
                }
            )
        )

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.provider_used, "openai")
        self.assertEqual(result.model_used, "gpt-5-mini")
        self.assertEqual(result.metrics.total_tokens, 10)
        self.assertEqual(result.metrics.provider_success_rate, 0.98)
        self.assertIn("task_completed", [item["event_type"] for item in telemetry.calls])

    async def test_unsupported_task_rejection_contract(self):
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
            logger=logging.getLogger("execution-contracts-test"),
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

    async def test_provider_fallback_contract(self):
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
            logger=logging.getLogger("execution-contracts-test"),
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
        self.assertTrue(result.metrics.fallback_used)
        self.assertIn("provider_fallback", [item["event_type"] for item in telemetry.calls])

    async def test_governance_enforcement_contract(self):
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
            logger=logging.getLogger("execution-contracts-test"),
            declared_task_families_provider=lambda: ["task.classification"],
            accepted_capability_profile_provider=lambda: {"declared_task_families": ["task.classification"]},
            governance_bundle_provider=lambda: {"generic_node_class_rules": {"allow_task_families": ["summarization"]}},
        )

        result = await service.execute(
            TaskExecutionRequest.model_validate(
                {
                    "task_id": "task-governance",
                    "task_family": "task.classification",
                    "requested_by": "service.alpha",
                    "inputs": {"text": "hello"},
                    "trace_id": "trace-governance",
                }
            )
        )

        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.error_code, "governance_violation_task_family")

    async def test_lease_lifecycle_contract(self):
        telemetry = _FakeExecutionTelemetryPublisher()
        runner = LeaseExecutionModeRunner(
            lease_integration=_FakeLeaseIntegration(),
            task_execution_service=_FakeTaskExecutionService(status="completed"),
            logger=logging.getLogger("execution-contracts-test"),
            heartbeat_interval_s=60.0,
            execution_telemetry_publisher=telemetry,
        )

        result = await runner.run_once(core_api_endpoint="http://10.0.0.100:9001", trust_token="trust-token")

        self.assertEqual(result["status"], "completed")
        self.assertIn("task_progress", [item["event_type"] for item in telemetry.calls])

    async def test_lease_expiration_contract(self):
        runner = LeaseExecutionModeRunner(
            lease_integration=_FakeLeaseIntegration(heartbeat_status="expired"),
            task_execution_service=_FakeTaskExecutionService(status="completed", delay_s=0.6),
            logger=logging.getLogger("execution-contracts-test"),
            heartbeat_interval_s=0.5,
        )

        result = await runner.run_once(core_api_endpoint="http://10.0.0.100:9001", trust_token="trust-token")

        self.assertEqual(result["status"], "lease_lost")

    async def test_trusted_telemetry_transport_contract(self):
        status_publisher = _FakeStatusPublisher()
        publisher = ExecutionTelemetryPublisher(
            logger=logging.getLogger("execution-contracts-test"),
            node_id="node-001",
            trust_state_provider=lambda: {"operational_mqtt_host": "10.0.0.1", "operational_mqtt_port": 1883},
            status_publisher=status_publisher,
        )

        result = await publisher.publish_event(
            event_type="task_received",
            payload={"task_id": "task-telemetry", "task_family": "task.classification"},
        )

        self.assertTrue(result["published"])
        self.assertEqual(status_publisher.calls[0]["payload"]["event_type"], "task_received")
        self.assertEqual(status_publisher.calls[0]["node_id"], "node-001")


if __name__ == "__main__":
    unittest.main()
