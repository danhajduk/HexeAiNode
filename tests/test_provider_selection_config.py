import json
import logging
import tempfile
import unittest
from pathlib import Path

from ai_node.config.provider_selection_config import (
    ProviderSelectionConfigStore,
    create_provider_selection_config,
    validate_provider_selection_config,
)


class ProviderSelectionConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.logger = logging.getLogger("provider-selection-config-test")

    def test_create_defaults_support_openai_but_disabled_by_default(self):
        config = create_provider_selection_config()
        self.assertIn("openai", config["providers"]["supported"]["cloud"])
        self.assertEqual(config["providers"]["enabled"], [])

    def test_create_enables_openai_when_requested(self):
        config = create_provider_selection_config({"openai_enabled": True})
        self.assertIn("openai", config["providers"]["enabled"])

    def test_validate_rejects_enabled_provider_not_in_supported(self):
        is_valid, error = validate_provider_selection_config(
            {
                "schema_version": "1.0",
                "providers": {
                    "supported": {"cloud": ["openai"], "local": [], "future": []},
                    "enabled": ["anthropic"],
                },
                "services": {"enabled": [], "future": []},
            }
        )
        self.assertFalse(is_valid)
        self.assertEqual(error, "enabled_provider_not_supported")

    def test_store_save_load_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "provider_selection.json"
            store = ProviderSelectionConfigStore(path=str(path), logger=self.logger)
            config = create_provider_selection_config(
                {
                    "openai_enabled": True,
                    "supported_local_providers": ["ollama"],
                    "enabled_services": ["status_telemetry"],
                }
            )
            store.save(config)
            loaded = store.load()
            self.assertEqual(loaded, config)

    def test_store_load_returns_none_for_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "provider_selection.json"
            path.write_text("{broken", encoding="utf-8")
            store = ProviderSelectionConfigStore(path=str(path), logger=self.logger)
            self.assertIsNone(store.load())

    def test_store_load_or_create_creates_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "provider_selection.json"
            store = ProviderSelectionConfigStore(path=str(path), logger=self.logger)
            config = store.load_or_create(openai_enabled=False)
            self.assertIn("openai", config["providers"]["supported"]["cloud"])
            self.assertEqual(config["providers"]["enabled"], [])
            self.assertTrue(path.exists())
            persisted = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(persisted, config)


if __name__ == "__main__":
    unittest.main()
