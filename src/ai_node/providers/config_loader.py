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
    max_cost_cents: int | None = None


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
            settings = self.load_provider_settings(provider_id=provider_id, enabled=True)
            if settings is not None:
                providers[provider_id] = settings

        return ProviderRuntimeConfig(
            enabled_providers=sorted(set(enabled)),
            default_provider=default_provider,
            providers=providers,
        )

    def load_provider_settings(self, *, provider_id: str, enabled: bool) -> ProviderSettings | None:
        normalized_provider_id = str(provider_id or "").strip().lower()
        if not normalized_provider_id:
            return None
        upper = normalized_provider_id.upper().replace("-", "_")
        timeout = float(os.environ.get(f"SYNTHIA_PROVIDER_{upper}_TIMEOUT_SECONDS") or "20")
        retries = int(os.environ.get(f"SYNTHIA_PROVIDER_{upper}_RETRY_COUNT") or "1")
        provider_budget_limits = self._provider_budget_limits()
        provider_budget = provider_budget_limits.get(normalized_provider_id) if isinstance(provider_budget_limits, dict) else None
        max_cost_cents = provider_budget.get("max_cost_cents") if isinstance(provider_budget, dict) else None
        if normalized_provider_id == "openai":
            api_key_env = "OPENAI_API_KEY"
            stored_openai = self._openai_credentials()
            return ProviderSettings(
                provider_id=normalized_provider_id,
                provider_type="cloud",
                enabled=bool(enabled),
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
                            (stored_openai.get("selected_model_ids") or [None])
                            if isinstance(stored_openai, dict)
                            else [None]
                        )[0],
                        stored_openai.get("default_model_id") if isinstance(stored_openai, dict) else None,
                    )
                ),
                base_url=str(os.environ.get("SYNTHIA_OPENAI_BASE_URL") or "https://api.openai.com/v1").strip(),
                timeout_seconds=max(timeout, 1.0),
                retry_count=max(retries, 0),
                max_cost_cents=int(max_cost_cents) if max_cost_cents is not None else None,
            )
        return ProviderSettings(
            provider_id=normalized_provider_id,
            provider_type="local",
            enabled=bool(enabled),
            timeout_seconds=max(timeout, 1.0),
            retry_count=max(retries, 0),
            max_cost_cents=int(max_cost_cents) if max_cost_cents is not None else None,
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

    def _provider_budget_limits(self) -> dict:
        if self._provider_selection_store is None or not hasattr(self._provider_selection_store, "load_or_create"):
            return {}
        payload = self._provider_selection_store.load_or_create(openai_enabled=False)
        if not isinstance(payload, dict):
            return {}
        providers = payload.get("providers")
        if not isinstance(providers, dict):
            return {}
        limits = providers.get("budget_limits")
        return limits if isinstance(limits, dict) else {}


def _first_non_empty_string(*values: str | None) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
