from datetime import datetime, timezone
from typing import Optional, Tuple

from ai_node.capabilities.node_features import (
    create_node_feature_declarations,
    validate_node_feature_declarations,
)
from ai_node.capabilities.providers import validate_provider_capabilities
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
    task_families: list[str] | None = None,
    supported_providers: list[str] | None = None,
    enabled_providers: list[str] | None = None,
    node_features: list[str] | None = None,
    environment_hints: dict | None = None,
    manifest_version: str = CAPABILITY_MANIFEST_SCHEMA_VERSION,
    metadata: dict | None = None,
) -> dict:
    manifest = {
        "manifest_version": str(manifest_version).strip(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "node_id": str(node_id).strip(),
        "node_name": str(node_name).strip(),
        "capabilities": {
            "task_families": _normalize_string_list(task_families or []),
            "providers": {
                "supported": _normalize_string_list(supported_providers or []),
                "enabled": _normalize_string_list(enabled_providers or []),
            },
            "node_features": create_node_feature_declarations(node_features),
            "environment_hints": environment_hints if isinstance(environment_hints, dict) else {},
        },
        "metadata": {
            "schema_version": CAPABILITY_MANIFEST_SCHEMA_VERSION,
            **(metadata if isinstance(metadata, dict) else {}),
        },
    }
    is_valid, error = validate_capability_manifest(manifest)
    if not is_valid:
        raise ValueError(f"invalid capability manifest: {error}")
    return manifest


def validate_capability_manifest(data: object) -> Tuple[bool, Optional[str]]:
    if not isinstance(data, dict):
        return False, "invalid_manifest_object"
    if not _is_non_empty_string(data.get("manifest_version")):
        return False, "invalid_manifest_version"
    if not _is_non_empty_string(data.get("generated_at")):
        return False, "invalid_generated_at"
    if not _is_non_empty_string(data.get("node_id")):
        return False, "invalid_node_id"
    if not _is_non_empty_string(data.get("node_name")):
        return False, "invalid_node_name"

    capabilities = data.get("capabilities")
    if not isinstance(capabilities, dict):
        return False, "invalid_capabilities"

    task_families = capabilities.get("task_families")
    providers = capabilities.get("providers")
    node_features = capabilities.get("node_features")
    environment_hints = capabilities.get("environment_hints")

    if not isinstance(task_families, list):
        return False, "invalid_task_families"
    task_family_valid, task_family_error = validate_task_family_capabilities(task_families)
    if not task_family_valid:
        return False, task_family_error
    if not isinstance(providers, dict):
        return False, "invalid_providers"
    providers_valid, providers_error = validate_provider_capabilities(providers)
    if not providers_valid:
        return False, providers_error
    if not isinstance(node_features, list):
        return False, "invalid_node_features"
    features_valid, features_error = validate_node_feature_declarations(node_features)
    if not features_valid:
        return False, features_error
    if not isinstance(environment_hints, dict):
        return False, "invalid_environment_hints"

    metadata = data.get("metadata")
    if not isinstance(metadata, dict):
        return False, "invalid_metadata"
    if str(metadata.get("schema_version", "")).strip() != CAPABILITY_MANIFEST_SCHEMA_VERSION:
        return False, "invalid_schema_version"

    return True, None
