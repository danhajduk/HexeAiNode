import json
from pathlib import Path
from typing import Optional, Tuple


DEFAULT_PROVIDER_SELECTION_SCHEMA_VERSION = "1.0"
DEFAULT_OPENAI_PROVIDER = "openai"
VALID_PROVIDER_BUDGET_PERIODS = {"weekly", "monthly"}


def _is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _normalize_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        if _is_non_empty_string(item):
            normalized.append(str(item).strip())
    return normalized


def _collect_supported_providers(payload: dict) -> set[str]:
    providers = payload.get("providers", {})
    supported = providers.get("supported", {})
    all_supported: set[str] = set()
    for group in ("cloud", "local", "future"):
        all_supported.update(_normalize_string_list(supported.get(group)))
    return {item for item in all_supported if item}


def _normalize_provider_budget_limits(value: object) -> dict[str, dict[str, int | str]]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, dict[str, int | str]] = {}
    for provider_id, raw_limit in value.items():
        normalized_provider_id = str(provider_id or "").strip().lower()
        if not normalized_provider_id or not isinstance(raw_limit, dict):
            continue
        max_cost_cents = raw_limit.get("max_cost_cents")
        if max_cost_cents in (None, ""):
            continue
        normalized_cost = int(max_cost_cents)
        if normalized_cost < 0:
            raise ValueError("provider_budget_limit_must_be_non_negative")
        period = str(raw_limit.get("period") or "monthly").strip().lower()
        if period not in VALID_PROVIDER_BUDGET_PERIODS:
            raise ValueError("provider_budget_period_invalid")
        normalized[normalized_provider_id] = {
            "max_cost_cents": normalized_cost,
            "period": period,
        }
    return normalized


def validate_provider_selection_config(data: object) -> Tuple[bool, Optional[str]]:
    if not isinstance(data, dict):
        return False, "invalid_provider_selection_config_object"

    if not _is_non_empty_string(data.get("schema_version")):
        return False, "invalid_schema_version"

    providers = data.get("providers")
    if not isinstance(providers, dict):
        return False, "invalid_providers"
    supported = providers.get("supported")
    if not isinstance(supported, dict):
        return False, "invalid_supported_providers"

    supported_cloud = _normalize_string_list(supported.get("cloud"))
    supported_local = _normalize_string_list(supported.get("local"))
    supported_future = _normalize_string_list(supported.get("future"))
    if not supported_cloud and not supported_local and not supported_future:
        return False, "missing_supported_providers"

    enabled_providers = _normalize_string_list(providers.get("enabled"))
    supported_set = _collect_supported_providers(data)
    if any(provider not in supported_set for provider in enabled_providers):
        return False, "enabled_provider_not_supported"
    try:
        budget_limits = _normalize_provider_budget_limits(providers.get("budget_limits"))
    except (TypeError, ValueError):
        return False, "invalid_provider_budget_limits"
    if any(provider not in supported_set for provider in budget_limits):
        return False, "provider_budget_not_supported"

    services = data.get("services")
    if not isinstance(services, dict):
        return False, "invalid_services"
    _normalize_string_list(services.get("enabled"))
    _normalize_string_list(services.get("future"))
    return True, None


def create_provider_selection_config(input_data: dict | None = None) -> dict:
    raw = input_data if isinstance(input_data, dict) else {}
    openai_enabled = bool(raw.get("openai_enabled", False))

    cloud_supported = _normalize_string_list(raw.get("supported_cloud_providers")) or [DEFAULT_OPENAI_PROVIDER]
    if DEFAULT_OPENAI_PROVIDER not in cloud_supported:
        cloud_supported.append(DEFAULT_OPENAI_PROVIDER)
    local_supported = _normalize_string_list(raw.get("supported_local_providers"))
    future_supported = _normalize_string_list(raw.get("supported_future_providers"))

    enabled_providers = _normalize_string_list(raw.get("enabled_providers"))
    if openai_enabled and DEFAULT_OPENAI_PROVIDER not in enabled_providers:
        enabled_providers.append(DEFAULT_OPENAI_PROVIDER)
    budget_limits = _normalize_provider_budget_limits(raw.get("provider_budget_limits"))

    config = {
        "schema_version": DEFAULT_PROVIDER_SELECTION_SCHEMA_VERSION,
        "providers": {
            "supported": {
                "cloud": sorted(set(cloud_supported)),
                "local": sorted(set(local_supported)),
                "future": sorted(set(future_supported)),
            },
            "enabled": sorted(set(enabled_providers)),
            "budget_limits": budget_limits,
        },
        "services": {
            "enabled": sorted(set(_normalize_string_list(raw.get("enabled_services")))),
            "future": sorted(set(_normalize_string_list(raw.get("future_services")))),
        },
    }
    is_valid, error = validate_provider_selection_config(config)
    if not is_valid:
        raise ValueError(f"invalid provider selection config: {error}")
    return config


class ProviderSelectionConfigStore:
    def __init__(self, *, path: str, logger) -> None:
        self._path = Path(path)
        self._logger = logger

    def save(self, config: dict) -> None:
        is_valid, error = validate_provider_selection_config(config)
        if not is_valid:
            raise ValueError(f"cannot save invalid provider selection config: {error}")

        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._path.with_suffix(f"{self._path.suffix}.tmp")
        temp_path.write_text(json.dumps(config, indent=2, sort_keys=True), encoding="utf-8")
        temp_path.replace(self._path)

        if hasattr(self._logger, "info"):
            self._logger.info("[provider-selection-config-saved] %s", {"path": str(self._path)})

    def load(self) -> Optional[dict]:
        if not self._path.exists():
            return None
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            if hasattr(self._logger, "warning"):
                self._logger.warning(
                    "[provider-selection-config-invalid] %s",
                    {"path": str(self._path), "reason": "invalid_json"},
                )
            return None

        is_valid, error = validate_provider_selection_config(payload)
        if not is_valid:
            if hasattr(self._logger, "warning"):
                self._logger.warning(
                    "[provider-selection-config-invalid] %s",
                    {"path": str(self._path), "reason": error},
                )
            return None

        if hasattr(self._logger, "info"):
            self._logger.info("[provider-selection-config-loaded] %s", {"path": str(self._path)})
        return payload

    def load_or_create(self, *, openai_enabled: bool = False) -> dict:
        existing = self.load()
        if existing is not None:
            return existing
        created = create_provider_selection_config({"openai_enabled": openai_enabled})
        self.save(created)
        return created
