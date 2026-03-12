import unittest

from ai_node.execution.gateway import ExecutionGateway


class ExecutionGatewayTests(unittest.TestCase):
    def test_deny_when_prompt_not_registered(self):
        gateway = ExecutionGateway()
        result = gateway.authorize(
            prompt_id="prompt.missing",
            task_family="task.classification.text",
            prompt_services_state={"prompt_services": []},
        )
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "prompt_not_registered")

    def test_deny_when_prompt_is_in_probation(self):
        gateway = ExecutionGateway()
        result = gateway.authorize(
            prompt_id="prompt.alpha",
            task_family="task.classification.text",
            prompt_services_state={
                "prompt_services": [
                    {
                        "prompt_id": "prompt.alpha",
                        "task_family": "task.classification.text",
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
            task_family="task.classification.text",
            prompt_services_state={
                "prompt_services": [
                    {
                        "prompt_id": "prompt.alpha",
                        "task_family": "task.classification.text",
                        "status": "registered",
                    }
                ]
            },
        )
        self.assertTrue(result.allowed)
        self.assertEqual(result.reason, "authorized")


if __name__ == "__main__":
    unittest.main()
