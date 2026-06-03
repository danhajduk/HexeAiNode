import asyncio
import json
import logging
import tempfile
import threading
import unittest
from pathlib import Path

from ai_node.persistence.budget_state_store import BudgetStateStore, create_budget_state
from ai_node.persistence.internal_scheduler_state_store import InternalSchedulerStateStore
from ai_node.runtime.internal_scheduler import InternalScheduler


class StorageLockingTests(unittest.TestCase):
    def test_json_state_saves_are_serialized_per_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "budget_state.json"
            store = BudgetStateStore(path=str(path), logger=logging.getLogger("storage-locking-test"))
            errors = []

            def save_state(index: int) -> None:
                try:
                    payload = create_budget_state()
                    payload["updated_at"] = f"2026-06-03T00:00:{index:02d}-07:00"
                    store.save(payload)
                except Exception as exc:  # pragma: no cover - failure detail for thread assertions
                    errors.append(exc)

            threads = [threading.Thread(target=save_state, args=(index,)) for index in range(20)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(errors, [])
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], "1.0")
            self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_scheduler_snapshots_do_not_mutate_state_during_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "internal_scheduler_state.json"
            store = InternalSchedulerStateStore(
                path=str(path),
                logger=logging.getLogger("storage-locking-test"),
            )
            scheduler = InternalScheduler(logger=logging.getLogger("storage-locking-test"), store=store)
            scheduler.register_interval_task(
                task_id="fast_task",
                display_name="Fast Task",
                interval_seconds=1,
            )

            async def run_once() -> dict:
                return {"status": "ok", "items": [{"index": index} for index in range(20)]}

            async def exercise_scheduler() -> None:
                scheduler.start_interval_task(
                    task_id="fast_task",
                    coroutine_factory=run_once,
                    initial_delay_seconds=0,
                )
                for _ in range(10):
                    snapshot = scheduler.snapshot()
                    self.assertIn("fast_task", snapshot["tasks"])
                    await asyncio.sleep(0)
                await scheduler.stop_all()

            asyncio.run(exercise_scheduler())

            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], "1.0")
            self.assertIn("fast_task", payload["tasks"])


if __name__ == "__main__":
    unittest.main()
