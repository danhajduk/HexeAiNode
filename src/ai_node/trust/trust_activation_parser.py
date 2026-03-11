from typing import Tuple


REQUIRED_TRUST_FIELDS = (
    "node_id",
    "paired_core_id",
    "node_trust_token",
    "initial_baseline_policy",
    "operational_mqtt_identity",
    "operational_mqtt_token",
    "operational_mqtt_host",
    "operational_mqtt_port",
)


def _is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def parse_trust_activation_payload(payload: object) -> Tuple[bool, object]:
    if not isinstance(payload, dict):
        return False, "invalid_payload"

    if payload.get("status") != "approved":
        return False, "invalid_status"

    for key in REQUIRED_TRUST_FIELDS:
        if key not in payload:
            return False, f"missing_{key}"

    if not _is_non_empty_string(payload["node_id"]):
        return False, "invalid_node_id"
    if not _is_non_empty_string(payload["paired_core_id"]):
        return False, "invalid_paired_core_id"
    if not _is_non_empty_string(payload["node_trust_token"]):
        return False, "invalid_node_trust_token"
    if not isinstance(payload["initial_baseline_policy"], dict):
        return False, "invalid_initial_baseline_policy"
    if not _is_non_empty_string(payload["operational_mqtt_identity"]):
        return False, "invalid_operational_mqtt_identity"
    if not _is_non_empty_string(payload["operational_mqtt_token"]):
        return False, "invalid_operational_mqtt_token"
    if not _is_non_empty_string(payload["operational_mqtt_host"]):
        return False, "invalid_operational_mqtt_host"

    try:
        mqtt_port = int(payload["operational_mqtt_port"])
    except Exception:
        return False, "invalid_operational_mqtt_port"
    if mqtt_port <= 0:
        return False, "invalid_operational_mqtt_port"

    return (
        True,
        {
            "node_id": payload["node_id"].strip(),
            "paired_core_id": payload["paired_core_id"].strip(),
            "node_trust_token": payload["node_trust_token"].strip(),
            "initial_baseline_policy": payload["initial_baseline_policy"],
            "operational_mqtt_identity": payload["operational_mqtt_identity"].strip(),
            "operational_mqtt_token": payload["operational_mqtt_token"].strip(),
            "operational_mqtt_host": payload["operational_mqtt_host"].strip(),
            "operational_mqtt_port": mqtt_port,
        },
    )
