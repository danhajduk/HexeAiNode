import logging
import unittest
from datetime import datetime, timezone

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


class _FakeTaskCapabilitySelectionStore:
    def load_or_create(self, **_kwargs):
        return {
            "schema_version": "1.0",
            "selected_task_families": [
                "task.classification.text",
                "task.summarization.text",
            ],
        }


class _FakeClientAccepted:
    async def submit_manifest(self, **_kwargs):
        class _R:
            status = "accepted"
            payload = {"status": "accepted", "accepted_profile_id": "cap-1"}
            retryable = False
            error = None

        return _R()

    async def submit_provider_intelligence(self, **_kwargs):
        class _R:
            status = "accepted"
            payload = {"status": "accepted"}
            retryable = False
            error = None

        return _R()


class _FakeClientAcceptedCapture(_FakeClientAccepted):
    def __init__(self):
        self.last_manifest = None

    async def submit_manifest(self, **kwargs):
        self.last_manifest = kwargs.get("capability_manifest")
        return await super().submit_manifest(**kwargs)


class _FakeClientRetry:
    async def submit_manifest(self, **_kwargs):
        class _R:
            status = "retryable_failure"
            payload = {"detail": "timeout"}
            retryable = True
            error = "timeout"

        return _R()

    async def submit_provider_intelligence(self, **_kwargs):
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


class _FakeOperationalReadinessAuthNotReady:
    def status_payload(self):
        return {
            "ready": False,
            "last_attempt_at": "2026-03-11T00:00:00Z",
            "last_error": "connect_rc_5",
            "endpoint": {"host": "10.0.0.100", "port": 1883, "identity": "main-ai-node"},
        }

    async def check_once(self, **_kwargs):
        return self.status_payload()


class _FakeTelemetryPublisher:
    def __init__(self):
        self.last = None

    def status_payload(self):
        return {"published": self.last is not None, "last_topic": "synthia/nodes/node-001/status"}

    async def publish_status(self, **kwargs):
        self.last = kwargs
        return {"published": True, "last_error": None, "last_topic": "synthia/nodes/node-001/status"}


class _FakeTelemetryPublisherFailure:
    def status_payload(self):
        return {"published": False, "last_topic": "synthia/nodes/node-001/status"}

    async def publish_status(self, **_kwargs):
        return {"published": False, "last_error": "mqtt_unavailable", "last_topic": "synthia/nodes/node-001/status"}


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


class _FakePhase2StateStore:
    def __init__(self):
        self.saved = None

    def save(self, payload):
        self.saved = payload


class _FakePromptServiceStateStore:
    def load_or_create(self):
        return {
            "schema_version": "1.0",
            "prompt_services": [
                {
                    "prompt_id": "prompt.alpha",
                    "service_id": "svc-alpha",
                    "task_family": "task.classification.text",
                    "status": "registered",
                    "metadata": {},
                    "registered_at": "2026-03-12T00:00:00Z",
                    "updated_at": "2026-03-12T00:00:00Z",
                },
                {
                    "prompt_id": "prompt.beta",
                    "service_id": "svc-beta",
                    "task_family": "task.summarization.text",
                    "status": "probation",
                    "metadata": {},
                    "registered_at": "2026-03-12T00:00:00Z",
                    "updated_at": "2026-03-12T00:00:00Z",
                },
            ],
            "probation": {
                "active_prompt_ids": ["prompt.beta"],
                "reasons": {"prompt.beta": "quality_review"},
                "updated_at": "2026-03-12T00:00:00Z",
            },
            "updated_at": "2026-03-12T00:00:00Z",
        }


class _FakeProviderRuntimeManager:
    def openai_resolved_capabilities_payload(self):
        return {
            "provider_id": "openai",
            "classification_model": "gpt-5-mini",
            "enabled_model_ids": ["gpt-5-mini", "whisper-1"],
            "task_families": [
                "task.classification",
                "task.reasoning",
                "task.speech_to_text",
            ],
            "capabilities": {
                "reasoning": True,
                "vision": False,
                "image_generation": False,
                "audio_input": True,
                "audio_output": False,
                "realtime": False,
                "tool_calling": True,
                "structured_output": True,
                "long_context": False,
                "coding_strength": "medium",
                "speed_tier": "medium",
                "cost_tier": "medium",
                "recommended_for": ["classification", "reasoning"],
            },
            "enabled_models": [
                {
                    "model_id": "gpt-5-mini",
                    "family": "llm",
                    "reasoning": True,
                },
                {
                    "model_id": "whisper-1",
                    "family": "speech_to_text",
                    "audio_input": True,
                },
            ],
        }


class CapabilityDeclarationRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_accepted_submission_transitions_to_operational(self):
        lifecycle = NodeLifecycle(logger=logging.getLogger("capability-runner-test"))
        lifecycle.transition_to(NodeLifecycleState.TRUSTED)
        lifecycle.transition_to(NodeLifecycleState.CAPABILITY_SETUP_PENDING)
        state_store = _FakeCapabilityStateStore()
        governance_store = _FakeGovernanceStateStore()
        phase2_store = _FakePhase2StateStore()
        telemetry = _FakeTelemetryPublisher()
        runner = CapabilityDeclarationRunner(
            lifecycle=lifecycle,
            logger=logging.getLogger("capability-runner-test"),
            trust_store=_FakeTrustStore(),
            provider_selection_store=_FakeProviderSelectionStore(),
            task_capability_selection_store=_FakeTaskCapabilitySelectionStore(),
            node_id="node-001",
            capability_state_store=state_store,
            governance_state_store=governance_store,
            phase2_state_store=phase2_store,
            capability_client=_FakeClientAccepted(),
            governance_client=_FakeGovernanceClientSynced(),
            operational_readiness_checker=_FakeOperationalReadinessReady(),
            telemetry_publisher=telemetry,
            prompt_service_state_store=_FakePromptServiceStateStore(),
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
        self.assertIsNotNone(telemetry.last)
        self.assertEqual(telemetry.last["payload"]["registered_count"], 1)
        self.assertEqual(telemetry.last["payload"]["probation_count"], 1)
        self.assertIsNotNone(phase2_store.saved)
        self.assertIn("enabled_provider_selection", phase2_store.saved)

    async def test_retryable_submission_transitions_to_retry_pending(self):
        lifecycle = NodeLifecycle(logger=logging.getLogger("capability-runner-test"))
        lifecycle.transition_to(NodeLifecycleState.TRUSTED)
        lifecycle.transition_to(NodeLifecycleState.CAPABILITY_SETUP_PENDING)
        runner = CapabilityDeclarationRunner(
            lifecycle=lifecycle,
            logger=logging.getLogger("capability-runner-test"),
            trust_store=_FakeTrustStore(),
            provider_selection_store=_FakeProviderSelectionStore(),
            task_capability_selection_store=_FakeTaskCapabilitySelectionStore(),
            node_id="node-001",
            capability_client=_FakeClientRetry(),
            governance_client=_FakeGovernanceClientSynced(),
            operational_readiness_checker=_FakeOperationalReadinessReady(),
            telemetry_publisher=_FakeTelemetryPublisher(),
            phase2_state_store=_FakePhase2StateStore(),
        )
        result = await runner.submit_once()
        self.assertEqual(result["status"], "retryable_failure")
        self.assertEqual(lifecycle.get_state(), NodeLifecycleState.DEGRADED)
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
            task_capability_selection_store=_FakeTaskCapabilitySelectionStore(),
            node_id="node-001",
            capability_state_store=state_store,
            capability_client=_FakeClientAccepted(),
            governance_client=_FakeGovernanceClientSynced(),
            operational_readiness_checker=_FakeOperationalReadinessReady(),
            telemetry_publisher=_FakeTelemetryPublisher(),
            phase2_state_store=_FakePhase2StateStore(),
        )
        status = runner.status_payload()
        self.assertEqual(status["status"], "accepted")
        self.assertEqual(status["accepted_profile"]["accepted_profile_id"], "cap-1")

    async def test_resume_operational_if_ready_transitions_to_operational(self):
        lifecycle = NodeLifecycle(logger=logging.getLogger("capability-runner-test"))
        lifecycle.transition_to(NodeLifecycleState.TRUSTED)
        lifecycle.transition_to(NodeLifecycleState.CAPABILITY_SETUP_PENDING)
        now = datetime.now(timezone.utc).isoformat()
        runner = CapabilityDeclarationRunner(
            lifecycle=lifecycle,
            logger=logging.getLogger("capability-runner-test"),
            trust_store=_FakeTrustStore(),
            provider_selection_store=_FakeProviderSelectionStore(),
            task_capability_selection_store=_FakeTaskCapabilitySelectionStore(),
            node_id="node-001",
            capability_state_store=_FakeCapabilityStateStore(
                existing={
                    "schema_version": "1.0",
                    "accepted_declaration_version": "1.0",
                    "acceptance_timestamp": now,
                    "accepted_profile_id": "cap-1",
                    "core_restrictions": {},
                    "core_notes": None,
                    "raw_response": {"status": "accepted"},
                }
            ),
            governance_state_store=_FakeGovernanceStateStore(
                existing={
                    "schema_version": "1.0",
                    "policy_version": "1.0",
                    "issued_timestamp": now,
                    "synced_at": now,
                    "refresh_expectations": {"recommended_interval_seconds": 900, "max_stale_seconds": 3600},
                    "generic_node_class_rules": {},
                    "feature_gating_defaults": {},
                    "telemetry_expectations": {},
                    "raw_response": {},
                }
            ),
            capability_client=_FakeClientAccepted(),
            governance_client=_FakeGovernanceClientSynced(),
            operational_readiness_checker=_FakeOperationalReadinessReady(),
            telemetry_publisher=_FakeTelemetryPublisher(),
            phase2_state_store=_FakePhase2StateStore(),
        )
        result = await runner.resume_operational_if_ready()
        self.assertTrue(result["resumed"])
        self.assertEqual(result["target_state"], NodeLifecycleState.OPERATIONAL.value)
        self.assertEqual(lifecycle.get_state(), NodeLifecycleState.OPERATIONAL)

    async def test_resume_operational_if_ready_keeps_pending_when_prereq_missing(self):
        lifecycle = NodeLifecycle(logger=logging.getLogger("capability-runner-test"))
        lifecycle.transition_to(NodeLifecycleState.TRUSTED)
        lifecycle.transition_to(NodeLifecycleState.CAPABILITY_SETUP_PENDING)
        runner = CapabilityDeclarationRunner(
            lifecycle=lifecycle,
            logger=logging.getLogger("capability-runner-test"),
            trust_store=_FakeTrustStore(),
            provider_selection_store=_FakeProviderSelectionStore(),
            task_capability_selection_store=_FakeTaskCapabilitySelectionStore(),
            node_id="node-001",
            capability_state_store=_FakeCapabilityStateStore(existing=None),
            governance_state_store=_FakeGovernanceStateStore(existing=None),
            capability_client=_FakeClientAccepted(),
            governance_client=_FakeGovernanceClientSynced(),
            operational_readiness_checker=_FakeOperationalReadinessReady(),
            telemetry_publisher=_FakeTelemetryPublisher(),
            phase2_state_store=_FakePhase2StateStore(),
        )
        result = await runner.resume_operational_if_ready()
        self.assertFalse(result["resumed"])
        self.assertEqual(result["reason"], "accepted_capability_missing")
        self.assertEqual(lifecycle.get_state(), NodeLifecycleState.CAPABILITY_SETUP_PENDING)

    async def test_governance_sync_retry_moves_to_retry_pending(self):
        lifecycle = NodeLifecycle(logger=logging.getLogger("capability-runner-test"))
        lifecycle.transition_to(NodeLifecycleState.TRUSTED)
        lifecycle.transition_to(NodeLifecycleState.CAPABILITY_SETUP_PENDING)
        runner = CapabilityDeclarationRunner(
            lifecycle=lifecycle,
            logger=logging.getLogger("capability-runner-test"),
            trust_store=_FakeTrustStore(),
            provider_selection_store=_FakeProviderSelectionStore(),
            task_capability_selection_store=_FakeTaskCapabilitySelectionStore(),
            node_id="node-001",
            capability_state_store=_FakeCapabilityStateStore(),
            capability_client=_FakeClientAccepted(),
            governance_client=_FakeGovernanceClientRetry(),
            operational_readiness_checker=_FakeOperationalReadinessReady(),
            telemetry_publisher=_FakeTelemetryPublisher(),
            phase2_state_store=_FakePhase2StateStore(),
        )
        result = await runner.submit_once()
        self.assertEqual(result["status"], "retryable_failure")
        self.assertEqual(lifecycle.get_state(), NodeLifecycleState.DEGRADED)
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
            task_capability_selection_store=_FakeTaskCapabilitySelectionStore(),
            node_id="node-001",
            governance_state_store=governance_store,
            capability_client=_FakeClientAccepted(),
            governance_client=_FakeGovernanceClientRetry(),
        )
        result = await runner.refresh_governance_once()
        self.assertEqual(result["status"], "retryable_failure")
        self.assertEqual(result["governance_status"]["refresh_state"], "core_temporarily_unavailable")

    async def test_submit_manifest_uses_selected_task_capabilities(self):
        lifecycle = NodeLifecycle(logger=logging.getLogger("capability-runner-test"))
        lifecycle.transition_to(NodeLifecycleState.TRUSTED)
        lifecycle.transition_to(NodeLifecycleState.CAPABILITY_SETUP_PENDING)
        client = _FakeClientAcceptedCapture()
        runner = CapabilityDeclarationRunner(
            lifecycle=lifecycle,
            logger=logging.getLogger("capability-runner-test"),
            trust_store=_FakeTrustStore(),
            provider_selection_store=_FakeProviderSelectionStore(),
            task_capability_selection_store=_FakeTaskCapabilitySelectionStore(),
            node_id="node-001",
            capability_client=client,
            governance_client=_FakeGovernanceClientSynced(),
            operational_readiness_checker=_FakeOperationalReadinessReady(),
            telemetry_publisher=_FakeTelemetryPublisher(),
            phase2_state_store=_FakePhase2StateStore(),
        )
        await runner.submit_once()
        self.assertEqual(
            client.last_manifest["declared_task_families"],
            ["task.classification.text", "task.summarization.text"],
        )

    async def test_submit_manifest_uses_resolved_provider_task_capabilities_when_available(self):
        lifecycle = NodeLifecycle(logger=logging.getLogger("capability-runner-test"))
        lifecycle.transition_to(NodeLifecycleState.TRUSTED)
        lifecycle.transition_to(NodeLifecycleState.CAPABILITY_SETUP_PENDING)
        client = _FakeClientAcceptedCapture()
        runner = CapabilityDeclarationRunner(
            lifecycle=lifecycle,
            logger=logging.getLogger("capability-runner-test"),
            trust_store=_FakeTrustStore(),
            provider_selection_store=_FakeProviderSelectionStore(),
            task_capability_selection_store=_FakeTaskCapabilitySelectionStore(),
            node_id="node-001",
            capability_client=client,
            governance_client=_FakeGovernanceClientSynced(),
            operational_readiness_checker=_FakeOperationalReadinessReady(),
            telemetry_publisher=_FakeTelemetryPublisher(),
            phase2_state_store=_FakePhase2StateStore(),
            provider_runtime_manager=_FakeProviderRuntimeManager(),
        )

        await runner.submit_once()

        self.assertEqual(
            client.last_manifest["declared_task_families"],
            ["task.classification", "task.coding", "task.reasoning", "task.speech_to_text", "task.summarization"],
        )
        self.assertEqual(client.last_manifest["provider_metadata"][0]["classification_model"], "gpt-5-mini")
        self.assertEqual(
            client.last_manifest["provider_metadata"][0]["task_families"],
            ["task.classification", "task.reasoning", "task.speech_to_text"],
        )
        self.assertEqual(
            client.last_manifest["enabled_models"],
            [
                {"provider_id": "openai", "model_id": "gpt-5-mini"},
                {"provider_id": "openai", "model_id": "whisper-1"},
            ],
        )

    async def test_operational_readiness_failure_moves_to_retry_pending(self):
        lifecycle = NodeLifecycle(logger=logging.getLogger("capability-runner-test"))
        lifecycle.transition_to(NodeLifecycleState.TRUSTED)
        lifecycle.transition_to(NodeLifecycleState.CAPABILITY_SETUP_PENDING)
        runner = CapabilityDeclarationRunner(
            lifecycle=lifecycle,
            logger=logging.getLogger("capability-runner-test"),
            trust_store=_FakeTrustStore(),
            provider_selection_store=_FakeProviderSelectionStore(),
            task_capability_selection_store=_FakeTaskCapabilitySelectionStore(),
            node_id="node-001",
            capability_state_store=_FakeCapabilityStateStore(),
            governance_state_store=_FakeGovernanceStateStore(),
            capability_client=_FakeClientAccepted(),
            governance_client=_FakeGovernanceClientSynced(),
            operational_readiness_checker=_FakeOperationalReadinessNotReady(),
            telemetry_publisher=_FakeTelemetryPublisher(),
            phase2_state_store=_FakePhase2StateStore(),
        )
        result = await runner.submit_once()
        self.assertEqual(result["status"], "retryable_failure")
        self.assertEqual(lifecycle.get_state(), NodeLifecycleState.DEGRADED)
        self.assertEqual(runner.status_payload()["status"], "retry_pending")

    async def test_operational_mqtt_auth_failure_soft_fails_without_degraded(self):
        lifecycle = NodeLifecycle(logger=logging.getLogger("capability-runner-test"))
        lifecycle.transition_to(NodeLifecycleState.TRUSTED)
        lifecycle.transition_to(NodeLifecycleState.CAPABILITY_SETUP_PENDING)
        runner = CapabilityDeclarationRunner(
            lifecycle=lifecycle,
            logger=logging.getLogger("capability-runner-test"),
            trust_store=_FakeTrustStore(),
            provider_selection_store=_FakeProviderSelectionStore(),
            task_capability_selection_store=_FakeTaskCapabilitySelectionStore(),
            node_id="node-001",
            capability_state_store=_FakeCapabilityStateStore(),
            governance_state_store=_FakeGovernanceStateStore(),
            capability_client=_FakeClientAccepted(),
            governance_client=_FakeGovernanceClientSynced(),
            operational_readiness_checker=_FakeOperationalReadinessAuthNotReady(),
            telemetry_publisher=_FakeTelemetryPublisher(),
            phase2_state_store=_FakePhase2StateStore(),
        )
        result = await runner.submit_once()
        self.assertEqual(result["status"], "accepted_with_warning")
        self.assertEqual(lifecycle.get_state(), NodeLifecycleState.CAPABILITY_DECLARATION_FAILED_RETRY_PENDING)
        self.assertEqual(runner.status_payload()["status"], "accepted_with_warning")

    async def test_recover_from_degraded_to_capability_setup_pending(self):
        lifecycle = NodeLifecycle(logger=logging.getLogger("capability-runner-test"))
        lifecycle.transition_to(NodeLifecycleState.TRUSTED)
        lifecycle.transition_to(NodeLifecycleState.CAPABILITY_SETUP_PENDING)
        lifecycle.transition_to(NodeLifecycleState.CAPABILITY_DECLARATION_IN_PROGRESS)
        lifecycle.transition_to(NodeLifecycleState.CAPABILITY_DECLARATION_FAILED_RETRY_PENDING)
        lifecycle.transition_to(NodeLifecycleState.DEGRADED)
        runner = CapabilityDeclarationRunner(
            lifecycle=lifecycle,
            logger=logging.getLogger("capability-runner-test"),
            trust_store=_FakeTrustStore(),
            provider_selection_store=_FakeProviderSelectionStore(),
            task_capability_selection_store=_FakeTaskCapabilitySelectionStore(),
            node_id="node-001",
            capability_state_store=_FakeCapabilityStateStore(),
            governance_state_store=_FakeGovernanceStateStore(),
            capability_client=_FakeClientAccepted(),
            governance_client=_FakeGovernanceClientSynced(),
            operational_readiness_checker=_FakeOperationalReadinessNotReady(),
            telemetry_publisher=_FakeTelemetryPublisher(),
            phase2_state_store=_FakePhase2StateStore(),
        )
        result = runner.recover_from_degraded()
        self.assertEqual(result["target_state"], NodeLifecycleState.CAPABILITY_SETUP_PENDING.value)
        self.assertEqual(lifecycle.get_state(), NodeLifecycleState.CAPABILITY_SETUP_PENDING)

    async def test_telemetry_publish_failure_moves_to_degraded(self):
        lifecycle = NodeLifecycle(logger=logging.getLogger("capability-runner-test"))
        lifecycle.transition_to(NodeLifecycleState.TRUSTED)
        lifecycle.transition_to(NodeLifecycleState.CAPABILITY_SETUP_PENDING)
        runner = CapabilityDeclarationRunner(
            lifecycle=lifecycle,
            logger=logging.getLogger("capability-runner-test"),
            trust_store=_FakeTrustStore(),
            provider_selection_store=_FakeProviderSelectionStore(),
            task_capability_selection_store=_FakeTaskCapabilitySelectionStore(),
            node_id="node-001",
            capability_state_store=_FakeCapabilityStateStore(),
            governance_state_store=_FakeGovernanceStateStore(),
            capability_client=_FakeClientAccepted(),
            governance_client=_FakeGovernanceClientSynced(),
            operational_readiness_checker=_FakeOperationalReadinessReady(),
            telemetry_publisher=_FakeTelemetryPublisherFailure(),
            phase2_state_store=_FakePhase2StateStore(),
        )
        result = await runner.submit_once()
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(lifecycle.get_state(), NodeLifecycleState.DEGRADED)


if __name__ == "__main__":
    unittest.main()
