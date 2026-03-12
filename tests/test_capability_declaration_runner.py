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


class _FakeGovernanceClientSynced:
    async def fetch_baseline_governance(self, **_kwargs):
        class _R:
            status = "synced"
            payload = {
                "policy_version": "1.0",
                "issued_timestamp": "2026-03-11T00:00:00Z",
                "refresh_expectations": {"recommended_interval_seconds": 900, "max_stale_seconds": 3600},
                "generic_node_class_rules": {"allow_task_families": ["summarization"]},
                "feature_gating_defaults": {"prompt_governance_ready": False},
                "telemetry_expectations": {"heartbeat_interval_seconds": 30},
            }
            retryable = False
            error = None

        return _R()


class _FakeGovernanceClientRetry:
    async def fetch_baseline_governance(self, **_kwargs):
        class _R:
            status = "retryable_failure"
            payload = {"detail": "timeout"}
            retryable = True
            error = "timeout"

        return _R()


class _FakeOperationalReadinessReady:
    def status_payload(self):
        return {"ready": True, "last_attempt_at": "2026-03-11T00:00:00Z", "last_error": None, "endpoint": None}

    async def check_once(self, **_kwargs):
        return {"ready": True, "last_attempt_at": "2026-03-11T00:00:00Z", "last_error": None, "endpoint": None}


class _FakeOperationalReadinessNotReady:
    def status_payload(self):
        return {
            "ready": False,
            "last_attempt_at": "2026-03-11T00:00:00Z",
            "last_error": "connect_timeout",
            "endpoint": {"host": "10.0.0.100", "port": 1883, "identity": "main-ai-node"},
        }

    async def check_once(self, **_kwargs):
        return self.status_payload()


class _FakeCapabilityStateStore:
    def __init__(self, existing=None):
        self.saved = None
        self.existing = existing

    def save(self, payload):
        self.saved = payload

    def load(self):
        return self.existing


class _FakeGovernanceStateStore:
    def __init__(self, existing=None):
        self.saved = None
        self.existing = existing

    def save(self, payload):
        self.saved = payload

    def load(self):
        return self.existing


class CapabilityDeclarationRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_accepted_submission_transitions_to_operational(self):
        lifecycle = NodeLifecycle(logger=logging.getLogger("capability-runner-test"))
        lifecycle.transition_to(NodeLifecycleState.TRUSTED)
        lifecycle.transition_to(NodeLifecycleState.CAPABILITY_SETUP_PENDING)
        state_store = _FakeCapabilityStateStore()
        governance_store = _FakeGovernanceStateStore()
        runner = CapabilityDeclarationRunner(
            lifecycle=lifecycle,
            logger=logging.getLogger("capability-runner-test"),
            trust_store=_FakeTrustStore(),
            provider_selection_store=_FakeProviderSelectionStore(),
            node_id="node-001",
            capability_state_store=state_store,
            governance_state_store=governance_store,
            capability_client=_FakeClientAccepted(),
            governance_client=_FakeGovernanceClientSynced(),
            operational_readiness_checker=_FakeOperationalReadinessReady(),
        )
        result = await runner.submit_once()
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(lifecycle.get_state(), NodeLifecycleState.OPERATIONAL)
        self.assertEqual(runner.status_payload()["status"], "accepted")
        self.assertIsNotNone(state_store.saved)
        self.assertEqual(state_store.saved["accepted_profile_id"], "cap-1")
        self.assertIsNotNone(result["governance_bundle"])
        self.assertEqual(governance_store.saved["policy_version"], "1.0")
        self.assertEqual(runner.status_payload()["governance_status"]["state"], "fresh")

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
            governance_client=_FakeGovernanceClientSynced(),
            operational_readiness_checker=_FakeOperationalReadinessReady(),
        )
        result = await runner.submit_once()
        self.assertEqual(result["status"], "retryable_failure")
        self.assertEqual(lifecycle.get_state(), NodeLifecycleState.CAPABILITY_DECLARATION_FAILED_RETRY_PENDING)
        self.assertEqual(runner.status_payload()["status"], "retry_pending")

    async def test_loads_accepted_profile_from_state_store_on_startup(self):
        lifecycle = NodeLifecycle(logger=logging.getLogger("capability-runner-test"))
        lifecycle.transition_to(NodeLifecycleState.TRUSTED)
        lifecycle.transition_to(NodeLifecycleState.CAPABILITY_SETUP_PENDING)
        state_store = _FakeCapabilityStateStore(
            existing={
                "schema_version": "1.0",
                "accepted_declaration_version": "1.0",
                "acceptance_timestamp": "2026-03-11T00:00:00Z",
                "accepted_profile_id": "cap-1",
                "core_restrictions": {},
                "core_notes": None,
                "raw_response": {"status": "accepted"},
            }
        )
        runner = CapabilityDeclarationRunner(
            lifecycle=lifecycle,
            logger=logging.getLogger("capability-runner-test"),
            trust_store=_FakeTrustStore(),
            provider_selection_store=_FakeProviderSelectionStore(),
            node_id="node-001",
            capability_state_store=state_store,
            capability_client=_FakeClientAccepted(),
            governance_client=_FakeGovernanceClientSynced(),
            operational_readiness_checker=_FakeOperationalReadinessReady(),
        )
        status = runner.status_payload()
        self.assertEqual(status["status"], "accepted")
        self.assertEqual(status["accepted_profile"]["accepted_profile_id"], "cap-1")

    async def test_governance_sync_retry_moves_to_retry_pending(self):
        lifecycle = NodeLifecycle(logger=logging.getLogger("capability-runner-test"))
        lifecycle.transition_to(NodeLifecycleState.TRUSTED)
        lifecycle.transition_to(NodeLifecycleState.CAPABILITY_SETUP_PENDING)
        runner = CapabilityDeclarationRunner(
            lifecycle=lifecycle,
            logger=logging.getLogger("capability-runner-test"),
            trust_store=_FakeTrustStore(),
            provider_selection_store=_FakeProviderSelectionStore(),
            node_id="node-001",
            capability_state_store=_FakeCapabilityStateStore(),
            capability_client=_FakeClientAccepted(),
            governance_client=_FakeGovernanceClientRetry(),
            operational_readiness_checker=_FakeOperationalReadinessReady(),
        )
        result = await runner.submit_once()
        self.assertEqual(result["status"], "retryable_failure")
        self.assertEqual(lifecycle.get_state(), NodeLifecycleState.CAPABILITY_DECLARATION_FAILED_RETRY_PENDING)
        self.assertEqual(runner.status_payload()["status"], "retry_pending")

    async def test_governance_refresh_returns_retryable_with_existing_bundle(self):
        lifecycle = NodeLifecycle(logger=logging.getLogger("capability-runner-test"))
        lifecycle.transition_to(NodeLifecycleState.TRUSTED)
        lifecycle.transition_to(NodeLifecycleState.CAPABILITY_SETUP_PENDING)
        governance_store = _FakeGovernanceStateStore(
            existing={
                "schema_version": "1.0",
                "policy_version": "1.0",
                "issued_timestamp": "2026-03-11T00:00:00+00:00",
                "synced_at": "2026-03-11T00:05:00+00:00",
                "refresh_expectations": {"recommended_interval_seconds": 900, "max_stale_seconds": 3600},
                "generic_node_class_rules": {},
                "feature_gating_defaults": {},
                "telemetry_expectations": {},
                "raw_response": {},
            }
        )
        runner = CapabilityDeclarationRunner(
            lifecycle=lifecycle,
            logger=logging.getLogger("capability-runner-test"),
            trust_store=_FakeTrustStore(),
            provider_selection_store=_FakeProviderSelectionStore(),
            node_id="node-001",
            governance_state_store=governance_store,
            capability_client=_FakeClientAccepted(),
            governance_client=_FakeGovernanceClientRetry(),
        )
        result = await runner.refresh_governance_once()
        self.assertEqual(result["status"], "retryable_failure")
        self.assertEqual(result["governance_status"]["refresh_state"], "core_temporarily_unavailable")

    async def test_operational_readiness_failure_moves_to_retry_pending(self):
        lifecycle = NodeLifecycle(logger=logging.getLogger("capability-runner-test"))
        lifecycle.transition_to(NodeLifecycleState.TRUSTED)
        lifecycle.transition_to(NodeLifecycleState.CAPABILITY_SETUP_PENDING)
        runner = CapabilityDeclarationRunner(
            lifecycle=lifecycle,
            logger=logging.getLogger("capability-runner-test"),
            trust_store=_FakeTrustStore(),
            provider_selection_store=_FakeProviderSelectionStore(),
            node_id="node-001",
            capability_state_store=_FakeCapabilityStateStore(),
            governance_state_store=_FakeGovernanceStateStore(),
            capability_client=_FakeClientAccepted(),
            governance_client=_FakeGovernanceClientSynced(),
            operational_readiness_checker=_FakeOperationalReadinessNotReady(),
        )
        result = await runner.submit_once()
        self.assertEqual(result["status"], "retryable_failure")
        self.assertEqual(lifecycle.get_state(), NodeLifecycleState.CAPABILITY_DECLARATION_FAILED_RETRY_PENDING)
        self.assertEqual(runner.status_payload()["status"], "retry_pending")


if __name__ == "__main__":
    unittest.main()
