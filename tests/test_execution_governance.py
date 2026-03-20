import unittest

from ai_node.execution.governance import evaluate_execution_governance


class ExecutionGovernanceTests(unittest.TestCase):
    def test_allows_broader_existing_task_family_when_governance_uses_generic_family_name(self):
        decision = evaluate_execution_governance(
            task_family="task.summarization.text",
            timeout_s=30,
            inputs={"text": "hello"},
            governance_bundle={"generic_node_class_rules": {"allow_task_families": ["summarization"]}},
        )

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "governance_allowed")

    def test_rejects_task_family_not_allowed_by_governance(self):
        decision = evaluate_execution_governance(
            task_family="task.classification.text",
            timeout_s=30,
            inputs={"text": "hello"},
            governance_bundle={"generic_node_class_rules": {"allow_task_families": ["summarization"]}},
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "governance_violation_task_family")

    def test_rejects_timeout_and_input_size_violations(self):
        timeout_decision = evaluate_execution_governance(
            task_family="task.classification.text",
            timeout_s=90,
            inputs={"text": "hello"},
            request_governance_constraints={"routing_policy_constraints": {"max_timeout_s": 30}},
        )
        self.assertFalse(timeout_decision.allowed)
        self.assertEqual(timeout_decision.reason, "governance_violation_timeout")

        input_decision = evaluate_execution_governance(
            task_family="task.classification.text",
            timeout_s=30,
            inputs={"text": "hello world"},
            request_governance_constraints={"routing_policy_constraints": {"max_input_bytes": 5}},
        )
        self.assertFalse(input_decision.allowed)
        self.assertEqual(input_decision.reason, "governance_violation_input_size")

    def test_rejects_provider_and_model_not_approved(self):
        provider_decision = evaluate_execution_governance(
            task_family="task.classification.text",
            timeout_s=30,
            inputs={"text": "hello"},
            request_governance_constraints={"approved_providers": ["local"]},
            provider_id="openai",
        )
        self.assertFalse(provider_decision.allowed)
        self.assertEqual(provider_decision.reason, "governance_violation_provider")

        model_decision = evaluate_execution_governance(
            task_family="task.classification.text",
            timeout_s=30,
            inputs={"text": "hello"},
            request_governance_constraints={"approved_models": {"openai": ["gpt-5-mini"]}},
            provider_id="openai",
            model_id="gpt-5-nano",
        )
        self.assertFalse(model_decision.allowed)
        self.assertEqual(model_decision.reason, "governance_violation_model")


if __name__ == "__main__":
    unittest.main()
