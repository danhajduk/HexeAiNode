import logging
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from ai_node.execution.task_models import TaskExecutionRequest
from ai_node.persistence.budget_state_store import BudgetStateStore
from ai_node.providers.models import ModelCapability
from ai_node.providers.provider_registry import ProviderRegistry
from ai_node.runtime.budget_manager import BudgetManager
from ai_node.time_utils import local_now


class _FakeRuntimeManager:
    def __init__(self, provider_budget_limits=None):
        self._registry = ProviderRegistry()
        self._provider_budget_limits = provider_budget_limits or {}
        self._registry.set_models_for_provider(
            provider_id="openai",
            models=[
                ModelCapability(
                    model_id="gpt-5-mini",
                    display_name="gpt-5-mini",
                    pricing_input=1.0,
                    pricing_output=4.0,
                    status="available",
                )
            ],
        )

    def provider_selection_context_payload(self):
        return {"provider_budget_limits": self._provider_budget_limits}


def _active_budget_policy() -> dict:
    return {
        "node_id": "node-001",
        "service": "service.alpha",
        "status": "active",
        "budget_policy_version": "bp-001",
        "governance_version": "gov-001",
        "period_start": "2026-03-20T00:00:00+00:00",
        "period_end": "2099-03-21T00:00:00+00:00",
        "issued_at": "2026-03-20T00:00:00+00:00",
        "grants": [
            {
                "grant_id": "grant-node",
                "consumer_node_id": "node-001",
                "service": "service.alpha",
                "period_start": "2026-03-20T00:00:00+00:00",
                "period_end": "2099-03-21T00:00:00+00:00",
                "limits": {"max_cost_cents": 100},
                "status": "active",
                "scope_kind": "node",
                "subject_id": "node-001",
                "governance_version": "gov-001",
                "budget_policy_version": "bp-001",
                "metadata": {},
                "issued_at": "2026-03-20T00:00:00+00:00",
            },
            {
                "grant_id": "grant-customer",
                "consumer_node_id": "node-001",
                "service": "service.alpha",
                "period_start": "2026-03-20T00:00:00+00:00",
                "period_end": "2099-03-21T00:00:00+00:00",
                "limits": {"max_cost_cents": 50},
                "status": "active",
                "scope_kind": "customer",
                "subject_id": "customer-001",
                "governance_version": "gov-001",
                "budget_policy_version": "bp-001",
                "metadata": {},
                "issued_at": "2026-03-20T00:00:00+00:00",
            },
            {
                "grant_id": "grant-provider",
                "consumer_node_id": "node-001",
                "service": "service.alpha",
                "period_start": "2026-03-20T00:00:00+00:00",
                "period_end": "2099-03-21T00:00:00+00:00",
                "limits": {"max_cost_cents": 25},
                "status": "active",
                "scope_kind": "provider",
                "subject_id": "openai",
                "governance_version": "gov-001",
                "budget_policy_version": "bp-001",
                "metadata": {},
                "issued_at": "2026-03-20T00:00:00+00:00",
            },
        ],
    }


class BudgetManagerTests(unittest.TestCase):
    def test_reserve_and_finalize_updates_usage(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = BudgetStateStore(path=str(Path(tmp) / "budget_state.json"), logger=logging.getLogger("budget-manager-test"))
            manager = BudgetManager(
                store=store,
                logger=logging.getLogger("budget-manager-test"),
                provider_runtime_manager=_FakeRuntimeManager(),
            )
            manager.cache_policy_from_governance(governance_bundle={"budget_policy": _active_budget_policy()})
            request = TaskExecutionRequest.model_validate(
                {
                    "task_id": "task-001",
                    "task_family": "task.classification",
                    "requested_by": "service.alpha",
                    "service_id": "service.alpha",
                    "customer_id": "customer-001",
                    "requested_provider": "openai",
                    "requested_model": "gpt-5-mini",
                    "inputs": {"text": "hello", "max_tokens": 32},
                    "constraints": {"max_cost_cents": 10},
                    "trace_id": "trace-001",
                }
            )

            reserved = manager.reserve_execution(
                task_id=request.task_id,
                request=request,
                provider_id="openai",
                model_id="gpt-5-mini",
                governance_bundle={"budget_policy": _active_budget_policy()},
            )

            self.assertTrue(reserved.allowed)
            finalized = manager.finalize_execution(
                task_id=request.task_id,
                metrics=type("Metrics", (), {"estimated_cost": 0.05, "total_tokens": 20})(),
                status="completed",
            )
            self.assertEqual(len(finalized["finalized"]), 3)
            payload = manager.status_payload()
            self.assertEqual(payload["grant_count"], 3)
            self.assertEqual(payload["grants"][0]["used_requests"], 1)

    def test_reserve_rejects_when_no_applicable_grant_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = BudgetStateStore(path=str(Path(tmp) / "budget_state.json"), logger=logging.getLogger("budget-manager-test"))
            manager = BudgetManager(store=store, logger=logging.getLogger("budget-manager-test"))
            manager.cache_policy_from_governance(governance_bundle={"budget_policy": _active_budget_policy()})
            request = TaskExecutionRequest.model_validate(
                {
                    "task_id": "task-002",
                    "task_family": "task.classification",
                    "requested_by": "service.beta",
                    "service_id": "service.beta",
                    "customer_id": "missing-customer",
                    "requested_provider": "openai",
                    "requested_model": "gpt-5-mini",
                    "inputs": {"text": "hello"},
                    "trace_id": "trace-002",
                }
            )

            result = manager.reserve_execution(
                task_id=request.task_id,
                request=request,
                provider_id="other-provider",
                model_id="gpt-5-mini",
                governance_bundle={"budget_policy": _active_budget_policy()},
            )

            self.assertFalse(result.allowed)
            self.assertEqual(result.reason, "missing_budget_grant")

    def test_provider_budget_weekly_window_uses_local_monday_to_sunday(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = BudgetStateStore(path=str(Path(tmp) / "budget_state.json"), logger=logging.getLogger("budget-manager-test"))
            manager = BudgetManager(
                store=store,
                logger=logging.getLogger("budget-manager-test"),
                provider_runtime_manager=_FakeRuntimeManager(
                    provider_budget_limits={"openai": {"max_cost_cents": 25, "period": "weekly"}}
                ),
            )
            request = TaskExecutionRequest.model_validate(
                {
                    "task_id": "task-weekly",
                    "task_family": "task.classification",
                    "requested_by": "service.alpha",
                    "service_id": "service.alpha",
                    "requested_provider": "openai",
                    "requested_model": "gpt-5-mini",
                    "inputs": {"text": "hello"},
                    "constraints": {"max_cost_cents": 10},
                    "trace_id": "trace-weekly",
                }
            )
            frozen_now = local_now().replace(year=2026, month=3, day=18, hour=9, minute=30, second=0, microsecond=0)
            with patch("ai_node.runtime.budget_manager._now", return_value=frozen_now):
                reserved = manager.reserve_execution(
                    task_id=request.task_id,
                    request=request,
                    provider_id="openai",
                    model_id="gpt-5-mini",
                    governance_bundle=None,
                )

            self.assertTrue(reserved.allowed)
            payload = manager.status_payload()
            self.assertEqual(payload["provider_budgets"][0]["provider_id"], "openai")
            self.assertEqual(payload["provider_budgets"][0]["period"], "weekly")
            self.assertEqual(payload["provider_budgets"][0]["period_start"], "2026-03-16T00:00:00-07:00")
            self.assertEqual(payload["provider_budgets"][0]["period_end"], "2026-03-22T23:59:59.999999-07:00")

    def test_provider_budget_can_deny_before_core_policy_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = BudgetStateStore(path=str(Path(tmp) / "budget_state.json"), logger=logging.getLogger("budget-manager-test"))
            manager = BudgetManager(
                store=store,
                logger=logging.getLogger("budget-manager-test"),
                provider_runtime_manager=_FakeRuntimeManager(
                    provider_budget_limits={"openai": {"max_cost_cents": 5, "period": "monthly"}}
                ),
            )
            request = TaskExecutionRequest.model_validate(
                {
                    "task_id": "task-provider-limit",
                    "task_family": "task.classification",
                    "requested_by": "service.alpha",
                    "service_id": "service.alpha",
                    "requested_provider": "openai",
                    "requested_model": "gpt-5-mini",
                    "inputs": {"text": "hello"},
                    "constraints": {"max_cost_cents": 10},
                    "trace_id": "trace-provider-limit",
                }
            )

            result = manager.reserve_execution(
                task_id=request.task_id,
                request=request,
                provider_id="openai",
                model_id="gpt-5-mini",
                governance_bundle=None,
            )

            self.assertFalse(result.allowed)
            self.assertEqual(result.reason, "provider_budget_exhausted")


if __name__ == "__main__":
    unittest.main()
