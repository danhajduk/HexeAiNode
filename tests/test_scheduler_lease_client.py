import logging
import unittest

from ai_node.core_api.scheduler_lease_client import SchedulerLeaseClient


class _FakeHttpAdapter:
    def __init__(self, *, status_code=200, payload=None):
        self._status_code = status_code
        self._payload = payload or {"status": "ok"}
        self.last_url = None
        self.last_headers = None
        self.last_body = None

    async def post_json(self, url: str, headers: dict, body: dict):
        self.last_url = url
        self.last_headers = headers
        self.last_body = body
        return self._status_code, dict(self._payload)


class SchedulerLeaseClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_request_lease_uses_canonical_scheduler_request_contract(self):
        adapter = _FakeHttpAdapter(payload={"lease": {"lease_id": "lease-001"}, "job": {"job_id": "job-001"}})
        client = SchedulerLeaseClient(logger=logging.getLogger("scheduler-lease-client-test"), http_adapter=adapter)

        result = await client.request_lease(
            core_api_endpoint="http://10.0.0.100:9001",
            worker_id="node-001",
            capabilities=["task.classification", "task.summarization.text"],
            max_units=2,
            trust_token="trust-token",
            node_id="node-001",
        )

        self.assertEqual(result.status, "ok")
        self.assertEqual(adapter.last_url, "http://10.0.0.100:9001/api/system/scheduler/leases/request")
        self.assertEqual(adapter.last_body["worker_id"], "node-001")
        self.assertEqual(adapter.last_body["capabilities"], ["task.classification", "task.summarization.text"])
        self.assertEqual(adapter.last_body["max_units"], 2)

    async def test_heartbeat_report_and_complete_use_lease_routes(self):
        adapter = _FakeHttpAdapter()
        client = SchedulerLeaseClient(logger=logging.getLogger("scheduler-lease-client-test"), http_adapter=adapter)

        heartbeat = await client.heartbeat(
            core_api_endpoint="http://10.0.0.100:9001",
            lease_id="lease-001",
            worker_id="node-001",
        )
        self.assertEqual(heartbeat.status, "ok")
        self.assertTrue(adapter.last_url.endswith("/api/system/scheduler/leases/lease-001/heartbeat"))

        report = await client.report_progress(
            core_api_endpoint="http://10.0.0.100:9001",
            lease_id="lease-001",
            worker_id="node-001",
            progress=0.5,
            metrics={"duration_ms": 10},
            message="running",
        )
        self.assertEqual(report.status, "ok")
        self.assertEqual(adapter.last_body["progress"], 0.5)

        complete = await client.complete(
            core_api_endpoint="http://10.0.0.100:9001",
            lease_id="lease-001",
            worker_id="node-001",
            status="completed",
            result={"task_id": "task-001"},
        )
        self.assertEqual(complete.status, "ok")
        self.assertEqual(adapter.last_body["status"], "completed")


if __name__ == "__main__":
    unittest.main()
