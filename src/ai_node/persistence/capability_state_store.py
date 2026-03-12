import json
from pathlib import Path
from typing import Optional, Tuple


CAPABILITY_STATE_SCHEMA_VERSION = "1.0"

REQUIRED_FIELDS = (
    "schema_version",
    "accepted_declaration_version",
    "acceptance_timestamp",
)


def _is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_capability_state(data: object) -> Tuple[bool, Optional[str]]:
    if not isinstance(data, dict):
        return False, "invalid_capability_state_object"
    for key in REQUIRED_FIELDS:
        if key not in data:
            return False, f"missing_{key}"
    if str(data.get("schema_version")).strip() != CAPABILITY_STATE_SCHEMA_VERSION:
        return False, "invalid_schema_version"
    if not _is_non_empty_string(data.get("accepted_declaration_version")):
        return False, "invalid_accepted_declaration_version"
    if not _is_non_empty_string(data.get("acceptance_timestamp")):
        return False, "invalid_acceptance_timestamp"
    if data.get("core_restrictions") is not None and not isinstance(data.get("core_restrictions"), (dict, list)):
        return False, "invalid_core_restrictions"
    if data.get("raw_response") is not None and not isinstance(data.get("raw_response"), dict):
        return False, "invalid_raw_response"
    return True, None


class CapabilityStateStore:
    def __init__(self, *, path: str, logger) -> None:
        self._path = Path(path)
        self._logger = logger

    def save(self, payload: dict) -> None:
        is_valid, error = validate_capability_state(payload)
        if not is_valid:
            raise ValueError(f"cannot save invalid capability state: {error}")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._path.with_suffix(f"{self._path.suffix}.tmp")
        temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        temp_path.replace(self._path)
        if hasattr(self._logger, "info"):
            self._logger.info("[capability-state-saved] %s", {"path": str(self._path)})

    def load(self) -> Optional[dict]:
        if not self._path.exists():
            return None
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            if hasattr(self._logger, "warning"):
                self._logger.warning("[capability-state-invalid] %s", {"path": str(self._path), "reason": "invalid_json"})
            return None
        is_valid, error = validate_capability_state(payload)
        if not is_valid:
            if hasattr(self._logger, "warning"):
                self._logger.warning("[capability-state-invalid] %s", {"path": str(self._path), "reason": error})
            return None
        if hasattr(self._logger, "info"):
            self._logger.info("[capability-state-loaded] %s", {"path": str(self._path)})
        return payload
