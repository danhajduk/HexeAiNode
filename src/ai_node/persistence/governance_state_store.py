import json
from pathlib import Path
from typing import Optional, Tuple


GOVERNANCE_STATE_SCHEMA_VERSION = "1.0"

REQUIRED_FIELDS = (
    "schema_version",
    "policy_version",
    "issued_timestamp",
    "synced_at",
    "refresh_expectations",
    "generic_node_class_rules",
    "feature_gating_defaults",
    "telemetry_expectations",
)


def _is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_governance_state(data: object) -> Tuple[bool, Optional[str]]:
    if not isinstance(data, dict):
        return False, "invalid_governance_state_object"
    for key in REQUIRED_FIELDS:
        if key not in data:
            return False, f"missing_{key}"
    if str(data.get("schema_version")).strip() != GOVERNANCE_STATE_SCHEMA_VERSION:
        return False, "invalid_schema_version"
    if not _is_non_empty_string(data.get("policy_version")):
        return False, "invalid_policy_version"
    if not _is_non_empty_string(data.get("issued_timestamp")):
        return False, "invalid_issued_timestamp"
    if not _is_non_empty_string(data.get("synced_at")):
        return False, "invalid_synced_at"
    for key in (
        "refresh_expectations",
        "generic_node_class_rules",
        "feature_gating_defaults",
        "telemetry_expectations",
    ):
        if not isinstance(data.get(key), dict):
            return False, f"invalid_{key}"
    if data.get("raw_response") is not None and not isinstance(data.get("raw_response"), dict):
        return False, "invalid_raw_response"
    return True, None


class GovernanceStateStore:
    def __init__(self, *, path: str, logger) -> None:
        self._path = Path(path)
        self._logger = logger

    def save(self, payload: dict) -> None:
        is_valid, error = validate_governance_state(payload)
        if not is_valid:
            raise ValueError(f"cannot save invalid governance state: {error}")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._path.with_suffix(f"{self._path.suffix}.tmp")
        temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        temp_path.replace(self._path)
        if hasattr(self._logger, "info"):
            self._logger.info("[governance-state-saved] %s", {"path": str(self._path)})

    def load(self) -> Optional[dict]:
        if not self._path.exists():
            return None
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            if hasattr(self._logger, "warning"):
                self._logger.warning("[governance-state-invalid] %s", {"path": str(self._path), "reason": "invalid_json"})
            return None
        is_valid, error = validate_governance_state(payload)
        if not is_valid:
            if hasattr(self._logger, "warning"):
                self._logger.warning("[governance-state-invalid] %s", {"path": str(self._path), "reason": error})
            return None
        if hasattr(self._logger, "info"):
            self._logger.info("[governance-state-loaded] %s", {"path": str(self._path)})
        return payload
