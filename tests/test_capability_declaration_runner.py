import logging
import unittest
from datetime import datetime, timezone

from ai_node.lifecycle.node_lifecycle import NodeLifecycle, NodeLifecycleState
from ai_node.runtime.capability_declaration_runner import CapabilityDeclarationRunner
from ai_node.time_utils import local_now_iso


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
                "task.classification",
                "task.summarization",
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
        self.last_provider_intelligence_report = None

    async def submit_manifest(self, **kwargs):
        self.last_manifest = kwargs.get("capability_manifest")
        return await super().submit_manifest(**kwargs)

    async def submit_provider_intelligence(self, **kwargs):
        self.last_provider_intelligence_report = kwargs.get("provider_intelligence_report")
        return await super().submit_provider_intelligence(**kwargs)


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
        return {"published": self.last is not None, "last_topic": "hexe/nodes/node-001/status"}

    async def publish_status(self, **kwargs):
        self.last = kwargs
        return {"published": True, "last_error": None, "last_topic": "hexe/nodes/node-001/status"}


class _FakeTelemetryPublisherFailure:
    def status_payload(self):
        return {"published": False, "last_topic": "hexe/nodes/node-001/status"}

    async def publish_status(self, **_kwargs):
        return {"published": False, "last_error": "mqtt_unavailable", "last_topic": "hexe/nodes/node-001/status"}


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
                    "task_family": "task.classification",
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
    async def refresh(self):
        return {
            "generated_at": "2026-03-13T00:00:00Z",
            "providers": [
                {
                    "provider_id": "openai",
                    "availability": "available",
                    "models": [{"model_id": "gpt-5-mini"}],
                }
            ],
        }

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

    def node_capabilities_payload(self):
        return {
            "enabled_task_capabilities": [
                "task.reasoning",
                "task.classification",
                "task.summarization",
                "task.speech_to_text",
            ],
            "feature_union": {"reasoning": True, "chat": True, "speech_to_text": True},
            "capability_graph_version": "1.0",
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

    async def test_telemetry_publish_failure_does_not_force_degraded(self):
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
        self.assertEqual(lifecycle.get_state(), NodeLifecycleState.OPERATIONAL)
        self.assertEqual(runner.status_payload()["last_error"], "mqtt_unavailable")

    def test_recover_from_degraded_returns_operational_with_fresh_governance_even_when_mqtt_not_ready(self):
        lifecycle = NodeLifecycle(logger=logging.getLogger("capability-runner-test"))
        lifecycle.transition_to(NodeLifecycleState.TRUSTED)
        lifecycle.transition_to(NodeLifecycleState.CAPABILITY_SETUP_PENDING)
        lifecycle.transition_to(NodeLifecycleState.CAPABILITY_DECLARATION_IN_PROGRESS)
        lifecycle.transition_to(NodeLifecycleState.CAPABILITY_DECLARATION_ACCEPTED)
        lifecycle.transition_to(NodeLifecycleState.OPERATIONAL)
        lifecycle.transition_to(NodeLifecycleState.DEGRADED)
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
                    "acceptance_timestamp": "2026-03-11T00:00:00Z",
                }
            ),
            governance_state_store=_FakeGovernanceStateStore(
                existing={
                    "policy_version": "1.0",
                    "issued_timestamp": local_now_iso(),
                    "synced_at": local_now_iso(),
                    "refresh_expectations": {"recommended_interval_seconds": 900, "max_stale_seconds": 3600},
                }
            ),
            operational_readiness_checker=_FakeOperationalReadinessNotReady(),
            telemetry_publisher=_FakeTelemetryPublisher(),
            phase2_state_store=_FakePhase2StateStore(),
        )

        result = runner.recover_from_degraded()

        self.assertEqual(result["target_state"], NodeLifecycleState.OPERATIONAL.value)
        self.assertEqual(lifecycle.get_state(), NodeLifecycleState.OPERATIONAL)

    async def test_redeclare_from_capability_setup_pending_runs_full_declaration_flow(self):
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
            task_capability_selection_store=_FakeTaskCapabilitySelectionStore(),
            node_id="node-001",
            capability_state_store=state_store,
            governance_state_store=governance_store,
            capability_client=_FakeClientAccepted(),
            governance_client=_FakeGovernanceClientSynced(),
            operational_readiness_checker=_FakeOperationalReadinessReady(),
            telemetry_publisher=_FakeTelemetryPublisher(),
            phase2_state_store=_FakePhase2StateStore(),
        )

        result = await runner.redeclare_if_needed(reason="manual_redeclare", force=True)

        self.assertEqual(result["status"], "accepted")
        self.assertEqual(lifecycle.get_state(), NodeLifecycleState.OPERATIONAL)
        self.assertEqual(runner.status_payload()["status"], "accepted")
        self.assertIsNotNone(state_store.saved)
        self.assertIsNotNone(governance_store.saved)

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
        now = local_now_iso()
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

    async def test_resume_or_refresh_on_startup_refreshes_stale_governance_and_resumes(self):
        lifecycle = NodeLifecycle(logger=logging.getLogger("capability-runner-test"))
        lifecycle.transition_to(NodeLifecycleState.TRUSTED)
        lifecycle.transition_to(NodeLifecycleState.CAPABILITY_SETUP_PENDING)
        stale_time = "2026-03-11T00:00:00+00:00"
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
                    "acceptance_timestamp": stale_time,
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
                    "issued_timestamp": stale_time,
                    "synced_at": stale_time,
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

        result = await runner.resume_or_refresh_on_startup()

        self.assertTrue(result["resumed"])
        self.assertEqual(result["reason"], "governance_refreshed_on_startup")
        self.assertEqual(result["governance_refresh"]["status"], "synced")
        self.assertEqual(lifecycle.get_state(), NodeLifecycleState.OPERATIONAL)

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
            ["task.classification", "task.summarization"],
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
            ["task.classification", "task.reasoning", "task.speech_to_text", "task.summarization"],
        )
        self.assertNotIn("provider_metadata", client.last_manifest)
        self.assertNotIn("enabled_models", client.last_manifest)

    async def test_declaration_integration_includes_resolved_tasks_and_provider_intelligence(self):
        lifecycle = NodeLifecycle(logger=logging.getLogger("capability-runner-test"))
        lifecycle.transition_to(NodeLifecycleState.TRUSTED)
        lifecycle.transition_to(NodeLifecycleState.CAPABILITY_SETUP_PENDING)
        runtime_manager = _FakeProviderRuntimeManager()
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
            provider_runtime_manager=runtime_manager,
        )

        result = await runner.submit_once()
        self.assertEqual(result["status"], "accepted")

        resolved_tasks = runtime_manager.node_capabilities_payload()["enabled_task_capabilities"]
        self.assertTrue(set(resolved_tasks).issubset(set(client.last_manifest["declared_task_families"])))
        self.assertNotIn("provider_metadata", client.last_manifest)
        self.assertNotIn("enabled_models", client.last_manifest)
        self.assertIsInstance(client.last_provider_intelligence_report, dict)
        self.assertEqual(client.last_provider_intelligence_report["providers"][0]["provider_id"], "openai")

    async def test_operational_readiness_failure_keeps_operational_transition(self):
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
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(lifecycle.get_state(), NodeLifecycleState.OPERATIONAL)
        self.assertEqual(runner.status_payload()["status"], "accepted")
        self.assertEqual(runner.status_payload()["last_error"], "connect_timeout")

    async def test_operational_mqtt_auth_failure_keeps_operational_transition(self):
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
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(lifecycle.get_state(), NodeLifecycleState.OPERATIONAL)
        self.assertEqual(runner.status_payload()["status"], "accepted")
        self.assertEqual(runner.status_payload()["last_error"], "connect_rc_5")

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
        self.assertEqual(lifecycle.get_state(), NodeLifecycleState.OPERATIONAL)
        self.assertEqual(runner.status_payload()["last_error"], "mqtt_unavailable")

    async def test_emit_workflow_status_telemetry_publishes_workflow_payload(self):
        lifecycle = NodeLifecycle(logger=logging.getLogger("capability-runner-test"))
        lifecycle.transition_to(NodeLifecycleState.TRUSTED)
        lifecycle.transition_to(NodeLifecycleState.CAPABILITY_SETUP_PENDING)
        telemetry = _FakeTelemetryPublisher()
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
            telemetry_publisher=telemetry,
            phase2_state_store=_FakePhase2StateStore(),
        )
        result = await runner.emit_workflow_status_telemetry(
            workflow_request="openai_model_classification_refresh",
            workflow_status="done",
            details={"status": "refreshed"},
        )
        self.assertTrue(result["published"])
        self.assertIsNotNone(telemetry.last)
        self.assertEqual(telemetry.last["payload"]["event_type"], "workflow_request")
        self.assertEqual(telemetry.last["payload"]["workflow_request"], "openai_model_classification_refresh")
        self.assertEqual(telemetry.last["payload"]["workflow_status"], "done")


if __name__ == "__main__":
    unittest.main()
