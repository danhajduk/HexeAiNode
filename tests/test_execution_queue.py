import asyncio
import logging
import tempfile
import unittest
from pathlib import Path

from ai_node.runtime.execution_queue import ExecutionQueueService


class ExecutionQueueServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_enqueue_returns_queued_response_and_completes_job(self):
        queue = ExecutionQueueService(logger=logging.getLogger("execution-queue-test"), local_concurrency=1)

        response = await queue.enqueue(
            queue="local",
            importance="normal",
            job_name="smoke-job",
            request_payload={"task_id": "task-001"},
            runner=lambda: _completed({"ok": True}),
            routing_decision={"selected_queue": "local", "reason": "test"},
        )

        self.assertEqual(response["status"], "queued")
        self.assertEqual(response["job_name"], "smoke-job")
        self.assertEqual(response["queue"], "local")
        self.assertEqual(response["routing_decision"]["reason"], "test")
        self.assertIn("eta", response)
        self.assertIn("/api/execution/jobs/", response["status_url"])

        status = await _wait_for_status(queue, job_id=response["job_id"], status="completed")
        self.assertEqual(status["result"], {"ok": True})
        self.assertEqual(status["routing_decision"]["selected_queue"], "local")
        self.assertIsNone(status["queue_position"])
        self.assertIsNone(status["eta"])

    async def test_local_queue_prioritizes_importance_after_active_slot(self):
        queue = ExecutionQueueService(logger=logging.getLogger("execution-queue-test"), local_concurrency=1)
        release_first = asyncio.Event()
        execution_order: list[str] = []

        first = await queue.enqueue(
            queue="local",
            importance="normal",
            job_name="first",
            request_payload={"task_id": "first"},
            runner=lambda: _blocking_job(name="first", order=execution_order, release=release_first),
        )
        await _wait_for_status(queue, job_id=first["job_id"], status="running")

        background = await queue.enqueue(
            queue="local",
            importance="background",
            job_name="background",
            request_payload={"task_id": "background"},
            runner=lambda: _ordered_job(name="background", order=execution_order),
        )
        critical = await queue.enqueue(
            queue="local",
            importance="critical",
            job_name="critical",
            request_payload={"task_id": "critical"},
            runner=lambda: _ordered_job(name="critical", order=execution_order),
        )

        self.assertEqual((await queue.job_status(job_id=critical["job_id"]))["queue_position"], 1)
        self.assertEqual((await queue.job_status(job_id=background["job_id"]))["queue_position"], 2)

        release_first.set()
        await _wait_for_status(queue, job_id=background["job_id"], status="completed")
        await _wait_for_status(queue, job_id=critical["job_id"], status="completed")

        self.assertEqual(execution_order, ["first", "critical", "background"])

    async def test_failure_payload_does_not_expose_traceback(self):
        queue = ExecutionQueueService(logger=logging.getLogger("execution-queue-test"), local_concurrency=1)
        response = await queue.enqueue(
            queue="local",
            importance="normal",
            job_name="failure",
            request_payload={"task_id": "failure"},
            runner=_failing_job,
        )

        status = await _wait_for_status(queue, job_id=response["job_id"], status="failed")
        self.assertEqual(status["error"]["code"], "boom")
        self.assertNotIn("traceback", status["error"])

    async def test_queue_pressure_counts_active_and_queued_jobs(self):
        queue = ExecutionQueueService(logger=logging.getLogger("execution-queue-test"), local_concurrency=1)
        release_first = asyncio.Event()
        first = await queue.enqueue(
            queue="local",
            importance="normal",
            job_name="first",
            request_payload={"task_id": "first"},
            runner=lambda: _blocking_job(name="first", order=[], release=release_first),
        )
        await _wait_for_status(queue, job_id=first["job_id"], status="running")
        await queue.enqueue(
            queue="local",
            importance="normal",
            job_name="second",
            request_payload={"task_id": "second"},
            runner=lambda: _completed({"ok": True}),
        )

        pressure = await queue.queue_pressure(queue="local")

        self.assertEqual(pressure["active_count"], 1)
        self.assertEqual(pressure["queued_count"], 1)
        self.assertEqual(pressure["pending_count"], 2)
        release_first.set()

    async def test_queue_eta_estimates_start_time_from_position_and_active_jobs(self):
        queue = ExecutionQueueService(
            logger=logging.getLogger("execution-queue-test"),
            local_concurrency=1,
            check_after_seconds=7,
        )
        release_first = asyncio.Event()
        first = await queue.enqueue(
            queue="local",
            importance="normal",
            job_name="first",
            request_payload={"task_id": "first"},
            runner=lambda: _blocking_job(name="first", order=[], release=release_first),
        )
        await _wait_for_status(queue, job_id=first["job_id"], status="running")

        second = await queue.enqueue(
            queue="local",
            importance="normal",
            job_name="second",
            request_payload={"task_id": "second"},
            runner=lambda: _completed({"ok": True}),
        )
        second_status = await queue.job_status(job_id=second["job_id"])

        self.assertEqual(second["eta"]["estimated_start_seconds"], 7)
        self.assertEqual(second["eta"]["source"], "queue_position")
        self.assertEqual(second["eta"]["confidence"], "rough")
        self.assertEqual(second_status["eta"]["estimated_start_seconds"], 7)
        self.assertIsNotNone(second_status["eta"]["estimated_start_at"])

        running_status = await queue.job_status(job_id=first["job_id"])
        self.assertEqual(running_status["eta"]["estimated_start_seconds"], 0)
        self.assertEqual(running_status["eta"]["source"], "already_running")

        release_first.set()
        await _wait_for_status(queue, job_id=second["job_id"], status="completed")

    async def test_cancel_queued_job_removes_it_from_queue(self):
        queue = ExecutionQueueService(logger=logging.getLogger("execution-queue-test"), local_concurrency=1)
        release_first = asyncio.Event()
        first = await queue.enqueue(
            queue="local",
            importance="normal",
            job_name="first",
            request_payload={"task_id": "first"},
            runner=lambda: _blocking_job(name="first", order=[], release=release_first),
        )
        await _wait_for_status(queue, job_id=first["job_id"], status="running")
        second = await queue.enqueue(
            queue="local",
            importance="normal",
            job_name="second",
            request_payload={"task_id": "second"},
            runner=lambda: _completed({"should_not_run": True}),
        )

        cancelled = await queue.cancel_job(job_id=second["job_id"], reason="client_cancelled")
        status = await queue.job_status(job_id=second["job_id"])
        pressure = await queue.queue_pressure(queue="local")

        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(cancelled["error"]["code"], "cancelled")
        self.assertEqual(cancelled["error"]["message"], "client_cancelled")
        self.assertEqual(status["status"], "cancelled")
        self.assertEqual(status["queue_position"], None)
        self.assertEqual(pressure["queued_count"], 0)
        release_first.set()
        await _wait_for_status(queue, job_id=first["job_id"], status="completed")

    async def test_cancel_running_job_is_rejected(self):
        queue = ExecutionQueueService(logger=logging.getLogger("execution-queue-test"), local_concurrency=1)
        release_first = asyncio.Event()
        first = await queue.enqueue(
            queue="local",
            importance="normal",
            job_name="first",
            request_payload={"task_id": "first"},
            runner=lambda: _blocking_job(name="first", order=[], release=release_first),
        )
        await _wait_for_status(queue, job_id=first["job_id"], status="running")

        response = await queue.cancel_job(job_id=first["job_id"], reason="too_late")

        self.assertEqual(response["status"], "running")
        self.assertFalse(response["cancellable"])
        self.assertEqual(response["cancel_rejected_reason"], "job_already_running")
        release_first.set()
        await _wait_for_status(queue, job_id=first["job_id"], status="completed")

    async def test_persists_completed_job_for_later_status_polling(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "execution_queue_jobs.json"
            queue = ExecutionQueueService(
                logger=logging.getLogger("execution-queue-test"),
                local_concurrency=1,
                state_path=str(state_path),
            )
            response = await queue.enqueue(
                queue="local",
                importance="normal",
                job_name="persisted",
                request_payload={"task_id": "persisted"},
                runner=lambda: _completed({"ok": True}),
            )
            await _wait_for_status(queue, job_id=response["job_id"], status="completed")

            restored = ExecutionQueueService(
                logger=logging.getLogger("execution-queue-test"),
                local_concurrency=1,
                state_path=str(state_path),
            )
            status = await restored.job_status(job_id=response["job_id"])
            diagnostics = await restored.diagnostics()

            self.assertEqual(status["status"], "completed")
            self.assertEqual(status["result"], {"ok": True})
            self.assertTrue(diagnostics["persistence"]["configured"])
            self.assertEqual(diagnostics["persistence"]["recovered_unfinished_count"], 0)

    async def test_rejects_client_when_pending_limit_is_reached(self):
        queue = ExecutionQueueService(
            logger=logging.getLogger("execution-queue-test"),
            local_concurrency=1,
            max_pending_per_client=1,
        )
        release_first = asyncio.Event()
        first = await queue.enqueue(
            queue="local",
            importance="normal",
            job_name="first",
            request_payload={"task_id": "first"},
            runner=lambda: _blocking_job(name="first", order=[], release=release_first),
            client_id="client-a",
        )
        await _wait_for_status(queue, job_id=first["job_id"], status="running")

        rejected = await queue.enqueue(
            queue="cloud",
            importance="normal",
            job_name="second",
            request_payload={"task_id": "second"},
            runner=lambda: _completed({"ok": True}),
            client_id="client-a",
        )
        other_client = await queue.enqueue(
            queue="cloud",
            importance="normal",
            job_name="third",
            request_payload={"task_id": "third"},
            runner=lambda: _completed({"ok": True}),
            client_id="client-b",
        )
        diagnostics = await queue.diagnostics()

        self.assertEqual(rejected["status"], "rejected")
        self.assertEqual(rejected["error_code"], "queue_client_limit_exceeded")
        self.assertEqual(rejected["pending_count"], 1)
        self.assertEqual(other_client["status"], "queued")
        self.assertEqual(diagnostics["fairness"]["max_pending_per_client"], 1)
        await _wait_for_status(queue, job_id=other_client["job_id"], status="completed")
        release_first.set()
        await _wait_for_status(queue, job_id=first["job_id"], status="completed")

    async def test_recovers_unfinished_jobs_as_failed_after_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "execution_queue_jobs.json"
            queue = ExecutionQueueService(
                logger=logging.getLogger("execution-queue-test"),
                local_concurrency=1,
                state_path=str(state_path),
            )
            release_first = asyncio.Event()
            first = await queue.enqueue(
                queue="local",
                importance="normal",
                job_name="running",
                request_payload={"task_id": "running"},
                runner=lambda: _blocking_job(name="running", order=[], release=release_first),
            )
            await _wait_for_status(queue, job_id=first["job_id"], status="running")
            second = await queue.enqueue(
                queue="local",
                importance="normal",
                job_name="queued",
                request_payload={"task_id": "queued"},
                runner=lambda: _completed({"ok": True}),
            )

            restored = ExecutionQueueService(
                logger=logging.getLogger("execution-queue-test"),
                local_concurrency=1,
                state_path=str(state_path),
            )
            running_status = await restored.job_status(job_id=first["job_id"])
            queued_status = await restored.job_status(job_id=second["job_id"])
            diagnostics = await restored.diagnostics()

            self.assertEqual(running_status["status"], "failed")
            self.assertEqual(queued_status["status"], "failed")
            self.assertEqual(running_status["error"]["code"], "execution_queue_recovery_required")
            self.assertEqual(queued_status["error"]["code"], "execution_queue_recovery_required")
            self.assertEqual(diagnostics["persistence"]["recovered_unfinished_count"], 2)
            release_first.set()
            await _wait_for_status(queue, job_id=first["job_id"], status="completed")


async def _completed(payload: dict) -> dict:
    return payload


async def _ordered_job(*, name: str, order: list[str]) -> dict:
    order.append(name)
    return {"name": name}


async def _blocking_job(*, name: str, order: list[str], release: asyncio.Event) -> dict:
    order.append(name)
    await release.wait()
    return {"name": name}


async def _failing_job() -> dict:
    raise RuntimeError("boom")


async def _wait_for_status(queue: ExecutionQueueService, *, job_id: str, status: str) -> dict:
    for _ in range(50):
        payload = await queue.job_status(job_id=job_id)
        if payload.get("status") == status:
            return payload
        await asyncio.sleep(0.01)
    raise AssertionError(f"job {job_id} did not reach {status}")


if __name__ == "__main__":
    unittest.main()
