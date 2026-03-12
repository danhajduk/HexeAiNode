import os
from dataclasses import dataclass, field


@dataclass
class ProviderSettings:
    provider_id: str
    provider_type: str
    enabled: bool
    api_key_env: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    timeout_seconds: float = 20.0
    retry_count: int = 1


@dataclass
class ProviderRuntimeConfig:
    enabled_providers: list[str] = field(default_factory=list)
    default_provider: str | None = None
    providers: dict[str, ProviderSettings] = field(default_factory=dict)


class ProviderConfigLoader:
    def __init__(self, *, logger, provider_selection_store=None) -> None:
        self._logger = logger
        self._provider_selection_store = provider_selection_store

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
                providers[provider_id] = ProviderSettings(
                    provider_id=provider_id,
                    provider_type="cloud",
                    enabled=True,
                    api_key_env=api_key_env,
                    api_key=str(os.environ.get(api_key_env) or "").strip() or None,
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
