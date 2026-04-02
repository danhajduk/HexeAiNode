import json
from pathlib import Path
from typing import Optional, Tuple

from ai_node.diagnostics.onboarding_logger import OnboardingDiagnosticsLogger
from ai_node.identity.node_ids import (
    derive_operational_mqtt_identity,
    is_valid_canonical_node_id,
    normalize_node_id,
)
from ai_node.security.redaction import redact_dict


REQUIRED_TRUST_STATE_FIELDS = (
    "node_id",
    "node_name",
    "node_type",
    "paired_core_id",
    "core_api_endpoint",
    "node_trust_token",
    "initial_baseline_policy",
    "baseline_policy_version",
    "operational_mqtt_identity",
    "operational_mqtt_token",
    "operational_mqtt_host",
    "operational_mqtt_port",
    "bootstrap_mqtt_host",
    "registration_timestamp",
)

SENSITIVE_TRUST_FIELDS = ("node_trust_token", "operational_mqtt_token")


def _is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def redact_trust_state(data: dict) -> dict:
    return redact_dict(data)


def normalize_trust_state(data: dict) -> dict:
    normalized = dict(data)
    if "node_id" in normalized:
        normalized["node_id"] = normalize_node_id(normalized.get("node_id"))
        normalized["operational_mqtt_identity"] = derive_operational_mqtt_identity(normalized.get("node_id"))
    return normalized


def validate_trust_state(data: object) -> Tuple[bool, Optional[str]]:
    if not isinstance(data, dict):
        return False, "invalid_trust_state_object"
    data = normalize_trust_state(data)

    for key in REQUIRED_TRUST_STATE_FIELDS:
        if key not in data:
            return False, f"missing_{key}"

    string_fields = (
        "node_id",
        "node_name",
        "node_type",
        "paired_core_id",
        "core_api_endpoint",
        "node_trust_token",
        "baseline_policy_version",
        "operational_mqtt_identity",
        "operational_mqtt_token",
        "operational_mqtt_host",
        "bootstrap_mqtt_host",
        "registration_timestamp",
    )
    for key in string_fields:
        if not _is_non_empty_string(data.get(key)):
            return False, f"invalid_{key}"
    if not is_valid_canonical_node_id(data.get("node_id")):
        return False, "invalid_node_id"

    if data.get("node_type") != "ai-node":
        return False, "invalid_node_type"
    if not isinstance(data.get("initial_baseline_policy"), dict):
        return False, "invalid_initial_baseline_policy"

    try:
        mqtt_port = int(data.get("operational_mqtt_port"))
    except Exception:
        return False, "invalid_operational_mqtt_port"
    if mqtt_port <= 0:
        return False, "invalid_operational_mqtt_port"

    return True, None


class TrustStateStore:
    def __init__(self, *, path: str, logger) -> None:
        self._path = Path(path)
        self._logger = logger
        self._diag = OnboardingDiagnosticsLogger(logger)

    def save(self, trust_state: dict) -> None:
        trust_state = normalize_trust_state(trust_state)
        is_valid, error = validate_trust_state(trust_state)
        if not is_valid:
            raise ValueError(f"cannot save invalid trust state: {error}")

        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._path.with_suffix(f"{self._path.suffix}.tmp")
        temp_path.write_text(json.dumps(trust_state, indent=2, sort_keys=True), encoding="utf-8")
        temp_path.replace(self._path)
        self._diag.trust_persistence({"action": "save", "path": str(self._path)})
        if hasattr(self._logger, "info"):
            self._logger.info("[trust-state-saved] %s", {"path": str(self._path)})

    def load(self) -> Optional[dict]:
        if not self._path.exists():
            return None
        try:
            raw = self._path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except Exception:
            if hasattr(self._logger, "warning"):
                self._logger.warning(
                    "[trust-state-invalid] %s",
                    {"path": str(self._path), "reason": "invalid_json"},
                )
            self._diag.trust_persistence(
                {"action": "load", "path": str(self._path), "result": "invalid", "reason": "invalid_json"}
            )
            return None

        normalized = normalize_trust_state(data)
        is_valid, error = validate_trust_state(normalized)
        if not is_valid:
            if hasattr(self._logger, "warning"):
                self._logger.warning(
                    "[trust-state-invalid] %s",
                    {"path": str(self._path), "reason": error},
                )
            self._diag.trust_persistence(
                {"action": "load", "path": str(self._path), "result": "invalid", "reason": error}
            )
            return None

        self._diag.trust_persistence({"action": "load", "path": str(self._path), "result": "valid"})
        if hasattr(self._logger, "info"):
            self._logger.info(
                "[trust-state-loaded] %s",
                {"path": str(self._path), "state": redact_trust_state(normalized)},
            )
        if normalized != data:
            self.save(normalized)
        return normalized
