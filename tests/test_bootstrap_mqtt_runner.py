import unittest

from ai_node.runtime.bootstrap_mqtt_runner import _build_bootstrap_client_id


class BootstrapMqttRunnerTests(unittest.TestCase):
    def test_build_bootstrap_client_id_sanitizes_friendly_node_name(self):
        self.assertEqual(_build_bootstrap_client_id("Main AI Node"), "bootstrap-main-ai-node")

    def test_build_bootstrap_client_id_falls_back_when_name_has_no_safe_chars(self):
        self.assertEqual(_build_bootstrap_client_id("   !!!   "), "bootstrap-ai-node")


if __name__ == "__main__":
    unittest.main()
