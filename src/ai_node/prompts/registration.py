from datetime import datetime, timezone

from ai_node.capabilities.task_families import CANONICAL_TASK_FAMILIES

VALID_PROMPT_SERVICE_STATUS = {"registered", "probation"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _non_empty(value: object, *, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} is required")
    return text


def create_prompt_service_registration(*, prompt_id: str, service_id: str, task_family: str, metadata: dict | None = None) -> dict:
    prompt = _non_empty(prompt_id, name="prompt_id")
    service = _non_empty(service_id, name="service_id")
    task = _non_empty(task_family, name="task_family")
    if task not in set(CANONICAL_TASK_FAMILIES):
        raise ValueError("unsupported task_family")
    now = _now_iso()
    return {
        "prompt_id": prompt,
        "service_id": service,
        "task_family": task,
        "status": "registered",
        "metadata": metadata if isinstance(metadata, dict) else {},
        "registered_at": now,
        "updated_at": now,
    }


def apply_probation_transition(*, entry: dict, action: str, reason: str | None = None) -> dict:
    if not isinstance(entry, dict):
        raise ValueError("entry is required")
    current_status = str(entry.get("status") or "").strip().lower()
    if current_status not in VALID_PROMPT_SERVICE_STATUS:
        raise ValueError("invalid current status")

    action_value = str(action or "").strip().lower()
    if action_value == "start":
        if current_status == "probation":
            return entry
        entry["status"] = "probation"
        entry["updated_at"] = _now_iso()
        if reason:
            details = entry.setdefault("metadata", {})
            if isinstance(details, dict):
                details["probation_reason"] = str(reason).strip()
        return entry

    if action_value == "clear":
        if current_status == "registered":
            return entry
        entry["status"] = "registered"
        entry["updated_at"] = _now_iso()
        return entry

    raise ValueError("unsupported probation action")
