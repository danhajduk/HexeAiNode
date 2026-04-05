import logging
import tempfile
import unittest
from pathlib import Path

from ai_node.persistence.budget_state_store import BudgetStateStore, create_budget_state, validate_budget_state


class BudgetStateStoreTests(unittest.TestCase):
    def test_create_default_state_is_valid(self):
        payload = create_budget_state()
        is_valid, error = validate_budget_state(payload)
        self.assertTrue(is_valid)
        self.assertIsNone(error)

    def test_store_round_trip_preserves_budget_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = BudgetStateStore(path=str(Path(tmp) / "budget_state.json"), logger=logging.getLogger("budget-state-test"))
            payload = create_budget_state()
            payload["budget_policy"] = {
                "node_id": "node-001",
                "service": "ai.inference",
                "status": "active",
                "budget_policy_version": "bp-001",
                "governance_version": "gov-001",
                "period_start": "2026-03-20T00:00:00+00:00",
                "period_end": "2026-03-21T00:00:00+00:00",
                "issued_at": "2026-03-20T00:00:00+00:00",
                "grants": [
                    {
                        "grant_id": "grant-node",
                        "consumer_node_id": "node-001",
                        "service": "ai.inference",
                        "period_start": "2026-03-20T00:00:00+00:00",
                        "period_end": "2026-03-21T00:00:00+00:00",
                        "limits": {"max_cost_cents": 100},
                        "status": "active",
                        "scope_kind": "node",
                        "subject_id": "node-001",
                        "governance_version": "gov-001",
                        "budget_policy_version": "bp-001",
                        "metadata": {},
                        "issued_at": "2026-03-20T00:00:00+00:00",
                    }
                ],
            }
            store.save(payload)
            loaded = store.load()
            self.assertEqual(loaded, payload)

    def test_not_configured_policy_without_grants_is_valid(self):
        payload = create_budget_state()
        payload["budget_policy"] = {
            "node_id": "node-001",
            "service": "ai.inference",
            "status": "not_configured",
            "budget_policy_version": None,
            "governance_version": "gov-001",
            "grants": [],
        }

        is_valid, error = validate_budget_state(payload)

        self.assertTrue(is_valid)
        self.assertIsNone(error)


if __name__ == "__main__":
    unittest.main()
