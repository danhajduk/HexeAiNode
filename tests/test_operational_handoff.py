import unittest

from ai_node.trust.operational_handoff import prepare_operational_mqtt_handoff


class OperationalHandoffTests(unittest.TestCase):
    def test_prepare_handoff_separates_bootstrap_and_operational_context(self):
        handoff = prepare_operational_mqtt_handoff(
            trust_state={
                "operational_mqtt_host": "192.168.1.50",
                "operational_mqtt_port": 1883,
                "operational_mqtt_identity": "main-ai-node",
                "operational_mqtt_token": "mqtt-token",
            },
            bootstrap_config={
                "bootstrap_host": "192.168.1.10",
                "port": 1884,
                "topic": "synthia/bootstrap/core",
            },
        )

        self.assertTrue(handoff.bootstrap.anonymous)
        self.assertFalse(handoff.bootstrap.publish_allowed)
        self.assertFalse(handoff.operational.anonymous)
        self.assertEqual(handoff.operational.identity, "main-ai-node")

    def test_prepare_handoff_rejects_shared_bootstrap_and_operational_endpoint(self):
        with self.assertRaisesRegex(ValueError, "must remain logically separated"):
            prepare_operational_mqtt_handoff(
                trust_state={
                    "operational_mqtt_host": "192.168.1.10",
                    "operational_mqtt_port": 1884,
                    "operational_mqtt_identity": "main-ai-node",
                    "operational_mqtt_token": "mqtt-token",
                },
                bootstrap_config={
                    "bootstrap_host": "192.168.1.10",
                    "port": 1884,
                    "topic": "synthia/bootstrap/core",
                },
            )


if __name__ == "__main__":
    unittest.main()
