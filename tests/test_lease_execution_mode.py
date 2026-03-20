import asyncio
import logging
import unittest

from ai_node.execution.task_models import TaskExecutionResult
from ai_node.runtime.lease_execution_mode import LeaseExecutionModeRunner


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
                                "task_id": "task-001",
                                "task_family": "task.classification",
                                "requested_by": "scheduler.core",
                                "inputs": {"text": "hello"},
                                "trace_id": "trace-001",
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
            await asyncio.sleep(self.delay_s)
        return TaskExecutionResult.model_validate(
            {
                "task_id": request.task_id,
                "status": self.status,
                "output": {"text": "ok"} if self.status in {"completed", "degraded"} else None,
                "error_code": None if self.status == "completed" else "internal_execution_error",
                "error_message": None if self.status == "completed" else "failed",
                "provider_used": "openai",
                "model_used": "gpt-5-mini",
                "completed_at": "2026-03-19T17:00:00Z",
            }
        )


class _FakeExecutionTelemetryPublisher:
    def __init__(self):
        self.calls = []

    async def publish_event(self, *, event_type: str, payload: dict | None = None):
        self.calls.append({"event_type": event_type, "payload": payload if isinstance(payload, dict) else {}})
        return {"published": True}


class LeaseExecutionModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_once_requests_lease_executes_task_and_completes(self):
        integration = _FakeLeaseIntegration()
        service = _FakeTaskExecutionService(status="completed")
        telemetry = _FakeExecutionTelemetryPublisher()
        runner = LeaseExecutionModeRunner(
            lease_integration=integration,
            task_execution_service=service,
            logger=logging.getLogger("lease-execution-mode-test"),
            heartbeat_interval_s=60.0,
            execution_telemetry_publisher=telemetry,
        )

        result = await runner.run_once(core_api_endpoint="http://10.0.0.100:9001", trust_token="trust-token")

        self.assertEqual(result["status"], "completed")
        self.assertEqual(service.last_request.lease_id, "lease-001")
        self.assertEqual(integration.calls[0][0], "request_lease")
        self.assertTrue(any(call[0] == "complete" for call in integration.calls))
        self.assertIn("task_progress", [call["event_type"] for call in telemetry.calls])

    async def test_run_once_reports_lease_lost_when_heartbeat_fails(self):
        integration = _FakeLeaseIntegration(heartbeat_status="expired")
        service = _FakeTaskExecutionService(status="completed", delay_s=0.6)
        runner = LeaseExecutionModeRunner(
            lease_integration=integration,
            task_execution_service=service,
            logger=logging.getLogger("lease-execution-mode-test"),
            heartbeat_interval_s=0.5,
        )

        result = await runner.run_once(core_api_endpoint="http://10.0.0.100:9001", trust_token="trust-token")

        self.assertEqual(result["status"], "lease_lost")

    async def test_run_once_completes_lease_when_execution_result_is_degraded(self):
        integration = _FakeLeaseIntegration()
        service = _FakeTaskExecutionService(status="degraded")
        runner = LeaseExecutionModeRunner(
            lease_integration=integration,
            task_execution_service=service,
            logger=logging.getLogger("lease-execution-mode-test"),
            heartbeat_interval_s=60.0,
        )

        result = await runner.run_once(core_api_endpoint="http://10.0.0.100:9001", trust_token="trust-token")

        self.assertEqual(result["status"], "completed")
        complete_calls = [call for call in integration.calls if call[0] == "complete"]
        self.assertTrue(complete_calls)
        self.assertEqual(complete_calls[-1][1]["status"], "completed")


if __name__ == "__main__":
    unittest.main()
