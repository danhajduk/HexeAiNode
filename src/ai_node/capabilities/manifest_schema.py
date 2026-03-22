from typing import Optional, Tuple

from ai_node.capabilities.node_features import (
    CAPABILITY_DECLARATION_SUPPORT,
    OPERATIONAL_MQTT_SUPPORT,
    POLICY_ENFORCEMENT_SUPPORT,
    PROMPT_GOVERNANCE_READY,
    TELEMETRY_SUPPORT,
    create_node_feature_declarations,
)
from ai_node.capabilities.environment_hints import (
    collect_environment_hints,
)
from ai_node.capabilities.task_families import validate_task_family_capabilities

CAPABILITY_MANIFEST_SCHEMA_VERSION = "1.0"
_ROOT_ALLOWED_KEYS = {
    "manifest_version",
    "node",
    "declared_task_families",
    "supported_providers",
    "enabled_providers",
    "node_features",
    "environment_hints",
    "provider_intelligence",
}
_NODE_ALLOWED_KEYS = {"node_id", "node_type", "node_name", "node_software_version"}
_NODE_FEATURE_ALLOWED_KEYS = {"telemetry", "governance_refresh", "lifecycle_events", "provider_failover"}
_ENVIRONMENT_HINT_ALLOWED_KEYS = {"deployment_target", "acceleration", "network_tier", "region"}
_PROVIDER_INTELLIGENCE_ALLOWED_KEYS = {"provider", "available_models"}
_PROVIDER_MODEL_ALLOWED_KEYS = {"model_id", "pricing", "latency_metrics"}


def _is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _normalize_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized = []
    for item in value:
        if _is_non_empty_string(item):
            normalized.append(str(item).strip())
    return sorted(set(normalized))


def _normalize_optional_string(value: object, *, max_length: int = 64) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return normalized[:max_length]


def _normalize_numeric_map(value: object) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, float] = {}
    for key, item in value.items():
        if not _is_non_empty_string(key):
            continue
        if not isinstance(item, (int, float)) or isinstance(item, bool) or item < 0:
            continue
        normalized[str(key).strip()] = float(item)
    return normalized


def _normalize_environment_hints(value: object) -> dict:
    raw = value if isinstance(value, dict) else {}
    if any(key in raw for key in _ENVIRONMENT_HINT_ALLOWED_KEYS):
        deployment_target = _normalize_optional_string(raw.get("deployment_target"))
        acceleration = _normalize_optional_string(raw.get("acceleration"))
        network_tier = _normalize_optional_string(raw.get("network_tier"))
        region = _normalize_optional_string(raw.get("region"))
    else:
        deployment_target = "edge"
        acceleration = "gpu" if bool(raw.get("gpu_present")) else "cpu"
        network_tier = "lan"
        region = "local"
    return {
        "deployment_target": deployment_target,
        "acceleration": acceleration,
        "network_tier": network_tier,
        "region": region,
    }


def _normalize_provider_intelligence(value: object) -> list[dict]:
    if not isinstance(value, list):
        return []
    normalized_entries: list[dict] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        provider = str(item.get("provider") or "").strip().lower()
        if not provider:
            continue
        models: list[dict] = []
        for model in item.get("available_models") or []:
            if not isinstance(model, dict):
                continue
            model_id = str(model.get("model_id") or "").strip()
            if not model_id:
                continue
            model_payload = {"model_id": model_id}
            pricing = _normalize_numeric_map(model.get("pricing"))
            latency_metrics = _normalize_numeric_map(model.get("latency_metrics"))
            if pricing:
                model_payload["pricing"] = pricing
            if latency_metrics:
                model_payload["latency_metrics"] = latency_metrics
            models.append(model_payload)
        normalized_entries.append({"provider": provider, "available_models": models})
    return normalized_entries


def create_capability_manifest(
    *,
    node_id: str,
    node_name: str,
    node_type: str = "ai-node",
    node_software_version: str = "0.1.0",
    task_families: list[str] | None = None,
    supported_providers: list[str] | None = None,
    enabled_providers: list[str] | None = None,
    node_features: list[str] | None = None,
    environment_hints: dict | None = None,
    provider_intelligence: list[dict] | None = None,
    provider_metadata: list[dict] | None = None,
    enabled_models: list[dict] | None = None,
    manifest_version: str = CAPABILITY_MANIFEST_SCHEMA_VERSION,
    metadata: dict | None = None,
) -> dict:
    resolved_environment_hints = (
        environment_hints if isinstance(environment_hints, dict) else collect_environment_hints()
    )
    feature_declarations = create_node_feature_declarations(node_features)
    feature_map = {str(item.get("name")): bool(item.get("enabled")) for item in feature_declarations if isinstance(item, dict)}
    manifest = {
        "manifest_version": CAPABILITY_MANIFEST_SCHEMA_VERSION,
        "node": {
            "node_id": str(node_id).strip(),
            "node_type": str(node_type).strip() or "ai-node",
            "node_name": str(node_name).strip(),
            "node_software_version": str(node_software_version).strip() or "0.1.0",
        },
        "declared_task_families": _normalize_string_list(task_families or []),
        "supported_providers": _normalize_string_list(supported_providers or []),
        "enabled_providers": _normalize_string_list(enabled_providers or []),
        "node_features": {
            "telemetry": feature_map.get(TELEMETRY_SUPPORT, True),
            "governance_refresh": feature_map.get(CAPABILITY_DECLARATION_SUPPORT, True),
            "lifecycle_events": feature_map.get(OPERATIONAL_MQTT_SUPPORT, True),
            "provider_failover": feature_map.get(POLICY_ENFORCEMENT_SUPPORT, True),
        },
        "environment_hints": _normalize_environment_hints(resolved_environment_hints),
    }
    if str(manifest_version).strip() and str(manifest_version).strip() != CAPABILITY_MANIFEST_SCHEMA_VERSION:
        manifest["manifest_version"] = str(manifest_version).strip()
    normalized_provider_intelligence = _normalize_provider_intelligence(provider_intelligence)
    if normalized_provider_intelligence:
        manifest["provider_intelligence"] = normalized_provider_intelligence
    if feature_map.get(PROMPT_GOVERNANCE_READY, False):
        manifest["node_features"]["governance_refresh"] = True
    is_valid, error = validate_capability_manifest(manifest)
    if not is_valid:
        raise ValueError(f"invalid capability manifest: {error}")
    return manifest


def validate_capability_manifest(data: object) -> Tuple[bool, Optional[str]]:
    if not isinstance(data, dict):
        return False, "invalid_manifest_object"
    unknown_keys = sorted(set(data.keys()) - _ROOT_ALLOWED_KEYS)
    if unknown_keys:
        return False, f"unknown_manifest_field:{unknown_keys[0]}"
    if str(data.get("manifest_version") or "").strip() != CAPABILITY_MANIFEST_SCHEMA_VERSION:
        return False, "invalid_manifest_version"

    node = data.get("node")
    if not isinstance(node, dict):
        return False, "invalid_node"
    unknown_node_keys = sorted(set(node.keys()) - _NODE_ALLOWED_KEYS)
    if unknown_node_keys:
        return False, f"unknown_node_field:{unknown_node_keys[0]}"
    if not _is_non_empty_string(node.get("node_id")):
        return False, "invalid_node_id"
    node_id = str(node.get("node_id")).strip()
    if len(node_id) < 3 or len(node_id) > 128 or not node_id.startswith("node-"):
        return False, "invalid_node_id"
    if not _is_non_empty_string(node.get("node_type")):
        return False, "invalid_node_type"
    if len(str(node.get("node_type")).strip()) > 64:
        return False, "invalid_node_type"
    if not _is_non_empty_string(node.get("node_name")):
        return False, "invalid_node_name"
    if len(str(node.get("node_name")).strip()) > 128:
        return False, "invalid_node_name"
    if not _is_non_empty_string(node.get("node_software_version")):
        return False, "invalid_node_software_version"
    if len(str(node.get("node_software_version")).strip()) > 64:
        return False, "invalid_node_software_version"

    task_families = data.get("declared_task_families")
    if not isinstance(task_families, list):
        return False, "invalid_declared_task_families"
    if not task_families:
        return False, "declared_task_families_empty"
    task_family_valid, task_family_error = validate_task_family_capabilities(task_families)
    if not task_family_valid:
        return False, task_family_error

    supported_providers = _normalize_string_list(data.get("supported_providers"))
    if not supported_providers:
        return False, "supported_providers_empty"

    enabled_providers = _normalize_string_list(data.get("enabled_providers"))
    if any(provider not in set(supported_providers) for provider in enabled_providers):
        return False, "enabled_provider_not_supported"

    node_features = data.get("node_features")
    if not isinstance(node_features, dict):
        return False, "invalid_node_features"
    unknown_feature_keys = sorted(set(node_features.keys()) - _NODE_FEATURE_ALLOWED_KEYS)
    if unknown_feature_keys:
        return False, f"unknown_node_feature:{unknown_feature_keys[0]}"
    for key, value in node_features.items():
        if not isinstance(value, bool):
            return False, f"invalid_node_feature_{key}"

    environment_hints = data.get("environment_hints")
    if not isinstance(environment_hints, dict):
        return False, "invalid_environment_hints"
    unknown_hint_keys = sorted(set(environment_hints.keys()) - _ENVIRONMENT_HINT_ALLOWED_KEYS)
    if unknown_hint_keys:
        return False, f"unknown_environment_hint:{unknown_hint_keys[0]}"
    for key, value in environment_hints.items():
        if value is None:
            continue
        if not _is_non_empty_string(value) or len(str(value).strip()) > 64:
            return False, f"invalid_environment_hint_{key}"

    if "provider_intelligence" in data:
        provider_intelligence = data.get("provider_intelligence")
        if not isinstance(provider_intelligence, list):
            return False, "invalid_provider_intelligence"
        for item in provider_intelligence:
            if not isinstance(item, dict):
                return False, "invalid_provider_intelligence_entry"
            unknown_provider_keys = sorted(set(item.keys()) - _PROVIDER_INTELLIGENCE_ALLOWED_KEYS)
            if unknown_provider_keys:
                return False, f"unknown_provider_intelligence_field:{unknown_provider_keys[0]}"
            provider = str(item.get("provider") or "").strip()
            if not provider:
                return False, "invalid_provider_intelligence_provider"
            if provider not in set(supported_providers):
                return False, "provider_intelligence_provider_not_supported"
            available_models = item.get("available_models", [])
            if not isinstance(available_models, list):
                return False, "invalid_provider_intelligence_available_models"
            for model in available_models:
                if not isinstance(model, dict):
                    return False, "invalid_provider_intelligence_model"
                unknown_model_keys = sorted(set(model.keys()) - _PROVIDER_MODEL_ALLOWED_KEYS)
                if unknown_model_keys:
                    return False, f"unknown_provider_model_field:{unknown_model_keys[0]}"
                if not _is_non_empty_string(model.get("model_id")):
                    return False, "invalid_provider_intelligence_model_id"
                for field in ("pricing", "latency_metrics"):
                    if field not in model:
                        continue
                    value = model.get(field)
                    if not isinstance(value, dict):
                        return False, f"invalid_provider_intelligence_{field}"
                    for key, metric in value.items():
                        if not _is_non_empty_string(key):
                            return False, f"invalid_provider_intelligence_{field}_key"
                        if not isinstance(metric, (int, float)) or isinstance(metric, bool) or metric < 0:
                            return False, f"invalid_provider_intelligence_{field}_value"

    return True, None
