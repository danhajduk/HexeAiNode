import asyncio
import json
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from ai_node.execution.idempotency import ExecutionIdempotencyStore, IdempotencyConflictError
from ai_node.execution.task_models import TaskExecutionRequest
from ai_node.lifecycle.node_lifecycle import NodeLifecycle
from ai_node.runtime.node_control_api import NodeControlState, create_node_control_app


class ExecutionIdempotencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_replay_returns_original_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ExecutionIdempotencyStore(path=str(Path(tmp) / "idempotency.json"))
            calls = 0

            async def operation():
                nonlocal calls
                calls += 1
                return {"status": "completed", "value": calls}

            first = await store.execute(caller_id="caller-a", idempotency_key="key-1", request_payload={"x": 1}, operation=operation)
            second = await store.execute(caller_id="caller-a", idempotency_key="key-1", request_payload={"x": 1}, operation=operation)

            self.assertEqual(first, second)
            self.assertEqual(calls, 1)

    async def test_same_key_conflicts_only_within_caller_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ExecutionIdempotencyStore(path=str(Path(tmp) / "idempotency.json"))

            async def operation():
                return {"status": "completed"}

            await store.execute(caller_id="caller-a", idempotency_key="shared", request_payload={"x": 1}, operation=operation)
            with self.assertRaisesRegex(IdempotencyConflictError, "idempotency_key_conflict"):
                await store.execute(caller_id="caller-a", idempotency_key="shared", request_payload={"x": 2}, operation=operation)
            response = await store.execute(caller_id="caller-b", idempotency_key="shared", request_payload={"x": 2}, operation=operation)
            self.assertEqual(response["status"], "completed")

    async def test_concurrent_exact_submissions_execute_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ExecutionIdempotencyStore(path=str(Path(tmp) / "idempotency.json"))
            calls = 0

            async def operation():
                nonlocal calls
                calls += 1
                await asyncio.sleep(0.02)
                return {"job_id": "job-1", "status": "queued"}

            responses = await asyncio.gather(
                *[
                    store.execute(caller_id="caller-a", idempotency_key="key-1", request_payload={"x": 1}, operation=operation)
                    for _ in range(8)
                ]
            )
            self.assertEqual(calls, 1)
            self.assertTrue(all(response == responses[0] for response in responses))

    async def test_completed_mapping_survives_restart_and_expiration_allows_reuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "idempotency.json"

            async def first_operation():
                return {"job_id": "job-original", "status": "queued"}

            first = ExecutionIdempotencyStore(path=str(path))
            await first.execute(caller_id="caller-a", idempotency_key="key-1", request_payload={"x": 1}, operation=first_operation)
            restarted = ExecutionIdempotencyStore(path=str(path))

            async def must_not_run():
                raise AssertionError("durable replay executed duplicate work")

            replay = await restarted.execute(caller_id="caller-a", idempotency_key="key-1", request_payload={"x": 1}, operation=must_not_run)
            self.assertEqual(replay["job_id"], "job-original")

            persisted = json.loads(path.read_text())
            for record in persisted["records"].values():
                record["expires_at"] = "2000-01-01T00:00:00+00:00"
            path.write_text(json.dumps(persisted), encoding="utf-8")
            expired = ExecutionIdempotencyStore(path=str(path))

            async def replacement():
                return {"job_id": "job-new", "status": "queued"}

            response = await expired.execute(caller_id="caller-a", idempotency_key="key-1", request_payload={"x": 2}, operation=replacement)
            self.assertEqual(response["job_id"], "job-new")

    async def test_node_execution_boundary_replays_without_executing_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ExecutionIdempotencyStore(path=str(Path(tmp) / "idempotency.json"))
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("idempotency-test")),
                config_path=str(Path(tmp) / "bootstrap.json"),
                logger=logging.getLogger("idempotency-test"),
                execution_idempotency_store=store,
            )
            state._execute_direct_once = AsyncMock(return_value={"status": "completed", "task_id": "task-1"})
            request = TaskExecutionRequest(
                task_id="task-1",
                idempotency_key="explicit-key",
                task_family="task.classification",
                requested_by="caller-a",
                inputs={},
                trace_id="trace-1",
            )

            first = await state.execute_direct(request=request)
            second = await state.execute_direct(request=request)

            self.assertEqual(first, second)
            state._execute_direct_once.assert_awaited_once()

    async def test_http_conflicting_reuse_returns_409(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = NodeControlState(
                lifecycle=NodeLifecycle(logger=logging.getLogger("idempotency-test")),
                config_path=str(Path(tmp) / "bootstrap.json"),
                logger=logging.getLogger("idempotency-test"),
            )
            state._execute_direct_once = AsyncMock(return_value={"status": "completed", "task_id": "task-1"})
            app = create_node_control_app(state=state, logger=logging.getLogger("idempotency-test"))
            payload = {
                "task_id": "task-1",
                "idempotency_key": "explicit-key",
                "task_family": "task.classification",
                "requested_by": "caller-a",
                "inputs": {},
                "trace_id": "trace-1",
            }
            with TestClient(app) as client:
                first = client.post("/api/execution/direct", json=payload)
                conflict = client.post("/api/execution/direct", json={**payload, "inputs": {"changed": True}})

            self.assertEqual(first.status_code, 200)
            self.assertEqual(conflict.status_code, 409)
            self.assertEqual(conflict.json()["detail"], "idempotency_key_conflict")
            state._execute_direct_once.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
