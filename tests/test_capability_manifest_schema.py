import unittest

from ai_node.capabilities.manifest_schema import (
    create_capability_manifest,
    validate_capability_manifest,
)


class CapabilityManifestSchemaTests(unittest.TestCase):
    @staticmethod
    def _valid_environment_hints() -> dict:
        return {
            "hostname": "node-a",
            "os_platform": "linux-test",
            "memory_class": "standard",
            "gpu_present": False,
        }

    def test_create_manifest_with_required_groups(self):
        manifest = create_capability_manifest(
            node_id="node-001",
            node_type="ai-node",
            node_name="main-ai-node",
            node_software_version="0.1.0",
            task_families=["text_classification"],
            supported_providers=["openai"],
            enabled_providers=[],
            node_features=["telemetry_support"],
            environment_hints=self._valid_environment_hints(),
        )
        is_valid, error = validate_capability_manifest(manifest)
        self.assertTrue(is_valid)
        self.assertIsNone(error)

    def test_validate_rejects_enabled_provider_not_supported(self):
        manifest = create_capability_manifest(
            node_id="node-001",
            node_type="ai-node",
            node_name="main-ai-node",
            node_software_version="0.1.0",
            task_families=[],
            supported_providers=["openai"],
            enabled_providers=[],
            node_features=["telemetry_support"],
            environment_hints=self._valid_environment_hints(),
        )
        manifest["enabled_providers"] = ["anthropic"]
        is_valid, error = validate_capability_manifest(manifest)
        self.assertFalse(is_valid)
        self.assertEqual(error, "enabled_provider_not_supported")

    def test_validate_rejects_missing_node_group(self):
        is_valid, error = validate_capability_manifest(
            {
                "manifest_version": "1.0",
                "declared_task_families": ["text_classification"],
                "supported_providers": ["openai"],
                "enabled_providers": [],
                "node_features": {
                    "telemetry": True,
                    "governance_refresh": True,
                    "lifecycle_events": True,
                    "provider_failover": True,
                },
                "environment_hints": {
                    "deployment_target": "edge",
                    "acceleration": "cpu",
                    "network_tier": "lan",
                    "region": "local",
                },
            }
        )
        self.assertFalse(is_valid)
        self.assertEqual(error, "invalid_node")

    def test_validate_rejects_unknown_task_family(self):
        manifest = create_capability_manifest(
            node_id="node-001",
            node_type="ai-node",
            node_name="main-ai-node",
            node_software_version="0.1.0",
            task_families=[],
            supported_providers=["openai"],
            enabled_providers=[],
            node_features=["telemetry_support"],
            environment_hints=self._valid_environment_hints(),
        )
        manifest["declared_task_families"] = ["audio_transcription"]
        is_valid, error = validate_capability_manifest(manifest)
        self.assertFalse(is_valid)
        self.assertEqual(error, "unknown_task_family:audio_transcription")

    def test_validate_rejects_metadata_field(self):
        manifest = create_capability_manifest(
            node_id="node-001",
            node_type="ai-node",
            node_name="main-ai-node",
            node_software_version="0.1.0",
            task_families=["text_classification"],
            supported_providers=["openai"],
            enabled_providers=["openai"],
            node_features=["telemetry_support"],
            environment_hints=self._valid_environment_hints(),
        )
        manifest["metadata"] = {"schema_version": "1.0"}
        is_valid, error = validate_capability_manifest(manifest)
        self.assertFalse(is_valid)
        self.assertEqual(error, "metadata_not_allowed")


if __name__ == "__main__":
    unittest.main()
