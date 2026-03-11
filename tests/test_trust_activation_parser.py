import unittest

from ai_node.trust.trust_activation_parser import parse_trust_activation_payload


class TrustActivationParserTests(unittest.TestCase):
    def test_parse_valid_trust_activation_payload(self):
        ok, parsed = parse_trust_activation_payload(
            {
                "status": "approved",
                "node_id": "node-ai-001",
                "paired_core_id": "core-main",
                "node_trust_token": "node-token",
                "initial_baseline_policy": {"policy_version": "v1"},
                "operational_mqtt_identity": "main-ai-node",
                "operational_mqtt_token": "mqtt-token",
                "operational_mqtt_host": "192.168.1.50",
                "operational_mqtt_port": 1883,
            }
        )
        self.assertTrue(ok)
        self.assertEqual(parsed["node_id"], "node-ai-001")
        self.assertEqual(parsed["operational_mqtt_port"], 1883)

    def test_rejects_non_approved_or_incomplete_payload(self):
        ok, error = parse_trust_activation_payload({"status": "rejected"})
        self.assertFalse(ok)
        self.assertEqual(error, "invalid_status")

        ok, error = parse_trust_activation_payload(
            {
                "status": "approved",
                "node_id": "node-ai-001",
                "paired_core_id": "core-main",
            }
        )
        self.assertFalse(ok)
        self.assertTrue(error.startswith("missing_"))

    def test_rejects_malformed_trusted_fields(self):
        ok, error = parse_trust_activation_payload(
            {
                "status": "approved",
                "node_id": "node-ai-001",
                "paired_core_id": "core-main",
                "node_trust_token": "node-token",
                "initial_baseline_policy": "not-a-dict",
                "operational_mqtt_identity": "main-ai-node",
                "operational_mqtt_token": "mqtt-token",
                "operational_mqtt_host": "192.168.1.50",
                "operational_mqtt_port": 1883,
            }
        )
        self.assertFalse(ok)
        self.assertEqual(error, "invalid_initial_baseline_policy")


if __name__ == "__main__":
    unittest.main()
