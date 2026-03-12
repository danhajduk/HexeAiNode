import unittest
import tempfile
import json
from pathlib import Path

from ai_node.main import run


class MainEntrypointTests(unittest.TestCase):
    def test_run_once_returns_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc = run(
                once=True,
                interval_seconds=0.01,
                api_port=0,
                bootstrap_config_path=f"{tmp}/bootstrap_config.json",
                node_identity_path=f"{tmp}/node_identity.json",
                log_file=f"{tmp}/backend.log",
            )
            self.assertEqual(rc, 0)

    def test_run_once_creates_node_identity_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            identity_path = Path(tmp) / "node_identity.json"
            rc = run(
                once=True,
                interval_seconds=0.01,
                api_port=0,
                bootstrap_config_path=f"{tmp}/bootstrap_config.json",
                node_identity_path=str(identity_path),
                log_file=f"{tmp}/backend.log",
            )
            self.assertEqual(rc, 0)
            self.assertTrue(identity_path.exists())

    def test_run_once_reuses_existing_node_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            identity_path = Path(tmp) / "node_identity.json"
            rc1 = run(
                once=True,
                interval_seconds=0.01,
                api_port=0,
                bootstrap_config_path=f"{tmp}/bootstrap_config.json",
                node_identity_path=str(identity_path),
                log_file=f"{tmp}/backend.log",
            )
            first_payload = identity_path.read_text(encoding="utf-8")
            rc2 = run(
                once=True,
                interval_seconds=0.01,
                api_port=0,
                bootstrap_config_path=f"{tmp}/bootstrap_config.json",
                node_identity_path=str(identity_path),
                log_file=f"{tmp}/backend.log",
            )
            second_payload = identity_path.read_text(encoding="utf-8")
            self.assertEqual(rc1, 0)
            self.assertEqual(rc2, 0)
            self.assertEqual(first_payload, second_payload)

    def test_run_once_backfills_identity_from_trust_state_node_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            identity_path = Path(tmp) / "node_identity.json"
            trust_path = Path(tmp) / "trust_state.json"
            trust_path.write_text(
                json.dumps(
                    {
                        "node_id": "legacy-node-001",
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
                ),
                encoding="utf-8",
            )
            rc = run(
                once=True,
                interval_seconds=0.01,
                api_port=0,
                bootstrap_config_path=f"{tmp}/bootstrap_config.json",
                trust_state_path=str(trust_path),
                node_identity_path=str(identity_path),
                log_file=f"{tmp}/backend.log",
            )
            self.assertEqual(rc, 0)
            payload = json.loads(identity_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["node_id"], "legacy-node-001")
            self.assertEqual(payload["id_format"], "legacy")

    def test_run_once_fails_when_trust_state_node_id_mismatches_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            identity_path = Path(tmp) / "node_identity.json"
            identity_path.write_text(
                json.dumps(
                    {
                        "node_id": "123e4567-e89b-42d3-a456-426614174000",
                        "created_at": "2026-03-11T00:00:00Z",
                        "id_format": "uuidv4",
                    }
                ),
                encoding="utf-8",
            )
            trust_path = Path(tmp) / "trust_state.json"
            trust_path.write_text(
                json.dumps(
                    {
                        "node_id": "legacy-node-002",
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
                ),
                encoding="utf-8",
            )
            rc = run(
                once=True,
                interval_seconds=0.01,
                api_port=0,
                bootstrap_config_path=f"{tmp}/bootstrap_config.json",
                trust_state_path=str(trust_path),
                node_identity_path=str(identity_path),
                log_file=f"{tmp}/backend.log",
            )
            self.assertEqual(rc, 1)

    def test_run_once_with_valid_trust_state_uses_trusted_resume_startup_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            identity_path = Path(tmp) / "node_identity.json"
            identity_path.write_text(
                json.dumps(
                    {
                        "node_id": "123e4567-e89b-42d3-a456-426614174000",
                        "created_at": "2026-03-11T00:00:00Z",
                        "id_format": "uuidv4",
                    }
                ),
                encoding="utf-8",
            )
            trust_path = Path(tmp) / "trust_state.json"
            trust_path.write_text(
                json.dumps(
                    {
                        "node_id": "123e4567-e89b-42d3-a456-426614174000",
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
                ),
                encoding="utf-8",
            )
            log_path = Path(tmp) / "backend.log"
            rc = run(
                once=True,
                interval_seconds=0.01,
                api_port=0,
                bootstrap_config_path=f"{tmp}/bootstrap_config.json",
                trust_state_path=str(trust_path),
                node_identity_path=str(identity_path),
                log_file=str(log_path),
            )
            self.assertEqual(rc, 0)
            log_text = log_path.read_text(encoding="utf-8")
            self.assertIn("'startup_mode': 'trusted_resume'", log_text)
            self.assertIn("'mode': 'trusted_resume'", log_text)

    def test_run_once_corrects_loopback_operational_host_in_trust_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            identity_path = Path(tmp) / "node_identity.json"
            identity_path.write_text(
                json.dumps(
                    {
                        "node_id": "123e4567-e89b-42d3-a456-426614174000",
                        "created_at": "2026-03-11T00:00:00Z",
                        "id_format": "uuidv4",
                    }
                ),
                encoding="utf-8",
            )
            trust_path = Path(tmp) / "trust_state.json"
            trust_path.write_text(
                json.dumps(
                    {
                        "node_id": "123e4567-e89b-42d3-a456-426614174000",
                        "node_name": "main-ai-node",
                        "node_type": "ai-node",
                        "paired_core_id": "core-main",
                        "core_api_endpoint": "http://10.0.0.100:9001",
                        "node_trust_token": "token",
                        "initial_baseline_policy": {"policy_version": "1.0"},
                        "baseline_policy_version": "1.0",
                        "operational_mqtt_identity": "main-ai-node",
                        "operational_mqtt_token": "mqtt-token",
                        "operational_mqtt_host": "127.0.0.1",
                        "operational_mqtt_port": 1883,
                        "bootstrap_mqtt_host": "10.0.0.100",
                        "registration_timestamp": "2026-03-11T00:00:00Z",
                    }
                ),
                encoding="utf-8",
            )
            rc = run(
                once=True,
                interval_seconds=0.01,
                api_port=0,
                bootstrap_config_path=f"{tmp}/bootstrap_config.json",
                trust_state_path=str(trust_path),
                node_identity_path=str(identity_path),
                log_file=f"{tmp}/backend.log",
            )
            self.assertEqual(rc, 0)
            saved = json.loads(trust_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["operational_mqtt_host"], "10.0.0.100")


if __name__ == "__main__":
    unittest.main()
