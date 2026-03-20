import logging
import unittest

from ai_node.core_api.scheduler_lease_client import SchedulerLeaseResult
from ai_node.execution.task_models import TaskExecutionRequest
from ai_node.runtime.scheduler_lease_integration import SchedulerLeaseIntegration


class _FakeSchedulerClient:
    def __init__(self):
        self.last_call = None

    async def request_lease(self, **kwargs):
        self.last_call = ("request_lease", kwargs)
        return SchedulerLeaseResult(status="ok", payload={"lease": {"lease_id": "lease-001"}}, retryable=False)

    async def heartbeat(self, **kwargs):
        self.last_call = ("heartbeat", kwargs)
        return SchedulerLeaseResult(status="ok", payload={"status": "ok"}, retryable=False)

    async def report_progress(self, **kwargs):
        self.last_call = ("report_progress", kwargs)
        return SchedulerLeaseResult(status="ok", payload={"status": "ok"}, retryable=False)

    async def complete(self, **kwargs):
        self.last_call = ("complete", kwargs)
        return SchedulerLeaseResult(status="ok", payload={"status": "ok"}, retryable=False)


class SchedulerLeaseIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_node_binding_maps_worker_id_to_node_id_and_declared_capabilities(self):
        integration = SchedulerLeaseIntegration(
            scheduler_client=_FakeSchedulerClient(),
            logger=logging.getLogger("scheduler-lease-integration-test"),
            node_id_provider=lambda: "node-001",
            capability_provider=lambda: ["task.classification", "task.summarization.text"],
        )

        binding = integration.node_binding()

        self.assertEqual(binding.node_id, "node-001")
        self.assertEqual(binding.worker_id, "node-001")
        self.assertEqual(binding.capabilities, ["task.classification", "task.summarization.text"])

    async def test_request_lease_uses_binding_values(self):
        client = _FakeSchedulerClient()
        integration = SchedulerLeaseIntegration(
            scheduler_client=client,
            logger=logging.getLogger("scheduler-lease-integration-test"),
            node_id_provider=lambda: "node-001",
            capability_provider=lambda: ["task.classification"],
        )

        result = await integration.request_lease(core_api_endpoint="http://10.0.0.100:9001", trust_token="trust-token")

        self.assertEqual(result.status, "ok")
        self.assertEqual(client.last_call[0], "request_lease")
        self.assertEqual(client.last_call[1]["worker_id"], "node-001")
        self.assertEqual(client.last_call[1]["capabilities"], ["task.classification"])

    async def test_bind_lease_to_task_request_preserves_existing_request_shape(self):
        request = TaskExecutionRequest.model_validate(
            {
                "task_id": "task-001",
                "task_family": "task.classification",
                "requested_by": "scheduler.core",
                "inputs": {"text": "hello"},
                "trace_id": "trace-001",
            }
        )

        bound = SchedulerLeaseIntegration.bind_lease_to_task_request(request=request, lease_id="lease-001")

        self.assertEqual(bound.lease_id, "lease-001")
        self.assertEqual(bound.task_id, "task-001")


if __name__ == "__main__":
    unittest.main()
