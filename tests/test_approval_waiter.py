import logging
import unittest

from ai_node.lifecycle.node_lifecycle import NodeLifecycle, NodeLifecycleState
from ai_node.registration.approval_waiter import (
    ApprovalRejectedError,
    PendingApprovalWaiter,
)


class _FakeHttpAdapter:
    def __init__(self, responses: list[dict]):
        self._responses = responses
        self.post_calls = 0
        self.get_calls = 0
        self.last_url = None

    async def post_json(self, _url: str, _payload: dict):
        self.post_calls += 1
        return {}

    async def get_json(self, url: str):
        self.get_calls += 1
        self.last_url = url
        if not self._responses:
            return {"status": "pending_approval"}
        return self._responses.pop(0)


class PendingApprovalWaiterTests(unittest.IsolatedAsyncioTestCase):
    async def test_begin_pending_approval_transitions_state_and_returns_metadata(self):
        logger = logging.getLogger("approval-waiter-test")
        lifecycle = NodeLifecycle(logger=logger)
        lifecycle.transition_to(NodeLifecycleState.BOOTSTRAP_CONNECTING)
        lifecycle.transition_to(NodeLifecycleState.BOOTSTRAP_CONNECTED)
        lifecycle.transition_to(NodeLifecycleState.CORE_DISCOVERED)
        lifecycle.transition_to(NodeLifecycleState.REGISTRATION_PENDING)

        adapter = _FakeHttpAdapter([])
        waiter = PendingApprovalWaiter(
            lifecycle=lifecycle,
            http_adapter=adapter,
            logger=logger,
            poll_interval_seconds=0.001,
            max_polls=5,
        )

        info = waiter.begin_pending_approval(
            {
                "status": "pending_approval",
                "approval_url": "http://core.local/ui/nodes/pending",
                "status_url": "http://core.local/api/nodes/requests/req-1/status",
            }
        )

        self.assertEqual(info.approval_url, "http://core.local/ui/nodes/pending")
        self.assertEqual(info.status_url, "http://core.local/api/nodes/requests/req-1/status")
        self.assertEqual(lifecycle.get_state(), NodeLifecycleState.PENDING_APPROVAL)

    async def test_wait_for_decision_polls_until_approved_without_reregister(self):
        logger = logging.getLogger("approval-waiter-test")
        lifecycle = NodeLifecycle(logger=logger)
        lifecycle.transition_to(NodeLifecycleState.BOOTSTRAP_CONNECTING)
        lifecycle.transition_to(NodeLifecycleState.BOOTSTRAP_CONNECTED)
        lifecycle.transition_to(NodeLifecycleState.CORE_DISCOVERED)
        lifecycle.transition_to(NodeLifecycleState.REGISTRATION_PENDING)

        adapter = _FakeHttpAdapter(
            [
                {"status": "pending_approval"},
                {"status": "pending_approval"},
                {"status": "approved", "node_id": "node-ai-001"},
            ]
        )
        waiter = PendingApprovalWaiter(
            lifecycle=lifecycle,
            http_adapter=adapter,
            logger=logger,
            poll_interval_seconds=0.001,
            max_polls=5,
        )
        info = waiter.begin_pending_approval(
            {
                "status": "pending_approval",
                "approval_url": "http://core.local/ui/nodes/pending",
                "status_url": "http://core.local/api/nodes/requests/req-1/status",
            }
        )

        result = await waiter.wait_for_decision(info)

        self.assertEqual(result["status"], "approved")
        self.assertEqual(adapter.get_calls, 3)
        self.assertEqual(adapter.post_calls, 0)

    async def test_wait_for_decision_times_out(self):
        logger = logging.getLogger("approval-waiter-test")
        lifecycle = NodeLifecycle(logger=logger)
        lifecycle.transition_to(NodeLifecycleState.BOOTSTRAP_CONNECTING)
        lifecycle.transition_to(NodeLifecycleState.BOOTSTRAP_CONNECTED)
        lifecycle.transition_to(NodeLifecycleState.CORE_DISCOVERED)
        lifecycle.transition_to(NodeLifecycleState.REGISTRATION_PENDING)

        adapter = _FakeHttpAdapter(
            [{"status": "pending_approval"}, {"status": "pending_approval"}, {"status": "pending_approval"}]
        )
        waiter = PendingApprovalWaiter(
            lifecycle=lifecycle,
            http_adapter=adapter,
            logger=logger,
            poll_interval_seconds=0.001,
            max_polls=2,
        )
        info = waiter.begin_pending_approval(
            {
                "status": "pending_approval",
                "approval_url": "http://core.local/ui/nodes/pending",
                "status_url": "http://core.local/api/nodes/requests/req-1/status",
            }
        )

        with self.assertRaises(TimeoutError):
            await waiter.wait_for_decision(info)

    async def test_handle_final_decision_approved_returns_handoff_payload(self):
        logger = logging.getLogger("approval-waiter-test")
        lifecycle = NodeLifecycle(logger=logger)
        lifecycle.transition_to(NodeLifecycleState.BOOTSTRAP_CONNECTING)
        lifecycle.transition_to(NodeLifecycleState.BOOTSTRAP_CONNECTED)
        lifecycle.transition_to(NodeLifecycleState.CORE_DISCOVERED)
        lifecycle.transition_to(NodeLifecycleState.REGISTRATION_PENDING)
        lifecycle.transition_to(NodeLifecycleState.PENDING_APPROVAL)

        adapter = _FakeHttpAdapter([])
        waiter = PendingApprovalWaiter(
            lifecycle=lifecycle,
            http_adapter=adapter,
            logger=logger,
        )

        decision = waiter.handle_final_decision(
            {
                "status": "approved",
                "node_id": "node-ai-001",
                "node_trust_token": "redacted-token",
            }
        )

        self.assertEqual(decision.status, "approved")
        self.assertIsNotNone(decision.trust_activation_payload)
        self.assertEqual(decision.trust_activation_payload["node_id"], "node-ai-001")

    async def test_handle_final_decision_rejected_stops_with_clear_error(self):
        logger = logging.getLogger("approval-waiter-test")
        lifecycle = NodeLifecycle(logger=logger)
        lifecycle.transition_to(NodeLifecycleState.BOOTSTRAP_CONNECTING)
        lifecycle.transition_to(NodeLifecycleState.BOOTSTRAP_CONNECTED)
        lifecycle.transition_to(NodeLifecycleState.CORE_DISCOVERED)
        lifecycle.transition_to(NodeLifecycleState.REGISTRATION_PENDING)
        lifecycle.transition_to(NodeLifecycleState.PENDING_APPROVAL)

        adapter = _FakeHttpAdapter([])
        waiter = PendingApprovalWaiter(
            lifecycle=lifecycle,
            http_adapter=adapter,
            logger=logger,
        )

        with self.assertRaisesRegex(ApprovalRejectedError, "operator denied request"):
            waiter.handle_final_decision(
                {
                    "status": "rejected",
                    "reason": "operator denied request",
                }
            )


if __name__ == "__main__":
    unittest.main()
