import logging
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from ai_node.lifecycle.node_lifecycle import NodeLifecycle, NodeLifecycleState
from ai_node.runtime.node_control_api import NodeControlState, create_node_control_app


class NodeControlFastApiTests(unittest.TestCase):
    class _FakeProviderSelectionStore:
        def __init__(self):
            self.payload = {
                "schema_version": "1.0",
                "providers": {
                    "supported": {"cloud": ["openai"], "local": [], "future": []},
                    "enabled": [],
                },
                "services": {"enabled": [], "future": []},
            }

        def load_or_create(self, **_kwargs):
            return self.payload

        def save(self, payload):
            self.payload = payload

    class _FakeNodeIdentityStore:
        def load(self):
            return {"node_id": "node-001", "created_at": "2026-03-11T00:00:00Z"}

    class _FakeCapabilityRunner:
        async def submit_once(self):
            return {"status": "accepted"}

        async def refresh_governance_once(self):
            return {"status": "synced"}

        def recover_from_degraded(self):
            return {"status": "recovered", "target_state": "capability_setup_pending"}

        def status_payload(self):
            return {
                "status": "idle",
                "governance_status": {
                    "state": "fresh",
                    "active_governance_version": "1.0",
                    "last_sync_time": "2026-03-11T00:00:00+00:00",
                },
            }

    class _FakeTrustStateStore:
        def load(self):
            return {
                "node_id": "node-001",
                "node_name": "main-ai-node",
                "node_type": "ai-node",
                "paired_core_id": "core-main",
                "core_api_endpoint": "http://10.0.0.100:9001",
                "node_trust_token": "token",
                "initial_baseline_policy": {"policy_version": "1.0"},
                "baseline_policy_version": "1.0",
                "operational_mqtt_identity": "node:node-001",
                "operational_mqtt_token": "mqtt-token",
                "operational_mqtt_host": "10.0.0.100",
                "operational_mqtt_port": 1883,
                "bootstrap_mqtt_host": "10.0.0.100",
                "registration_timestamp": "2026-03-11T00:00:00Z",
            }

    class _FakeServiceManager:
        def __init__(self):
            self.status = {"backend": "running", "frontend": "running", "node": "running"}

        def get_status(self):
            return self.status

        def restart(self, *, target: str):
            return {"target": target, "result": "restarted"}

    def test_status_and_onboarding_endpoints(self):
        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-fastapi-test"))
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-fastapi-test"),
                provider_selection_store=self._FakeProviderSelectionStore(),
                capability_runner=self._FakeCapabilityRunner(),
                service_manager=self._FakeServiceManager(),
            )
            app = create_node_control_app(state=state, logger=logging.getLogger("node-control-fastapi-test"))
            client = TestClient(app)

            status_response = client.get("/api/node/status")
            self.assertEqual(status_response.status_code, 200)
            self.assertEqual(status_response.json()["status"], "unconfigured")
            self.assertIn("node_id", status_response.json())
            self.assertIn("identity_state", status_response.json())
            self.assertIn("pending_node_nonce", status_response.json())
            self.assertIn("startup_mode", status_response.json())

            initiate_response = client.post(
                "/api/onboarding/initiate",
                json={"mqtt_host": "10.0.0.100", "node_name": "main-ai-node"},
            )
            self.assertEqual(initiate_response.status_code, 200)
            self.assertEqual(initiate_response.json()["status"], "bootstrap_connecting")

            provider_get_response = client.get("/api/providers/config")
            self.assertEqual(provider_get_response.status_code, 200)
            self.assertIn("config", provider_get_response.json())

            provider_set_response = client.post("/api/providers/config", json={"openai_enabled": True})
            self.assertEqual(provider_set_response.status_code, 200)
            self.assertIn("openai", provider_set_response.json()["config"]["providers"]["enabled"])

            capability_declare_response = client.post("/api/capabilities/declare")
            self.assertEqual(capability_declare_response.status_code, 409)
            self.assertEqual(
                capability_declare_response.json()["detail"]["error_code"],
                "capability_setup_prerequisites_unmet",
            )

            governance_status_response = client.get("/api/governance/status")
            self.assertEqual(governance_status_response.status_code, 200)
            self.assertEqual(governance_status_response.json()["status"]["state"], "fresh")

            governance_refresh_response = client.post("/api/governance/refresh")
            self.assertEqual(governance_refresh_response.status_code, 200)
            self.assertEqual(governance_refresh_response.json()["status"], "synced")

            node_recover_response = client.post("/api/node/recover")
            self.assertEqual(node_recover_response.status_code, 200)
            self.assertEqual(node_recover_response.json()["status"], "recovered")

            services_status_response = client.get("/api/services/status")
            self.assertEqual(services_status_response.status_code, 200)
            self.assertEqual(services_status_response.json()["services"]["backend"], "running")

            services_restart_response = client.post("/api/services/restart", json={"target": "backend"})
            self.assertEqual(services_restart_response.status_code, 200)
            self.assertEqual(services_restart_response.json()["target"], "backend")

    def test_capability_declare_succeeds_when_capability_setup_is_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-fastapi-test"))
            lifecycle.transition_to(NodeLifecycleState.TRUSTED, {"source": "test"})
            lifecycle.transition_to(NodeLifecycleState.CAPABILITY_SETUP_PENDING, {"source": "test"})
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-fastapi-test"),
                provider_selection_store=self._FakeProviderSelectionStore(),
                capability_runner=self._FakeCapabilityRunner(),
                node_identity_store=self._FakeNodeIdentityStore(),
                trust_state_store=self._FakeTrustStateStore(),
                startup_mode="trusted_resume",
                trusted_runtime_context={
                    "paired_core_id": "core-main",
                    "core_api_endpoint": "http://10.0.0.100:9001",
                    "operational_mqtt_host": "10.0.0.100",
                    "operational_mqtt_port": 1883,
                },
            )
            app = create_node_control_app(state=state, logger=logging.getLogger("node-control-fastapi-test"))
            client = TestClient(app)
            response = client.post("/api/capabilities/declare")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "accepted")


if __name__ == "__main__":
    unittest.main()
