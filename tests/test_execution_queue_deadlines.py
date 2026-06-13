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
