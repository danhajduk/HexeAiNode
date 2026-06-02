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
                    "schedule_name": "hourly",
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

    def test_provider_capability_refresh_last_result_is_summarized(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = InternalSchedulerStateStore(
                path=str(Path(tmp) / "internal_scheduler_state.json"),
                logger=logging.getLogger("internal-scheduler-store-test"),
            )
            payload = create_internal_scheduler_state()
            payload["tasks"] = {
                "provider_capability_refresh": {
                    "task_id": "provider_capability_refresh",
                    "display_name": "Provider Capability Refresh",
                    "task_kind": "provider_specific_recurring",
                    "schedule_name": "hourly",
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
                    "last_result": {
                        "status": "refreshed",
                        "changed": True,
                        "core_submission": {
                            "submitted": True,
                            "status": "accepted",
                            "retryable": False,
                            "error": None,
                        },
                        "report": {
                            "generated_at": "2026-04-05T14:00:01Z",
                            "providers": [
                                {
                                    "provider_id": "openai",
                                    "availability": "available",
                                    "models": [
                                        {"model_id": f"model-{index}", "blob": "x" * 1000}
                                        for index in range(20)
                                    ],
                                }
                            ],
                        },
                    },
                    "attempt_count": 1,
                    "consecutive_failures": 0,
                    "updated_at": "2026-04-05T14:00:01Z",
                }
            }

            store.save(payload)
            loaded = store.load()

            last_result = loaded["tasks"]["provider_capability_refresh"]["last_result"]
            self.assertEqual(last_result["status"], "refreshed")
            self.assertTrue(last_result["changed"])
            self.assertEqual(last_result["core_submission"]["status"], "accepted")
            self.assertEqual(last_result["report"]["provider_count"], 1)
            self.assertEqual(last_result["report"]["providers"][0]["provider_id"], "openai")
            self.assertEqual(last_result["report"]["providers"][0]["model_count"], 20)
            self.assertNotIn("models", last_result["report"]["providers"][0])


if __name__ == "__main__":
    unittest.main()
