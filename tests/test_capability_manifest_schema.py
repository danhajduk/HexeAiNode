import unittest

from ai_node.capabilities.manifest_schema import (
    create_capability_manifest,
    validate_capability_manifest,
)


class CapabilityManifestSchemaTests(unittest.TestCase):
    def test_create_manifest_with_required_groups(self):
        manifest = create_capability_manifest(
            node_id="node-001",
            node_name="main-ai-node",
            task_families=["text_classification"],
            supported_providers=["openai"],
            enabled_providers=[],
            node_features=["telemetry_support"],
            environment_hints={"hostname": "synthia-node"},
        )
        is_valid, error = validate_capability_manifest(manifest)
        self.assertTrue(is_valid)
        self.assertIsNone(error)

    def test_validate_rejects_enabled_provider_not_supported(self):
        manifest = create_capability_manifest(
            node_id="node-001",
            node_name="main-ai-node",
            task_families=[],
            supported_providers=["openai"],
            enabled_providers=[],
            node_features=["telemetry_support"],
            environment_hints={},
        )
        manifest["capabilities"]["providers"]["enabled"] = ["anthropic"]
        is_valid, error = validate_capability_manifest(manifest)
        self.assertFalse(is_valid)
        self.assertEqual(error, "enabled_provider_not_supported")

    def test_validate_rejects_missing_capabilities_group(self):
        is_valid, error = validate_capability_manifest(
            {
                "manifest_version": "1.0",
                "generated_at": "2026-03-11T00:00:00Z",
                "node_id": "node-001",
                "node_name": "main-ai-node",
                "metadata": {"schema_version": "1.0"},
            }
        )
        self.assertFalse(is_valid)
        self.assertEqual(error, "invalid_capabilities")

    def test_validate_rejects_unknown_task_family(self):
        manifest = create_capability_manifest(
            node_id="node-001",
            node_name="main-ai-node",
            task_families=[],
            supported_providers=["openai"],
            enabled_providers=[],
            node_features=["telemetry_support"],
            environment_hints={},
        )
        manifest["capabilities"]["task_families"] = ["audio_transcription"]
        is_valid, error = validate_capability_manifest(manifest)
        self.assertFalse(is_valid)
        self.assertEqual(error, "unknown_task_family:audio_transcription")


if __name__ == "__main__":
    unittest.main()
