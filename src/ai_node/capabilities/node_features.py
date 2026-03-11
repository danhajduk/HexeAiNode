from typing import Optional, Tuple


POLICY_ENFORCEMENT_SUPPORT = "policy_enforcement_support"
TELEMETRY_SUPPORT = "telemetry_support"
OPERATIONAL_MQTT_SUPPORT = "operational_mqtt_support"
CAPABILITY_DECLARATION_SUPPORT = "capability_declaration_support"
PROMPT_GOVERNANCE_READY = "prompt_governance_ready"

CANONICAL_NODE_FEATURES = (
    POLICY_ENFORCEMENT_SUPPORT,
    TELEMETRY_SUPPORT,
    OPERATIONAL_MQTT_SUPPORT,
    CAPABILITY_DECLARATION_SUPPORT,
    PROMPT_GOVERNANCE_READY,
)


def _normalize_feature_name(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def _normalize_node_feature(feature: object) -> dict | None:
    if isinstance(feature, str):
        name = _normalize_feature_name(feature)
        if not name:
            return None
        return {"name": name, "enabled": True}
    if not isinstance(feature, dict):
        return None
    name = _normalize_feature_name(feature.get("name"))
    if not name:
        return None
    enabled = bool(feature.get("enabled", False))
    return {"name": name, "enabled": enabled}


def _normalize_feature_list(value: object) -> list[dict]:
    if not isinstance(value, list):
        return []
    dedup: dict[str, dict] = {}
    for raw in value:
        normalized = _normalize_node_feature(raw)
        if normalized is None:
            continue
        dedup[normalized["name"]] = normalized
    return [dedup[name] for name in sorted(dedup.keys())]


def create_node_feature_declarations(features: list[dict] | list[str] | None = None) -> list[dict]:
    if isinstance(features, list):
        declarations = _normalize_feature_list(features)
    else:
        declarations = [
            {"name": POLICY_ENFORCEMENT_SUPPORT, "enabled": True},
            {"name": TELEMETRY_SUPPORT, "enabled": True},
            {"name": OPERATIONAL_MQTT_SUPPORT, "enabled": True},
            {"name": CAPABILITY_DECLARATION_SUPPORT, "enabled": True},
            # Reserved for future governance phase, explicitly not active yet.
            {"name": PROMPT_GOVERNANCE_READY, "enabled": False},
        ]
    is_valid, error = validate_node_feature_declarations(declarations)
    if not is_valid:
        raise ValueError(f"invalid node feature declarations: {error}")
    return declarations


def validate_node_feature_declarations(features: object) -> Tuple[bool, Optional[str]]:
    if not isinstance(features, list):
        return False, "invalid_node_features"
    normalized = _normalize_feature_list(features)
    if not normalized:
        return False, "missing_node_features"
    for feature in normalized:
        name = feature["name"]
        if name not in CANONICAL_NODE_FEATURES:
            return False, f"unknown_node_feature:{name}"
        if not isinstance(feature.get("enabled"), bool):
            return False, f"invalid_node_feature_enabled:{name}"
    return True, None
