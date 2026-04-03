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
    def __init__(self, provider_budget_limits=None, intelligence_payload=None):
        self._registry = ProviderRegistry()
        self._provider_budget_limits = provider_budget_limits or {}
        self._intelligence_payload = intelligence_payload or {"providers": []}
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

    def intelligence_payload(self):
        return self._intelligence_payload


class _FakeNotificationService:
    def __init__(self):
        self.calls = []

    def notify(self, **kwargs):
        self.calls.append(kwargs)


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
                payload = manager.status_payload()

            self.assertTrue(reserved.allowed)
            self.assertEqual(payload["provider_budgets"][0]["provider_id"], "openai")
            self.assertEqual(payload["provider_budgets"][0]["period"], "weekly")
            self.assertEqual(payload["provider_budgets"][0]["period_start"], "2026-03-16T00:00:00-07:00")
            self.assertEqual(payload["provider_budgets"][0]["period_end"], "2026-03-22T23:59:59.999999-07:00")

    def test_finalize_execution_updates_provider_budget_usage_without_crashing(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = BudgetStateStore(path=str(Path(tmp) / "budget_state.json"), logger=logging.getLogger("budget-manager-test"))
            manager = BudgetManager(
                store=store,
                logger=logging.getLogger("budget-manager-test"),
                provider_runtime_manager=_FakeRuntimeManager(
                    provider_budget_limits={"openai": {"max_cost_cents": 25, "period": "monthly"}}
                ),
            )
            request = TaskExecutionRequest.model_validate(
                {
                    "task_id": "task-provider-budget",
                    "task_family": "task.classification",
                    "requested_by": "service.alpha",
                    "service_id": "service.alpha",
                    "requested_provider": "openai",
                    "requested_model": "gpt-5-mini",
                    "inputs": {"text": "hello"},
                    "constraints": {"max_cost_cents": 10},
                    "trace_id": "trace-provider-budget",
                }
            )

            reserved = manager.reserve_execution(
                task_id=request.task_id,
                request=request,
                provider_id="openai",
                model_id="gpt-5-mini",
                governance_bundle=None,
            )

            self.assertTrue(reserved.allowed)
            finalized = manager.finalize_execution(
                task_id=request.task_id,
                metrics=type("Metrics", (), {"estimated_cost": 0.05, "total_tokens": 20})(),
                status="completed",
            )

            self.assertEqual(len(finalized["provider_finalized"]), 1)
            payload = manager.status_payload()
            self.assertEqual(payload["provider_budgets"][0]["provider_id"], "openai")
            self.assertEqual(payload["provider_budgets"][0]["used_cost_cents"], 5)
            self.assertEqual(payload["provider_budgets"][0]["used_cost_usd_exact"], 0.05)

    def test_provider_budget_threshold_warning_emits_once_above_ninety_percent(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = BudgetStateStore(path=str(Path(tmp) / "budget_state.json"), logger=logging.getLogger("budget-manager-test"))
            notifications = _FakeNotificationService()
            manager = BudgetManager(
                store=store,
                logger=logging.getLogger("budget-manager-test"),
                provider_runtime_manager=_FakeRuntimeManager(
                    provider_budget_limits={"openai": {"max_cost_cents": 25, "period": "monthly"}}
                ),
                notification_service=notifications,
            )
            request = TaskExecutionRequest.model_validate(
                {
                    "task_id": "task-threshold",
                    "task_family": "task.classification",
                    "requested_by": "service.alpha",
                    "service_id": "service.alpha",
                    "requested_provider": "openai",
                    "requested_model": "gpt-5-mini",
                    "inputs": {"text": "hello"},
                    "constraints": {"max_cost_cents": 10},
                    "trace_id": "trace-threshold",
                }
            )

            for index in range(2):
                task_id = f"task-threshold-{index}"
                reserved = manager.reserve_execution(
                    task_id=task_id,
                    request=request.model_copy(update={"task_id": task_id}),
                    provider_id="openai",
                    model_id="gpt-5-mini",
                    governance_bundle=None,
                )
                self.assertTrue(reserved.allowed)
                manager.finalize_execution(
                    task_id=task_id,
                    metrics=type("Metrics", (), {"estimated_cost": 0.115, "total_tokens": 20})(),
                    status="completed",
                )

            warning_calls = [
                call for call in notifications.calls if call.get("event_type") == "provider_budget_threshold_warning"
            ]
            self.assertEqual(len(warning_calls), 1)
            self.assertEqual(warning_calls[0]["severity"], "warning")

    def test_new_provider_budget_period_emits_period_started_notification(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = BudgetStateStore(path=str(Path(tmp) / "budget_state.json"), logger=logging.getLogger("budget-manager-test"))
            notifications = _FakeNotificationService()
            manager = BudgetManager(
                store=store,
                logger=logging.getLogger("budget-manager-test"),
                provider_runtime_manager=_FakeRuntimeManager(
                    provider_budget_limits={"openai": {"max_cost_cents": 25, "period": "monthly"}}
                ),
                notification_service=notifications,
            )
            request = TaskExecutionRequest.model_validate(
                {
                    "task_id": "task-period",
                    "task_family": "task.classification",
                    "requested_by": "service.alpha",
                    "service_id": "service.alpha",
                    "requested_provider": "openai",
                    "requested_model": "gpt-5-mini",
                    "inputs": {"text": "hello"},
                    "constraints": {"max_cost_cents": 10},
                    "trace_id": "trace-period",
                }
            )
            march_now = local_now().replace(year=2026, month=3, day=31, hour=9, minute=0, second=0, microsecond=0)
            april_now = local_now().replace(year=2026, month=4, day=1, hour=9, minute=0, second=0, microsecond=0)

            with patch("ai_node.runtime.budget_manager._now", return_value=march_now):
                reserved = manager.reserve_execution(
                    task_id="task-period-1",
                    request=request.model_copy(update={"task_id": "task-period-1"}),
                    provider_id="openai",
                    model_id="gpt-5-mini",
                    governance_bundle=None,
                )
                self.assertTrue(reserved.allowed)

            with patch("ai_node.runtime.budget_manager._now", return_value=april_now):
                reserved = manager.reserve_execution(
                    task_id="task-period-2",
                    request=request.model_copy(update={"task_id": "task-period-2"}),
                    provider_id="openai",
                    model_id="gpt-5-mini",
                    governance_bundle=None,
                )
                self.assertTrue(reserved.allowed)

            period_calls = [call for call in notifications.calls if call.get("event_type") == "provider_budget_period_started"]
            self.assertEqual(len(period_calls), 1)
            self.assertEqual(period_calls[0]["data"]["provider_id"], "openai")

    def test_budget_denial_emits_user_notification(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = BudgetStateStore(path=str(Path(tmp) / "budget_state.json"), logger=logging.getLogger("budget-manager-test"))
            notifications = _FakeNotificationService()
            manager = BudgetManager(
                store=store,
                logger=logging.getLogger("budget-manager-test"),
                notification_service=notifications,
            )
            manager.cache_policy_from_governance(governance_bundle={"budget_policy": _active_budget_policy()})
            request = TaskExecutionRequest.model_validate(
                {
                    "task_id": "task-denial",
                    "task_family": "task.classification",
                    "requested_by": "service.beta",
                    "service_id": "service.beta",
                    "customer_id": "missing-customer",
                    "requested_provider": "openai",
                    "requested_model": "gpt-5-mini",
                    "inputs": {"text": "hello"},
                    "trace_id": "trace-denial",
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
            denial_calls = [call for call in notifications.calls if call.get("event_type") == "budget_denial"]
            self.assertEqual(len(denial_calls), 1)
            self.assertEqual(denial_calls[0]["severity"], "warning")

    def test_status_payload_includes_configured_provider_budget_before_usage(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = BudgetStateStore(path=str(Path(tmp) / "budget_state.json"), logger=logging.getLogger("budget-manager-test"))
            manager = BudgetManager(
                store=store,
                logger=logging.getLogger("budget-manager-test"),
                provider_runtime_manager=_FakeRuntimeManager(
                    provider_budget_limits={"openai": {"max_cost_cents": 2500, "period": "monthly"}}
                ),
            )

            payload = manager.status_payload()

            self.assertEqual(len(payload["provider_budgets"]), 1)
            self.assertEqual(payload["provider_budgets"][0]["provider_id"], "openai")
            self.assertEqual(payload["provider_budgets"][0]["budget_limit_cents"], 2500)
            self.assertEqual(payload["provider_budgets"][0]["remaining_cost_cents"], 2500)
            self.assertEqual(payload["provider_budgets"][0]["used_cost_cents"], 0)
            self.assertEqual(payload["provider_budgets"][0]["used_cost_usd_exact"], 0.0)
            self.assertEqual(payload["provider_budgets"][0]["reserved_cost_cents"], 0)

    def test_status_payload_falls_back_to_runtime_exact_spend_for_provider_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = BudgetStateStore(path=str(Path(tmp) / "budget_state.json"), logger=logging.getLogger("budget-manager-test"))
            manager = BudgetManager(
                store=store,
                logger=logging.getLogger("budget-manager-test"),
                provider_runtime_manager=_FakeRuntimeManager(
                    provider_budget_limits={"openai": {"max_cost_cents": 500, "period": "monthly"}},
                    intelligence_payload={
                        "providers": [
                            {
                                "provider_id": "openai",
                                "models": [
                                    {
                                        "pricing_input": 2.5,
                                        "pricing_output": 15.0,
                                        "usage_metrics": {"prompt_tokens": 69, "completion_tokens": 41},
                                    },
                                    {
                                        "pricing_input": 0.2,
                                        "pricing_output": 1.25,
                                        "usage_metrics": {"prompt_tokens": 5575, "completion_tokens": 732},
                                    },
                                ],
                            }
                        ]
                    },
                ),
            )

            payload = manager.status_payload()

            self.assertAlmostEqual(payload["provider_budgets"][0]["used_cost_usd_exact"], 0.0028175, places=10)
            self.assertAlmostEqual(payload["provider_budgets"][0]["remaining_cost_usd_exact"], 4.9971825, places=10)

    def test_status_payload_prefers_runtime_exact_spend_over_stale_saved_usd(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = BudgetStateStore(path=str(Path(tmp) / "budget_state.json"), logger=logging.getLogger("budget-manager-test"))
            state = store.load_or_create()
            state["provider_budget_usage"] = {
                "openai:monthly:2026-04-01T00:00:00-07:00": {
                    "provider_id": "openai",
                    "period": "monthly",
                    "period_start": "2026-04-01T00:00:00-07:00",
                    "period_end": "2026-04-30T23:59:59.999999-07:00",
                    "budget_limit_cents": 500,
                    "used_cost_cents": 16,
                    "used_cost_usd_exact": 0.16,
                    "reserved_cost_cents": 0,
                    "reservations": {},
                    "updated_at": "2026-04-02T18:41:57.203779-07:00",
                }
            }
            store.save(state)
            manager = BudgetManager(
                store=store,
                logger=logging.getLogger("budget-manager-test"),
                provider_runtime_manager=_FakeRuntimeManager(
                    provider_budget_limits={"openai": {"max_cost_cents": 500, "period": "monthly"}},
                    intelligence_payload={
                        "providers": [
                            {
                                "provider_id": "openai",
                                "models": [
                                    {
                                        "pricing_input": 2.5,
                                        "pricing_output": 15.0,
                                        "usage_metrics": {"prompt_tokens": 69, "completion_tokens": 41},
                                    },
                                    {
                                        "pricing_input": 0.2,
                                        "pricing_output": 1.25,
                                        "usage_metrics": {"prompt_tokens": 5575, "completion_tokens": 732},
                                    },
                                ],
                            }
                        ]
                    },
                ),
            )

            payload = manager.status_payload()

            self.assertAlmostEqual(payload["provider_budgets"][0]["used_cost_usd_exact"], 0.0028175, places=10)
            self.assertEqual(payload["provider_budgets"][0]["used_cost_cents"], 1)
            self.assertAlmostEqual(payload["provider_budgets"][0]["remaining_cost_usd_exact"], 4.9971825, places=10)

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

    def test_provider_budget_uses_exact_spend_for_reservation_decisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = BudgetStateStore(path=str(Path(tmp) / "budget_state.json"), logger=logging.getLogger("budget-manager-test"))
            state = store.load_or_create()
            state["provider_budget_usage"] = {
                "openai:monthly:2026-04-01T00:00:00-07:00": {
                    "provider_id": "openai",
                    "period": "monthly",
                    "period_start": "2026-04-01T00:00:00-07:00",
                    "period_end": "2026-04-30T23:59:59.999999-07:00",
                    "budget_limit_cents": 500,
                    "used_cost_cents": 485,
                    "used_cost_usd_exact": 0.06520515,
                    "reserved_cost_cents": 15,
                    "reservations": {},
                    "updated_at": "2026-04-03T08:49:49.463475-07:00",
                }
            }
            store.save(state)
            manager = BudgetManager(
                store=store,
                logger=logging.getLogger("budget-manager-test"),
                provider_runtime_manager=_FakeRuntimeManager(
                    provider_budget_limits={"openai": {"max_cost_cents": 500, "period": "monthly"}}
                ),
            )
            request = TaskExecutionRequest.model_validate(
                {
                    "task_id": "task-provider-exact-spend",
                    "task_family": "task.classification",
                    "requested_by": "service.alpha",
                    "service_id": "service.alpha",
                    "requested_provider": "openai",
                    "requested_model": "gpt-5-mini",
                    "inputs": {"text": "hello"},
                    "constraints": {"max_cost_cents": 1},
                    "trace_id": "trace-provider-exact-spend",
                }
            )

            result = manager.reserve_execution(
                task_id=request.task_id,
                request=request,
                provider_id="openai",
                model_id="gpt-5-mini",
                governance_bundle=None,
            )

            self.assertTrue(result.allowed)

    def test_finalize_provider_budget_rewrites_saved_cents_from_exact_spend(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = BudgetStateStore(path=str(Path(tmp) / "budget_state.json"), logger=logging.getLogger("budget-manager-test"))
            manager = BudgetManager(
                store=store,
                logger=logging.getLogger("budget-manager-test"),
                provider_runtime_manager=_FakeRuntimeManager(
                    provider_budget_limits={"openai": {"max_cost_cents": 500, "period": "monthly"}}
                ),
            )
            request = TaskExecutionRequest.model_validate(
                {
                    "task_id": "task-provider-exact-finalize",
                    "task_family": "task.classification",
                    "requested_by": "service.alpha",
                    "service_id": "service.alpha",
                    "requested_provider": "openai",
                    "requested_model": "gpt-5-mini",
                    "inputs": {"text": "hello"},
                    "constraints": {"max_cost_cents": 1},
                    "trace_id": "trace-provider-exact-finalize",
                }
            )

            reserved = manager.reserve_execution(
                task_id=request.task_id,
                request=request,
                provider_id="openai",
                model_id="gpt-5-mini",
                governance_bundle=None,
            )
            self.assertTrue(reserved.allowed)

            manager.finalize_execution(
                task_id=request.task_id,
                metrics=type("Metrics", (), {"estimated_cost": 0.00013015, "total_tokens": 20})(),
                status="completed",
            )

            payload = manager.status_payload()
            self.assertAlmostEqual(payload["provider_budgets"][0]["used_cost_usd_exact"], 0.00013015, places=10)
            self.assertEqual(payload["provider_budgets"][0]["used_cost_cents"], 1)


if __name__ == "__main__":
    unittest.main()
