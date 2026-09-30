import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "serve-frontend.py"
SPEC = importlib.util.spec_from_file_location("serve_frontend", SCRIPT_PATH)
SERVE_FRONTEND = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(SERVE_FRONTEND)


class FrontendServerTests(unittest.TestCase):
    def test_build_ui_config_uses_registered_core_and_persisted_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trust_path = root / "trust.json"
            identity_path = root / "identity.json"
            trust_path.write_text(
                json.dumps(
                    {
                        "node_id": "node-trust",
                        "core_api_endpoint": "http://10.0.0.100:9001/api",
                        "node_trust_token": "not-returned",
                    }
                ),
                encoding="utf-8",
            )
            identity_path.write_text(json.dumps({"node_id": "node-identity"}), encoding="utf-8")

            payload = SERVE_FRONTEND.build_ui_config(
                trust_state_path=trust_path,
                node_identity_path=identity_path,
            )

            self.assertEqual(payload["node_id"], "node-identity")
            self.assertEqual(
                payload["proxy_ui_url"],
                "http://10.0.0.100:9001/nodes/proxy/ui/node-identity/",
            )
            self.assertEqual(set(payload), {"node_id", "proxy_ui_url"})

    def test_build_ui_config_rejects_invalid_core_endpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trust_path = root / "trust.json"
            identity_path = root / "identity.json"
            trust_path.write_text(json.dumps({"core_api_endpoint": "file:///tmp/core"}), encoding="utf-8")
            identity_path.write_text(json.dumps({"node_id": "node-identity"}), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "invalid UI proxy configuration"):
                SERVE_FRONTEND.build_ui_config(
                    trust_state_path=trust_path,
                    node_identity_path=identity_path,
                )


if __name__ == "__main__":
    unittest.main()
