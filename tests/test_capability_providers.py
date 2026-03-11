import unittest

from ai_node.capabilities.providers import (
    create_provider_capabilities,
    create_provider_capabilities_from_selection_config,
    validate_provider_capabilities,
)


class CapabilityProviderTests(unittest.TestCase):
    def test_create_provider_capabilities_supports_openai_by_default(self):
        providers = create_provider_capabilities()
        self.assertIn("openai", providers["supported"])
        self.assertEqual(providers["enabled"], [])

    def test_create_provider_capabilities_from_selection_config(self):
        providers = create_provider_capabilities_from_selection_config(
            {
                "providers": {
                    "supported": {
                        "cloud": ["openai"],
                        "local": ["ollama"],
                        "future": [],
                    },
                    "enabled": ["openai"],
                }
            }
        )
        self.assertIn("openai", providers["supported"])
        self.assertIn("ollama", providers["supported"])
        self.assertEqual(providers["enabled"], ["openai"])

    def test_validate_rejects_enabled_provider_not_supported(self):
        is_valid, error = validate_provider_capabilities(
            {
                "supported": ["openai"],
                "enabled": ["anthropic"],
            }
        )
        self.assertFalse(is_valid)
        self.assertEqual(error, "enabled_provider_not_supported")


if __name__ == "__main__":
    unittest.main()
