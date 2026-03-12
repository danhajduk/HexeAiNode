import unittest

from ai_node.diagnostics.phase2_logger import Phase2DiagnosticsLogger


class _CaptureLogger:
    def __init__(self):
        self.entries = []

    def info(self, msg, payload):
        self.entries.append((msg, payload))

    def warning(self, msg, payload):
        self.entries.append((msg, payload))


class Phase2LoggerTests(unittest.TestCase):
    def test_phase2_logger_redacts_sensitive_fields(self):
        capture = _CaptureLogger()
        diag = Phase2DiagnosticsLogger(capture)
        diag.capability_submission(
            {
                "result_status": "retryable_failure",
                "token": "secret-token",
                "operational_mqtt_token": "mqtt-secret",
            }
        )
        _, payload = capture.entries[-1]
        self.assertEqual(payload["token"], "***REDACTED***")
        self.assertEqual(payload["operational_mqtt_token"], "***REDACTED***")


if __name__ == "__main__":
    unittest.main()
