from copy import deepcopy

from ai_node.capabilities.task_families import CANONICAL_TASK_FAMILIES
from ai_node.time_utils import local_now_iso


VALID_PROMPT_LIFECYCLE_STATES = {"probation", "active", "restricted", "suspended", "retired", "expired"}
LEGACY_PROMPT_STATES = {"registered": "active", "probation": "probation"}
VALID_PROMPT_PRIVACY_CLASSES = {"public", "internal", "restricted", "sensitive"}


def _now_iso() -> str:
    return local_now_iso()


def _non_empty(value: object, *, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} is required")
    return text


def _optional_string(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _normalize_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def _normalize_mapping(value: object) -> dict:
    return deepcopy(value) if isinstance(value, dict) else {}


def normalize_prompt_lifecycle_state(value: object) -> str:
    state = str(value or "").strip().lower()
    if state in LEGACY_PROMPT_STATES:
        return LEGACY_PROMPT_STATES[state]
    if state not in VALID_PROMPT_LIFECYCLE_STATES:
        raise ValueError("invalid_prompt_state")
    return state


def normalize_prompt_privacy_class(value: object) -> str:
    privacy = str(value or "internal").strip().lower()
    if privacy not in VALID_PROMPT_PRIVACY_CLASSES:
        raise ValueError("invalid_privacy_class")
    return privacy


def normalize_execution_policy(value: object) -> dict:
    payload = _normalize_mapping(value)
    return {
        "allow_direct_execution": bool(payload.get("allow_direct_execution", True)),
        "allow_version_pinning": bool(payload.get("allow_version_pinning", True)),
    }


def normalize_prompt_constraints(value: object) -> dict:
    payload = _normalize_mapping(value)
    max_timeout_s = payload.get("max_timeout_s")
    allowed_model_overrides = _normalize_string_list(payload.get("allowed_model_overrides"))
    return {
        "max_timeout_s": max(int(max_timeout_s), 1) if max_timeout_s is not None else None,
        "structured_output_required": bool(payload.get("structured_output_required", False)),
        "allowed_model_overrides": allowed_model_overrides,
    }


def normalize_provider_preferences(value: object) -> dict:
    payload = _normalize_mapping(value)
    preferred_providers = [item.lower() for item in _normalize_string_list(payload.get("preferred_providers"))]
    preferred_models = [item.lower() for item in _normalize_string_list(payload.get("preferred_models"))]
    default_provider = _optional_string(payload.get("default_provider"))
    default_model = _optional_string(payload.get("default_model"))
    return {
        "preferred_providers": preferred_providers,
        "preferred_models": preferred_models,
        "default_provider": default_provider.lower() if default_provider else None,
        "default_model": default_model.lower() if default_model else None,
    }


def normalize_prompt_definition(value: object) -> dict:
    payload = _normalize_mapping(value)
    return {
        "system_prompt": _optional_string(payload.get("system_prompt")),
        "prompt_template": _optional_string(payload.get("prompt_template")),
        "template_variables": _normalize_string_list(payload.get("template_variables")),
        "default_inputs": _normalize_mapping(payload.get("default_inputs")),
    }


def build_prompt_version(
    *,
    version: str,
    definition: dict | None = None,
    metadata: dict | None = None,
    created_at: str | None = None,
) -> dict:
    return {
        "version": _non_empty(version, name="version"),
        "definition": normalize_prompt_definition(definition),
        "metadata": _normalize_mapping(metadata),
        "created_at": _optional_string(created_at) or _now_iso(),
    }


def next_prompt_version(existing_versions: list[dict] | None) -> str:
    max_version = 0
    for entry in list(existing_versions or []):
        if not isinstance(entry, dict):
            continue
        version = str(entry.get("version") or "").strip().lower()
        if version.startswith("v") and version[1:].isdigit():
            max_version = max(max_version, int(version[1:]))
    return f"v{max_version + 1}"


def create_prompt_service_registration(
    *,
    prompt_id: str,
    service_id: str,
    task_family: str,
    metadata: dict | None = None,
    prompt_name: str | None = None,
    owner_service: str | None = None,
    privacy_class: str = "internal",
    execution_policy: dict | None = None,
    provider_preferences: dict | None = None,
    constraints: dict | None = None,
    definition: dict | None = None,
    version: str | None = None,
    status: str = "active",
) -> dict:
    prompt = _non_empty(prompt_id, name="prompt_id")
    service = _non_empty(service_id, name="service_id")
    task = _non_empty(task_family, name="task_family")
    if task not in set(CANONICAL_TASK_FAMILIES):
        raise ValueError("unsupported task_family")
    version_value = _optional_string(version) or "v1"
    now = _now_iso()
    lifecycle_state = normalize_prompt_lifecycle_state(status)
    version_entry = build_prompt_version(version=version_value, definition=definition, metadata=metadata, created_at=now)
    return {
        "prompt_id": prompt,
        "prompt_name": _optional_string(prompt_name) or prompt,
        "service_id": service,
        "owner_service": _optional_string(owner_service) or service,
        "task_family": task,
        "status": lifecycle_state,
        "privacy_class": normalize_prompt_privacy_class(privacy_class),
        "execution_policy": normalize_execution_policy(execution_policy),
        "provider_preferences": normalize_provider_preferences(provider_preferences),
        "constraints": normalize_prompt_constraints(constraints),
        "metadata": _normalize_mapping(metadata),
        "current_version": version_value,
        "versions": [version_entry],
        "lifecycle_history": [
            {
                "state": lifecycle_state,
                "reason": "created",
                "changed_at": now,
            }
        ],
        "usage": {
            "execution_count": 0,
            "success_count": 0,
            "failure_count": 0,
            "denial_count": 0,
            "last_used_at": None,
            "last_denial_reason": None,
            "last_denied_at": None,
            "last_failure_reason": None,
            "last_failure_at": None,
            "last_execution_status": None,
        },
        "registered_at": now,
        "updated_at": now,
        "retired_at": None,
    }


def update_prompt_service_definition(
    entry: dict,
    *,
    prompt_name: str | None = None,
    owner_service: str | None = None,
    task_family: str | None = None,
    privacy_class: str | None = None,
    execution_policy: dict | None = None,
    provider_preferences: dict | None = None,
    constraints: dict | None = None,
    metadata: dict | None = None,
    definition: dict | None = None,
    version: str | None = None,
) -> dict:
    if not isinstance(entry, dict):
        raise ValueError("entry is required")
    if task_family is not None:
        normalized_task_family = _non_empty(task_family, name="task_family")
        if normalized_task_family not in set(CANONICAL_TASK_FAMILIES):
            raise ValueError("unsupported task_family")
        entry["task_family"] = normalized_task_family
    if prompt_name is not None:
        entry["prompt_name"] = _non_empty(prompt_name, name="prompt_name")
    if owner_service is not None:
        entry["owner_service"] = _non_empty(owner_service, name="owner_service")
    if privacy_class is not None:
        entry["privacy_class"] = normalize_prompt_privacy_class(privacy_class)
    if execution_policy is not None:
        entry["execution_policy"] = normalize_execution_policy(execution_policy)
    if provider_preferences is not None:
        entry["provider_preferences"] = normalize_provider_preferences(provider_preferences)
    if constraints is not None:
        entry["constraints"] = normalize_prompt_constraints(constraints)
    if metadata is not None:
        entry["metadata"] = _normalize_mapping(metadata)
    if definition is not None or version is not None:
        versions = entry.get("versions")
        if not isinstance(versions, list):
            versions = []
            entry["versions"] = versions
        version_value = _optional_string(version) or next_prompt_version(versions)
        if any(str(item.get("version") or "").strip() == version_value for item in versions if isinstance(item, dict)):
            raise ValueError("duplicate_prompt_version")
        versions.append(
            build_prompt_version(
                version=version_value,
                definition=definition,
                metadata=metadata if metadata is not None else entry.get("metadata"),
            )
        )
        entry["current_version"] = version_value
    entry["updated_at"] = _now_iso()
    return entry


def transition_prompt_lifecycle(*, entry: dict, state: str, reason: str | None = None) -> dict:
    if not isinstance(entry, dict):
        raise ValueError("entry is required")
    current_state = normalize_prompt_lifecycle_state(entry.get("status") or "active")
    next_state = normalize_prompt_lifecycle_state(state)
    if current_state == next_state:
        return entry
    now = _now_iso()
    entry["status"] = next_state
    entry["updated_at"] = now
    if next_state == "retired":
        entry["retired_at"] = now
    history = entry.get("lifecycle_history")
    if not isinstance(history, list):
        history = []
        entry["lifecycle_history"] = history
    history.append({"state": next_state, "reason": _optional_string(reason) or "manual_transition", "changed_at": now})
    return entry


def apply_probation_transition(*, entry: dict, action: str, reason: str | None = None) -> dict:
    action_value = str(action or "").strip().lower()
    if action_value == "start":
        return transition_prompt_lifecycle(entry=entry, state="probation", reason=reason or "probation_started")
    if action_value == "clear":
        return transition_prompt_lifecycle(entry=entry, state="active", reason=reason or "probation_cleared")
    raise ValueError("unsupported probation action")


def find_prompt_entry(*, prompt_services_state: dict | None, prompt_id: str) -> dict | None:
    entries = prompt_services_state.get("prompt_services") if isinstance(prompt_services_state, dict) else []
    prompt_value = str(prompt_id or "").strip()
    if not isinstance(entries, list) or not prompt_value:
        return None
    for entry in entries:
        if isinstance(entry, dict) and str(entry.get("prompt_id") or "").strip() == prompt_value:
            return entry
    return None


def find_prompt_version(entry: dict, version: str | None = None) -> dict | None:
    versions = entry.get("versions")
    if not isinstance(versions, list) or not versions:
        fallback_version = _optional_string(version) or _optional_string(entry.get("current_version")) or "v1"
        return {
            "version": fallback_version,
            "definition": {},
            "metadata": _normalize_mapping(entry.get("metadata")),
            "created_at": _optional_string(entry.get("registered_at")) or _now_iso(),
        }
    target_version = _optional_string(version) or _optional_string(entry.get("current_version"))
    if target_version is None:
        return None
    for item in versions:
        if isinstance(item, dict) and str(item.get("version") or "").strip() == target_version:
            return item
    return None
