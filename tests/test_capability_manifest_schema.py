import unittest

from ai_node.capabilities.manifest_schema import (
    create_capability_manifest,
    validate_capability_manifest,
)


class CapabilityManifestSchemaTests(unittest.TestCase):
    @staticmethod
    def _valid_environment_hints() -> dict:
        return {
            "deployment_target": "edge",
            "acceleration": "cpu",
            "network_tier": "lan",
            "region": "local",
        }

    def test_create_manifest_with_required_groups(self):
        manifest = create_capability_manifest(
            node_id="node-001",
            node_type="ai-node",
            node_name="main-ai-node",
            node_software_version="0.1.0",
            task_families=["task.classification"],
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
            task_families=["task.classification"],
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
                "declared_task_families": ["task.classification"],
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
            task_families=["task.classification"],
            supported_providers=["openai"],
            enabled_providers=[],
            node_features=["telemetry_support"],
            environment_hints=self._valid_environment_hints(),
        )
        manifest["declared_task_families"] = ["BAD FAMILY"]
        is_valid, error = validate_capability_manifest(manifest)
        self.assertFalse(is_valid)
        self.assertEqual(error, "invalid_task_family:bad family")

    def test_validate_rejects_unknown_manifest_field(self):
        manifest = create_capability_manifest(
            node_id="node-001",
            node_type="ai-node",
            node_name="main-ai-node",
            node_software_version="0.1.0",
            task_families=["task.classification"],
            supported_providers=["openai"],
            enabled_providers=["openai"],
            node_features=["telemetry_support"],
            environment_hints=self._valid_environment_hints(),
        )
        manifest["metadata"] = {"schema_version": "1.0"}
        is_valid, error = validate_capability_manifest(manifest)
        self.assertFalse(is_valid)
        self.assertEqual(error, "unknown_manifest_field:metadata")

    def test_create_manifest_accepts_provider_intelligence(self):
        manifest = create_capability_manifest(
            node_id="node-001",
            node_type="ai-node",
            node_name="main-ai-node",
            node_software_version="0.1.0",
            task_families=["task.classification", "task.reasoning"],
            supported_providers=["openai"],
            enabled_providers=["openai"],
            node_features=["telemetry_support"],
            environment_hints=self._valid_environment_hints(),
            provider_intelligence=[
                {
                    "provider": "openai",
                    "available_models": [
                        {
                            "model_id": "gpt-5-mini",
                            "pricing": {"input_per_million": 0.25},
                            "latency_metrics": {"p95_ms": 420},
                        }
                    ],
                }
            ],
        )

        is_valid, error = validate_capability_manifest(manifest)

        self.assertTrue(is_valid)
        self.assertIsNone(error)
        self.assertEqual(manifest["provider_intelligence"][0]["provider"], "openai")
        self.assertEqual(manifest["provider_intelligence"][0]["available_models"][0]["model_id"], "gpt-5-mini")

    def test_validate_rejects_provider_intelligence_for_unsupported_provider(self):
        manifest = create_capability_manifest(
            node_id="node-001",
            node_type="ai-node",
            node_name="main-ai-node",
            node_software_version="0.1.0",
            task_families=["task.classification"],
            supported_providers=["openai"],
            enabled_providers=["openai"],
            node_features=["telemetry_support"],
            environment_hints=self._valid_environment_hints(),
        )
        manifest["provider_intelligence"] = [{"provider": "anthropic", "available_models": [{"model_id": "claude"}]}]

        is_valid, error = validate_capability_manifest(manifest)

        self.assertFalse(is_valid)
        self.assertEqual(error, "provider_intelligence_provider_not_supported")

    def test_create_manifest_accepts_granular_code_task_families(self):
        manifest = create_capability_manifest(
            node_id="node-001",
            node_type="ai-node",
            node_name="main-ai-node",
            node_software_version="0.1.0",
            task_families=["task.code_debugging", "task.code_generation"],
            supported_providers=["openai"],
            enabled_providers=["openai"],
            node_features=["telemetry_support"],
            environment_hints=self._valid_environment_hints(),
        )

        is_valid, error = validate_capability_manifest(manifest)

        self.assertTrue(is_valid)
        self.assertIsNone(error)


if __name__ == "__main__":
    unittest.main()
