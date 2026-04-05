import unittest

from ai_node.execution.gateway import ExecutionGateway


class ExecutionGatewayTests(unittest.TestCase):
    def test_deny_when_prompt_not_registered(self):
        gateway = ExecutionGateway()
        result = gateway.authorize(
            prompt_id="prompt.missing",
            task_family="task.classification",
            prompt_services_state={"prompt_services": []},
        )
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "prompt_not_registered")

    def test_deny_when_prompt_is_in_probation(self):
        gateway = ExecutionGateway()
        result = gateway.authorize(
            prompt_id="prompt.alpha",
            task_family="task.classification",
            prompt_services_state={
                "prompt_services": [
                    {
                        "prompt_id": "prompt.alpha",
                        "task_family": "task.classification",
                        "status": "probation",
                    }
                ]
            },
        )
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "prompt_in_probation")

    def test_allow_registered_prompt(self):
        gateway = ExecutionGateway()
        result = gateway.authorize(
            prompt_id="prompt.alpha",
            task_family="task.classification",
            prompt_services_state={
                "prompt_services": [
                    {
                        "prompt_id": "prompt.alpha",
                        "task_family": "task.classification",
                        "status": "registered",
                    }
                ]
            },
        )
        self.assertTrue(result.allowed)
        self.assertEqual(result.reason, "authorized")
        self.assertEqual(result.prompt_version, "v1")

    def test_allow_review_due_prompt(self):
        gateway = ExecutionGateway()
        result = gateway.authorize(
            prompt_id="prompt.alpha",
            task_family="task.classification",
            requested_by="svc-alpha",
            service_id="svc-alpha",
            prompt_services_state={
                "prompt_services": [
                    {
                        "prompt_id": "prompt.alpha",
                        "service_id": "svc-alpha",
                        "owner_service": "svc-alpha",
                        "task_family": "task.classification",
                        "status": "review_due",
                    }
                ]
            },
        )
        self.assertTrue(result.allowed)
        self.assertEqual(result.prompt_state, "review_due")

    def test_deny_when_prompt_access_scope_blocks_caller(self):
        gateway = ExecutionGateway()
        result = gateway.authorize(
            prompt_id="prompt.alpha",
            task_family="task.classification",
            requested_by="svc-beta",
            service_id="svc-beta",
            prompt_services_state={
                "prompt_services": [
                    {
                        "prompt_id": "prompt.alpha",
                        "service_id": "svc-alpha",
                        "owner_service": "svc-alpha",
                        "task_family": "task.classification",
                        "status": "active",
                        "access_scope": "service",
                    }
                ]
            },
        )
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "prompt_access_denied")

    def test_deny_when_prompt_version_is_missing(self):
        gateway = ExecutionGateway()
        result = gateway.authorize(
            prompt_id="prompt.alpha",
            prompt_version="v2",
            task_family="task.classification",
            prompt_services_state={
                "prompt_services": [
                    {
                        "prompt_id": "prompt.alpha",
                        "task_family": "task.classification",
                        "status": "active",
                        "current_version": "v1",
                        "versions": [{"version": "v1", "definition": {}}],
                    }
                ]
            },
        )
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "invalid_prompt_version")

    def test_deny_when_structured_output_required_and_missing(self):
        gateway = ExecutionGateway()
        result = gateway.authorize(
            prompt_id="prompt.alpha",
            task_family="task.classification",
            prompt_services_state={
                "prompt_services": [
                    {
                        "prompt_id": "prompt.alpha",
                        "task_family": "task.classification",
                        "status": "active",
                        "current_version": "v1",
                        "versions": [{"version": "v1", "definition": {}}],
                        "constraints": {"structured_output_required": True},
                    }
                ]
            },
            inputs={"text": "hello"},
        )
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "prompt_structured_output_required")


if __name__ == "__main__":
    unittest.main()
