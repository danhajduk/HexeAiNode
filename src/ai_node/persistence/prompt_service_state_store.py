import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

from ai_node.prompts.registration import (
    apply_probation_transition,
    create_prompt_service_registration,
    find_prompt_entry,
    normalize_execution_policy,
    normalize_prompt_constraints,
    normalize_prompt_lifecycle_state,
    normalize_prompt_privacy_class,
    normalize_provider_preferences,
)


PROMPT_SERVICE_STATE_SCHEMA_VERSION = "2.0"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _normalize_usage(value: object) -> dict:
    payload = deepcopy(value) if isinstance(value, dict) else {}
    return {
        "execution_count": max(int(payload.get("execution_count") or 0), 0),
        "success_count": max(int(payload.get("success_count") or 0), 0),
        "failure_count": max(int(payload.get("failure_count") or 0), 0),
        "denial_count": max(int(payload.get("denial_count") or 0), 0),
        "last_used_at": payload.get("last_used_at"),
        "last_denial_reason": payload.get("last_denial_reason"),
        "last_denied_at": payload.get("last_denied_at"),
        "last_failure_reason": payload.get("last_failure_reason"),
        "last_failure_at": payload.get("last_failure_at"),
        "last_execution_status": payload.get("last_execution_status"),
    }


def _normalize_versions(entry: dict, fallback_metadata: dict | None = None) -> list[dict]:
    versions = entry.get("versions")
    if not isinstance(versions, list) or not versions:
        current_version = str(entry.get("current_version") or entry.get("version") or "v1").strip() or "v1"
        return [
            {
                "version": current_version,
                "definition": {
                    "system_prompt": None,
                    "prompt_template": None,
                    "template_variables": [],
                    "default_inputs": {},
                },
                "metadata": deepcopy(fallback_metadata if isinstance(fallback_metadata, dict) else entry.get("metadata") or {}),
                "created_at": str(entry.get("registered_at") or entry.get("updated_at") or _now_iso()),
            }
        ]
    normalized: list[dict] = []
    for version_entry in versions:
        if not isinstance(version_entry, dict):
            continue
        version_value = str(version_entry.get("version") or "").strip()
        if not version_value:
            continue
        definition = version_entry.get("definition") if isinstance(version_entry.get("definition"), dict) else {}
        normalized.append(
            {
                "version": version_value,
                "definition": {
                    "system_prompt": definition.get("system_prompt"),
                    "prompt_template": definition.get("prompt_template"),
                    "template_variables": list(definition.get("template_variables") or []),
                    "default_inputs": deepcopy(definition.get("default_inputs") or {}),
                },
                "metadata": deepcopy(version_entry.get("metadata") if isinstance(version_entry.get("metadata"), dict) else {}),
                "created_at": str(version_entry.get("created_at") or entry.get("updated_at") or _now_iso()),
            }
        )
    return normalized


def _normalize_entry(entry: dict) -> dict:
    if not isinstance(entry, dict):
        raise ValueError("invalid_prompt_service_entry")
    if str(entry.get("schema_version") or "").strip() == "1.0" and _is_non_empty_string(entry.get("prompt_id")):
        entry = create_prompt_service_registration(
            prompt_id=str(entry.get("prompt_id")),
            service_id=str(entry.get("service_id")),
            task_family=str(entry.get("task_family")),
            metadata=entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {},
            status=str(entry.get("status") or "active"),
        )
    prompt_id = str(entry.get("prompt_id") or "").strip()
    service_id = str(entry.get("service_id") or "").strip()
    task_family = str(entry.get("task_family") or "").strip()
    if not prompt_id or not service_id or not task_family:
        raise ValueError("invalid_prompt_service_entry")
    normalized = deepcopy(entry)
    normalized["prompt_id"] = prompt_id
    normalized["prompt_name"] = str(entry.get("prompt_name") or prompt_id).strip() or prompt_id
    normalized["service_id"] = service_id
    normalized["owner_service"] = str(entry.get("owner_service") or service_id).strip() or service_id
    normalized["task_family"] = task_family
    normalized["status"] = normalize_prompt_lifecycle_state(entry.get("status") or "active")
    normalized["privacy_class"] = normalize_prompt_privacy_class(entry.get("privacy_class") or "internal")
    normalized["execution_policy"] = normalize_execution_policy(entry.get("execution_policy"))
    normalized["provider_preferences"] = normalize_provider_preferences(entry.get("provider_preferences"))
    normalized["constraints"] = normalize_prompt_constraints(entry.get("constraints"))
    normalized["metadata"] = deepcopy(entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {})
    normalized["versions"] = _normalize_versions(entry, fallback_metadata=normalized["metadata"])
    current_version = str(entry.get("current_version") or "").strip()
    normalized["current_version"] = current_version or str(normalized["versions"][-1]["version"])
    normalized["registered_at"] = str(entry.get("registered_at") or entry.get("updated_at") or _now_iso())
    normalized["updated_at"] = str(entry.get("updated_at") or normalized["registered_at"])
    normalized["retired_at"] = entry.get("retired_at")
    lifecycle_history = entry.get("lifecycle_history")
    if not isinstance(lifecycle_history, list) or not lifecycle_history:
        lifecycle_history = [{"state": normalized["status"], "reason": "migrated", "changed_at": normalized["updated_at"]}]
    normalized["lifecycle_history"] = lifecycle_history
    normalized["usage"] = _normalize_usage(entry.get("usage"))
    return normalized


def _rebuild_probation_index(payload: dict) -> dict:
    active_prompt_ids: list[str] = []
    reasons: dict[str, str] = {}
    for entry in payload.get("prompt_services") or []:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("status") or "").strip().lower() != "probation":
            continue
        prompt_id = str(entry.get("prompt_id") or "").strip()
        if not prompt_id:
            continue
        active_prompt_ids.append(prompt_id)
        history = entry.get("lifecycle_history") if isinstance(entry.get("lifecycle_history"), list) else []
        if history:
            latest = history[-1]
            reason = str(latest.get("reason") or "").strip()
            if reason:
                reasons[prompt_id] = reason
    payload["probation"] = {
        "active_prompt_ids": sorted(set(active_prompt_ids)),
        "reasons": reasons,
        "updated_at": _now_iso(),
    }
    return payload


def create_prompt_service_state() -> dict:
    payload = {
        "schema_version": PROMPT_SERVICE_STATE_SCHEMA_VERSION,
        "prompt_services": [],
        "probation": {
            "active_prompt_ids": [],
            "reasons": {},
            "updated_at": _now_iso(),
        },
        "updated_at": _now_iso(),
    }
    return payload


def normalize_prompt_service_state(data: object) -> dict:
    if not isinstance(data, dict):
        raise ValueError("invalid_prompt_service_state_object")
    schema_version = str(data.get("schema_version") or "").strip()
    payload = deepcopy(data)
    if schema_version not in {"1.0", PROMPT_SERVICE_STATE_SCHEMA_VERSION}:
        raise ValueError("invalid_schema_version")
    entries = payload.get("prompt_services")
    if not isinstance(entries, list):
        raise ValueError("invalid_prompt_services")
    normalized_entries = [_normalize_entry(entry) for entry in entries]
    normalized = {
        "schema_version": PROMPT_SERVICE_STATE_SCHEMA_VERSION,
        "prompt_services": normalized_entries,
        "probation": {
            "active_prompt_ids": [],
            "reasons": {},
            "updated_at": _now_iso(),
        },
        "updated_at": str(payload.get("updated_at") or _now_iso()),
    }
    return _rebuild_probation_index(normalized)


def validate_prompt_service_state(data: object) -> Tuple[bool, Optional[str]]:
    try:
        normalize_prompt_service_state(data)
    except ValueError as exc:
        return False, str(exc)
    return True, None


class PromptServiceStateStore:
    def __init__(self, *, path: str, logger) -> None:
        self._path = Path(path)
        self._logger = logger

    def save(self, payload: dict) -> None:
        try:
            normalized = normalize_prompt_service_state(payload)
        except ValueError as exc:
            raise ValueError(f"cannot save invalid prompt service state: {exc}") from exc
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._path.with_suffix(f"{self._path.suffix}.tmp")
        temp_path.write_text(json.dumps(normalized, indent=2, sort_keys=True), encoding="utf-8")
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
        try:
            normalized = normalize_prompt_service_state(payload)
        except ValueError as exc:
            if hasattr(self._logger, "warning"):
                self._logger.warning(
                    "[prompt-service-state-invalid] %s",
                    {"path": str(self._path), "reason": str(exc)},
                )
            return None
        return normalized

    def load_or_create(self) -> dict:
        payload = self.load()
        if isinstance(payload, dict):
            return payload
        created = create_prompt_service_state()
        self.save(created)
        return created
