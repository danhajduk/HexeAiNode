import asyncio
import logging
import unittest
from datetime import timedelta

from ai_node.runtime.execution_queue import ExecutionQueueService
from ai_node.time_utils import local_now


class ExecutionQueueDeadlineTests(unittest.IsolatedAsyncioTestCase):
    async def test_deadline_sorts_within_same_importance(self):
        queue = ExecutionQueueService(logger=logging.getLogger("queue-deadline-test"), local_concurrency=1, check_after_seconds=5)
        release = asyncio.Event()

        async def _runner():
            return {"status": "ok"}

        blocker = await queue.enqueue(
            queue="local",
            importance="normal",
            job_name="blocker",
            request_payload={"task_id": "blocker"},
            runner=lambda: self._blocking(release),
        )
        await self._wait_for_status(queue, blocker["job_id"], "running")
        late = await queue.enqueue(
            queue="local",
            importance="normal",
            job_name="late",
            request_payload={"task_id": "late"},
            runner=_runner,
            queue_intent={"deadline_at": (local_now() + timedelta(minutes=30)).isoformat()},
        )
        early = await queue.enqueue(
            queue="local",
            importance="normal",
            job_name="early",
            request_payload={"task_id": "early"},
            runner=_runner,
            queue_intent={"deadline_at": (local_now() + timedelta(minutes=5)).isoformat()},
        )

        self.assertEqual(late["queue_position"], 1)
        self.assertEqual(early["queue_position"], 1)
        self.assertEqual((await queue.job_status(job_id=late["job_id"]))["queue_position"], 2)
        release.set()
        await self._wait_for_status(queue, blocker["job_id"], "completed")

    async def test_wait_budget_rejects_unreachable_queue(self):
        release = asyncio.Event()
        queue = ExecutionQueueService(logger=logging.getLogger("queue-deadline-test"), local_concurrency=1, check_after_seconds=10)

        async def _blocking():
            await release.wait()
            return {"status": "ok"}

        blocker = await queue.enqueue(
            queue="local",
            importance="normal",
            job_name="blocker",
            request_payload={"task_id": "blocker"},
            runner=_blocking,
        )
        await self._wait_for_status(queue, blocker["job_id"], "running")

        rejected = await queue.enqueue(
            queue="local",
            importance="normal",
            job_name="too impatient",
            request_payload={"task_id": "too-impatient"},
            runner=lambda: self._completed(),
            queue_intent={"max_wait_seconds": 0},
        )

        release.set()
        await self._wait_for_status(queue, blocker["job_id"], "completed")
        self.assertEqual(rejected["status"], "rejected")
        self.assertEqual(rejected["error_code"], "rejected_deadline_unreachable")

    async def test_queue_start_estimate_reports_new_job_wait(self):
        release = asyncio.Event()
        queue = ExecutionQueueService(logger=logging.getLogger("queue-deadline-test"), local_concurrency=1, check_after_seconds=10)
        blocker = await queue.enqueue(
            queue="local",
            importance="normal",
            job_name="blocker",
            request_payload={"task_id": "blocker"},
            runner=lambda: self._blocking(release),
        )
        await self._wait_for_status(queue, blocker["job_id"], "running")

        estimate = await queue.queue_start_estimate(queue="local")

        release.set()
        await self._wait_for_status(queue, blocker["job_id"], "completed")
        self.assertEqual(estimate["queue"], "local")
        self.assertEqual(estimate["estimated_start_seconds"], 10)

    async def test_deadline_monitor_expires_overdue_local_only_job(self):
        queue = ExecutionQueueService(logger=logging.getLogger("queue-deadline-test"), local_concurrency=1, check_after_seconds=10)
        old = (local_now() - timedelta(seconds=30)).isoformat()
        queue._jobs["job-expire"] = {
            "job_id": "job-expire",
            "job_name": "expire",
            "queue": "local",
            "importance": "normal",
            "queue_intent": {"max_wait_seconds": 1, "allow_cloud_spillover": False},
            "status": "queued",
            "queued_at": old,
            "created_at": old,
            "sequence": 1,
            "_runner": lambda: self._completed(),
        }
        queue._queues["local"].append(queue._queue_entry(rank=2, deadline_sort=0, sequence=1, job_id="job-expire"))

        status = await queue.job_status(job_id="job-expire")

        self.assertEqual(status["status"], "expired_wait_budget")
        self.assertEqual(status["error"]["code"], "expired_wait_budget")

    async def test_deadline_monitor_reroutes_cloud_allowed_job(self):
        queue = ExecutionQueueService(logger=logging.getLogger("queue-deadline-test"), local_concurrency=1, check_after_seconds=10)
        old = (local_now() - timedelta(seconds=30)).isoformat()
        queue._jobs["job-reroute"] = {
            "job_id": "job-reroute",
            "job_name": "reroute",
            "queue": "local",
            "importance": "high",
            "queue_intent": {"max_wait_seconds": 1, "allow_cloud_spillover": True},
            "routing_decision": {"selected_queue": "local"},
            "status": "queued",
            "queued_at": old,
            "created_at": old,
            "sequence": 1,
            "_runner": lambda: self._completed(),
        }
        queue._queues["local"].append(queue._queue_entry(rank=1, deadline_sort=0, sequence=1, job_id="job-reroute"))

        status = await queue.job_status(job_id="job-reroute")

        self.assertEqual(status["status"], "queued")
        self.assertEqual(status["queue"], "cloud")
        self.assertEqual(status["routing_decision"]["reason"], "rerouted_to_cloud")

    async def _completed(self):
        return {"status": "ok"}

    async def _blocking(self, release: asyncio.Event):
        await release.wait()
        return {"status": "ok"}

    async def _wait_for_status(self, queue, job_id: str, status: str) -> dict:
        for _ in range(100):
            payload = await queue.job_status(job_id=job_id)
            if payload.get("status") == status:
                return payload
            await asyncio.sleep(0.01)
        self.fail(f"job {job_id} did not reach {status}")


if __name__ == "__main__":
    unittest.main()
