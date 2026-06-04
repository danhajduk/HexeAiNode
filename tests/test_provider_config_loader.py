import logging
import os
import unittest
from unittest.mock import patch

from ai_node.providers.config_loader import (
    LOCAL_PROVIDER_BUILTIN_DEFAULT_MODEL_ID,
    ProviderConfigLoader,
)


class ProviderConfigLoaderTests(unittest.TestCase):
    def test_local_provider_default_model_uses_builtin_fallback(self):
        loader = ProviderConfigLoader(logger=logging.getLogger("provider-config-loader-test"))

        with patch.dict(os.environ, {"HEXE_PROVIDER_LOCAL_DEFAULT_MODEL_ID": ""}, clear=False):
            settings = loader.load_provider_settings(provider_id="local", enabled=True)

        self.assertIsNotNone(settings)
        self.assertEqual(settings.default_model_id, LOCAL_PROVIDER_BUILTIN_DEFAULT_MODEL_ID)

    def test_local_provider_default_model_prefers_explicit_env(self):
        loader = ProviderConfigLoader(logger=logging.getLogger("provider-config-loader-test"))

        with patch.dict(os.environ, {"HEXE_PROVIDER_LOCAL_DEFAULT_MODEL_ID": "llama-3.1-8b-instruct-q4_k_m"}, clear=False):
            settings = loader.load_provider_settings(provider_id="local", enabled=True)

        self.assertIsNotNone(settings)
        self.assertEqual(settings.default_model_id, "llama-3.1-8b-instruct-q4_k_m")


if __name__ == "__main__":
    unittest.main()
