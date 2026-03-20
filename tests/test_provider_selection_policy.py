import unittest

from ai_node.execution.provider_selection_policy import (
    ProviderSelectionPolicyInput,
    build_provider_selection_policy,
)


class ProviderSelectionPolicyTests(unittest.TestCase):
    def test_prefers_requested_then_default_then_remaining_enabled_provider_order(self):
        decision = build_provider_selection_policy(
            ProviderSelectionPolicyInput(
                enabled_providers=["openai", "local"],
                default_provider="openai",
                requested_provider="local",
                provider_health={
                    "openai": {"availability": "available"},
                    "local": {"availability": "degraded"},
                },
                provider_retry_count={"openai": 1, "local": 0},
                request_timeout_s=60,
            )
        )

        self.assertEqual(decision.provider_order, ["local", "openai"])
        self.assertTrue(decision.fallback_allowed)
        self.assertEqual(decision.retry_count_by_provider, {"local": 0, "openai": 1})

    def test_filters_out_providers_blocked_by_governance(self):
        decision = build_provider_selection_policy(
            ProviderSelectionPolicyInput(
                enabled_providers=["openai", "local"],
                default_provider="openai",
                provider_health={
                    "openai": {"availability": "available"},
                    "local": {"availability": "available"},
                },
                governance_constraints={"approved_providers": ["local"]},
            )
        )

        self.assertEqual(decision.provider_order, ["local"])
        self.assertFalse(decision.fallback_allowed)

    def test_intersects_usable_models_with_governance_approved_models(self):
        decision = build_provider_selection_policy(
            ProviderSelectionPolicyInput(
                enabled_providers=["openai"],
                default_provider="openai",
                provider_health={"openai": {"availability": "available"}},
                usable_models_by_provider={"openai": ["gpt-5-mini", "gpt-5-nano"]},
                governance_constraints={"approved_models": {"openai": ["gpt-5-nano", "gpt-5.4"]}},
            )
        )

        self.assertEqual(decision.model_allowlist_by_provider["openai"], ["gpt-5-nano"])

    def test_requested_model_narrows_allowlist(self):
        decision = build_provider_selection_policy(
            ProviderSelectionPolicyInput(
                enabled_providers=["openai"],
                default_provider="openai",
                requested_model="gpt-5-nano",
                provider_health={"openai": {"availability": "available"}},
                usable_models_by_provider={"openai": ["gpt-5-mini", "gpt-5-nano"]},
            )
        )

        self.assertEqual(decision.model_allowlist_by_provider["openai"], ["gpt-5-nano"])

    def test_caps_timeout_and_retry_count_using_governance_constraints(self):
        decision = build_provider_selection_policy(
            ProviderSelectionPolicyInput(
                enabled_providers=["openai"],
                default_provider="openai",
                provider_health={"openai": {"availability": "available"}},
                provider_retry_count={"openai": 3},
                request_timeout_s=120,
                governance_constraints={"routing_policy_constraints": {"max_timeout_s": 30, "max_retry_count": 1}},
            )
        )

        self.assertEqual(decision.timeout_s, 30)
        self.assertEqual(decision.retry_count_by_provider["openai"], 1)

    def test_rejects_when_no_eligible_provider_is_available(self):
        decision = build_provider_selection_policy(
            ProviderSelectionPolicyInput(
                enabled_providers=["openai"],
                default_provider="openai",
                provider_health={"openai": {"availability": "unavailable"}},
            )
        )

        self.assertEqual(decision.provider_order, [])
        self.assertEqual(decision.rejection_reason, "no_eligible_provider_available")


if __name__ == "__main__":
    unittest.main()
