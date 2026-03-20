from dataclasses import dataclass, field
from datetime import datetime, timezone


EXECUTION_LIFECYCLE_STATES = (
    "idle",
    "receiving_task",
    "validating_task",
    "queued_local",
    "executing",
    "reporting_progress",
    "completed",
    "failed",
    "degraded",
    "rejected",
)

_TERMINAL_EXECUTION_LIFECYCLE_STATES = {"completed", "failed", "degraded", "rejected"}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_string(value: object) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


@dataclass(frozen=True)
class ExecutionLifecycleRecord:
    task_id: str
    state: str
    updated_at: str
    lease_id: str | None = None
    provider_id: str | None = None
    model_id: str | None = None
    details: dict = field(default_factory=dict)


class ExecutionLifecycleTracker:
    def __init__(self, *, history_limit: int = 100) -> None:
        self._history_limit = max(int(history_limit), 1)
        self._active_tasks: dict[str, ExecutionLifecycleRecord] = {}
        self._history: list[ExecutionLifecycleRecord] = []

    def update(
        self,
        *,
        task_id: str,
        state: str,
        lease_id: str | None = None,
        provider_id: str | None = None,
        model_id: str | None = None,
        details: dict | None = None,
    ) -> ExecutionLifecycleRecord:
        normalized_task_id = _normalize_string(task_id)
        normalized_state = _normalize_string(state)
        if normalized_task_id is None:
            raise ValueError("task_id_required")
        if normalized_state is None or normalized_state not in set(EXECUTION_LIFECYCLE_STATES):
            raise ValueError("invalid_execution_lifecycle_state")

        record = ExecutionLifecycleRecord(
            task_id=normalized_task_id,
            state=normalized_state,
            updated_at=_iso_now(),
            lease_id=_normalize_string(lease_id),
            provider_id=_normalize_string(provider_id),
            model_id=_normalize_string(model_id),
            details=details if isinstance(details, dict) else {},
        )
        if normalized_state in _TERMINAL_EXECUTION_LIFECYCLE_STATES:
            self._active_tasks.pop(normalized_task_id, None)
            self._history.append(record)
            self._history = self._history[-self._history_limit :]
        else:
            self._active_tasks[normalized_task_id] = record
        return record

    def get_active(self, *, task_id: str) -> ExecutionLifecycleRecord | None:
        normalized_task_id = _normalize_string(task_id)
        if normalized_task_id is None:
            return None
        return self._active_tasks.get(normalized_task_id)

    def active_payload(self) -> dict:
        return {
            "active_tasks": [self._serialize(record) for record in self._active_tasks.values()],
            "active_count": len(self._active_tasks),
        }

    def history_payload(self) -> dict:
        return {
            "history": [self._serialize(record) for record in self._history],
            "history_count": len(self._history),
        }

    @staticmethod
    def _serialize(record: ExecutionLifecycleRecord) -> dict:
        return {
            "task_id": record.task_id,
            "state": record.state,
            "updated_at": record.updated_at,
            "lease_id": record.lease_id,
            "provider_id": record.provider_id,
            "model_id": record.model_id,
            "details": dict(record.details),
        }
