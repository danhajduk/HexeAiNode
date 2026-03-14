import os
from dataclasses import dataclass, field

from ai_node.config.provider_credentials_config import ProviderCredentialsStore


@dataclass
class ProviderSettings:
    provider_id: str
    provider_type: str
    enabled: bool
    api_key_env: str | None = None
    api_key: str | None = None
    default_model_id: str | None = None
    base_url: str | None = None
    timeout_seconds: float = 20.0
    retry_count: int = 1


@dataclass
class ProviderRuntimeConfig:
    enabled_providers: list[str] = field(default_factory=list)
    default_provider: str | None = None
    providers: dict[str, ProviderSettings] = field(default_factory=dict)


class ProviderConfigLoader:
    def __init__(self, *, logger, provider_selection_store=None, provider_credentials_store: ProviderCredentialsStore | None = None) -> None:
        self._logger = logger
        self._provider_selection_store = provider_selection_store
        self._provider_credentials_store = provider_credentials_store

    def load(self) -> ProviderRuntimeConfig:
        enabled = self._enabled_from_selection_store()
        if not enabled:
            raw = str(os.environ.get("SYNTHIA_ENABLED_PROVIDERS") or "openai").strip()
            enabled = [item.strip() for item in raw.split(",") if item.strip()]

        default_provider = str(os.environ.get("SYNTHIA_DEFAULT_PROVIDER") or "").strip() or (enabled[0] if enabled else None)
        providers: dict[str, ProviderSettings] = {}

        for provider_id in enabled:
            upper = provider_id.upper().replace("-", "_")
            timeout = float(os.environ.get(f"SYNTHIA_PROVIDER_{upper}_TIMEOUT_SECONDS") or "20")
            retries = int(os.environ.get(f"SYNTHIA_PROVIDER_{upper}_RETRY_COUNT") or "1")
            if provider_id == "openai":
                api_key_env = "OPENAI_API_KEY"
                stored_openai = self._openai_credentials()
                providers[provider_id] = ProviderSettings(
                    provider_id=provider_id,
                    provider_type="cloud",
                    enabled=True,
                    api_key_env=api_key_env,
                    api_key=(
                        _first_non_empty_string(
                            str(os.environ.get(api_key_env) or "").strip() or None,
                            (
                                stored_openai.get("api_token") or stored_openai.get("api_key")
                                if isinstance(stored_openai, dict)
                                else None
                            ),
                        )
                    ),
                    default_model_id=(
                        _first_non_empty_string(
                            str(os.environ.get("SYNTHIA_OPENAI_DEFAULT_MODEL_ID") or "").strip() or None,
                            (
                                (stored_openai.get("selected_model_ids") or [None])[0]
                                if isinstance(stored_openai, dict)
                                else None
                            ),
                            stored_openai.get("default_model_id") if isinstance(stored_openai, dict) else None,
                        )
                    ),
                    base_url=str(os.environ.get("SYNTHIA_OPENAI_BASE_URL") or "https://api.openai.com/v1").strip(),
                    timeout_seconds=max(timeout, 1.0),
                    retry_count=max(retries, 0),
                )
                continue
            providers[provider_id] = ProviderSettings(
                provider_id=provider_id,
                provider_type="local",
                enabled=True,
                timeout_seconds=max(timeout, 1.0),
                retry_count=max(retries, 0),
            )

        return ProviderRuntimeConfig(
            enabled_providers=sorted(set(enabled)),
            default_provider=default_provider,
            providers=providers,
        )

    def _enabled_from_selection_store(self) -> list[str]:
        if self._provider_selection_store is None or not hasattr(self._provider_selection_store, "load_or_create"):
            return []
        payload = self._provider_selection_store.load_or_create(openai_enabled=False)
        if not isinstance(payload, dict):
            return []
        providers = payload.get("providers")
        if not isinstance(providers, dict):
            return []
        raw = providers.get("enabled")
        if not isinstance(raw, list):
            return []
        return [str(item).strip() for item in raw if str(item).strip()]

    def _openai_credentials(self) -> dict:
        if self._provider_credentials_store is None or not hasattr(self._provider_credentials_store, "load"):
            return {}
        payload = self._provider_credentials_store.load()
        if not isinstance(payload, dict):
            return {}
        providers = payload.get("providers")
        if not isinstance(providers, dict):
            return {}
        openai_payload = providers.get("openai")
        return openai_payload if isinstance(openai_payload, dict) else {}


def _first_non_empty_string(*values: str | None) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
