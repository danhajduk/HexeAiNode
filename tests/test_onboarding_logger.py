import json
import tempfile
from pathlib import Path
import unittest

from ai_node.diagnostics.onboarding_logger import OnboardingDiagnosticsLogger


class _CaptureLogger:
    def __init__(self):
        self.entries = []

    def info(self, msg, payload):
        self.entries.append((msg, payload))

    def warning(self, msg, payload):
        self.entries.append((msg, payload))


class OnboardingLoggerTests(unittest.TestCase):
    def test_diagnostics_logger_redacts_sensitive_fields(self):
        capture = _CaptureLogger()
        diag = OnboardingDiagnosticsLogger(capture)
        diag.trust_persistence(
            {
                "action": "load",
                "node_trust_token": "secret-token",
                "operational_mqtt_token": "mqtt-secret",
            }
        )
        _, payload = capture.entries[-1]
        self.assertEqual(payload["node_trust_token"], "***REDACTED***")
        self.assertEqual(payload["operational_mqtt_token"], "***REDACTED***")

    def test_registration_attempt_writes_structured_onboarding_json_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            capture = _CaptureLogger()
            path = f"{tmp}/logs/onboarding.json"
            diag = OnboardingDiagnosticsLogger(capture, json_log_path=path)

            diag.registration_attempt(
                {
                    "url": "http://core.local/api/system/nodes/onboarding/sessions",
                    "node_id": "node-123",
                    "ui_endpoint": "http://node.local:8081/",
                    "node_trust_token": "secret-token",
                }
            )

            payload = json.loads(Path(path).read_text(encoding="utf-8"))
            self.assertEqual(payload["event"], "registration_attempt")
            self.assertEqual(payload["payload"]["ui_endpoint"], "http://node.local:8081/")
            self.assertEqual(payload["payload"]["node_trust_token"], "***REDACTED***")

    def test_registration_attempt_overwrites_previous_onboarding_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            capture = _CaptureLogger()
            path = f"{tmp}/logs/onboarding.json"
            diag = OnboardingDiagnosticsLogger(capture, json_log_path=path)

            diag.registration_attempt({"node_id": "node-1"})
            diag.registration_attempt({"node_id": "node-2"})

            payload = json.loads(Path(path).read_text(encoding="utf-8"))
            self.assertEqual(payload["payload"]["node_id"], "node-2")


if __name__ == "__main__":
    unittest.main()
