import logging
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from ai_node.persistence.budget_state_store import BudgetStateStore, create_budget_state
from ai_node.runtime.budget_manager import BudgetManager


class _UsageClient:
    def __init__(self, *, accepted=True):
        self.accepted = accepted
        self.calls = []

    async def submit(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            accepted=self.accepted,
            retryable=not self.accepted,
            error=None if self.accepted else "unavailable",
        )


class BudgetUsageFlushTests(unittest.IsolatedAsyncioTestCase):
    def _manager(self, tmp, client):
        store = BudgetStateStore(path=str(Path(tmp) / "budget.json"), logger=logging.getLogger("test"))
        state = create_budget_state()
        state["pending_usage_summaries"] = [
            {
                "grant_id": "grant-1",
                "service": "ai.inference",
                "period_start": "2026-09-01T00:00:00Z",
                "period_end": "2026-10-01T00:00:00Z",
                "used_requests": 2,
                "used_tokens": 100,
                "used_cost_cents": 4,
                "queued_at": "2026-09-27T00:00:00Z",
            }
        ]
        store.save(state)
        manager = BudgetManager(
            store=store,
            logger=logging.getLogger("test"),
            budget_usage_client=client,
            trust_state_provider=lambda: {
                "node_id": "node-001",
                "core_api_endpoint": "http://core.local:9001",
                "node_trust_token": "trust-token",
            },
        )
        return manager, store

    async def test_successful_flush_removes_delivered_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = _UsageClient()
            manager, store = self._manager(tmp, client)

            result = await manager.flush_pending_usage_summaries()

            self.assertEqual(result["submitted"], 1)
            self.assertEqual(result["remaining"], 0)
            self.assertEqual(store.load()["pending_usage_summaries"], [])
            self.assertEqual(client.calls[0]["node_id"], "node-001")

    async def test_failed_flush_preserves_summary_for_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager, store = self._manager(tmp, _UsageClient(accepted=False))

            result = await manager.flush_pending_usage_summaries()

            self.assertEqual(result["submitted"], 0)
            self.assertEqual(result["remaining"], 1)
            self.assertEqual(len(store.load()["pending_usage_summaries"]), 1)


if __name__ == "__main__":
    unittest.main()
