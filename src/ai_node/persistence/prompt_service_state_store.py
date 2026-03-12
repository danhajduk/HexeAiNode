import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple


PROMPT_SERVICE_STATE_SCHEMA_VERSION = "1.0"
VALID_PROMPT_SERVICE_STATUS = {"registered", "probation"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def create_prompt_service_state() -> dict:
    return {
        "schema_version": PROMPT_SERVICE_STATE_SCHEMA_VERSION,
        "prompt_services": [],
        "probation": {
            "active_prompt_ids": [],
            "reasons": {},
            "updated_at": _now_iso(),
        },
        "updated_at": _now_iso(),
    }


def validate_prompt_service_state(data: object) -> Tuple[bool, Optional[str]]:
    if not isinstance(data, dict):
        return False, "invalid_prompt_service_state_object"
    if str(data.get("schema_version") or "").strip() != PROMPT_SERVICE_STATE_SCHEMA_VERSION:
        return False, "invalid_schema_version"

    prompt_services = data.get("prompt_services")
    if not isinstance(prompt_services, list):
        return False, "invalid_prompt_services"
    for index, item in enumerate(prompt_services):
        if not isinstance(item, dict):
            return False, f"invalid_prompt_service_entry:{index}"
        for key in ("prompt_id", "service_id", "task_family", "status", "registered_at", "updated_at"):
            if not _is_non_empty_string(item.get(key)):
                return False, f"invalid_prompt_service_{key}:{index}"
        if item.get("status") not in VALID_PROMPT_SERVICE_STATUS:
            return False, f"invalid_prompt_service_status:{index}"
        if item.get("metadata") is not None and not isinstance(item.get("metadata"), dict):
            return False, f"invalid_prompt_service_metadata:{index}"

    probation = data.get("probation")
    if not isinstance(probation, dict):
        return False, "invalid_probation"
    active_prompt_ids = probation.get("active_prompt_ids")
    if not isinstance(active_prompt_ids, list):
        return False, "invalid_probation_active_prompt_ids"
    if any(not _is_non_empty_string(item) for item in active_prompt_ids):
        return False, "invalid_probation_active_prompt_id"
    reasons = probation.get("reasons")
    if not isinstance(reasons, dict):
        return False, "invalid_probation_reasons"
    for key, value in reasons.items():
        if not _is_non_empty_string(key) or not _is_non_empty_string(value):
            return False, "invalid_probation_reason_entry"
    if not _is_non_empty_string(probation.get("updated_at")):
        return False, "invalid_probation_updated_at"

    if not _is_non_empty_string(data.get("updated_at")):
        return False, "invalid_updated_at"

    return True, None


class PromptServiceStateStore:
    def __init__(self, *, path: str, logger) -> None:
        self._path = Path(path)
        self._logger = logger

    def save(self, payload: dict) -> None:
        is_valid, error = validate_prompt_service_state(payload)
        if not is_valid:
            raise ValueError(f"cannot save invalid prompt service state: {error}")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._path.with_suffix(f"{self._path.suffix}.tmp")
        temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        temp_path.replace(self._path)
        if hasattr(self._logger, "info"):
            self._logger.info("[prompt-service-state-saved] %s", {"path": str(self._path)})

    def load(self) -> Optional[dict]:
        if not self._path.exists():
            return None
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            if hasattr(self._logger, "warning"):
                self._logger.warning(
                    "[prompt-service-state-invalid] %s",
                    {"path": str(self._path), "reason": "invalid_json"},
                )
            return None
        is_valid, error = validate_prompt_service_state(payload)
        if not is_valid:
            if hasattr(self._logger, "warning"):
                self._logger.warning(
                    "[prompt-service-state-invalid] %s",
                    {"path": str(self._path), "reason": error},
                )
            return None
        return payload

    def load_or_create(self) -> dict:
        payload = self.load()
        if isinstance(payload, dict):
            return payload
        created = create_prompt_service_state()
        self.save(created)
        return created
