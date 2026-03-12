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

    class _FakeTaskCapabilitySelectionStore:
        def __init__(self):
            self.payload = {
                "schema_version": "1.0",
                "selected_task_families": [
                    "task.classification.text",
                    "task.summarization.text",
                ],
            }

        def load_or_create(self, **_kwargs):
            return self.payload

        def save(self, payload):
            self.payload = payload

    class _FakeCapabilityRunner:
        async def submit_once(self):
            return {"status": "accepted"}

        async def refresh_governance_once(self):
            return {"status": "synced"}

        async def refresh_provider_capabilities_once(self, *, force_refresh: bool = False):
            return {"status": "refreshed", "changed": bool(force_refresh)}

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

    class _FakePromptServiceStateStore:
        def __init__(self):
            self.payload = {
                "schema_version": "1.0",
                "prompt_services": [],
                "probation": {"active_prompt_ids": [], "reasons": {}, "updated_at": "2026-03-12T00:00:00Z"},
                "updated_at": "2026-03-12T00:00:00Z",
            }

        def load_or_create(self):
            return self.payload

        def save(self, payload):
            self.payload = payload

    class _FakeProviderRuntimeManager:
        def providers_snapshot(self):
            return {"providers": [{"provider_id": "openai", "availability": "available", "models": []}]}

        def models_snapshot(self):
            return {"providers": [{"provider_id": "openai", "models": [{"model_id": "gpt-4o-mini"}]}]}

        def metrics_snapshot(self):
            return {"providers": {"openai": {"totals": {"total_requests": 1}}}}

    def test_status_and_onboarding_endpoints(self):
        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-fastapi-test"))
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-fastapi-test"),
                provider_selection_store=self._FakeProviderSelectionStore(),
                task_capability_selection_store=self._FakeTaskCapabilitySelectionStore(),
                capability_runner=self._FakeCapabilityRunner(),
                provider_runtime_manager=self._FakeProviderRuntimeManager(),
                service_manager=self._FakeServiceManager(),
                prompt_service_state_store=self._FakePromptServiceStateStore(),
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

            capability_config_get_response = client.get("/api/capabilities/config")
            self.assertEqual(capability_config_get_response.status_code, 200)
            self.assertIn("selected_task_families", capability_config_get_response.json()["config"])

            capability_config_set_response = client.post(
                "/api/capabilities/config",
                json={"selected_task_families": ["task.classification.text"]},
            )
            self.assertEqual(capability_config_set_response.status_code, 200)
            self.assertEqual(
                capability_config_set_response.json()["config"]["selected_task_families"],
                ["task.classification.text"],
            )

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

            provider_refresh_response = client.post(
                "/api/capabilities/providers/refresh",
                json={"force_refresh": True},
            )
            self.assertEqual(provider_refresh_response.status_code, 200)
            self.assertEqual(provider_refresh_response.json()["status"], "refreshed")
            self.assertTrue(provider_refresh_response.json()["changed"])

            node_recover_response = client.post("/api/node/recover")
            self.assertEqual(node_recover_response.status_code, 200)
            self.assertEqual(node_recover_response.json()["status"], "recovered")

            prompt_register_response = client.post(
                "/api/prompts/services",
                json={
                    "prompt_id": "prompt.alpha",
                    "service_id": "svc-alpha",
                    "task_family": "task.classification.text",
                    "metadata": {"owner": "ops"},
                },
            )
            self.assertEqual(prompt_register_response.status_code, 200)
            prompt_get_response = client.get("/api/prompts/services")
            self.assertEqual(prompt_get_response.status_code, 200)
            self.assertEqual(len(prompt_get_response.json()["state"]["prompt_services"]), 1)

            exec_authorize_response = client.post(
                "/api/execution/authorize",
                json={"prompt_id": "prompt.alpha", "task_family": "task.classification.text"},
            )
            self.assertEqual(exec_authorize_response.status_code, 200)
            self.assertTrue(exec_authorize_response.json()["allowed"])

            prompt_probation_response = client.post(
                "/api/prompts/services/prompt.alpha/probation",
                json={"action": "start", "reason": "manual_review"},
            )
            self.assertEqual(prompt_probation_response.status_code, 200)
            exec_denied_response = client.post(
                "/api/execution/authorize",
                json={"prompt_id": "prompt.alpha", "task_family": "task.classification.text"},
            )
            self.assertEqual(exec_denied_response.status_code, 200)
            self.assertFalse(exec_denied_response.json()["allowed"])
            self.assertEqual(exec_denied_response.json()["reason"], "prompt_in_probation")

            services_status_response = client.get("/api/services/status")
            self.assertEqual(services_status_response.status_code, 200)
            self.assertEqual(services_status_response.json()["services"]["backend"], "running")

            services_restart_response = client.post("/api/services/restart", json={"target": "backend"})
            self.assertEqual(services_restart_response.status_code, 200)
            self.assertEqual(services_restart_response.json()["target"], "backend")

            debug_providers_response = client.get("/debug/providers")
            self.assertEqual(debug_providers_response.status_code, 200)
            self.assertTrue(debug_providers_response.json()["configured"])
            self.assertEqual(debug_providers_response.json()["providers"][0]["provider_id"], "openai")

            debug_models_response = client.get("/debug/providers/models")
            self.assertEqual(debug_models_response.status_code, 200)
            self.assertEqual(debug_models_response.json()["providers"][0]["models"][0]["model_id"], "gpt-4o-mini")

            debug_metrics_response = client.get("/debug/providers/metrics")
            self.assertEqual(debug_metrics_response.status_code, 200)
            self.assertEqual(debug_metrics_response.json()["providers"]["openai"]["totals"]["total_requests"], 1)

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
                task_capability_selection_store=self._FakeTaskCapabilitySelectionStore(),
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
