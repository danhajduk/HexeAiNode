import asyncio
import json
import logging
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
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
        self.assertEqual(response["queue_state"]["runtime_lane"], "text_llm")
        self.assertEqual(response["routing_decision"]["reason"], "test")
        self.assertIn("eta", response)
        self.assertIn("/api/execution/jobs/", response["status_url"])

        status = await _wait_for_status(queue, job_id=response["job_id"], status="completed")
        self.assertEqual(status["result"], {"ok": True})
        self.assertEqual(status["routing_decision"]["selected_queue"], "local")
        self.assertIsNone(status["queue_position"])
        self.assertIsNone(status["eta"])

    async def test_artifact_acknowledgement_is_persisted_and_idempotent(self):
        queue = ExecutionQueueService(logger=logging.getLogger("execution-queue-test"), local_concurrency=1)
        response = await queue.enqueue(
            queue="visual_gpu",
            importance="normal",
            job_name="image-job",
            request_payload={"task_id": "image-001"},
            runner=lambda: _completed({"status": "completed"}),
        )
        await _wait_for_status(queue, job_id=response["job_id"], status="completed")

        first = await queue.acknowledge_artifacts(
            job_id=response["job_id"],
            acknowledgement={"artifact_count": 1, "deleted": ["weather/test.png"]},
        )
        second = await queue.acknowledge_artifacts(
            job_id=response["job_id"],
            acknowledgement={"artifact_count": 99},
        )
        status = await queue.job_status(job_id=response["job_id"])

        self.assertEqual(first["status"], "acknowledged")
        self.assertEqual(second, first)
        self.assertEqual(status["artifact_acknowledgement"], first)

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

    async def test_lane_admission_blocks_job_without_dropping_queue_entry(self):
        def _deny_visual_lane(job):
            return {"allowed": False, "reason": "visual_runtime_executor_not_ready", "job_id": job.get("job_id")}

        async def _should_not_run():
            raise AssertionError("blocked job should not execute")

        queue = ExecutionQueueService(
            logger=logging.getLogger("execution-queue-test"),
            local_concurrency=1,
            lane_admission_provider=_deny_visual_lane,
        )
        response = await queue.enqueue(
            queue="visual_gpu",
            importance="normal",
            job_name="visual blocked",
            request_payload={"task_id": "visual-blocked", "task_family": "task.image_generation"},
            runner=_should_not_run,
        )
        await asyncio.sleep(0.05)

        status = await queue.job_status(job_id=response["job_id"])
        diagnostics = await queue.diagnostics()

        self.assertEqual(status["status"], "queued")
        self.assertEqual(status["blocked_reason"], "visual_runtime_executor_not_ready")
        self.assertEqual(status["queue_position"], 1)
        self.assertEqual(diagnostics["lanes"]["visual_gpu"]["queued_count"], 1)
        self.assertEqual(diagnostics["lanes"]["visual_gpu"]["staged_count"], 0)
        self.assertEqual(diagnostics["lanes"]["visual_gpu"]["backlog_count"], 1)
        self.assertIsNone(diagnostics["lanes"]["visual_gpu"]["staged_job"])
        self.assertEqual(diagnostics["lanes"]["visual_gpu"]["blocked_reason"], "visual_runtime_executor_not_ready")
        self.assertEqual(diagnostics["lanes"]["visual_gpu"]["next_job"]["job_name"], "visual blocked")

    async def test_blocked_lane_retries_and_dispatches_when_admission_recovers(self):
        attempts = 0

        def _recovering_admission(_job):
            nonlocal attempts
            attempts += 1
            return {
                "allowed": attempts > 1,
                "reason": "ready" if attempts > 1 else "visual_cpu_resource_pressure",
                "retry_after_seconds": 1,
            }

        queue = ExecutionQueueService(
            logger=logging.getLogger("execution-queue-test"),
            lane_admission_provider=_recovering_admission,
            blocked_retry_seconds=1,
        )
        response = await queue.enqueue(
            queue="visual_cpu",
            importance="background",
            job_name="retry visual cpu",
            request_payload={"task_id": "retry-visual-cpu", "task_family": "task.image_generation"},
            runner=lambda: _completed({"ok": True}),
        )

        status = await _wait_for_status(queue, job_id=response["job_id"], status="completed", attempts=150)

        self.assertEqual(status["result"], {"ok": True})
        self.assertGreaterEqual(attempts, 2)

    async def test_lane_admission_blocked_job_expires_from_backlog(self):
        def _deny_visual_lane(job):
            return {"allowed": False, "reason": "visual_runtime_executor_not_ready", "job_id": job.get("job_id")}

        async def _should_not_run():
            raise AssertionError("blocked job should not execute")

        queue = ExecutionQueueService(
            logger=logging.getLogger("execution-queue-test"),
            local_concurrency=1,
            lane_admission_provider=_deny_visual_lane,
        )
        response = await queue.enqueue(
            queue="visual_gpu",
            importance="normal",
            job_name="visual timeout",
            request_payload={"task_id": "visual-timeout", "task_family": "task.image_generation"},
            queue_intent={"max_wait_seconds": 0},
            runner=_should_not_run,
        )
        await asyncio.sleep(0.05)

        status = await queue.job_status(job_id=response["job_id"])
        diagnostics = await queue.diagnostics()

        self.assertEqual(status["status"], "expired_wait_budget")
        self.assertEqual(status["error"]["code"], "expired_wait_budget")
        self.assertEqual(diagnostics["lanes"]["visual_gpu"]["queued_count"], 0)
        self.assertEqual(diagnostics["lanes"]["visual_gpu"]["backlog_count"], 0)

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

    async def test_visual_cpu_queue_diagnostics_reports_active_and_oldest_queued_age(self):
        queue = ExecutionQueueService(logger=logging.getLogger("execution-queue-test"), local_concurrency=1)
        release_first = asyncio.Event()
        first = await queue.enqueue(
            queue="visual_cpu",
            importance="background",
            job_name="cpu image first",
            request_payload={"task_id": "cpu-image-first"},
            runner=lambda: _blocking_job(name="first", order=[], release=release_first),
        )
        await _wait_for_status(queue, job_id=first["job_id"], status="running")
        await queue.enqueue(
            queue="visual_cpu",
            importance="background",
            job_name="cpu image queued",
            request_payload={"task_id": "cpu-image-queued"},
            runner=lambda: _completed({"ok": True}),
        )

        diagnostics = await queue.diagnostics()
        cpu_queue = diagnostics["queues"]["visual_cpu"]

        self.assertEqual(cpu_queue["active_count"], 1)
        self.assertEqual(cpu_queue["queued_count"], 1)
        self.assertEqual(cpu_queue["concurrency"], 1)
        self.assertEqual(cpu_queue["runtime_lane"], "visual_cpu")
        self.assertEqual(cpu_queue["active_job"]["task_id"], "cpu-image-first")
        self.assertIsNotNone(cpu_queue["oldest_queued_at"])
        self.assertIsNotNone(cpu_queue["oldest_queued_age_seconds"])
        self.assertEqual(diagnostics["lanes"]["visual_cpu"]["active_count"], 1)
        self.assertEqual(diagnostics["lanes"]["visual_cpu"]["queued_count"], 1)
        release_first.set()

    async def test_runtime_lane_contract_reports_visual_gpu_and_visual_cpu_separately(self):
        queue = ExecutionQueueService(logger=logging.getLogger("execution-queue-test"), local_concurrency=1)
        release_gpu = asyncio.Event()
        release_cpu = asyncio.Event()
        gpu = await queue.enqueue(
            queue="visual_gpu",
            importance="normal",
            job_name="gpu image",
            request_payload={"task_id": "gpu-image", "task_family": "task.image_generation"},
            runner=lambda: _blocking_job(name="gpu", order=[], release=release_gpu),
        )
        cpu = await queue.enqueue(
            queue="visual_cpu",
            importance="background",
            job_name="cpu image",
            request_payload={"task_id": "cpu-image", "task_family": "task.image_generation"},
            runner=lambda: _blocking_job(name="cpu", order=[], release=release_cpu),
        )
        await _wait_for_status(queue, job_id=gpu["job_id"], status="running")
        await _wait_for_status(queue, job_id=cpu["job_id"], status="running")

        diagnostics = await queue.diagnostics()

        self.assertIn("lane_contract", diagnostics)
        self.assertEqual(diagnostics["queues"]["visual_gpu"]["runtime_lane"], "visual_gpu")
        self.assertEqual(diagnostics["queues"]["visual_cpu"]["runtime_lane"], "visual_cpu")
        self.assertEqual(diagnostics["lanes"]["visual_gpu"]["active_count"], 1)
        self.assertEqual(diagnostics["lanes"]["visual_cpu"]["active_count"], 1)
        self.assertEqual(diagnostics["lanes"]["visual_gpu"]["capacity"]["max_active"], 1)
        self.assertEqual(diagnostics["lanes"]["visual_gpu"]["capacity"]["max_staged"], 1)
        release_gpu.set()
        release_cpu.set()

    async def test_global_queue_reports_active_staged_and_scheduler_backlog(self):
        queue = ExecutionQueueService(logger=logging.getLogger("execution-queue-test"), local_concurrency=1)
        release_first = asyncio.Event()
        first = await queue.enqueue(
            queue="local",
            importance="normal",
            job_name="first",
            request_payload={"task_id": "first", "task_family": "task.chat"},
            runner=lambda: _blocking_job(name="first", order=[], release=release_first),
        )
        await _wait_for_status(queue, job_id=first["job_id"], status="running")
        for index in range(9):
            await queue.enqueue(
                queue="local",
                importance="normal",
                job_name=f"queued-{index}",
                request_payload={"task_id": f"queued-{index}", "task_family": "task.chat"},
                runner=lambda: _completed({"ok": True}),
            )

        diagnostics = await queue.diagnostics()
        global_queue = diagnostics["global_queue"]
        text_lane = diagnostics["lanes"]["text_llm"]

        self.assertEqual(global_queue["active_count"], 1)
        self.assertEqual(global_queue["queued_count"], 9)
        self.assertEqual(global_queue["staged_count"], 1)
        self.assertEqual(global_queue["backlog_count"], 8)
        self.assertEqual(text_lane["active_count"], 1)
        self.assertEqual(text_lane["staged_count"], 1)
        self.assertEqual(text_lane["backlog_count"], 8)
        self.assertEqual(text_lane["staged_job"]["task_id"], "queued-0")
        self.assertEqual(global_queue["next_dispatch_candidate"]["task_id"], "queued-0")
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
        self.assertEqual(response["cancel_rejected_reason"], "running_cancellation_unsupported")
        release_first.set()
        await _wait_for_status(queue, job_id=first["job_id"], status="completed")

    async def test_cancel_supported_running_job_releases_slot(self):
        queue = ExecutionQueueService(logger=logging.getLogger("execution-queue-test"), local_concurrency=1)
        release = asyncio.Event()
        runner_stopped = asyncio.Event()

        async def cancellable_runner():
            try:
                await release.wait()
                return {"unexpected": True}
            finally:
                runner_stopped.set()

        first = await queue.enqueue(
            queue="local",
            importance="normal",
            job_name="cancellable",
            request_payload={"task_id": "cancellable"},
            runner=cancellable_runner,
            running_cancellation_supported=True,
        )
        await _wait_for_status(queue, job_id=first["job_id"], status="running")
        second = await queue.enqueue(
            queue="local",
            importance="normal",
            job_name="next",
            request_payload={"task_id": "next"},
            runner=lambda: _completed({"ok": True}),
        )

        cancelled = await queue.cancel_job(job_id=first["job_id"], reason="client_cancelled")

        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(cancelled["error"], {"code": "cancelled", "message": "client_cancelled"})
        self.assertIsNone(cancelled["result"])
        self.assertTrue(runner_stopped.is_set())
        await _wait_for_status(queue, job_id=second["job_id"], status="completed")

    async def test_expired_terminal_records_are_deleted_on_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "execution-jobs.json"
            state_path.write_text(
                json.dumps(
                    {
                        "schema_version": "2.0",
                        "jobs": [
                            {
                                "job_id": "job-expired",
                                "status": "completed",
                                "queue": "local",
                                "importance": "normal",
                                "sequence": 1,
                                "expires_at": "2000-01-01T00:00:00+00:00",
                            },
                            {
                                "job_id": "job-retained",
                                "status": "cancelled",
                                "queue": "local",
                                "importance": "normal",
                                "sequence": 2,
                                "expires_at": "2099-01-01T00:00:00+00:00",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            queue = ExecutionQueueService(logger=logging.getLogger("execution-queue-test"), state_path=str(state_path))

            self.assertEqual((await queue.job_status(job_id="job-expired"))["status"], "not_found")
            self.assertEqual((await queue.job_status(job_id="job-retained"))["status"], "cancelled")
            diagnostics = await queue.diagnostics()
            self.assertEqual(diagnostics["persistence"]["expired_record_count"], 1)
            persisted_ids = {job["job_id"] for job in json.loads(state_path.read_text(encoding="utf-8"))["jobs"]}
            self.assertEqual(persisted_ids, {"job-retained"})

    async def test_terminal_record_is_deleted_at_expiration_without_polling(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "execution-jobs.json"
            state_path.write_text(
                json.dumps(
                    {
                        "schema_version": "2.0",
                        "jobs": [
                            {
                                "job_id": "job-soon-expired",
                                "status": "completed",
                                "queue": "local",
                                "importance": "normal",
                                "sequence": 1,
                                "expires_at": (datetime.now(timezone.utc) + timedelta(milliseconds=50)).isoformat(),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            queue = ExecutionQueueService(logger=logging.getLogger("execution-queue-test"), state_path=str(state_path))
            await queue.start_recovered_jobs()

            await asyncio.sleep(0.1)

            persisted = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["jobs"], [])
            self.assertEqual((await queue.diagnostics())["persistence"]["expired_record_count"], 1)

    async def test_matching_work_snapshot_reports_local_vision_jobs_and_reroute_candidates(self):
        queue = ExecutionQueueService(logger=logging.getLogger("execution-queue-test"), local_concurrency=1)
        release_first = asyncio.Event()
        running = await queue.enqueue(
            queue="local",
            importance="normal",
            job_name="running vision",
            request_payload={
                "task_id": "vision-running",
                "task_family": "task.vision_analysis",
                "constraints": {"routing_policy": {"mode": "local_only"}},
            },
            runner=lambda: _blocking_job(name="running", order=[], release=release_first),
        )
        await _wait_for_status(queue, job_id=running["job_id"], status="running")
        await queue.enqueue(
            queue="local",
            importance="normal",
            job_name="queued vision",
            request_payload={
                "task_id": "vision-queued",
                "task_family": "task.vision_analysis",
                "constraints": {"routing_policy": {"mode": "local_preferred"}},
            },
            runner=lambda: _completed({"ok": True}),
        )

        snapshot = await queue.matching_work_snapshot(
            queue="local",
            task_families={"task.vision_analysis"},
            statuses={"queued", "running"},
        )

        self.assertEqual(snapshot["active_count"], 1)
        self.assertEqual(snapshot["queued_count"], 1)
        self.assertEqual(snapshot["cloud_reroute_candidate_count"], 1)
        self.assertEqual([item["task_id"] for item in snapshot["jobs"]], ["vision-running", "vision-queued"])
        self.assertFalse(snapshot["jobs"][0]["cloud_reroute_candidate"])
        self.assertTrue(snapshot["jobs"][1]["cloud_reroute_candidate"])
        release_first.set()
        await _wait_for_status(queue, job_id=running["job_id"], status="completed")

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

    async def test_recovers_queued_jobs_and_does_not_replay_running_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "execution_queue_jobs.json"
            state_path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "jobs": [
                            {
                                "job_id": "job-running",
                                "job_name": "running",
                                "client_id": "client-a",
                                "queue": "local",
                                "importance": "normal",
                                "status": "running",
                                "request": {"task_id": "running", "task_family": "task.classification"},
                                "created_at": "2026-09-27T01:00:00-07:00",
                                "queued_at": "2026-09-27T01:00:00-07:00",
                                "started_at": "2026-09-27T01:00:01-07:00",
                                "expires_at": "2099-09-27T01:00:00-07:00",
                                "sequence": 1,
                            },
                            {
                                "job_id": "job-queued",
                                "job_name": "queued",
                                "client_id": "client-a",
                                "queue": "local",
                                "importance": "high",
                                "status": "queued",
                                "request": {"task_id": "queued", "task_family": "task.classification"},
                                "routing_decision": {"selected_queue": "local", "reason": "explicit_provider"},
                                "queue_intent": {"runtime_lane": "text_llm", "priority": "high"},
                                "created_at": "2026-09-27T01:00:02-07:00",
                                "queued_at": "2026-09-27T01:00:02-07:00",
                                "expires_at": "2099-09-27T01:00:00-07:00",
                                "sequence": 2,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            recovered_requests = []

            def recovery_runner(job):
                request = job["request"]
                return lambda: _record_completed(request=request, recovered_requests=recovered_requests)

            restored = ExecutionQueueService(
                logger=logging.getLogger("execution-queue-test"),
                local_concurrency=1,
                state_path=str(state_path),
                recovery_runner_factory=recovery_runner,
            )
            running_status = await restored.job_status(job_id="job-running")
            queued_before_start = await restored.job_status(job_id="job-queued")
            startup = await restored.start_recovered_jobs()
            queued_status = await _wait_for_status(restored, job_id="job-queued", status="completed")
            diagnostics = await restored.diagnostics()

            self.assertEqual(running_status["status"], "failed")
            self.assertEqual(running_status["error"]["code"], "execution_queue_restart_while_running")
            self.assertEqual(running_status["recovery"]["status"], "not_replayed")
            self.assertEqual(queued_before_start["status"], "queued")
            self.assertEqual(queued_status["result"], {"task_id": "queued", "recovered": True})
            self.assertEqual(recovered_requests, [{"task_id": "queued", "task_family": "task.classification"}])
            self.assertEqual(startup["recovered_queued_count"], 1)
            self.assertEqual(diagnostics["persistence"]["recovered_unfinished_count"], 2)
            self.assertEqual(diagnostics["persistence"]["recovered_queued_count"], 1)
            self.assertEqual(diagnostics["persistence"]["recovered_running_count"], 1)


async def _completed(payload: dict) -> dict:
    return payload


async def _record_completed(*, request: dict, recovered_requests: list[dict]) -> dict:
    recovered_requests.append(request)
    return {"task_id": request["task_id"], "recovered": True}


async def _ordered_job(*, name: str, order: list[str]) -> dict:
    order.append(name)
    return {"name": name}


async def _blocking_job(*, name: str, order: list[str], release: asyncio.Event) -> dict:
    order.append(name)
    await release.wait()
    return {"name": name}


async def _failing_job() -> dict:
    raise RuntimeError("boom")


async def _wait_for_status(
    queue: ExecutionQueueService,
    *,
    job_id: str,
    status: str,
    attempts: int = 50,
) -> dict:
    for _ in range(attempts):
        payload = await queue.job_status(job_id=job_id)
        if payload.get("status") == status:
            return payload
        await asyncio.sleep(0.01)
    raise AssertionError(f"job {job_id} did not reach {status}")


if __name__ == "__main__":
    unittest.main()
