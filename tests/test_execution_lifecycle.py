import unittest

from ai_node.execution.lifecycle import EXECUTION_LIFECYCLE_STATES, ExecutionLifecycleTracker


class ExecutionLifecycleTests(unittest.TestCase):
    def test_canonical_execution_lifecycle_states_match_phase3_contract(self):
        self.assertEqual(
            EXECUTION_LIFECYCLE_STATES,
            (
                "idle",
                "receiving_task",
                "validating_task",
                "queued_local",
                "executing",
                "reporting_progress",
                "completed",
                "failed",
                "degraded",
                "rejected",
            ),
        )

    def test_tracker_keeps_non_terminal_tasks_active(self):
        tracker = ExecutionLifecycleTracker()

        record = tracker.update(task_id="task-001", state="executing", provider_id="openai", model_id="gpt-5-mini")

        self.assertEqual(record.state, "executing")
        self.assertEqual(tracker.active_payload()["active_count"], 1)
        self.assertEqual(tracker.get_active(task_id="task-001").provider_id, "openai")

    def test_tracker_moves_terminal_states_into_history(self):
        tracker = ExecutionLifecycleTracker()

        tracker.update(task_id="task-001", state="executing")
        tracker.update(task_id="task-001", state="completed", details={"status": "ok"})

        self.assertEqual(tracker.active_payload()["active_count"], 0)
        self.assertEqual(tracker.history_payload()["history_count"], 1)
        self.assertEqual(tracker.history_payload()["history"][0]["state"], "completed")

    def test_tracker_rejects_unknown_state(self):
        tracker = ExecutionLifecycleTracker()

        with self.assertRaises(ValueError):
            tracker.update(task_id="task-001", state="not-a-real-state")


if __name__ == "__main__":
    unittest.main()
