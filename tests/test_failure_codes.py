import unittest

from ai_node.execution.failure_codes import FAILURE_CODE_TAXONOMY, classify_failure_code


class FailureCodesTests(unittest.TestCase):
    def test_requested_phase3_failure_categories_are_defined(self):
        self.assertEqual(
            sorted(FAILURE_CODE_TAXONOMY.keys()),
            sorted(
                [
                    "budget_violation",
                    "unsupported_task_family",
                    "provider_unavailable",
                    "model_unavailable",
                    "governance_violation",
                    "invalid_input",
                    "execution_timeout",
                    "lease_expired",
                    "internal_execution_error",
                ]
            ),
        )

    def test_specific_reasons_classify_to_broader_taxonomy(self):
        self.assertEqual(classify_failure_code("no_eligible_provider_available"), "provider_unavailable")
        self.assertEqual(classify_failure_code("no_eligible_model_available"), "model_unavailable")
        self.assertEqual(classify_failure_code("prompt_in_probation"), "governance_violation")
        self.assertEqual(classify_failure_code("governance_violation_timeout"), "governance_violation")
        self.assertEqual(classify_failure_code("invalid_input"), "invalid_input")


if __name__ == "__main__":
    unittest.main()
