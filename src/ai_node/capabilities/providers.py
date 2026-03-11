from typing import Optional, Tuple


DEFAULT_SUPPORTED_PROVIDERS = ("openai",)


def _normalize_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            normalized.append(item.strip())
    return sorted(set(normalized))


def create_provider_capabilities(
    *,
    supported_providers: list[str] | None = None,
    enabled_providers: list[str] | None = None,
) -> dict:
    supported = _normalize_string_list(supported_providers)
    if not supported:
        supported = list(DEFAULT_SUPPORTED_PROVIDERS)
    if "openai" not in supported:
        supported.append("openai")
    enabled = _normalize_string_list(enabled_providers)

    payload = {
        "supported": sorted(set(supported)),
        "enabled": sorted(set(enabled)),
    }
    is_valid, error = validate_provider_capabilities(payload)
    if not is_valid:
        raise ValueError(f"invalid provider capabilities: {error}")
    return payload


def create_provider_capabilities_from_selection_config(provider_selection_config: dict | None) -> dict:
    config = provider_selection_config if isinstance(provider_selection_config, dict) else {}
    providers = config.get("providers", {}) if isinstance(config.get("providers"), dict) else {}
    supported = providers.get("supported", {}) if isinstance(providers.get("supported"), dict) else {}
    supported_flat = []
    supported_flat.extend(_normalize_string_list(supported.get("cloud")))
    supported_flat.extend(_normalize_string_list(supported.get("local")))
    supported_flat.extend(_normalize_string_list(supported.get("future")))

    return create_provider_capabilities(
        supported_providers=supported_flat,
        enabled_providers=providers.get("enabled"),
    )


def validate_provider_capabilities(payload: object) -> Tuple[bool, Optional[str]]:
    if not isinstance(payload, dict):
        return False, "invalid_provider_capabilities"
    supported = _normalize_string_list(payload.get("supported"))
    enabled = _normalize_string_list(payload.get("enabled"))
    if not supported:
        return False, "missing_supported_providers"
    if any(provider not in set(supported) for provider in enabled):
        return False, "enabled_provider_not_supported"
    return True, None
