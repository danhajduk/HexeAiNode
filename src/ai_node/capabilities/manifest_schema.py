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
    manifest_version: str = CAPABILITY_MANIFEST_SCHEMA_VERSION,
    metadata: dict | None = None,
) -> dict:
    resolved_environment_hints = (
        environment_hints if isinstance(environment_hints, dict) else collect_environment_hints()
    )
    feature_declarations = create_node_feature_declarations(node_features)
    feature_map = {str(item.get("name")): bool(item.get("enabled")) for item in feature_declarations if isinstance(item, dict)}
    manifest = {
        "manifest_version": str(manifest_version).strip(),
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
        "environment_hints": {
            "deployment_target": "edge",
            "acceleration": "gpu" if bool(resolved_environment_hints.get("gpu_present")) else "cpu",
            "network_tier": "lan",
            "region": "local",
        },
    }
    if feature_map.get(PROMPT_GOVERNANCE_READY, False):
        manifest["node_features"]["governance_refresh"] = True
    is_valid, error = validate_capability_manifest(manifest)
    if not is_valid:
        raise ValueError(f"invalid capability manifest: {error}")
    return manifest


def validate_capability_manifest(data: object) -> Tuple[bool, Optional[str]]:
    if not isinstance(data, dict):
        return False, "invalid_manifest_object"
    if not _is_non_empty_string(data.get("manifest_version")):
        return False, "invalid_manifest_version"

    node = data.get("node")
    if not isinstance(node, dict):
        return False, "invalid_node"
    if not _is_non_empty_string(node.get("node_id")):
        return False, "invalid_node_id"
    if not _is_non_empty_string(node.get("node_type")):
        return False, "invalid_node_type"
    if not _is_non_empty_string(node.get("node_name")):
        return False, "invalid_node_name"
    if not _is_non_empty_string(node.get("node_software_version")):
        return False, "invalid_node_software_version"

    task_families = data.get("declared_task_families")
    if not isinstance(task_families, list):
        return False, "invalid_declared_task_families"
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
    for key in ("telemetry", "governance_refresh", "lifecycle_events", "provider_failover"):
        if key not in node_features or not isinstance(node_features.get(key), bool):
            return False, f"invalid_node_feature_{key}"

    environment_hints = data.get("environment_hints")
    if not isinstance(environment_hints, dict):
        return False, "invalid_environment_hints"
    for key in ("deployment_target", "acceleration", "network_tier", "region"):
        if not _is_non_empty_string(environment_hints.get(key)):
            return False, f"invalid_environment_hint_{key}"

    if "metadata" in data:
        return False, "metadata_not_allowed"

    return True, None
