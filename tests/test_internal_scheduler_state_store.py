import logging
import tempfile
import unittest
from pathlib import Path

from ai_node.persistence.internal_scheduler_state_store import (
    InternalSchedulerStateStore,
    create_internal_scheduler_state,
    validate_internal_scheduler_state,
)


class InternalSchedulerStateStoreTests(unittest.TestCase):
    def test_create_default_state_is_valid(self):
        payload = create_internal_scheduler_state()
        is_valid, error = validate_internal_scheduler_state(payload)
        self.assertTrue(is_valid)
        self.assertIsNone(error)

    def test_store_round_trip_preserves_task_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = InternalSchedulerStateStore(
                path=str(Path(tmp) / "internal_scheduler_state.json"),
                logger=logging.getLogger("internal-scheduler-store-test"),
            )
            payload = create_internal_scheduler_state()
            payload["scheduler_status"] = "running"
            payload["tasks"] = {
                "provider_capability_refresh": {
                    "task_id": "provider_capability_refresh",
                    "display_name": "Provider Capability Refresh",
                    "task_kind": "provider_specific_recurring",
                    "schedule_name": "interval",
                    "schedule_detail": "Every 900 seconds after startup refresh",
                    "interval_seconds": 900,
                    "enabled": True,
                    "running": False,
                    "status": "healthy",
                    "readiness_critical": False,
                    "last_started_at": "2026-04-05T14:00:00Z",
                    "last_success_at": "2026-04-05T14:00:01Z",
                    "last_failure_at": None,
                    "last_completed_at": "2026-04-05T14:00:01Z",
                    "last_error": None,
                    "current_error": None,
                    "next_run_at": "2026-04-05T14:15:01Z",
                    "last_result": {"status": "refreshed"},
                    "attempt_count": 1,
                    "consecutive_failures": 0,
                    "updated_at": "2026-04-05T14:00:01Z",
                }
            }

            store.save(payload)
            loaded = store.load()

            self.assertEqual(loaded, payload)


if __name__ == "__main__":
    unittest.main()
