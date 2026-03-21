import unittest

from ai_node.security.boundaries import (
    enforce_bootstrap_security_boundary,
    require_approval_before_trust_activation,
)
from ai_node.security.redaction import redact_dict


class SecurityBoundariesTests(unittest.TestCase):
    def test_enforce_bootstrap_boundary_rejects_trust_fields(self):
        ok, error = enforce_bootstrap_security_boundary(
            {
                "topic": "hexe/bootstrap/core",
                "node_trust_token": "bad",
            }
        )
        self.assertFalse(ok)
        self.assertIn("forbidden_bootstrap_fields", error)

    def test_enforce_bootstrap_boundary_accepts_discovery_only_payload(self):
        ok, error = enforce_bootstrap_security_boundary({"topic": "hexe/bootstrap/core"})
        self.assertTrue(ok)
        self.assertIsNone(error)

    def test_approval_required_before_trust_activation(self):
        approved = require_approval_before_trust_activation({"status": "approved", "node_id": "node-1"})
        self.assertEqual(approved["status"], "approved")
        with self.assertRaisesRegex(ValueError, "approval is required before trust activation"):
            require_approval_before_trust_activation({"status": "rejected"})

    def test_redaction_masks_sensitive_keys(self):
        redacted = redact_dict(
            {
                "node_trust_token": "secret-token",
                "operational_mqtt_token": "mqtt-secret",
                "nested": {"password": "abc123"},
                "safe": "value",
            }
        )
        self.assertEqual(redacted["node_trust_token"], "***REDACTED***")
        self.assertEqual(redacted["operational_mqtt_token"], "***REDACTED***")
        self.assertEqual(redacted["nested"]["password"], "***REDACTED***")
        self.assertEqual(redacted["safe"], "value")


if __name__ == "__main__":
    unittest.main()
