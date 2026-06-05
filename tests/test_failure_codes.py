import unittest

from ai_node.execution.failure_codes import FAILURE_CODE_TAXONOMY, classify_failure_code, recovery_policy_for_failure_code


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
        self.assertEqual(classify_failure_code("prompt_access_denied"), "governance_violation")
        self.assertEqual(classify_failure_code("governance_violation_timeout"), "governance_violation")
        self.assertEqual(classify_failure_code("invalid_input"), "invalid_input")

    def test_recovery_policy_maps_retry_and_fallback_by_failure_category(self):
        provider_policy = recovery_policy_for_failure_code("no_eligible_provider_available")
        self.assertEqual(provider_policy["failure_category"], "provider_unavailable")
        self.assertTrue(provider_policy["retryable"])
        self.assertTrue(provider_policy["fallback_allowed"])
        self.assertEqual(provider_policy["action"], "retry_or_fallback")

        governance_policy = recovery_policy_for_failure_code("prompt_access_denied")
        self.assertFalse(governance_policy["retryable"])
        self.assertFalse(governance_policy["fallback_allowed"])
        self.assertEqual(governance_policy["action"], "fix_request_or_policy")


if __name__ == "__main__":
    unittest.main()
