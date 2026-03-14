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

    class _FakeProviderCredentialsStore:
        def __init__(self):
            self.payload = {"schema_version": "1.0", "providers": {}}

        def load_or_create(self):
            return self.payload

        def load(self):
            return self.payload

        def upsert_openai_credentials(self, *, api_key: str, admin_key=None, user_identifier=None):
            self.payload["providers"]["openai"] = {
                "api_key": api_key,
                "admin_key": admin_key,
                "user_identifier": user_identifier,
                "default_model_id": self.payload.get("providers", {}).get("openai", {}).get("default_model_id"),
                "selected_model_ids": self.payload.get("providers", {}).get("openai", {}).get("selected_model_ids", []),
                "updated_at": "2026-03-13T00:00:00Z",
            }
            return self.payload

        def update_openai_preferences(self, *, default_model_id=None, selected_model_ids=None):
            self.payload.setdefault("providers", {}).setdefault("openai", {})
            self.payload["providers"]["openai"]["default_model_id"] = default_model_id
            self.payload["providers"]["openai"]["selected_model_ids"] = list(selected_model_ids or ([] if default_model_id is None else [default_model_id]))
            self.payload["providers"]["openai"]["updated_at"] = "2026-03-13T00:00:00Z"
            return self.payload

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
        async def refresh_pricing(self, *, force: bool):
            return {"status": "manual_only", "changed": False, "notes": ["live_pricing_scrape_disabled"]}

        def save_manual_openai_pricing(self, *, model_id: str, display_name=None, input_price_per_1m=None, output_price_per_1m=None):
            return {
                "status": "manual_saved",
                "model_id": model_id,
                "display_name": display_name,
                "input_price_per_1m": input_price_per_1m,
                "output_price_per_1m": output_price_per_1m,
            }

        def pricing_diagnostics_payload(self):
            return {
                "configured": True,
                "refresh_state": "manual",
                "stale": False,
                "entry_count": 3,
                "source_urls": ["https://openai.com/api/pricing/"],
                "source_url_used": "manual://local_override",
                "last_refresh_time": "2026-03-13T00:00:00Z",
                "unknown_models": [],
                "last_error": None,
                "notes": ["live_pricing_scrape_disabled"],
            }

        def providers_snapshot(self):
            return {"providers": [{"provider_id": "openai", "availability": "available", "models": []}]}

        def models_snapshot(self):
            return {"providers": [{"provider_id": "openai", "models": [{"model_id": "gpt-4o-mini"}]}]}

        def metrics_snapshot(self):
            return {"providers": {"openai": {"totals": {"total_requests": 1}}}}

        def latest_models_payload(self, *, provider_id: str, limit: int = 3):
            return {
                "provider_id": provider_id,
                "models": [
                    {
                        "model_id": "gpt-5",
                        "display_name": "gpt-5",
                        "created": 1741046400,
                        "pricing_input": 1.25,
                        "pricing_output": 10.0,
                        "status": "available",
                    }
                ][:limit],
                "source": "provider_registry",
                "generated_at": "2026-03-13T00:00:00Z",
            }

    def test_status_and_onboarding_endpoints(self):
        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-fastapi-test"))
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-fastapi-test"),
                provider_selection_store=self._FakeProviderSelectionStore(),
                provider_credentials_store=self._FakeProviderCredentialsStore(),
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

            credentials_get_response = client.get("/api/providers/openai/credentials")
            self.assertEqual(credentials_get_response.status_code, 200)
            self.assertFalse(credentials_get_response.json()["configured"])

            credentials_set_response = client.post(
                "/api/providers/openai/credentials",
                json={"api_key": "test-api-key-1234", "admin_key": "test-admin-key-7890", "user_identifier": "ops"},
            )
            self.assertEqual(credentials_set_response.status_code, 200)
            self.assertTrue(credentials_set_response.json()["credentials"]["has_api_key"])
            self.assertTrue(credentials_set_response.json()["credentials"]["api_key_hint"].endswith("1234"))

            preferences_set_response = client.post(
                "/api/providers/openai/preferences",
                json={"default_model_id": "gpt-5.4-pro", "selected_model_ids": ["gpt-5.4-pro", "gpt-5.4-mini"]},
            )
            self.assertEqual(preferences_set_response.status_code, 200)
            self.assertEqual(preferences_set_response.json()["credentials"]["default_model_id"], "gpt-5.4-pro")
            self.assertEqual(preferences_set_response.json()["credentials"]["selected_model_ids"], ["gpt-5.4-pro", "gpt-5.4-mini"])

            latest_models_response = client.get("/api/providers/openai/models/latest?limit=3")
            self.assertEqual(latest_models_response.status_code, 200)
            self.assertEqual(latest_models_response.json()["models"][0]["model_id"], "gpt-5")

            pricing_diagnostics_response = client.get("/api/providers/openai/pricing/diagnostics")
            self.assertEqual(pricing_diagnostics_response.status_code, 200)
            self.assertEqual(pricing_diagnostics_response.json()["entry_count"], 3)

            pricing_refresh_response = client.post(
                "/api/providers/openai/pricing/refresh",
                json={"force_refresh": True},
            )
            self.assertEqual(pricing_refresh_response.status_code, 200)
            self.assertEqual(pricing_refresh_response.json()["provider_id"], "openai")
            self.assertEqual(pricing_refresh_response.json()["status"], "manual_only")

            manual_pricing_response = client.post(
                "/api/providers/openai/pricing/manual",
                json={"model_id": "gpt-5.4-pro", "input_price_per_1m": 3.0, "output_price_per_1m": 15.0},
            )
            self.assertEqual(manual_pricing_response.status_code, 200)
            self.assertEqual(manual_pricing_response.json()["status"], "manual_saved")

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
