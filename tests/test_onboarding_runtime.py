import asyncio
import json
import logging
import tempfile
import unittest

from ai_node.lifecycle.node_lifecycle import NodeLifecycle, NodeLifecycleState
from ai_node.runtime.onboarding_runtime import OnboardingRuntime


class _FakeRegistrationClient:
    def __init__(self, lifecycle: NodeLifecycle):
        self._lifecycle = lifecycle
        self.last_kwargs = None

    async def register(self, **kwargs):
        self.last_kwargs = kwargs
        self._lifecycle.transition_to(NodeLifecycleState.REGISTRATION_PENDING)
        return {
            "status": "pending_approval",
            "session": {
                "session_id": "session-001",
                "approval_url": "http://core.local/approve",
                "finalize": {"path": "/api/system/nodes/onboarding/sessions/session-001/finalize"},
            },
        }


class _FakeRegistrationClientDuplicateThenPending:
    def __init__(self, lifecycle: NodeLifecycle):
        self._lifecycle = lifecycle
        self.calls = []

    async def register(self, **kwargs):
        self.calls.append(kwargs)
        self._lifecycle.transition_to(NodeLifecycleState.REGISTRATION_PENDING)
        if len(self.calls) == 1:
            raise RuntimeError("{'error': 'duplicate_node_identity', 'message': 'node identity already registered'}")
        return {
            "status": "pending_approval",
            "session": {
                "session_id": "session-002",
                "approval_url": "http://core.local/approve",
                "finalize": {"path": "/api/system/nodes/onboarding/sessions/session-002/finalize"},
            },
        }


class _FakeHttpAdapter:
    def __init__(self):
        self._calls = 0

    async def get_json(self, _url: str):
        self._calls += 1
        if self._calls == 1:
            raise TimeoutError()
        if self._calls == 2:
            return {"onboarding_status": "pending_approval"}
        return {
            "onboarding_status": "approved",
            "activation": {
                "node_id": "node-123e4567-e89b-42d3-a456-426614174000",
                "node_type": "ai-node",
                "paired_core_id": "core-main",
                "node_trust_token": "token",
                "initial_baseline_policy": {"policy_version": "1.0"},
                "operational_mqtt_identity": "node:123e4567-e89b-42d3-a456-426614174000",
                "operational_mqtt_token": "mqtt-token",
                "operational_mqtt_host": "10.0.0.100",
                "operational_mqtt_port": 1883,
            },
        }


class _FakeHttpAdapterLoopbackHost(_FakeHttpAdapter):
    async def get_json(self, _url: str):
        self._calls += 1
        if self._calls == 1:
            raise TimeoutError()
        if self._calls == 2:
            return {"onboarding_status": "pending_approval"}
        return {
            "onboarding_status": "approved",
            "activation": {
                "node_id": "node-123e4567-e89b-42d3-a456-426614174000",
                "node_type": "ai-node",
                "paired_core_id": "core-main",
                "node_trust_token": "token",
                "initial_baseline_policy": {"policy_version": "1.0"},
                "operational_mqtt_identity": "node:123e4567-e89b-42d3-a456-426614174000",
                "operational_mqtt_token": "mqtt-token",
                "operational_mqtt_host": "127.0.0.1",
                "operational_mqtt_port": 1883,
            },
        }


class _FakeHttpAdapterWildcardHost(_FakeHttpAdapter):
    async def get_json(self, _url: str):
        self._calls += 1
        if self._calls == 1:
            raise TimeoutError()
        if self._calls == 2:
            return {"onboarding_status": "pending_approval"}
        return {
            "onboarding_status": "approved",
            "activation": {
                "node_id": "node-123e4567-e89b-42d3-a456-426614174000",
                "node_type": "ai-node",
                "paired_core_id": "core-main",
                "node_trust_token": "token",
                "initial_baseline_policy": {"policy_version": "1.0"},
                "operational_mqtt_identity": "node:123e4567-e89b-42d3-a456-426614174000",
                "operational_mqtt_token": "mqtt-token",
                "operational_mqtt_host": "0.0.0.0",
                "operational_mqtt_port": 1883,
            },
        }


class _FakeNodeIdentityStore:
    def __init__(self):
        self.created = 0

    def create(self):
        self.created += 1
        return {
            "node_id": "node-aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "created_at": "2026-04-05T12:31:00-07:00",
            "id_format": "uuidv4",
        }


class OnboardingRuntimeTests(unittest.TestCase):
    def test_registration_threads_ui_endpoint_to_client(self):
        lifecycle = NodeLifecycle(logger=logging.getLogger("onboarding-runtime-test"))
        lifecycle.transition_to(NodeLifecycleState.BOOTSTRAP_CONNECTING)
        lifecycle.transition_to(NodeLifecycleState.BOOTSTRAP_CONNECTED)
        lifecycle.transition_to(NodeLifecycleState.CORE_DISCOVERED)

        runtime = OnboardingRuntime(
            lifecycle=lifecycle,
            logger=logging.getLogger("onboarding-runtime-test"),
            node_id="node-123e4567-e89b-42d3-a456-426614174000",
            ui_endpoint="http://node-ui.local:8081/",
            api_base_url="http://node-api.local:9002",
            finalize_poll_interval_seconds=0.01,
        )
        fake_registration_client = _FakeRegistrationClient(lifecycle)
        runtime._registration_client = fake_registration_client
        runtime._http_adapter = _FakeHttpAdapter()

        asyncio.run(
            runtime._run_registration_async(
                bootstrap_payload={"api_base": "http://10.0.0.100:9001", "mqtt_host": "10.0.0.100"},
                node_name="main-ai-node",
                run_id=runtime._run_id,
            )
        )

        self.assertEqual(fake_registration_client.last_kwargs["ui_endpoint"], "http://node-ui.local:8081/")
        self.assertEqual(fake_registration_client.last_kwargs["api_base_url"], "http://node-api.local:9002")

    def test_transient_finalize_poll_error_does_not_force_degraded(self):
        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = NodeLifecycle(logger=logging.getLogger("onboarding-runtime-test"))
            lifecycle.transition_to(NodeLifecycleState.BOOTSTRAP_CONNECTING)
            lifecycle.transition_to(NodeLifecycleState.BOOTSTRAP_CONNECTED)
            lifecycle.transition_to(NodeLifecycleState.CORE_DISCOVERED)

            runtime = OnboardingRuntime(
                lifecycle=lifecycle,
                logger=logging.getLogger("onboarding-runtime-test"),
                node_id="node-123e4567-e89b-42d3-a456-426614174000",
                trust_state_path=f"{tmp}/trust_state.json",
                finalize_poll_interval_seconds=0.01,
            )
            runtime._registration_client = _FakeRegistrationClient(lifecycle)
            runtime._http_adapter = _FakeHttpAdapter()

            asyncio.run(
                runtime._run_registration_async(
                    bootstrap_payload={"api_base": "http://10.0.0.100:9001", "mqtt_host": "10.0.0.100"},
                    node_name="main-ai-node",
                    run_id=runtime._run_id,
                )
            )

            self.assertEqual(lifecycle.get_state(), NodeLifecycleState.CAPABILITY_SETUP_PENDING)

    def test_loopback_operational_host_is_corrected_to_bootstrap_host(self):
        with tempfile.TemporaryDirectory() as tmp:
            trust_state_path = f"{tmp}/trust_state.json"
            lifecycle = NodeLifecycle(logger=logging.getLogger("onboarding-runtime-test"))
            lifecycle.transition_to(NodeLifecycleState.BOOTSTRAP_CONNECTING)
            lifecycle.transition_to(NodeLifecycleState.BOOTSTRAP_CONNECTED)
            lifecycle.transition_to(NodeLifecycleState.CORE_DISCOVERED)

            runtime = OnboardingRuntime(
                lifecycle=lifecycle,
                logger=logging.getLogger("onboarding-runtime-test"),
                node_id="node-123e4567-e89b-42d3-a456-426614174000",
                trust_state_path=trust_state_path,
                finalize_poll_interval_seconds=0.01,
            )
            runtime._registration_client = _FakeRegistrationClient(lifecycle)
            runtime._http_adapter = _FakeHttpAdapterLoopbackHost()

            asyncio.run(
                runtime._run_registration_async(
                    bootstrap_payload={"api_base": "http://10.0.0.100:9001", "mqtt_host": "10.0.0.100"},
                    node_name="main-ai-node",
                    run_id=runtime._run_id,
                )
            )

            payload = json.loads(open(trust_state_path, "r", encoding="utf-8").read())
            self.assertEqual(payload["operational_mqtt_host"], "10.0.0.100")

    def test_wildcard_operational_host_is_corrected_to_bootstrap_host(self):
        with tempfile.TemporaryDirectory() as tmp:
            trust_state_path = f"{tmp}/trust_state.json"
            lifecycle = NodeLifecycle(logger=logging.getLogger("onboarding-runtime-test"))
            lifecycle.transition_to(NodeLifecycleState.BOOTSTRAP_CONNECTING)
            lifecycle.transition_to(NodeLifecycleState.BOOTSTRAP_CONNECTED)
            lifecycle.transition_to(NodeLifecycleState.CORE_DISCOVERED)

            runtime = OnboardingRuntime(
                lifecycle=lifecycle,
                logger=logging.getLogger("onboarding-runtime-test"),
                node_id="node-123e4567-e89b-42d3-a456-426614174000",
                trust_state_path=trust_state_path,
                finalize_poll_interval_seconds=0.01,
            )
            runtime._registration_client = _FakeRegistrationClient(lifecycle)
            runtime._http_adapter = _FakeHttpAdapterWildcardHost()

            asyncio.run(
                runtime._run_registration_async(
                    bootstrap_payload={"api_base": "http://10.0.0.100:9001", "mqtt_host": "10.0.0.100"},
                    node_name="main-ai-node",
                    run_id=runtime._run_id,
                )
            )

            payload = json.loads(open(trust_state_path, "r", encoding="utf-8").read())
            self.assertEqual(payload["operational_mqtt_host"], "10.0.0.100")

    def test_retrust_flow_retries_with_new_identity_after_duplicate_registration(self):
        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = NodeLifecycle(logger=logging.getLogger("onboarding-runtime-test"))
            lifecycle.transition_to(NodeLifecycleState.BOOTSTRAP_CONNECTING)
            lifecycle.transition_to(NodeLifecycleState.BOOTSTRAP_CONNECTED)
            lifecycle.transition_to(NodeLifecycleState.CORE_DISCOVERED)

            observed_identity_changes = []
            identity_store = _FakeNodeIdentityStore()
            runtime = OnboardingRuntime(
                lifecycle=lifecycle,
                logger=logging.getLogger("onboarding-runtime-test"),
                node_id="node-123e4567-e89b-42d3-a456-426614174000",
                trust_state_path=f"{tmp}/trust_state.json",
                finalize_poll_interval_seconds=0.01,
                node_identity_store=identity_store,
                on_node_identity_changed=observed_identity_changes.append,
            )
            runtime.prepare_retrust(allow_identity_reset_on_duplicate=True)
            duplicate_then_pending = _FakeRegistrationClientDuplicateThenPending(lifecycle)
            runtime._registration_client = duplicate_then_pending
            runtime._http_adapter = _FakeHttpAdapter()

            asyncio.run(
                runtime._run_registration_async(
                    bootstrap_payload={"api_base": "http://10.0.0.100:9001", "mqtt_host": "10.0.0.100"},
                    node_name="main-ai-node",
                    run_id=runtime._run_id,
                )
            )

            self.assertEqual(identity_store.created, 1)
            self.assertEqual(observed_identity_changes, ["node-aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"])
            self.assertEqual(duplicate_then_pending.calls[0]["node_id"], "node-123e4567-e89b-42d3-a456-426614174000")
            self.assertEqual(duplicate_then_pending.calls[1]["node_id"], "node-aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
            self.assertEqual(lifecycle.get_state(), NodeLifecycleState.CAPABILITY_SETUP_PENDING)


if __name__ == "__main__":
    unittest.main()
