from datetime import datetime, timedelta, timezone
import unittest

from pydantic import ValidationError

from ai_node.execution.task_models import TaskExecutionRequest


class TaskQueueIntentTests(unittest.TestCase):
    def _base_request(self, **overrides):
        payload = {
            "task_id": "task-queue-intent-001",
            "task_family": "task.classification",
            "requested_by": "client-a",
            "trace_id": "trace-queue-intent-001",
        }
        payload.update(overrides)
        return TaskExecutionRequest.model_validate(payload)

    def test_queue_intent_accepts_importance_and_wait_budget(self):
        request = self._base_request(
            queue={
                "importance": "critical",
                "max_wait_seconds": 30,
                "deadline_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
                "allow_cloud_spillover": True,
                "local_preferred": True,
                "reason": "doorbell response",
            }
        )

        self.assertEqual(request.queue.importance, "critical")
        self.assertEqual(request.queue.max_wait_seconds, 30)
        self.assertTrue(request.queue.allow_cloud_spillover)
        self.assertTrue(request.queue.local_preferred)

    def test_background_image_request_gets_background_queue_defaults(self):
        request = self._base_request(
            task_family="task.image_generation",
            priority="background",
        )

        self.assertEqual(request.queue.importance, "background")
        self.assertEqual(request.queue.priority, "background")
        self.assertEqual(request.queue.queue_class, "background")
        self.assertEqual(request.queue.runtime_lane, "visual_gpu")
        self.assertEqual(request.queue.max_wait_seconds, 6 * 60 * 60)
        self.assertEqual(request.queue.routing_policy, "local_preferred")
        self.assertTrue(request.queue.local_preferred)

    def test_vision_request_gets_vision_lane_default(self):
        request = self._base_request(task_family="task.vision_analysis")

        self.assertEqual(request.queue.runtime_lane, "vision_llm")
        self.assertEqual(request.queue.priority, "normal")

    def test_queue_intent_accepts_lane_priority_and_estimates(self):
        request = self._base_request(
            queue={
                "importance": "high",
                "priority": "low",
                "runtime_lane": "visual_cpu",
                "routing_policy": "local_only",
                "estimated_vram_mib": 512,
                "estimated_runtime_seconds": 90,
            }
        )

        self.assertEqual(request.queue.importance, "high")
        self.assertEqual(request.queue.priority, "low")
        self.assertEqual(request.queue.runtime_lane, "visual_cpu")
        self.assertEqual(request.queue.routing_policy, "local_only")
        self.assertEqual(request.queue.estimated_vram_mib, 512)
        self.assertEqual(request.queue.estimated_runtime_seconds, 90)
        self.assertFalse(request.queue.local_preferred)

    def test_negative_wait_budget_is_rejected(self):
        with self.assertRaises(ValidationError):
            self._base_request(queue={"max_wait_seconds": -1})

    def test_negative_estimates_are_rejected(self):
        with self.assertRaises(ValidationError):
            self._base_request(queue={"estimated_vram_mib": -1})

    def test_past_deadline_is_rejected(self):
        with self.assertRaises(ValidationError):
            self._base_request(queue={"deadline_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()})


if __name__ == "__main__":
    unittest.main()
