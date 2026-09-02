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

    def test_openai_provider_default_model_prefers_stored_default_over_selected_order(self):
        class _CredentialsStore:
            def load_or_create(self):
                return {
                    "schema_version": "1.0",
                    "providers": {
                        "openai": {
                            "api_token": "token-alpha-1234",
                            "service_token": "service-token-1234",
                            "project_name": "ops",
                            "default_model_id": "gpt-5.6-luna",
                            "selected_model_ids": ["gpt-5-nano", "gpt-5.6-luna"],
                            "updated_at": "2026-09-02T00:00:00-07:00",
                        }
                    },
                }

            def load(self):
                return self.load_or_create()

        loader = ProviderConfigLoader(
            logger=logging.getLogger("provider-config-loader-test"),
            provider_credentials_store=_CredentialsStore(),
        )

        with patch.dict(os.environ, {"HEXE_OPENAI_DEFAULT_MODEL_ID": "", "OPENAI_API_KEY": ""}, clear=False):
            settings = loader.load_provider_settings(provider_id="openai", enabled=True)

        self.assertIsNotNone(settings)
        self.assertEqual(settings.default_model_id, "gpt-5.6-luna")


if __name__ == "__main__":
    unittest.main()
