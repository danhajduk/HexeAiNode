"""Capability manifest helpers."""

from importlib import import_module

from ai_node.capabilities.manifest_schema import (
    CAPABILITY_MANIFEST_SCHEMA_VERSION,
    create_capability_manifest,
    validate_capability_manifest,
)
from ai_node.capabilities.task_families import (
    CANONICAL_TASK_FAMILIES,
    create_declared_task_family_capabilities,
    validate_task_family_capabilities,
)
from ai_node.capabilities.providers import (
    DEFAULT_SUPPORTED_PROVIDERS,
    create_provider_capabilities,
    create_provider_capabilities_from_selection_config,
    validate_provider_capabilities,
)
from ai_node.capabilities.node_features import (
    CANONICAL_NODE_FEATURES,
    create_node_feature_declarations,
    validate_node_feature_declarations,
)
from ai_node.capabilities.environment_hints import (
    VALID_MEMORY_CLASSES,
    collect_environment_hints,
    validate_environment_hints,
)

__all__ = [
    "CAPABILITY_MANIFEST_SCHEMA_VERSION",
    "create_capability_manifest",
    "validate_capability_manifest",
    "CANONICAL_TASK_FAMILIES",
    "create_declared_task_family_capabilities",
    "validate_task_family_capabilities",
    "DEFAULT_SUPPORTED_PROVIDERS",
    "create_provider_capabilities",
    "create_provider_capabilities_from_selection_config",
    "validate_provider_capabilities",
    "CANONICAL_NODE_FEATURES",
    "create_node_feature_declarations",
    "validate_node_feature_declarations",
    "VALID_MEMORY_CLASSES",
    "collect_environment_hints",
    "validate_environment_hints",
    "PROVIDER_INTELLIGENCE_SCHEMA_VERSION",
    "DEFAULT_PROVIDER_CAPABILITY_REFRESH_INTERVAL_SECONDS",
    "ProviderIntelligenceService",
    "compact_provider_intelligence_report",
]


_LAZY_PROVIDER_INTELLIGENCE_EXPORTS = {
    "DEFAULT_PROVIDER_CAPABILITY_REFRESH_INTERVAL_SECONDS",
    "PROVIDER_INTELLIGENCE_SCHEMA_VERSION",
    "ProviderIntelligenceService",
    "compact_provider_intelligence_report",
}


def __getattr__(name: str):
    if name in _LAZY_PROVIDER_INTELLIGENCE_EXPORTS:
        module = import_module("ai_node.capabilities.provider_intelligence")
        value = getattr(module, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
