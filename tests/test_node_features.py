import unittest

from ai_node.capabilities.node_features import (
    PROMPT_GOVERNANCE_READY,
    create_node_feature_declarations,
    validate_node_feature_declarations,
)


class NodeFeatureDeclarationTests(unittest.TestCase):
    def test_default_node_features_include_disabled_prompt_governance_ready(self):
        features = create_node_feature_declarations()
        matching = [item for item in features if item["name"] == PROMPT_GOVERNANCE_READY]
        self.assertEqual(len(matching), 1)
        self.assertFalse(matching[0]["enabled"])

    def test_validate_rejects_unknown_feature(self):
        is_valid, error = validate_node_feature_declarations(
            [{"name": "telemetry_support", "enabled": True}, {"name": "gpu_scheduler_ready", "enabled": False}]
        )
        self.assertFalse(is_valid)
        self.assertEqual(error, "unknown_node_feature:gpu_scheduler_ready")

    def test_validate_accepts_string_short_form(self):
        is_valid, error = validate_node_feature_declarations(["telemetry_support", "operational_mqtt_support"])
        self.assertTrue(is_valid)
        self.assertIsNone(error)


if __name__ == "__main__":
    unittest.main()
