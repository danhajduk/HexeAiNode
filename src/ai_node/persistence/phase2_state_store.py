import json
from pathlib import Path
from typing import Optional, Tuple

from ai_node.persistence.file_storage_lock import file_storage_lock, locked_json_temp_path


PHASE2_STATE_SCHEMA_VERSION = "1.0"


def validate_phase2_state(data: object) -> Tuple[bool, Optional[str]]:
    if not isinstance(data, dict):
        return False, "invalid_phase2_state_object"
    if str(data.get("schema_version")).strip() != PHASE2_STATE_SCHEMA_VERSION:
        return False, "invalid_schema_version"
    for key in ("enabled_provider_selection", "accepted_capability", "active_governance", "timestamps"):
        if key not in data:
            return False, f"missing_{key}"
    if not isinstance(data.get("enabled_provider_selection"), dict):
        return False, "invalid_enabled_provider_selection"
    if data.get("accepted_capability") is not None and not isinstance(data.get("accepted_capability"), dict):
        return False, "invalid_accepted_capability"
    if data.get("active_governance") is not None and not isinstance(data.get("active_governance"), dict):
        return False, "invalid_active_governance"
    if not isinstance(data.get("timestamps"), dict):
        return False, "invalid_timestamps"
    return True, None


def _migrate_legacy_payload(data: dict) -> dict:
    if str(data.get("schema_version")).strip() == PHASE2_STATE_SCHEMA_VERSION:
        return data
    migrated = {
        "schema_version": PHASE2_STATE_SCHEMA_VERSION,
        "enabled_provider_selection": data.get("provider_selection") or data.get("enabled_provider_selection") or {},
        "accepted_capability": data.get("capability_state") or data.get("accepted_capability"),
        "active_governance": data.get("governance_state") or data.get("active_governance"),
        "timestamps": data.get("timestamps") or {},
    }
    return migrated


class Phase2StateStore:
    def __init__(self, *, path: str, logger) -> None:
        self._path = Path(path)
        self._logger = logger

    def save(self, payload: dict) -> None:
        with file_storage_lock(self._path):
            is_valid, error = validate_phase2_state(payload)
            if not is_valid:
                raise ValueError(f"cannot save invalid phase2 state: {error}")
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = locked_json_temp_path(self._path)
            temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
            temp_path.replace(self._path)
        if hasattr(self._logger, "info"):
            self._logger.info("[phase2-state-saved] %s", {"path": str(self._path)})

    def load(self) -> Optional[dict]:
        if not self._path.exists():
            return None
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            if hasattr(self._logger, "warning"):
                self._logger.warning("[phase2-state-invalid] %s", {"path": str(self._path), "reason": "invalid_json"})
            return None
        if not isinstance(payload, dict):
            return None
        migrated = _migrate_legacy_payload(payload)
        is_valid, error = validate_phase2_state(migrated)
        if not is_valid:
            if hasattr(self._logger, "warning"):
                self._logger.warning("[phase2-state-invalid] %s", {"path": str(self._path), "reason": error})
            return None
        return migrated
