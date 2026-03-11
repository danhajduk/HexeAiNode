import logging
import unittest

from ai_node.lifecycle.node_lifecycle import NodeLifecycle, NodeLifecycleState
from ai_node.runtime.capability_declaration_runner import CapabilityDeclarationRunner


class _FakeTrustStore:
    def __init__(self):
        self.payload = {
            "node_id": "node-001",
            "node_name": "main-ai-node",
            "node_type": "ai-node",
            "paired_core_id": "core-main",
            "core_api_endpoint": "http://10.0.0.100:9001",
            "node_trust_token": "token",
            "initial_baseline_policy": {"policy_version": "1.0"},
            "baseline_policy_version": "1.0",
            "operational_mqtt_identity": "main-ai-node",
            "operational_mqtt_token": "mqtt-token",
            "operational_mqtt_host": "10.0.0.100",
            "operational_mqtt_port": 1883,
            "bootstrap_mqtt_host": "10.0.0.100",
            "registration_timestamp": "2026-03-11T00:00:00Z",
        }

    def load(self):
        return self.payload


class _FakeProviderSelectionStore:
    def load_or_create(self, **_kwargs):
        return {
            "schema_version": "1.0",
            "providers": {
                "supported": {"cloud": ["openai"], "local": [], "future": []},
                "enabled": ["openai"],
            },
            "services": {"enabled": [], "future": []},
        }


class _FakeClientAccepted:
    async def submit_manifest(self, **_kwargs):
        class _R:
            status = "accepted"
            payload = {"status": "accepted", "accepted_profile_id": "cap-1"}
            retryable = False
            error = None

        return _R()


class _FakeClientRetry:
    async def submit_manifest(self, **_kwargs):
        class _R:
            status = "retryable_failure"
            payload = {"detail": "timeout"}
            retryable = True
            error = "timeout"

        return _R()


class CapabilityDeclarationRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_accepted_submission_transitions_to_operational(self):
        lifecycle = NodeLifecycle(logger=logging.getLogger("capability-runner-test"))
        lifecycle.transition_to(NodeLifecycleState.TRUSTED)
        lifecycle.transition_to(NodeLifecycleState.CAPABILITY_SETUP_PENDING)
        runner = CapabilityDeclarationRunner(
            lifecycle=lifecycle,
            logger=logging.getLogger("capability-runner-test"),
            trust_store=_FakeTrustStore(),
            provider_selection_store=_FakeProviderSelectionStore(),
            node_id="node-001",
            capability_client=_FakeClientAccepted(),
        )
        result = await runner.submit_once()
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(lifecycle.get_state(), NodeLifecycleState.OPERATIONAL)
        self.assertEqual(runner.status_payload()["status"], "accepted")

    async def test_retryable_submission_transitions_to_retry_pending(self):
        lifecycle = NodeLifecycle(logger=logging.getLogger("capability-runner-test"))
        lifecycle.transition_to(NodeLifecycleState.TRUSTED)
        lifecycle.transition_to(NodeLifecycleState.CAPABILITY_SETUP_PENDING)
        runner = CapabilityDeclarationRunner(
            lifecycle=lifecycle,
            logger=logging.getLogger("capability-runner-test"),
            trust_store=_FakeTrustStore(),
            provider_selection_store=_FakeProviderSelectionStore(),
            node_id="node-001",
            capability_client=_FakeClientRetry(),
        )
        result = await runner.submit_once()
        self.assertEqual(result["status"], "retryable_failure")
        self.assertEqual(lifecycle.get_state(), NodeLifecycleState.CAPABILITY_DECLARATION_FAILED_RETRY_PENDING)
        self.assertEqual(runner.status_payload()["status"], "retry_pending")


if __name__ == "__main__":
    unittest.main()
