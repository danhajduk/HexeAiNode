import asyncio
from copy import deepcopy
from datetime import timedelta

from ai_node.time_utils import local_now, local_now_iso
from ai_node.runtime.internal_scheduler_catalog import get_schedule_definition, schedule_catalog_payload


class InternalScheduler:
    def __init__(self, *, logger, store=None) -> None:
        self._logger = logger
        self._store = store
        self._state = (
            self._store.load_or_create()
            if self._store is not None and hasattr(self._store, "load_or_create")
            else {"schema_version": "1.0", "scheduler_status": "idle", "tasks": {}, "updated_at": local_now_iso()}
        )
        self._task_handles: dict[str, asyncio.Task] = {}

    def register_interval_task(
        self,
        *,
        task_id: str,
        display_name: str,
        interval_seconds: int,
        schedule_name: str = "interval_seconds",
        schedule_detail: str | None = None,
        task_kind: str = "local_recurring",
        readiness_critical: bool = False,
    ) -> None:
        tasks = self._state.setdefault("tasks", {})
        current = dict(tasks.get(task_id) or {})
        schedule = get_schedule_definition(schedule_name, fallback_detail=schedule_detail)
        tasks[task_id] = {
            "task_id": task_id,
            "display_name": display_name,
            "task_kind": task_kind,
            "schedule_name": schedule["name"],
            "schedule_detail": schedule["detail"],
            "interval_seconds": max(int(interval_seconds), 1),
            "enabled": bool(current.get("enabled", True)),
            "running": bool(task_id in self._task_handles and not self._task_handles[task_id].done()),
            "status": str(current.get("status") or "idle"),
            "readiness_critical": bool(readiness_critical),
            "last_started_at": current.get("last_started_at"),
            "last_success_at": current.get("last_success_at"),
            "last_failure_at": current.get("last_failure_at"),
            "last_completed_at": current.get("last_completed_at"),
            "last_error": current.get("last_error"),
            "current_error": current.get("current_error"),
            "next_run_at": current.get("next_run_at"),
            "last_result": deepcopy(current.get("last_result")) if isinstance(current.get("last_result"), dict) else None,
            "attempt_count": int(current.get("attempt_count") or 0),
            "consecutive_failures": int(current.get("consecutive_failures") or 0),
            "updated_at": current.get("updated_at") or local_now_iso(),
        }
        self._save()

    def snapshot(self) -> dict:
        self._refresh_running_flags()
        payload = deepcopy(self._state)
        payload["schedule_catalog"] = schedule_catalog_payload()
        return payload

    def start_interval_task(self, *, task_id: str, coroutine_factory, initial_delay_seconds: int) -> None:
        existing = self._task_handles.get(task_id)
        if existing is not None and not existing.done():
            return
        self._task_handles[task_id] = asyncio.create_task(
            self._run_interval_task(
                task_id=task_id,
                coroutine_factory=coroutine_factory,
                initial_delay_seconds=max(int(initial_delay_seconds), 0),
            )
        )
        self._set_scheduler_status("running")

    async def stop_all(self) -> None:
        handles = list(self._task_handles.items())
        self._task_handles = {}
        for _, task in handles:
            task.cancel()
        for task_id, task in handles:
            try:
                await task
            except asyncio.CancelledError:
                self._mark_task_cancelled(task_id=task_id)
        self._set_scheduler_status("stopped")

    async def _run_interval_task(self, *, task_id: str, coroutine_factory, initial_delay_seconds: int) -> None:
        next_delay = initial_delay_seconds
        while True:
            self._mark_task_sleeping(task_id=task_id, delay_seconds=next_delay)
            await asyncio.sleep(next_delay)
            self._mark_task_running(task_id=task_id)
            try:
                result = await coroutine_factory()
            except asyncio.CancelledError:
                self._mark_task_cancelled(task_id=task_id)
                raise
            except Exception as exc:
                self._mark_task_failure(task_id=task_id, error=str(exc))
                if hasattr(self._logger, "warning"):
                    self._logger.warning("[internal-scheduler-task-error] %s", {"task_id": task_id, "error": str(exc)})
            else:
                self._mark_task_success(task_id=task_id, result=result if isinstance(result, dict) else None)
            entry = self._ensure_task(task_id)
            next_delay = max(int(entry.get("interval_seconds") or 1), 1)

    def _ensure_task(self, task_id: str) -> dict:
        tasks = self._state.setdefault("tasks", {})
        task = tasks.get(task_id)
        if not isinstance(task, dict):
            raise ValueError(f"unregistered_scheduler_task:{task_id}")
        return task

    def _mark_task_sleeping(self, *, task_id: str, delay_seconds: int) -> None:
        task = self._ensure_task(task_id)
        next_run_at = local_now() + timedelta(seconds=max(int(delay_seconds), 0))
        task["running"] = False
        task["status"] = "scheduled"
        task["current_error"] = None
        task["next_run_at"] = next_run_at.isoformat()
        task["updated_at"] = local_now_iso()
        self._save()

    def _mark_task_running(self, *, task_id: str) -> None:
        task = self._ensure_task(task_id)
        task["running"] = True
        task["status"] = "running"
        task["last_started_at"] = local_now_iso()
        task["attempt_count"] = int(task.get("attempt_count") or 0) + 1
        task["current_error"] = None
        task["updated_at"] = local_now_iso()
        self._save()

    def _mark_task_success(self, *, task_id: str, result: dict | None) -> None:
        task = self._ensure_task(task_id)
        now = local_now_iso()
        task["running"] = False
        task["status"] = "healthy"
        task["last_success_at"] = now
        task["last_completed_at"] = now
        task["last_result"] = deepcopy(result) if isinstance(result, dict) else None
        task["last_error"] = None
        task["current_error"] = None
        task["next_run_at"] = None
        task["consecutive_failures"] = 0
        task["updated_at"] = now
        self._save()

    def _mark_task_failure(self, *, task_id: str, error: str) -> None:
        task = self._ensure_task(task_id)
        now = local_now_iso()
        task["running"] = False
        task["status"] = "failing"
        task["last_failure_at"] = now
        task["last_completed_at"] = now
        task["last_error"] = error
        task["current_error"] = error
        task["next_run_at"] = None
        task["consecutive_failures"] = int(task.get("consecutive_failures") or 0) + 1
        task["updated_at"] = now
        self._save()

    def _mark_task_cancelled(self, *, task_id: str) -> None:
        if task_id not in self._state.get("tasks", {}):
            return
        task = self._ensure_task(task_id)
        task["running"] = False
        task["status"] = "stopped"
        task["current_error"] = None
        task["updated_at"] = local_now_iso()
        self._save()

    def _set_scheduler_status(self, status: str) -> None:
        self._state["scheduler_status"] = status
        self._state["updated_at"] = local_now_iso()
        self._save()

    def _refresh_running_flags(self) -> None:
        tasks = self._state.get("tasks") if isinstance(self._state.get("tasks"), dict) else {}
        for task_id, task in tasks.items():
            if not isinstance(task, dict):
                continue
            handle = self._task_handles.get(task_id)
            task["running"] = bool(handle is not None and not handle.done())

    def _save(self) -> None:
        self._refresh_running_flags()
        self._state["updated_at"] = local_now_iso()
        if self._store is not None and hasattr(self._store, "save"):
            self._store.save(self._state)
