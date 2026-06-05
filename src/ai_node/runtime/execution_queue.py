import asyncio
import heapq
import itertools
import uuid
from copy import deepcopy
from datetime import timedelta
from typing import Awaitable, Callable

from ai_node.time_utils import local_now, local_now_iso


IMPORTANCE_RANK = {
    "critical": 0,
    "high": 1,
    "normal": 2,
    "low": 3,
    "background": 4,
}


class ExecutionQueueService:
    def __init__(
        self,
        *,
        logger,
        local_concurrency: int = 1,
        cloud_concurrency: int = 4,
        check_after_seconds: int = 5,
        job_ttl_seconds: int = 3600,
    ) -> None:
        self._logger = logger
        self._local_concurrency = max(int(local_concurrency), 1)
        self._cloud_concurrency = max(int(cloud_concurrency), 1)
        self._check_after_seconds = max(int(check_after_seconds), 1)
        self._job_ttl_seconds = max(int(job_ttl_seconds), 60)
        self._sequence = itertools.count(1)
        self._lock = asyncio.Lock()
        self._jobs: dict[str, dict] = {}
        self._queues: dict[str, list[tuple[int, int, str]]] = {"local": [], "cloud": []}
        self._active_counts: dict[str, int] = {"local": 0, "cloud": 0}
        self._dispatcher_tasks: dict[str, asyncio.Task] = {}

    def queued_response(self, *, job_id: str, base_path: str = "/api/execution/jobs") -> dict:
        job = self._jobs.get(job_id) or {}
        return {
            "status": "queued",
            "job_id": job_id,
            "job_name": job.get("job_name"),
            "check_after_seconds": self._check_after_seconds,
            "status_url": f"{base_path}/{job_id}",
            "queue": job.get("queue"),
            "queue_position": self._queue_position(job_id=job_id),
            "importance": job.get("importance"),
            "expires_at": job.get("expires_at"),
        }

    async def enqueue(
        self,
        *,
        queue: str,
        importance: str,
        job_name: str,
        request_payload: dict,
        runner: Callable[[], Awaitable[dict]],
    ) -> dict:
        queue_key = "local" if str(queue or "").strip().lower() == "local" else "cloud"
        importance_key = str(importance or "normal").strip().lower()
        rank = IMPORTANCE_RANK.get(importance_key, IMPORTANCE_RANK["normal"])
        sequence = next(self._sequence)
        job_id = f"job-{uuid.uuid4().hex[:16]}"
        now = local_now()
        job = {
            "job_id": job_id,
            "job_name": str(job_name or job_id).strip() or job_id,
            "queue": queue_key,
            "importance": importance_key if importance_key in IMPORTANCE_RANK else "normal",
            "status": "queued",
            "request": deepcopy(request_payload) if isinstance(request_payload, dict) else {},
            "result": None,
            "error": None,
            "created_at": now.isoformat(),
            "queued_at": now.isoformat(),
            "started_at": None,
            "completed_at": None,
            "expires_at": (now + timedelta(seconds=self._job_ttl_seconds)).isoformat(),
            "sequence": sequence,
            "_runner": runner,
        }
        async with self._lock:
            self._jobs[job_id] = job
            heapq.heappush(self._queues[queue_key], (rank, sequence, job_id))
            self._ensure_dispatcher_locked(queue_key)
        return self.queued_response(job_id=job_id)

    async def job_status(self, *, job_id: str) -> dict:
        async with self._lock:
            job = self._jobs.get(str(job_id or "").strip())
            if not isinstance(job, dict):
                return {"status": "not_found", "job_id": job_id}
            return self._public_job_payload(job)

    async def diagnostics(self) -> dict:
        async with self._lock:
            queues = {}
            for queue_key, entries in self._queues.items():
                queued_ids = [item[2] for item in sorted(entries)]
                per_importance: dict[str, int] = {}
                oldest_queued_at = None
                for job_id in queued_ids:
                    job = self._jobs.get(job_id) or {}
                    importance = str(job.get("importance") or "normal")
                    per_importance[importance] = per_importance.get(importance, 0) + 1
                    queued_at = job.get("queued_at")
                    if queued_at and (oldest_queued_at is None or str(queued_at) < str(oldest_queued_at)):
                        oldest_queued_at = queued_at
                queues[queue_key] = {
                    "queued_count": len(queued_ids),
                    "active_count": self._active_counts.get(queue_key, 0),
                    "concurrency": self._concurrency(queue_key),
                    "oldest_queued_at": oldest_queued_at,
                    "per_importance": per_importance,
                }
            return {
                "configured": True,
                "queues": queues,
                "job_count": len(self._jobs),
                "generated_at": local_now_iso(),
            }

    def _ensure_dispatcher_locked(self, queue_key: str) -> None:
        task = self._dispatcher_tasks.get(queue_key)
        if task is not None and not task.done():
            return
        self._dispatcher_tasks[queue_key] = asyncio.create_task(self._dispatch_loop(queue_key))

    async def _dispatch_loop(self, queue_key: str) -> None:
        while True:
            async with self._lock:
                if self._active_counts.get(queue_key, 0) >= self._concurrency(queue_key):
                    return
                queue_entries = self._queues.get(queue_key) or []
                if not queue_entries:
                    return
                _, _, job_id = heapq.heappop(queue_entries)
                job = self._jobs.get(job_id)
                if not isinstance(job, dict) or job.get("status") != "queued":
                    continue
                job["status"] = "running"
                job["started_at"] = local_now_iso()
                self._active_counts[queue_key] = self._active_counts.get(queue_key, 0) + 1
                runner = job.get("_runner")
            asyncio.create_task(self._run_job(queue_key=queue_key, job_id=job_id, runner=runner))

    async def _run_job(self, *, queue_key: str, job_id: str, runner) -> None:
        try:
            if not callable(runner):
                raise RuntimeError("queued_job_runner_missing")
            result = await runner()
            async with self._lock:
                job = self._jobs.get(job_id)
                if isinstance(job, dict):
                    job["status"] = "completed"
                    job["result"] = result if isinstance(result, dict) else {}
                    job["completed_at"] = local_now_iso()
        except Exception as exc:
            if hasattr(self._logger, "warning"):
                self._logger.warning(
                    "[execution-queue-job-failed] %s",
                    {"job_id": job_id, "queue": queue_key, "error": str(exc)},
                )
            async with self._lock:
                job = self._jobs.get(job_id)
                if isinstance(job, dict):
                    job["status"] = "failed"
                    job["error"] = {
                        "code": str(exc).strip() or type(exc).__name__,
                        "message": str(exc).strip() or type(exc).__name__,
                    }
                    job["completed_at"] = local_now_iso()
        finally:
            async with self._lock:
                self._active_counts[queue_key] = max(self._active_counts.get(queue_key, 0) - 1, 0)
                self._ensure_dispatcher_locked(queue_key)

    def _queue_position(self, *, job_id: str) -> int | None:
        job = self._jobs.get(job_id)
        if not isinstance(job, dict):
            return None
        queue_key = str(job.get("queue") or "")
        queued_ids = [item[2] for item in sorted(self._queues.get(queue_key) or [])]
        if job_id not in queued_ids:
            return None
        return queued_ids.index(job_id) + 1

    def _concurrency(self, queue_key: str) -> int:
        return self._local_concurrency if queue_key == "local" else self._cloud_concurrency

    def _public_job_payload(self, job: dict) -> dict:
        payload = {
            key: deepcopy(job.get(key))
            for key in (
                "job_id",
                "job_name",
                "queue",
                "importance",
                "status",
                "created_at",
                "queued_at",
                "started_at",
                "completed_at",
                "expires_at",
                "request",
                "result",
                "error",
            )
        }
        payload["queue_position"] = self._queue_position(job_id=str(job.get("job_id") or ""))
        payload["check_after_seconds"] = self._check_after_seconds
        return payload
