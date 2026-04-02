import re
import uuid


_UUID_V4_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
_NODE_UUID_RE = re.compile(r"^node-([0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})$")


def normalize_node_id(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return ""
    if _UUID_V4_RE.match(normalized):
        return f"node-{normalized}"
    if _NODE_UUID_RE.match(normalized):
        return normalized
    return normalized


def is_valid_canonical_node_id(value: object) -> bool:
    normalized = normalize_node_id(value)
    if not normalized.startswith("node-"):
        return False
    match = _NODE_UUID_RE.match(normalized)
    if not match:
        return False
    try:
        parsed = uuid.UUID(match.group(1))
    except Exception:
        return False
    return parsed.version == 4 and str(parsed) == match.group(1)


def derive_operational_mqtt_identity(value: object) -> str:
    normalized = normalize_node_id(value)
    if not normalized:
        return ""
    return f"hn_{normalized}"
