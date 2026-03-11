import logging
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from ai_node.lifecycle.node_lifecycle import NodeLifecycle
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

    def test_status_and_onboarding_endpoints(self):
        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-fastapi-test"))
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-fastapi-test"),
                provider_selection_store=self._FakeProviderSelectionStore(),
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


if __name__ == "__main__":
    unittest.main()
