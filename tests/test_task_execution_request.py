import unittest

from pydantic import ValidationError

from ai_node.execution.task_models import TaskExecutionRequest, TaskExecutionResult


class TaskExecutionRequestTests(unittest.TestCase):
    def test_accepts_minimal_valid_payload(self):
        payload = TaskExecutionRequest.model_validate(
            {
                "task_id": "task-001",
                "task_family": "task.classification",
                "requested_by": "service.alpha",
                "inputs": {"text": "hello world"},
                "constraints": {"max_cost_usd": 0.02},
                "priority": "normal",
                "timeout_s": 45,
                "trace_id": "trace-001",
            }
        )

        self.assertEqual(payload.task_id, "task-001")
        self.assertEqual(payload.task_family, "task.classification")
        self.assertEqual(payload.priority, "normal")
        self.assertEqual(payload.timeout_s, 45)
        self.assertIsNone(payload.lease_id)
        self.assertEqual(payload.service_id, "service.alpha")

    def test_accepts_optional_lease_id(self):
        payload = TaskExecutionRequest.model_validate(
            {
                "task_id": "task-lease-001",
                "task_family": "task.summarization.text",
                "requested_by": "scheduler.core",
                "inputs": {"text": "meeting notes"},
                "priority": "high",
                "timeout_s": 120,
                "trace_id": "trace-lease-001",
                "lease_id": "lease-123",
            }
        )

        self.assertEqual(payload.lease_id, "lease-123")

    def test_canonicalizes_legacy_classification_family(self):
        payload = TaskExecutionRequest.model_validate(
            {
                "task_id": "task-legacy-family",
                "task_family": "task.classification.text",
                "requested_by": "service.alpha",
                "inputs": {"text": "legacy"},
                "trace_id": "trace-legacy-family",
            }
        )

        self.assertEqual(payload.task_family, "task.classification")

    def test_accepts_customer_id(self):
        payload = TaskExecutionRequest.model_validate(
            {
                "task_id": "task-customer-001",
                "task_family": "task.summarization.text",
                "requested_by": "service.alpha",
                "customer_id": "customer-001",
                "inputs": {"text": "meeting notes"},
                "priority": "high",
                "timeout_s": 120,
                "trace_id": "trace-customer-001",
            }
        )

        self.assertEqual(payload.customer_id, "customer-001")

    def test_rejects_invalid_task_family_shape(self):
        with self.assertRaises(ValidationError) as context:
            TaskExecutionRequest.model_validate(
                {
                    "task_id": "task-001",
                    "task_family": "BAD FAMILY",
                    "requested_by": "service.alpha",
                    "inputs": {"text": "hello world"},
                    "trace_id": "trace-001",
                }
            )

        self.assertIn("invalid_task_family", str(context.exception))

    def test_rejects_non_object_inputs(self):
        with self.assertRaises(ValidationError) as context:
            TaskExecutionRequest.model_validate(
                {
                    "task_id": "task-001",
                    "task_family": "task.classification",
                    "requested_by": "service.alpha",
                    "inputs": ["bad-input"],
                    "trace_id": "trace-001",
                }
            )

        self.assertIn("inputs", str(context.exception))

    def test_rejects_timeout_outside_phase3_bounds(self):
        with self.assertRaises(ValidationError) as low_context:
            TaskExecutionRequest.model_validate(
                {
                    "task_id": "task-low-timeout",
                    "task_family": "task.classification",
                    "requested_by": "service.alpha",
                    "inputs": {"text": "hello world"},
                    "trace_id": "trace-low-timeout",
                    "timeout_s": 0,
                }
            )
        self.assertIn("timeout_s_must_be_positive", str(low_context.exception))

        with self.assertRaises(ValidationError) as high_context:
            TaskExecutionRequest.model_validate(
                {
                    "task_id": "task-high-timeout",
                    "task_family": "task.classification",
                    "requested_by": "service.alpha",
                    "inputs": {"text": "hello world"},
                    "trace_id": "trace-high-timeout",
                    "timeout_s": 3601,
                }
            )
        self.assertIn("timeout_s_exceeds_phase3_limit", str(high_context.exception))

    def test_rejects_unknown_fields(self):
        with self.assertRaises(ValidationError) as context:
            TaskExecutionRequest.model_validate(
                {
                    "task_id": "task-001",
                    "task_family": "task.classification",
                    "requested_by": "service.alpha",
                    "inputs": {"text": "hello world"},
                    "trace_id": "trace-001",
                    "unexpected": True,
                }
            )

        self.assertIn("unexpected", str(context.exception))


if __name__ == "__main__":
    unittest.main()


class TaskExecutionResultTests(unittest.TestCase):
    def test_accepts_completed_result_payload(self):
        payload = TaskExecutionResult.model_validate(
            {
                "task_id": "task-001",
                "status": "completed",
                "output": {"label": "important"},
                "metrics": {
                    "execution_duration_ms": 125.5,
                    "provider_latency_ms": 121.0,
                    "provider_avg_latency_ms": 119.0,
                    "provider_p95_latency_ms": 140.0,
                    "provider_success_rate": 0.97,
                    "provider_total_requests": 88,
                    "provider_failed_requests": 3,
                    "retries": 0,
                    "fallback_used": False,
                    "prompt_tokens": 12,
                    "completion_tokens": 5,
                    "total_tokens": 17,
                    "estimated_cost": 0.00042,
                },
                "provider_used": "openai",
                "model_used": "gpt-5-mini",
                "completed_at": "2026-03-19T17:00:00Z",
            }
        )

        self.assertEqual(payload.status, "completed")
        self.assertEqual(payload.output, {"label": "important"})
        self.assertEqual(payload.provider_used, "openai")
        self.assertEqual(payload.metrics.total_tokens, 17)
        self.assertEqual(payload.metrics.provider_success_rate, 0.97)

    def test_accepts_non_terminal_accepted_result_without_completion_timestamp(self):
        payload = TaskExecutionResult.model_validate(
            {
                "task_id": "task-accept-001",
                "status": "accepted",
                "metrics": {"retries": 0},
            }
        )

        self.assertEqual(payload.status, "accepted")
        self.assertIsNone(payload.completed_at)

    def test_rejects_failed_result_without_error_code(self):
        with self.assertRaises(ValidationError) as context:
            TaskExecutionResult.model_validate(
                {
                    "task_id": "task-failed-001",
                    "status": "failed",
                    "error_message": "provider timed out",
                    "completed_at": "2026-03-19T17:00:00Z",
                }
            )

        self.assertIn("error_code_required_for_non_success_status", str(context.exception))

    def test_rejects_terminal_status_without_completed_at(self):
        with self.assertRaises(ValidationError) as context:
            TaskExecutionResult.model_validate(
                {
                    "task_id": "task-completed-001",
                    "status": "completed",
                    "output": {"summary": "hello"},
                }
            )

        self.assertIn("completed_at_required_for_terminal_status", str(context.exception))

    def test_rejects_completed_result_without_output(self):
        with self.assertRaises(ValidationError) as context:
            TaskExecutionResult.model_validate(
                {
                    "task_id": "task-completed-001",
                    "status": "completed",
                    "completed_at": "2026-03-19T17:00:00Z",
                }
            )

        self.assertIn("output_required_for_result_status", str(context.exception))
