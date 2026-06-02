import json
from copy import deepcopy
from pathlib import Path
from typing import Optional, Tuple

from ai_node.time_utils import local_now_iso


INTERNAL_SCHEDULER_STATE_SCHEMA_VERSION = "1.0"
MAX_LAST_RESULT_BYTES = 8192


def _now_iso() -> str:
    return local_now_iso()


def _is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _json_size(value: object) -> int:
    try:
        return len(json.dumps(value).encode("utf-8"))
    except Exception:
        return MAX_LAST_RESULT_BYTES + 1


def _summarize_provider_capability_refresh(payload: dict) -> dict:
    report = payload.get("report") if isinstance(payload.get("report"), dict) else {}
    providers = report.get("providers") if isinstance(report.get("providers"), list) else []
    provider_summary = []
    for provider in providers:
        if not isinstance(provider, dict):
            continue
        models = provider.get("models") if isinstance(provider.get("models"), list) else []
        model_count = provider.get("model_count")
        if not isinstance(model_count, int):
            model_count = len(models)
        provider_summary.append(
            {
                "provider_id": str(provider.get("provider_id") or "").strip() or None,
                "availability": str(provider.get("availability") or "").strip() or None,
                "model_count": model_count,
            }
        )

    core_submission = payload.get("core_submission") if isinstance(payload.get("core_submission"), dict) else {}
    summary = {
        "status": str(payload.get("status") or "").strip() or None,
        "changed": bool(payload.get("changed")) if payload.get("changed") is not None else None,
        "core_submission": {
            "submitted": bool(core_submission.get("submitted")) if core_submission.get("submitted") is not None else None,
            "status": str(core_submission.get("status") or "").strip() or None,
            "retryable": bool(core_submission.get("retryable")) if core_submission.get("retryable") is not None else None,
            "error": str(core_submission.get("error") or "").strip() or None,
        },
        "report": {
            "generated_at": str(report.get("generated_at") or "").strip() or None,
            "provider_count": len(providers),
            "providers": provider_summary,
        },
    }
    return summary


def _summarize_last_result(*, task_id: str, value: object) -> dict | None:
    if not isinstance(value, dict):
        return None

    result = deepcopy(value)
    if _json_size(result) <= MAX_LAST_RESULT_BYTES:
        return result

    normalized_task_id = str(task_id or "").strip()
    if normalized_task_id == "provider_capability_refresh":
        return _summarize_provider_capability_refresh(result)

    return {
        "status": str(result.get("status") or "summarized").strip() or "summarized",
        "summary": "last_result_truncated",
        "original_size_bytes": _json_size(result),
    }


def create_internal_scheduler_state() -> dict:
    return {
        "schema_version": INTERNAL_SCHEDULER_STATE_SCHEMA_VERSION,
        "scheduler_status": "idle",
        "tasks": {},
        "updated_at": _now_iso(),
    }


def normalize_internal_scheduler_state(data: object) -> dict:
    if not isinstance(data, dict):
        raise ValueError("invalid_internal_scheduler_state")
    if str(data.get("schema_version") or "").strip() != INTERNAL_SCHEDULER_STATE_SCHEMA_VERSION:
        raise ValueError("invalid_internal_scheduler_state_schema")
    tasks = data.get("tasks")
    if not isinstance(tasks, dict):
        raise ValueError("invalid_internal_scheduler_tasks")
    normalized_tasks = {}
    for task_id, entry in tasks.items():
        if not _is_non_empty_string(task_id) or not isinstance(entry, dict):
            raise ValueError("invalid_internal_scheduler_task_entry")
        normalized_tasks[str(task_id).strip()] = {
            "task_id": str(entry.get("task_id") or task_id).strip(),
            "display_name": str(entry.get("display_name") or task_id).strip() or str(task_id).strip(),
            "task_kind": str(entry.get("task_kind") or "local_recurring").strip() or "local_recurring",
            "schedule_name": str(entry.get("schedule_name") or "interval").strip() or "interval",
            "schedule_detail": str(entry.get("schedule_detail") or "").strip() or None,
            "interval_seconds": int(entry.get("interval_seconds") or 0),
            "enabled": bool(entry.get("enabled", True)),
            "running": bool(entry.get("running", False)),
            "status": str(entry.get("status") or "idle").strip() or "idle",
            "readiness_critical": bool(entry.get("readiness_critical", False)),
            "last_started_at": str(entry.get("last_started_at") or "").strip() or None,
            "last_success_at": str(entry.get("last_success_at") or "").strip() or None,
            "last_failure_at": str(entry.get("last_failure_at") or "").strip() or None,
            "last_completed_at": str(entry.get("last_completed_at") or "").strip() or None,
            "last_error": str(entry.get("last_error") or "").strip() or None,
            "current_error": str(entry.get("current_error") or "").strip() or None,
            "next_run_at": str(entry.get("next_run_at") or "").strip() or None,
            "last_result": _summarize_last_result(task_id=str(task_id), value=entry.get("last_result")),
            "attempt_count": max(int(entry.get("attempt_count") or 0), 0),
            "consecutive_failures": max(int(entry.get("consecutive_failures") or 0), 0),
            "updated_at": str(entry.get("updated_at") or _now_iso()),
        }
    return {
        "schema_version": INTERNAL_SCHEDULER_STATE_SCHEMA_VERSION,
        "scheduler_status": str(data.get("scheduler_status") or "idle").strip() or "idle",
        "tasks": normalized_tasks,
        "updated_at": str(data.get("updated_at") or _now_iso()),
    }


def validate_internal_scheduler_state(data: object) -> Tuple[bool, Optional[str]]:
    try:
        normalize_internal_scheduler_state(data)
    except ValueError as exc:
        return False, str(exc)
    return True, None


class InternalSchedulerStateStore:
    def __init__(self, *, path: str, logger) -> None:
        self._path = Path(path)
        self._logger = logger

    def save(self, payload: dict) -> None:
        normalized = normalize_internal_scheduler_state(payload)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._path.with_suffix(f"{self._path.suffix}.tmp")
        temp_path.write_text(json.dumps(normalized, indent=2), encoding="utf-8")
        temp_path.replace(self._path)

    def load(self) -> Optional[dict]:
        if not self._path.exists():
            return None
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return None
        try:
            return normalize_internal_scheduler_state(payload)
        except ValueError:
            return None

    def load_or_create(self) -> dict:
        payload = self.load()
        if isinstance(payload, dict):
            return payload
        payload = create_internal_scheduler_state()
        self.save(payload)
        return payload
